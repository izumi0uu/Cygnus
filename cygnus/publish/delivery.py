"""Outbound internal-channel delivery adapter for governed propagation.

Ownership:
- canonical payload/digest, request signing, destination/DNS/HTTPS policy,
  bounded retry/circuit/dead-letter, the signed acknowledgment transition, and
  the worker sweep for ``governance_propagation_deliveries`` live here
- only the signed acknowledgment path may set a propagation to ``synced``;
  every other transition stays pending/failed/manual with durable evidence

Policy:
- destinations are validated against the configured allowlist (the origins in
  ``DELIVERY_TARGETS_JSON``); every redirect hop is re-validated (scheme, DNS
  shape, allowlist) before it is followed
- HTTPS is required outside local/test environments; plain HTTP is accepted
  only in local/test (deterministic fake-consumer harnesses)
- retries are bounded by ``DELIVERY_MAX_ATTEMPTS``; exhausted deliveries are
  dead-lettered; a per-host in-memory circuit breaker backs off repeatedly
  failing destinations

This module never logs delivery bodies or the shared HMAC secret.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import TypedDict, cast
from urllib.parse import urljoin, urlsplit

import httpx
from loguru import logger
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.governance.ledger import (
    GovernanceEventType,
    append_draft_event,
    get_latest_draft_event,
    lock_draft_aggregate,
)
from cygnus.observability import (
    current_request_id,
    current_traceparent,
    outbound_trace_headers,
    record_delivery,
    record_propagation_mismatch,
    start_span,
)
from cygnus.publish.propagation import PropagationStatus
from cygnus.runtime.config import Settings, get_settings
from cygnus.runtime.database.models import (
    GovernanceAudienceBinding,
    GovernanceLedgerEvent,
    GovernancePropagation,
    GovernancePropagationDelivery,
    GovernancePublication,
)

_DELIVERY_PATH = "api/internal/propagation-delivery"
_ACK_SIGNATURE_PREFIX = "sha256="
_MAX_ACK_BODY_BYTES = 1024 * 1024
_MAX_ERROR_CHARS = 2000
_MAX_REDIRECT_HOPS = 5
_DELIVERY_SWEEP_LIMIT = 10
_DELIVERY_LEASE_TTL_SECONDS = 600
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_DNS_LABEL_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?")


class DeliveryStatus(str, Enum):
    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    SYNCED = "synced"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


class DeliveryPolicyError(ValueError):
    """A delivery destination violated the allowlist/DNS/HTTPS policy."""


class DeliveryVerificationError(ValueError):
    """A downstream acknowledgment failed signature or payload verification."""


class DeliveryReceiptNotFound(LookupError):
    """No durable delivery row matches the requested identity."""


class DeliveryAckConflict(ValueError):
    """A downstream acknowledgment drifted from the persisted delivery truth."""


# ---------------------------------------------------------------------------
# Canonical serialization + digest
# ---------------------------------------------------------------------------


def build_canonical_delivery_payload(
    *,
    publication_id: uuid.UUID,
    command_id: str,
    approval_ref: uuid.UUID,
    approval_sequence: int,
    object_ref: str,
    object_type: str,
    object_version: int,
    action_key: str,
    target_channels: Sequence[str],
    binding_rows: Sequence[GovernanceAudienceBinding],
    source_ids: Sequence[uuid.UUID],
    content_md: str,
) -> dict[str, object]:
    """Serialize the exact approved publication snapshot for delivery.

    Frozen at publish staging; retries re-send these exact bytes so the
    desired digest stays deterministic. Correlation/trace metadata is never
    included here (it would make exact replay volatile).
    """
    bindings: list[dict[str, object]] = []
    for binding in binding_rows:
        bindings.append(
            {
                "binding_key": binding.binding_key,
                "version": binding.version,
                "channel": binding.channel,
                "visibility": binding.visibility,
                "audience": {
                    "brands": list(binding.brands or ()),
                    "product_lines": list(binding.product_lines or ()),
                    "plans": list(binding.plans or ()),
                    "regions": list(binding.regions or ()),
                    "languages": list(binding.languages or ()),
                    "product_versions": list(binding.product_versions or ()),
                },
            }
        )
    return {
        "publication_id": str(publication_id),
        "command_id": command_id,
        "approval_ref": str(approval_ref),
        "approval_sequence": approval_sequence,
        "object_ref": object_ref,
        "object_type": object_type,
        "object_version": object_version,
        "action_key": action_key,
        "target_channels": list(target_channels),
        "bindings": bindings,
        "source_evidence_refs": [f"ev-src-{source_id}" for source_id in source_ids],
        "content_sha256": hashlib.sha256(content_md.encode("utf-8")).hexdigest(),
    }


def binding_version_refs(
    binding_rows: Sequence[GovernanceAudienceBinding],
) -> list[dict[str, object]]:
    return [
        {"binding_key": binding.binding_key, "version": binding.version}
        for binding in binding_rows
    ]


def canonical_json(payload: Mapping[str, object]) -> bytes:
    """Deterministic canonical JSON bytes for one delivery payload."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_delivery_digest(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


# ---------------------------------------------------------------------------
# Request signing / ack verification
# ---------------------------------------------------------------------------


def sign_body(body_bytes: bytes, secret: str) -> str:
    """HMAC-SHA256 hex digest of the exact outbound body bytes."""
    return hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()


def verify_ack_signature(body_bytes: bytes, header_value: str, secret: str) -> bool:
    """Constant-time check of an ``X-Cygnus-Ack-Signature: sha256=<hex>`` header."""
    if not secret or not header_value.startswith(_ACK_SIGNATURE_PREFIX):
        return False
    provided = header_value[len(_ACK_SIGNATURE_PREFIX) :].strip()
    expected = sign_body(body_bytes, secret)
    return hmac.compare_digest(provided, expected)


