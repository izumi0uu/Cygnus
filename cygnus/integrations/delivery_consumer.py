"""Bounded production receipt adapter for signed propagation deliveries.

This ASGI application accepts only the frozen internal propagation-delivery
contract.  It persists replay metadata rather than support content, then emits
the canonical signed acknowledgment the Cygnus delivery worker verifies.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Final, cast

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError

from cygnus.publish.delivery import (
    canonical_delivery_digest,
    canonical_json,
    sign_body,
    verify_ack_signature,
)
from cygnus.runtime.config import get_settings
from cygnus.runtime.database import get_async_session_factory
from cygnus.runtime.database.models import DeliveryConsumerReceipt

# The outbound adapter accepts signed acknowledgment bodies up to 1 MiB.  Keep
# the receiver at the same bounded protocol size before parsing or persisting.
_MAX_DELIVERY_BODY_BYTES: Final = 1024 * 1024
_MAX_DELIVERY_ID_CHARS: Final = 220
_MAX_SURFACE_ID_CHARS: Final = 120
_MAX_OBJECT_VERSION: Final = 2_147_483_647

app = FastAPI(
    title="Cygnus Delivery Consumer",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


class _DeliveryRequestError(ValueError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class _DeliveryReplayConflict(ValueError):
    """A receipt key has already bound different immutable delivery metadata."""


class _ReceiptStoreUnavailable(RuntimeError):
    """The receipt database transaction could not complete safely."""


@dataclass(frozen=True, slots=True)
class _ReceiptIdentity:
    delivery_id: str
    body_sha256: str
    publication_id: uuid.UUID
    surface_id: str
    object_version: int
    receipt_ref: str


def _error(status_code: int, detail: str) -> JSONResponse:
    """Return a deliberately bounded error without request or secret material."""
    return JSONResponse(status_code=status_code, content={"detail": detail})


def _configured_secret() -> str | None:
    """Resolve the existing shared secret without exposing configuration details."""
    try:
        secret = get_settings().delivery_hmac_secret
    except Exception:
        return None
    return secret or None


def _valid_signature(request: Request, body: bytes, secret: str) -> bool:
    signature_values = request.headers.getlist("X-Cygnus-Signature")
    signature = signature_values[0] if len(signature_values) == 1 else ""
    return verify_ack_signature(body, signature, secret)


def _required_header(request: Request, name: str, maximum: int) -> str:
    raw_values = request.headers.getlist(name)
    if len(raw_values) != 1:
        raise _DeliveryRequestError(400, f"{name} header is required")
    raw_value = raw_values[0]
    value = raw_value.strip()
    if not value or value != raw_value or len(value) > maximum:
        raise _DeliveryRequestError(400, f"{name} header is invalid")
    return value


def _optional_response_header(
    request: Request, name: str, maximum: int = 200
) -> str | None:
    """Echo one bounded trace header without trusting malformed duplicates."""
    raw_values = request.headers.getlist(name)
    if len(raw_values) != 1:
        return None
    raw_value = raw_values[0]
    value = raw_value.strip()
    if not value or value != raw_value or len(value) > maximum:
        return None
    return value


def _reject_nonfinite_json(_value: str) -> object:
    raise ValueError("non-finite JSON constants are not accepted")


async def _read_bounded_body(request: Request) -> bytes:
    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            parsed_length = int(declared_length)
        except ValueError as exc:
            raise _DeliveryRequestError(
                400, "delivery content length is invalid"
            ) from exc
        if parsed_length < 0:
            raise _DeliveryRequestError(400, "delivery content length is invalid")
        if parsed_length > _MAX_DELIVERY_BODY_BYTES:
            raise _DeliveryRequestError(413, "delivery body exceeds the size limit")

    body = bytearray()
    try:
        async for chunk in request.stream():
            if len(body) + len(chunk) > _MAX_DELIVERY_BODY_BYTES:
                raise _DeliveryRequestError(413, "delivery body exceeds the size limit")
            body.extend(chunk)
    except _DeliveryRequestError:
        raise
    except Exception as exc:
        raise _DeliveryRequestError(400, "delivery body could not be read") from exc
    return bytes(body)


def _require_json_content_type(request: Request) -> None:
    content_type = request.headers.get("content-type", "")
    media_type = content_type.split(";", maxsplit=1)[0].strip().lower()
    if media_type != "application/json":
        raise _DeliveryRequestError(
            415, "delivery content type must be application/json"
        )


def _receipt_ref(
    *,
    delivery_id: str,
    body_sha256: str,
    publication_id: uuid.UUID,
    surface_id: str,
    object_version: int,
) -> str:
    """Return one stable, bounded reference for the immutable receipt binding."""
    identity_digest = canonical_delivery_digest(
        {
            "body_sha256": body_sha256,
            "delivery_id": delivery_id,
            "object_version": object_version,
            "publication_id": str(publication_id),
            "surface_id": surface_id,
        }
    )
    return f"delivery-consumer:{identity_digest}"


def _decode_identity(request: Request, body: bytes) -> _ReceiptIdentity:
    try:
        decoded = json.loads(
            body.decode("utf-8"),
            parse_constant=_reject_nonfinite_json,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as exc:
        raise _DeliveryRequestError(400, "delivery body is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise _DeliveryRequestError(400, "delivery body must be a JSON object")
    payload = cast(dict[str, object], decoded)

    # The sender signs canonical_json(payload).  Reject alternate encodings so
    # canonical_delivery_digest(payload) is precisely the SHA-256 of `body`.
    try:
        canonical_body = canonical_json(payload)
    except (RecursionError, TypeError, ValueError) as exc:
        raise _DeliveryRequestError(400, "delivery body is not canonical JSON") from exc
    if canonical_body != body:
        raise _DeliveryRequestError(400, "delivery body is not canonical JSON")

    delivery_id = _required_header(
        request,
        "X-Cygnus-Delivery-Id",
        _MAX_DELIVERY_ID_CHARS,
    )
    header_publication_id = _required_header(
        request,
        "X-Cygnus-Publication-Id",
        36,
    )
    publication_value = payload.get("publication_id")
    if (
        not isinstance(publication_value, str)
        or publication_value != header_publication_id
    ):
        raise _DeliveryRequestError(400, "delivery publication identity does not match")
    try:
        publication_id = uuid.UUID(publication_value)
    except ValueError as exc:
        raise _DeliveryRequestError(
            400, "delivery publication identity is invalid"
        ) from exc
    if str(publication_id) != publication_value:
        raise _DeliveryRequestError(400, "delivery publication identity is invalid")

    surface_id = _required_header(
        request,
        "X-Cygnus-Surface",
        _MAX_SURFACE_ID_CHARS,
    )
    expected_delivery_id = f"delivery:{publication_id}:{surface_id}"
    if delivery_id != expected_delivery_id:
        raise _DeliveryRequestError(400, "delivery receipt identity does not match")
    raw_object_version = payload.get("object_version")
    if not isinstance(raw_object_version, int) or isinstance(raw_object_version, bool):
        raise _DeliveryRequestError(400, "delivery object_version must be positive")
    object_version = raw_object_version
    if object_version < 1 or object_version > _MAX_OBJECT_VERSION:
        raise _DeliveryRequestError(400, "delivery object_version must be positive")

    target_channels = payload.get("target_channels")
    if not isinstance(target_channels, list) or not target_channels:
        raise _DeliveryRequestError(400, "delivery target_channels are invalid")
    if any(
        not isinstance(channel, str)
        or not channel
        or channel != channel.strip()
        or len(channel) > _MAX_SURFACE_ID_CHARS
        for channel in target_channels
    ):
        raise _DeliveryRequestError(400, "delivery target_channels are invalid")
    normalized_channels = cast(list[str], target_channels)
    if len(set(normalized_channels)) != len(normalized_channels):
        raise _DeliveryRequestError(400, "delivery target_channels are invalid")
    if surface_id not in normalized_channels:
        raise _DeliveryRequestError(400, "delivery surface is not a target channel")

    try:
        body_sha256 = canonical_delivery_digest(payload)
    except (RecursionError, TypeError, ValueError) as exc:
        raise _DeliveryRequestError(400, "delivery body is not canonical JSON") from exc
    return _ReceiptIdentity(
        delivery_id=delivery_id,
        body_sha256=body_sha256,
        publication_id=publication_id,
        surface_id=surface_id,
        object_version=object_version,
        receipt_ref=_receipt_ref(
            delivery_id=delivery_id,
            body_sha256=body_sha256,
            publication_id=publication_id,
            surface_id=surface_id,
            object_version=object_version,
        ),
    )


def _stored_identity(receipt: DeliveryConsumerReceipt) -> _ReceiptIdentity:
    return _ReceiptIdentity(
        delivery_id=receipt.delivery_id,
        body_sha256=receipt.body_sha256,
        publication_id=receipt.publication_id,
        surface_id=receipt.surface_id,
        object_version=receipt.object_version,
        receipt_ref=receipt.receipt_ref,
    )


def _same_identity(
    receipt: DeliveryConsumerReceipt,
    incoming: _ReceiptIdentity,
) -> bool:
    return (
        receipt.body_sha256 == incoming.body_sha256
        and receipt.publication_id == incoming.publication_id
        and receipt.surface_id == incoming.surface_id
        and receipt.object_version == incoming.object_version
        and receipt.receipt_ref == incoming.receipt_ref
    )


async def _persist_receipt(incoming: _ReceiptIdentity) -> _ReceiptIdentity:
    """Atomically create one receipt or return its exact immutable replay."""
    try:
        session_factory = get_async_session_factory()
        async with session_factory() as session:
            statement = (
                pg_insert(DeliveryConsumerReceipt)
                .values(
                    delivery_id=incoming.delivery_id,
                    body_sha256=incoming.body_sha256,
                    publication_id=incoming.publication_id,
                    surface_id=incoming.surface_id,
                    object_version=incoming.object_version,
                    receipt_ref=incoming.receipt_ref,
                )
                .on_conflict_do_nothing(index_elements=["delivery_id"])
                .returning(DeliveryConsumerReceipt.delivery_id)
            )
            inserted = (await session.execute(statement)).scalar_one_or_none()
            if inserted is not None:
                await session.commit()
                return incoming

            receipt = await session.scalar(
                select(DeliveryConsumerReceipt).where(
                    DeliveryConsumerReceipt.delivery_id == incoming.delivery_id
                )
            )
            if receipt is None:
                raise _ReceiptStoreUnavailable()
            if not _same_identity(receipt, incoming):
                raise _DeliveryReplayConflict()
            return _stored_identity(receipt)
    except _DeliveryReplayConflict:
        raise
    except _ReceiptStoreUnavailable:
        raise
    except SQLAlchemyError as exc:
        raise _ReceiptStoreUnavailable() from exc
    except Exception as exc:
        raise _ReceiptStoreUnavailable() from exc


def _ack_body(receipt: _ReceiptIdentity) -> bytes:
    return canonical_json(
        {
            "digest": receipt.body_sha256,
            "publication_id": str(receipt.publication_id),
            "receipt_ref": receipt.receipt_ref,
            "surface_id": receipt.surface_id,
            "version": receipt.object_version,
        }
    )


async def _receipt_store_ready() -> bool:
    try:
        session_factory = get_async_session_factory()
        async with session_factory() as session:
            # Reading the receipt table verifies both database reachability and
            # that the consumer's migration has been applied.
            await session.execute(select(DeliveryConsumerReceipt.delivery_id).limit(1))
    except Exception:
        return False
    return True


@app.get("/health")
async def health() -> Response:
    """Report ready only when signing configuration and receipt storage work."""
    if _configured_secret() is None or not await _receipt_store_ready():
        return _error(503, "delivery consumer is unavailable")
    return JSONResponse(content={"status": "ok", "database": "ready"})


@app.head("/api/internal/propagation-delivery")
async def delivery_readiness(request: Request) -> Response:
    """Prove exact-route authentication and receipt-store readiness, without writes."""
    secret = _configured_secret()
    if secret is None:
        return _error(503, "delivery consumer is unavailable")
    try:
        body = await _read_bounded_body(request)
    except _DeliveryRequestError as exc:
        return _error(exc.status_code, exc.detail)
    if body or not _valid_signature(request, body, secret):
        return _error(401, "delivery readiness signature is invalid")
    if not await _receipt_store_ready():
        return _error(503, "delivery receipt store is unavailable")
    return Response(status_code=204)


@app.post("/api/internal/propagation-delivery")
async def accept_propagation_delivery(request: Request) -> Response:
    """Persist a signed delivery acceptance and return its signed canonical ack."""
    secret = _configured_secret()
    if secret is None:
        return _error(503, "delivery consumer is unavailable")

    try:
        _require_json_content_type(request)
        body = await _read_bounded_body(request)
    except _DeliveryRequestError as exc:
        return _error(exc.status_code, exc.detail)

    if not _valid_signature(request, body, secret):
        return _error(401, "delivery signature is invalid")

    try:
        incoming = _decode_identity(request, body)
    except _DeliveryRequestError as exc:
        return _error(exc.status_code, exc.detail)

    try:
        receipt = await _persist_receipt(incoming)
    except _DeliveryReplayConflict:
        return _error(409, "delivery receipt identity conflicts")
    except _ReceiptStoreUnavailable:
        return _error(503, "delivery receipt store is unavailable")

    ack_body = _ack_body(receipt)
    response_headers = {
        "X-Cygnus-Ack-Signature": f"sha256={sign_body(ack_body, secret)}"
    }
    for header_name in ("X-Cygnus-Correlation-Id", "traceparent"):
        header_value = _optional_response_header(request, header_name)
        if header_value is not None:
            response_headers[header_name] = header_value
    return Response(
        content=ack_body,
        media_type="application/json",
        headers=response_headers,
    )