def delivery_request_headers(
    delivery: GovernancePropagationDelivery,
    signature: str,
) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "X-Cygnus-Signature": f"sha256={signature}",
        "X-Cygnus-Delivery-Id": delivery.idempotency_key,
        "X-Cygnus-Publication-Id": str(delivery.publication_id),
        "X-Cygnus-Surface": delivery.surface_id,
    }
    if delivery.correlation_id:
        headers["X-Cygnus-Correlation-Id"] = delivery.correlation_id
    if delivery.traceparent:
        headers["traceparent"] = delivery.traceparent
    # Live correlation context wins when present (bounded, no secrets).
    headers.update(outbound_trace_headers())
    return headers


# ---------------------------------------------------------------------------
# Destination / DNS / HTTPS policy
# ---------------------------------------------------------------------------


def delivery_target_origins(targets: Mapping[str, str]) -> set[str]:
    """Allowlist netlocs derived from the configured delivery target URLs."""
    netlocs: set[str] = set()
    for raw_url in targets.values():
        parts = urlsplit(raw_url.strip())
        if parts.hostname is None:
            raise ValueError(f"delivery target has no host: {raw_url!r}")
        netlocs.add(_netloc(parts.hostname.lower().rstrip("."), parts.port))
    return netlocs


def delivery_endpoint_url(base_url: str) -> str:
    """Join the fixed delivery path onto a configured target base URL."""
    normalized = base_url.strip().rstrip("/")
    if not normalized:
        raise DeliveryPolicyError("delivery target base URL must not be blank")
    return urljoin(normalized + "/", _DELIVERY_PATH)


def url_host(raw_url: str) -> str:
    parts = urlsplit(raw_url.strip())
    if parts.hostname is None:
        raise DeliveryPolicyError("delivery destination has no host")
    return parts.hostname.lower().rstrip(".")


def validate_delivery_destination(
    raw_url: str,
    allowed_netlocs: set[str],
    *,
    allow_insecure_http: bool,
) -> str:
    """Validate one delivery URL against the allowlist/DNS/HTTPS policy.

    Used for the initial target and for every redirect hop. Returns the
    normalized URL. Raises :class:`DeliveryPolicyError` on any violation.
    """
    normalized = raw_url.strip()
    if not normalized:
        raise DeliveryPolicyError("delivery destination must not be blank")
    parts = urlsplit(normalized)
    if parts.scheme not in {"http", "https"}:
        raise DeliveryPolicyError(
            "delivery destination must use http or https, got " + repr(parts.scheme)
        )
    if parts.scheme == "http" and not allow_insecure_http:
        raise DeliveryPolicyError(
            "HTTPS is required for delivery destinations outside local/test"
        )
    if parts.username is not None or parts.password is not None:
        raise DeliveryPolicyError("delivery destination must not embed credentials")
    if parts.query or parts.fragment:
        raise DeliveryPolicyError(
            "delivery destination must not carry query or fragment"
        )
    if parts.hostname is None:
        raise DeliveryPolicyError("delivery destination has no host")
    host = parts.hostname.lower().rstrip(".")
    _validate_host_syntax(host)
    netloc = _netloc(host, parts.port)
    if netloc not in allowed_netlocs:
        raise DeliveryPolicyError(f"delivery destination {netloc} is not allowlisted")
    return f"{parts.scheme}://{netloc}{parts.path or '/'}"


def _netloc(host: str, port: int | None) -> str:
    return host if port is None else f"{host}:{port}"


def _validate_host_syntax(host: str) -> None:
    try:
        ipaddress.ip_address(host)
        return
    except ValueError:
        pass
    if not host or len(host) > 253:
        raise DeliveryPolicyError("delivery destination host is not a valid DNS name")
    for label in host.split("."):
        if not label or len(label) > 63 or _DNS_LABEL_RE.fullmatch(label) is None:
            raise DeliveryPolicyError(
                "delivery destination host is not a valid DNS name"
            )


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _HostCircuit:
    consecutive_failures: int = 0
    opened_at: float | None = None
    half_open: bool = False


class DeliveryCircuitBreaker:
    """In-memory per-host breaker that backs off failing destinations."""

    def __init__(self, *, threshold: int = 5, cooldown_seconds: float = 60.0) -> None:
        if threshold < 1:
            raise ValueError("circuit breaker threshold must be positive")
        if cooldown_seconds <= 0:
            raise ValueError("circuit breaker cooldown must be positive")
        self.threshold = threshold
        self.cooldown_seconds = cooldown_seconds
        self._hosts: dict[str, _HostCircuit] = {}

    def allow(self, host: str) -> bool:
        state = self._hosts.get(host)
        if state is None or state.opened_at is None:
            return True
        if state.half_open:
            return True
        if _monotonic() - state.opened_at >= self.cooldown_seconds:
            state.half_open = True
            return True
        return False

    def record_failure(self, host: str) -> None:
        state = self._hosts.setdefault(host, _HostCircuit())
        if state.half_open or state.opened_at is None:
            state.half_open = False
            state.consecutive_failures += 1
        else:
            state.consecutive_failures += 1
        if state.consecutive_failures >= self.threshold:
            state.opened_at = _monotonic()

    def record_success(self, host: str) -> None:
        self._hosts[host] = _HostCircuit()

    def reset(self) -> None:
        self._hosts.clear()


def _monotonic() -> float:
    from time import monotonic

    return monotonic()


def _monotonic_ns() -> int:
    from time import monotonic_ns

    return monotonic_ns()


# ---------------------------------------------------------------------------
# Outbound transport
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class DeliveryAttemptOutcome:
    delivered: bool
    synced: bool
    retryable: bool
    status_code: int | None = None
    error: str | None = None
    ack_body: bytes | None = None
    ack_signature: str | None = None
    acknowledged_digest: str | None = None
    ack_receipt_ref: str | None = None
    ack_correlation_id: str | None = None
    ack_traceparent: str | None = None


async def send_delivery_request(
    delivery: GovernancePropagationDelivery,
    *,
    secret: str,
    request_url: str,
    timeout_seconds: float,
    allowed_origins: set[str],
    allow_insecure_http: bool,
    circuit: DeliveryCircuitBreaker,
    client: httpx.AsyncClient | None = None,
) -> DeliveryAttemptOutcome:
    """Sign and POST the frozen canonical payload, then verify the signed ack."""
    started_ns = _monotonic_ns()
    channel = delivery.surface_id
    with start_span("cygnus.delivery", {"channel": channel}):
        outcome = await _send_delivery_request_impl(
            delivery,
            secret=secret,
            request_url=request_url,
            timeout_seconds=timeout_seconds,
            allowed_origins=allowed_origins,
            allow_insecure_http=allow_insecure_http,
            circuit=circuit,
            client=client,
        )
    record_delivery(
        channel=channel,
        status="ok" if outcome.synced else "error",
        duration_ms=max(0, (_monotonic_ns() - started_ns) // 1_000_000),
    )
    return outcome


async def _send_delivery_request_impl(
    delivery: GovernancePropagationDelivery,
    *,
    secret: str,
    request_url: str,
    timeout_seconds: float,
    allowed_origins: set[str],
    allow_insecure_http: bool,
    circuit: DeliveryCircuitBreaker,
    client: httpx.AsyncClient | None = None,
) -> DeliveryAttemptOutcome:
    host = url_host(request_url)
    body_bytes = canonical_json(delivery.canonical_payload)
    signature = sign_body(body_bytes, secret)
    headers = delivery_request_headers(delivery, signature)
    if client is None:
        client = httpx.AsyncClient(timeout=timeout_seconds)
        owns_client = True
    else:
        owns_client = False
    try:
        response = await _post_with_redirect_validation(
            client,
            request_url,
            body_bytes,
            headers,
            timeout_seconds=timeout_seconds,
            allowed_origins=allowed_origins,
            allow_insecure_http=allow_insecure_http,
        )
    except httpx.TimeoutException:
        circuit.record_failure(host)
        return DeliveryAttemptOutcome(
            delivered=False,
            synced=False,
            retryable=True,
            error="delivery_timeout",
        )
    except httpx.TransportError as exc:
        circuit.record_failure(host)
        return DeliveryAttemptOutcome(
            delivered=False,
            synced=False,
            retryable=True,
            error=f"delivery_transport_{type(exc).__name__.lower()}",
        )
    except DeliveryPolicyError as exc:
        circuit.record_failure(host)
        return DeliveryAttemptOutcome(
            delivered=False,
            synced=False,
            retryable=False,
            error=str(exc),
        )
    finally:
        if owns_client:
            await client.aclose()

    if response.status_code >= 500 or response.status_code in (408, 429):
        circuit.record_failure(host)
        return DeliveryAttemptOutcome(
            delivered=False,
            synced=False,
            retryable=True,
            status_code=response.status_code,
            error=f"http_{response.status_code}",
        )
    if response.status_code >= 400:
        circuit.record_failure(host)
        return DeliveryAttemptOutcome(
            delivered=False,
            synced=False,
            retryable=False,
            status_code=response.status_code,
            error=f"http_{response.status_code}",
        )

    ack_body = response.content
    ack_signature = response.headers.get("X-Cygnus-Ack-Signature", "")
    if not verify_ack_signature(ack_body, ack_signature, secret):
        circuit.record_failure(host)
        record_propagation_mismatch(kind="mismatch")
        return DeliveryAttemptOutcome(
            delivered=True,
            synced=False,
            retryable=False,
            status_code=response.status_code,
            error="ack_signature_invalid",
        )
    try:
        ack_payload = parse_ack_body(ack_body)
        _validate_ack_binding(ack_payload, delivery)
    except (DeliveryVerificationError, DeliveryAckConflict) as exc:
        circuit.record_failure(host)
        record_propagation_mismatch(kind="mismatch")
        return DeliveryAttemptOutcome(
            delivered=True,
            synced=False,
            retryable=False,
            status_code=response.status_code,
            error=str(exc),
        )
    circuit.record_success(host)
    return DeliveryAttemptOutcome(
        delivered=True,
        synced=True,
        retryable=False,
        status_code=response.status_code,
        ack_body=ack_body,
        ack_signature=ack_signature,
        acknowledged_digest=ack_payload["digest"],
        ack_receipt_ref=ack_payload.get("receipt_ref"),
        ack_correlation_id=response.headers.get("X-Cygnus-Correlation-Id"),
        ack_traceparent=response.headers.get("traceparent"),
    )


async def _post_with_redirect_validation(
    client: httpx.AsyncClient,
    url: str,
    body: bytes,
    headers: dict[str, str],
    *,
    timeout_seconds: float,
    allowed_origins: set[str],
    allow_insecure_http: bool,
) -> httpx.Response:
    current_url = url
    for _ in range(_MAX_REDIRECT_HOPS + 1):
        response = await client.post(
            current_url,
            content=body,
            headers=headers,
            timeout=timeout_seconds,
            follow_redirects=False,
        )
        if response.status_code not in _REDIRECT_STATUSES:
            return response
        location = response.headers.get("location")
        if not location:
            raise DeliveryPolicyError(
                "delivery redirect response has no Location header"
            )
        # DNS-per-redirect: re-validate scheme, DNS shape, and allowlist before
        # following the hop.
        current_url = validate_delivery_destination(
            urljoin(current_url, location),
            allowed_origins,
            allow_insecure_http=allow_insecure_http,
        )
    raise DeliveryPolicyError("delivery redirect chain exceeded the bounded hop limit")


class AckPayload(TypedDict):
    """A structurally validated signed acknowledgment body.

    Every field is checked by :func:`parse_ack_body` before this type is
    produced, so callers can rely on the precise shapes below.
    """

    publication_id: str
    surface_id: str
    version: int
    digest: str
    receipt_ref: str | None


def parse_ack_body(ack_body: bytes) -> AckPayload:
    """Parse and structurally validate a signed acknowledgment body."""
    if len(ack_body) > _MAX_ACK_BODY_BYTES:
        raise DeliveryVerificationError("ack body exceeds the bounded size limit")
    try:
        raw = json.loads(ack_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeliveryVerificationError("ack body is not valid JSON") from exc
    if not isinstance(raw, dict):
        raise DeliveryVerificationError("ack body must be a JSON object")
    payload = cast(dict[str, object], raw)
    publication_id = payload.get("publication_id")
    surface_id = payload.get("surface_id")
    version = payload.get("version")
    digest = payload.get("digest")
    receipt_ref = payload.get("receipt_ref")
    if not isinstance(publication_id, str):
        raise DeliveryVerificationError("ack publication_id must be a UUID string")
    try:
        uuid.UUID(publication_id)
    except ValueError as exc:
        raise DeliveryVerificationError(
            "ack publication_id is not a valid UUID"
        ) from exc
    if not isinstance(surface_id, str) or not surface_id.strip():
        raise DeliveryVerificationError("ack surface_id must not be blank")
    if not isinstance(version, int) or version < 1:
        raise DeliveryVerificationError("ack version must be a positive integer")
    if not isinstance(digest, str) or len(digest) != 64:
        raise DeliveryVerificationError("ack digest must be a 64-char SHA-256 hex")
    try:
        int(digest, 16)
    except ValueError as exc:
        raise DeliveryVerificationError("ack digest must be hex") from exc
    if receipt_ref is not None and (
        not isinstance(receipt_ref, str) or not receipt_ref.strip()
    ):
        raise DeliveryVerificationError("ack receipt_ref must be a non-blank string")
    # Validation guarantees receipt_ref is either None or a non-blank string;
    # normalize explicitly so the returned payload is precisely typed.
    normalized_receipt_ref = receipt_ref if isinstance(receipt_ref, str) else None
    return {
        "publication_id": publication_id,
        "surface_id": surface_id.strip(),
        "version": version,
        "digest": digest,
        "receipt_ref": normalized_receipt_ref,
    }


def _validate_ack_binding(
    ack_payload: AckPayload,
    delivery: GovernancePropagationDelivery,
) -> None:
    if uuid.UUID(ack_payload["publication_id"]) != delivery.publication_id:
        record_propagation_mismatch(kind="mismatch")
        raise DeliveryAckConflict("ack publication does not match the delivery receipt")
    if ack_payload["surface_id"] != delivery.surface_id:
        record_propagation_mismatch(kind="mismatch")
        raise DeliveryAckConflict("ack channel does not match the delivery receipt")
    if ack_payload["version"] != delivery.expected_page_version:
        record_propagation_mismatch(kind="mismatch")
        raise DeliveryAckConflict(
            "ack version does not match the delivered object version"
        )
    if ack_payload["digest"] != delivery.desired_digest:
        record_propagation_mismatch(kind="mismatch")
        raise DeliveryAckConflict("ack digest does not match the desired digest")


# ---------------------------------------------------------------------------
# Signed acknowledgment transition (the only path to ``synced``)
# ---------------------------------------------------------------------------


async def acknowledge_propagation_delivery(
    session: AsyncSession,
    *,
    delivery_id: uuid.UUID,
    ack_body: bytes,
    signature: str,
    secret: str,
    correlation_id: str | None = None,
    traceparent: str | None = None,
) -> dict[str, object]:
    """Verify one signed downstream acknowledgment and transition to synced.

    Replaying the exact same signed ack returns the stored receipt; any drift
    (signature, publication, channel, version, or digest) is denied and never
    syncs. A stale ack for an object superseded by a newer publication is
    denied too.
    """
    if not secret:
        raise DeliveryVerificationError(
            "delivery HMAC secret is not configured; acks are refused"
        )
    if not verify_ack_signature(ack_body, signature, secret):
        record_propagation_mismatch(kind="mismatch")
        raise DeliveryVerificationError("ack signature verification failed")
    ack_payload = parse_ack_body(ack_body)
    if correlation_id is None:
        correlation_id = current_request_id()
    if traceparent is None:
        traceparent = current_traceparent()

    delivery = (
        await session.execute(
            select(GovernancePropagationDelivery)
            .where(GovernancePropagationDelivery.id == delivery_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if delivery is None:
        raise DeliveryReceiptNotFound(
            f"delivery_id={delivery_id} has no durable receipt"
        )
    _validate_ack_binding(ack_payload, delivery)

    if delivery.status == DeliveryStatus.SYNCED.value:
        if (
            delivery.acknowledged_digest == ack_payload["digest"]
            and delivery.acknowledged_version == ack_payload["version"]
        ):
            return _ack_receipt(delivery, replayed=True)
        record_propagation_mismatch(kind="mismatch")
        raise DeliveryAckConflict(
            "delivery is already synced with a different acknowledgment"
        )

    publication = await session.get(GovernancePublication, delivery.publication_id)
    if publication is None:
        raise DeliveryReceiptNotFound(
            f"publication_id={delivery.publication_id} has no durable row"
        )
    latest = (
        await session.execute(
            select(GovernancePublication)
            .where(GovernancePublication.object_ref == publication.object_ref)
            .order_by(
                GovernancePublication.published_at.desc(),
                GovernancePublication.id.desc(),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest is not None and latest.id != publication.id:
        record_propagation_mismatch(kind="mismatch")
        raise DeliveryAckConflict(
            "ack is stale: the object was superseded by a newer publication"
        )

    await lock_draft_aggregate(session, publication.draft_id)
    idempotency_key = f"propagation-ack:{delivery.id}"
    existing_event = (
        await session.execute(
            select(GovernanceLedgerEvent).where(
                GovernanceLedgerEvent.idempotency_key == idempotency_key
            )
        )
    ).scalar_one_or_none()
    if existing_event is not None:
        if (
            existing_event.payload.get("ack_digest") != ack_payload["digest"]
            or existing_event.payload.get("ack_version") != ack_payload["version"]
        ):
            record_propagation_mismatch(kind="mismatch")
            raise DeliveryAckConflict(
                "replayed ack drift conflicts with the stored receipt"
            )
        return _ack_receipt(delivery, replayed=True)

    propagation = (
        await session.execute(
            select(GovernancePropagation)
            .where(GovernancePropagation.id == delivery.propagation_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if propagation is None:
        raise DeliveryReceiptNotFound(
            f"propagation_id={delivery.propagation_id} has no durable row"
        )
    current_event = await get_latest_draft_event(session, publication.draft_id)
    if current_event is None:
        raise DeliveryAckConflict(
            f"draft_id={publication.draft_id} has no governance state"
        )

    now_dt = datetime.now(timezone.utc)
    ack_digest = ack_payload["digest"]
    ack_version = ack_payload["version"]
    ack_receipt_ref = ack_payload.get("receipt_ref")
    event = await append_draft_event(
        session,
        draft_id=publication.draft_id,
        event_type=GovernanceEventType.PROPAGATION_UPDATED,
        from_state=current_event.to_state,
        to_state=current_event.to_state,
        actor_id=None,
        idempotency_key=idempotency_key,
        reason="downstream acknowledged the delivered digest",
        payload={
            "publication_id": str(publication.id),
            "surface_id": delivery.surface_id,
            "previous_status": propagation.status,
            "status": PropagationStatus.SYNCED.value,
            "previous_version": propagation.version,
            "version": propagation.version + 1,
            "delivery_id": str(delivery.id),
            "ack_digest": ack_digest,
            "ack_version": ack_version,
            "ack_receipt_ref": ack_receipt_ref,
            "ack_correlation_id": correlation_id,
            "ack_traceparent": traceparent,
            "result": _ack_receipt_payload(
                delivery,
                digest=ack_digest,
                version=ack_version,
                receipt_ref=ack_receipt_ref,
                correlated=True,
                replayed=False,
            ),
        },
        lock=False,
    )
    propagation.status = PropagationStatus.SYNCED.value
    propagation.reason = "downstream_acknowledged"
    propagation.follow_up_commands = []
    propagation.version = propagation.version + 1
    propagation.last_event_id = event.id
    propagation.updated_by_id = None
    delivery.status = DeliveryStatus.SYNCED.value
    delivery.acknowledged_digest = ack_digest
    delivery.acknowledged_version = ack_version
    delivery.acknowledged_at = now_dt
    delivery.ack_receipt_ref = ack_receipt_ref
    delivery.ack_correlation_id = correlation_id
    delivery.ack_traceparent = traceparent
    delivery.last_error = None
    await session.flush()
    return _ack_receipt(delivery, replayed=False)


def _ack_receipt(
    delivery: GovernancePropagationDelivery,
    *,
    replayed: bool,
) -> dict[str, object]:
    return _ack_receipt_payload(
        delivery,
        digest=delivery.acknowledged_digest,
        version=delivery.acknowledged_version,
        receipt_ref=delivery.ack_receipt_ref,
        correlated=False,
        replayed=replayed,
    )


def _ack_receipt_payload(
    delivery: GovernancePropagationDelivery,
    *,
    digest: str | None,
    version: int | None,
    receipt_ref: str | None,
    correlated: bool,
    replayed: bool,
) -> dict[str, object]:
    return {
        "delivery_id": str(delivery.id),
        "propagation_id": str(delivery.propagation_id),
        "publication_id": str(delivery.publication_id),
        "surface_id": delivery.surface_id,
        "status": DeliveryStatus.SYNCED.value,
        "acknowledged_digest": digest,
        "acknowledged_version": version,
        "acknowledged_at": (
            delivery.acknowledged_at.isoformat()
            if delivery.acknowledged_at is not None
            else None
        ),
        "ack_receipt_ref": receipt_ref,
        "persisted": True,
        "rehearsal": False,
        "replayed": replayed,
    }


# ---------------------------------------------------------------------------
# Persisted receipt serialization
# ---------------------------------------------------------------------------


def delivery_to_dict(
    delivery: GovernancePropagationDelivery,
    *,
    include_payload: bool = False,
) -> dict[str, object]:
    return {
        "delivery_id": str(delivery.id),
        "propagation_id": str(delivery.propagation_id),
        "publication_id": str(delivery.publication_id),
        "surface_id": delivery.surface_id,
        "status": delivery.status,
        "command_id": delivery.command_id,
        "idempotency_key": delivery.idempotency_key,
        "desired_digest": delivery.desired_digest,
        "canonical_payload": (
            dict(delivery.canonical_payload) if include_payload else None
        ),
        "expected_page_version": delivery.expected_page_version,
        "expected_approval_version": delivery.expected_approval_version,
        "expected_binding_versions": list(delivery.expected_binding_versions),
        "attempts": delivery.attempts,
        "max_attempts": delivery.max_attempts,
        "actor_id": (str(delivery.actor_id) if delivery.actor_id is not None else None),
        "correlation_id": delivery.correlation_id,
        "traceparent": delivery.traceparent,
        "last_error": delivery.last_error,
        "attempt_evidence": dict(delivery.attempt_evidence or {}),
        "acknowledged_digest": delivery.acknowledged_digest,
        "acknowledged_version": delivery.acknowledged_version,
        "acknowledged_at": (
            delivery.acknowledged_at.isoformat()
            if delivery.acknowledged_at is not None
            else None
        ),
        "ack_receipt_ref": delivery.ack_receipt_ref,
        "created_at": (
            delivery.created_at.isoformat() if delivery.created_at is not None else None
        ),
        "updated_at": (
            delivery.updated_at.isoformat() if delivery.updated_at is not None else None
        ),
    }


async def list_propagation_deliveries(
    session: AsyncSession,
    propagation_ids: Sequence[uuid.UUID],
) -> tuple[GovernancePropagationDelivery, ...]:
    if not propagation_ids:
        return ()
    records = (
        (
            await session.execute(
                select(GovernancePropagationDelivery)
                .where(
                    GovernancePropagationDelivery.propagation_id.in_(propagation_ids)
                )
                .order_by(GovernancePropagationDelivery.surface_id)
            )
        )
        .scalars()
        .all()
    )
    return tuple(records)


async def delivery_targets_ready(
    *,
    settings: Settings | None = None,
    client_factory: Callable[[], httpx.AsyncClient] | None = None,
) -> bool:
    """Prove exact-route authentication and receipt storage for every target.

    Worker startup uses this non-mutating signed probe before claiming durable
    rows. An unavailable route or receipt store therefore delays recovery until
    the cron sweep instead of consuming an attempt during unordered restart.
    """
    resolved_settings = settings or get_settings()
    try:
        targets = resolved_settings.delivery_targets
        if not targets:
            return True
        secret = resolved_settings.delivery_hmac_secret
        if not secret:
            return False
        allowed_origins = delivery_target_origins(targets)
        allow_insecure_http = (
            resolved_settings.environment in resolved_settings.LOCAL_TEST_ENVIRONMENTS
        )
    except (DeliveryPolicyError, ValueError):
        return False

    timeout_seconds = min(
        resolved_settings.delivery_timeout_seconds,
        resolved_settings.health_probe_timeout_seconds,
    )
    client = (
        client_factory()
        if client_factory is not None
        else httpx.AsyncClient(timeout=timeout_seconds)
    )
    try:
        for base_url in sorted(set(targets.values())):
            request_url = validate_delivery_destination(
                delivery_endpoint_url(base_url),
                allowed_origins,
                allow_insecure_http=allow_insecure_http,
            )
            probe_body = b""
            response = await client.request(
                "HEAD",
                request_url,
                content=probe_body,
                headers={
                    "X-Cygnus-Signature": (f"sha256={sign_body(probe_body, secret)}")
                },
                timeout=timeout_seconds,
                follow_redirects=False,
            )
            if response.status_code != 204:
                return False
    except (DeliveryPolicyError, httpx.HTTPError, ValueError):
        return False
    finally:
        await client.aclose()
    return True


# ---------------------------------------------------------------------------
# Worker sweep: claim, dispatch, and record durable outcomes
# ---------------------------------------------------------------------------


async def drain_propagation_deliveries(
    *,
    now: datetime | None = None,
    limit: int = _DELIVERY_SWEEP_LIMIT,
    session_factory: Callable[[], AsyncSession] | None = None,
    settings: Settings | None = None,
    circuit: DeliveryCircuitBreaker | None = None,
    client_factory: Callable[[], httpx.AsyncClient] | None = None,
) -> int:
    """Claim one bounded delivery batch, dispatch it, and record outcomes.

    Returns the number of claimed deliveries. Rows whose surface has no
    configured target (or whose destination circuit is open) are returned to
    ``pending`` without fabricating an attempt.
    """
    if not 1 <= limit <= _DELIVERY_SWEEP_LIMIT:
        raise ValueError(f"limit must be between 1 and {_DELIVERY_SWEEP_LIMIT}")
    resolved_settings = settings or get_settings()
    if session_factory is None:
        from cygnus.runtime.database import get_async_session_factory

        session_factory = get_async_session_factory()
    resolved_circuit = circuit or _CIRCUIT_BREAKER
    targets = resolved_settings.delivery_targets
    allowed_origins = delivery_target_origins(targets)
    allow_insecure_http = (
        resolved_settings.environment in resolved_settings.LOCAL_TEST_ENVIRONMENTS
    )
    timeout_seconds = resolved_settings.delivery_timeout_seconds
    max_attempts = resolved_settings.delivery_max_attempts
    secret = resolved_settings.delivery_hmac_secret

    async with session_factory() as claim_session:
        try:
            claimed = await _claim_pending_deliveries(
                claim_session,
                now=now,
                limit=limit,
            )
            await claim_session.commit()
        except Exception:
            await claim_session.rollback()
            raise

    for claimed_delivery in claimed:
        try:
            await _execute_delivery_claim(
                session_factory,
                claimed_delivery,
                secret=secret,
                targets=targets,
                allowed_origins=allowed_origins,
                allow_insecure_http=allow_insecure_http,
                timeout_seconds=timeout_seconds,
                max_attempts=max_attempts,
                circuit=resolved_circuit,
                client_factory=client_factory,
            )
        except Exception as exc:
            logger.warning(
                "Propagation delivery {} claim crashed {}; reverted to pending",
                claimed_delivery.id,
                type(exc).__name__,
            )
            await _revert_to_pending(
                session_factory,
                claimed_delivery.id,
                last_error="sweep_crashed_" + type(exc).__name__.lower(),
            )
    return len(claimed)


async def _claim_pending_deliveries(
    session: AsyncSession,
    *,
    now: datetime | None,
    limit: int,
) -> tuple[GovernancePropagationDelivery, ...]:
    now_dt = now or datetime.now(timezone.utc)
    lease_cutoff = now_dt - timedelta(seconds=_DELIVERY_LEASE_TTL_SECONDS)
    rows = (
        (
            await session.execute(
                select(GovernancePropagationDelivery)
                .where(
                    or_(
                        GovernancePropagationDelivery.status
                        == DeliveryStatus.PENDING.value,
                        and_(
                            GovernancePropagationDelivery.status
                            == DeliveryStatus.IN_FLIGHT.value,
                            GovernancePropagationDelivery.updated_at < lease_cutoff,
                        ),
                    )
                )
                .order_by(
                    GovernancePropagationDelivery.created_at,
                    GovernancePropagationDelivery.id,
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.status = DeliveryStatus.IN_FLIGHT.value
    await session.flush()
    return tuple(rows)


async def _execute_delivery_claim(
    session_factory: Callable[[], AsyncSession],
    claimed: GovernancePropagationDelivery,
    *,
    secret: str,
    targets: Mapping[str, str],
    allowed_origins: set[str],
    allow_insecure_http: bool,
    timeout_seconds: float,
    max_attempts: int,
    circuit: DeliveryCircuitBreaker,
    client_factory: Callable[[], httpx.AsyncClient] | None,
) -> str:
    occurred_at = datetime.now(timezone.utc)
    delivery_id = claimed.id
    base_url = targets.get(claimed.surface_id)
    if base_url is None:
        # No adapter configured for this surface: keep it pending without
        # fabricating an attempt or failure truth.
        await _revert_to_pending(
            session_factory,
            delivery_id,
            last_error="no_configured_delivery_target",
        )
        return "skipped_no_target"
    try:
        request_url = validate_delivery_destination(
            delivery_endpoint_url(base_url),
            allowed_origins,
            allow_insecure_http=allow_insecure_http,
        )
    except DeliveryPolicyError as exc:
        await _record_terminal(
            session_factory,
            delivery_id,
            attempt=max(1, claimed.attempts + 1),
            status=DeliveryStatus.FAILED,
            reason="delivery_destination_rejected",
            last_error=str(exc),
            status_code=None,
            occurred_at=occurred_at,
        )
        return "rejected_destination"
    host = url_host(request_url)
    if not circuit.allow(host):
        await _revert_to_pending(
            session_factory,
            delivery_id,
            last_error="circuit_open",
        )
        return "skipped_circuit_open"

    owns_client = client_factory is None
    if client_factory is None:
        client = httpx.AsyncClient(timeout=timeout_seconds)
    else:
        client = client_factory()
    try:
        outcome = await send_delivery_request(
            claimed,
            secret=secret,
            request_url=request_url,
            timeout_seconds=timeout_seconds,
            allowed_origins=allowed_origins,
            allow_insecure_http=allow_insecure_http,
            circuit=circuit,
            client=client,
        )
    finally:
        if owns_client:
            await client.aclose()

    attempt = max(1, claimed.attempts + 1)
    if outcome.synced:
        assert outcome.ack_body is not None
        assert outcome.ack_signature is not None
        async with session_factory() as session:
            try:
                _ = await acknowledge_propagation_delivery(
                    session,
                    delivery_id=delivery_id,
                    ack_body=outcome.ack_body,
                    signature=outcome.ack_signature,
                    secret=secret,
                    correlation_id=outcome.ack_correlation_id,
                    traceparent=outcome.ack_traceparent,
                )
                synced_delivery = await session.get(
                    GovernancePropagationDelivery, delivery_id
                )
                if synced_delivery is None:
                    raise DeliveryReceiptNotFound(
                        f"delivery_id={delivery_id} disappeared after acknowledgment"
                    )
                synced_delivery.attempts = attempt
                _append_attempt_evidence(
                    synced_delivery,
                    attempt=attempt,
                    outcome="synced",
                    status_code=outcome.status_code,
                    last_error=None,
                    occurred_at=occurred_at,
                )
                await session.commit()
            except Exception:
                await session.rollback()
                raise
        return "synced"
    if outcome.retryable:
        if attempt >= max_attempts:
            await _record_terminal(
                session_factory,
                delivery_id,
                attempt=attempt,
                status=DeliveryStatus.DEAD_LETTER,
                reason="delivery_attempts_exhausted",
                last_error=outcome.error,
                status_code=outcome.status_code,
                occurred_at=occurred_at,
            )
            return "dead_lettered"
        await _record_retry(
            session_factory,
            delivery_id,
            attempt=attempt,
            last_error=outcome.error,
            status_code=outcome.status_code,
            occurred_at=occurred_at,
        )
        return "retry_scheduled"
    await _record_terminal(
        session_factory,
        delivery_id,
        attempt=attempt,
        status=DeliveryStatus.FAILED,
        reason="delivery_rejected",
        last_error=outcome.error,
        status_code=outcome.status_code,
        occurred_at=occurred_at,
    )
    return "failed"


async def _revert_to_pending(
    session_factory: Callable[[], AsyncSession],
    delivery_id: uuid.UUID,
    *,
    last_error: str | None,
) -> None:
    async with session_factory() as session:
        delivery = (
            await session.execute(
                select(GovernancePropagationDelivery)
                .where(GovernancePropagationDelivery.id == delivery_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if delivery is None or delivery.status == DeliveryStatus.SYNCED.value:
            await session.rollback()
            return
        delivery.status = DeliveryStatus.PENDING.value
        if last_error is not None:
            delivery.last_error = _bounded_error(last_error)
        await session.commit()


async def _record_retry(
    session_factory: Callable[[], AsyncSession],
    delivery_id: uuid.UUID,
    *,
    attempt: int,
    last_error: str | None,
    status_code: int | None,
    occurred_at: datetime,
) -> None:
    async with session_factory() as session:
        delivery = (
            await session.execute(
                select(GovernancePropagationDelivery)
                .where(GovernancePropagationDelivery.id == delivery_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if delivery is None or delivery.status == DeliveryStatus.SYNCED.value:
            await session.rollback()
            return
        delivery.status = DeliveryStatus.PENDING.value
        delivery.attempts = attempt
        delivery.last_error = _bounded_error(last_error)
        _append_attempt_evidence(
            delivery,
            attempt=attempt,
            outcome="retryable_error",
            status_code=status_code,
            last_error=last_error,
            occurred_at=occurred_at,
        )
        await session.commit()


async def _record_terminal(
    session_factory: Callable[[], AsyncSession],
    delivery_id: uuid.UUID,
    *,
    attempt: int,
    status: DeliveryStatus,
    reason: str,
    last_error: str | None,
    status_code: int | None,
    occurred_at: datetime,
) -> None:
    async with session_factory() as session:
        delivery = (
            await session.execute(
                select(GovernancePropagationDelivery)
                .where(GovernancePropagationDelivery.id == delivery_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if delivery is None or delivery.status == DeliveryStatus.SYNCED.value:
            await session.rollback()
            return
        delivery.status = status.value
        delivery.attempts = attempt
        delivery.last_error = _bounded_error(last_error)
        _append_attempt_evidence(
            delivery,
            attempt=attempt,
            outcome=status.value,
            status_code=status_code,
            last_error=last_error,
            occurred_at=occurred_at,
        )
        if status is DeliveryStatus.DEAD_LETTER:
            record_propagation_mismatch(kind="mismatch")
        await _transition_propagation(
            session,
            delivery,
            to_status=PropagationStatus.FAILED,
            reason=reason,
            follow_up_commands=("review_dead_letter_delivery",)
            if status is DeliveryStatus.DEAD_LETTER
            else (),
            idempotency_key=f"propagation-delivery:{delivery.id}:terminal",
            occurred_at=occurred_at,
            extra_payload={
                "delivery_status": status.value,
                "attempts": attempt,
                "last_error": _bounded_error(last_error),
            },
        )
        await session.commit()


async def _transition_propagation(
    session: AsyncSession,
    delivery: GovernancePropagationDelivery,
    *,
    to_status: PropagationStatus,
    reason: str,
    follow_up_commands: Sequence[str],
    idempotency_key: str,
    occurred_at: datetime,
    extra_payload: Mapping[str, object] | None = None,
) -> None:
    propagation = (
        await session.execute(
            select(GovernancePropagation)
            .where(GovernancePropagation.id == delivery.propagation_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if propagation is None:
        raise DeliveryReceiptNotFound(
            f"propagation_id={delivery.propagation_id} has no durable row"
        )
    if propagation.status == to_status.value and propagation.reason == reason:
        return
    publication = await session.get(GovernancePublication, delivery.publication_id)
    if publication is None:
        raise DeliveryReceiptNotFound(
            f"publication_id={delivery.publication_id} has no durable row"
        )
    await lock_draft_aggregate(session, publication.draft_id)
    current_event = await get_latest_draft_event(session, publication.draft_id)
    if current_event is None:
        raise DeliveryAckConflict(
            f"draft_id={publication.draft_id} has no governance state"
        )
    payload: dict[str, object] = {
        "publication_id": str(publication.id),
        "surface_id": delivery.surface_id,
        "previous_status": propagation.status,
        "status": to_status.value,
        "previous_version": propagation.version,
        "version": propagation.version + 1,
        "delivery_id": str(delivery.id),
        "delivery_status": delivery.status,
    }
    if extra_payload:
        payload.update(extra_payload)
    event = await append_draft_event(
        session,
        draft_id=publication.draft_id,
        event_type=GovernanceEventType.PROPAGATION_UPDATED,
        from_state=current_event.to_state,
        to_state=current_event.to_state,
        actor_id=None,
        idempotency_key=idempotency_key,
        reason=reason,
        payload=payload,
        lock=False,
    )
    propagation.status = to_status.value
    propagation.reason = reason
    propagation.follow_up_commands = list(follow_up_commands)
    propagation.version = propagation.version + 1
    propagation.last_event_id = event.id
    propagation.updated_by_id = None
    await session.flush()


def _append_attempt_evidence(
    delivery: GovernancePropagationDelivery,
    *,
    attempt: int,
    outcome: str,
    status_code: int | None,
    last_error: str | None,
    occurred_at: datetime,
) -> None:
    entries = delivery.attempt_evidence or {}
    raw_attempts = entries.get("attempts")
    attempts = list(raw_attempts) if isinstance(raw_attempts, list) else []
    attempts.append(
        {
            "attempt": attempt,
            "at": occurred_at.isoformat(),
            "outcome": outcome,
            "status_code": status_code,
            "error": _bounded_error(last_error),
        }
    )
    cap = max(1, delivery.max_attempts)
    delivery.attempt_evidence = {**entries, "attempts": attempts[-cap:]}


def _bounded_error(error: str | None) -> str | None:
    if error is None:
        return None
    normalized = error.strip()
    if not normalized:
        return None
    return normalized[:_MAX_ERROR_CHARS]


# Module-level circuit breaker shared by worker sweeps in this process.
_CIRCUIT_BREAKER = DeliveryCircuitBreaker()


def reset_delivery_circuit() -> None:
    """Drop in-memory circuit state (used by deterministic tests)."""
    _CIRCUIT_BREAKER.reset()
