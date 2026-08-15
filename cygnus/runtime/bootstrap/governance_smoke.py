"""Compose-only durable governance golden-path smoke.

This module seeds one isolated, persisted support-governance aggregate, exercises
its public API path, and writes a receipt that survives an API process restart.
It is development verification infrastructure, never a production fixture
provider and never imported by runtime request handlers.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
from dataclasses import dataclass
import os
from pathlib import Path
from typing import cast
from urllib.parse import quote
import uuid

import httpx
from sqlalchemy import select

from cygnus.domain.audience import AudienceFilter, Visibility
from cygnus.domain.objects import KnowledgeObjectType, governed_object_ref
from cygnus.evidence.records import FreshnessState
from cygnus.governance.audience_bindings import (
    AudienceBindingCreate,
    create_audience_binding,
)
from cygnus.governance.signals import GovernanceSignalInput, create_governance_signal
from cygnus.review.contributions import (
    approve_wiki_draft,  # pyright: ignore[reportUnknownVariableType]
    create_wiki_draft,  # pyright: ignore[reportUnknownVariableType]
)
from cygnus.review.intake import PressureSignalType
from cygnus.runtime.database import get_async_session_factory
from cygnus.runtime.database.models import Employee, Notification, Source
from cygnus.runtime.services.notification_service import NotificationType, notify

_DEFAULT_RECEIPT_PATH = Path("/tmp/cygnus-governance-golden-path.json")
_TARGET_CHANNELS = ("agent-copilot", "internal-search")
_NOTIFICATION_TYPES = (
    NotificationType.WIKI_DRAFT_SUBMITTED,
    NotificationType.WIKI_DRAFT_RESUBMITTED,
    NotificationType.WIKI_DRAFT_CHANGES_REQUESTED,
    NotificationType.WIKI_DRAFT_REJECTED,
    NotificationType.WIKI_DRAFT_APPROVED,
    NotificationType.WIKI_DRAFT_WITHDRAWN,
)


class GoldenPathSmokeError(RuntimeError):
    """The compose golden path violated a durable-governance contract."""


def _require(condition: object, message: str) -> None:
    if not condition:
        raise GoldenPathSmokeError(message)


def _mapping(value: object, label: str) -> dict[str, object]:
    _require(isinstance(value, dict), f"{label} must be a JSON object")
    return cast(dict[str, object], value)


def _items(value: object, label: str) -> list[dict[str, object]]:
    _require(isinstance(value, list), f"{label} must be a JSON array")
    rows = cast(list[object], value)
    _require(
        all(isinstance(row, dict) for row in rows), f"{label} rows must be objects"
    )
    return [cast(dict[str, object], row) for row in rows]


def _write_receipt(path: Path, receipt: dict[str, object]) -> None:
    _ = path.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")


def _read_receipt(path: Path) -> dict[str, object]:
    try:
        payload = cast(object, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        raise GoldenPathSmokeError(f"cannot read smoke receipt {path}: {exc}") from exc
    return _mapping(payload, "smoke receipt")


async def _seed_persisted_truth(admin_email: str) -> dict[str, object]:
    run_id = uuid.uuid4().hex[:12]
    slug = f"cyg111-durable-{run_id}"
    signal_ref = f"ticket:cyg111:{run_id}"
    session_factory = get_async_session_factory()

    async with session_factory() as session:
        admin = (
            await session.execute(select(Employee).where(Employee.email == admin_email))
        ).scalar_one_or_none()
        _require(admin is not None, f"seeded admin {admin_email} was not found")
        assert admin is not None

        source = Source(
            title=f"CYG-111 verified support evidence {run_id}",
            full_text="Verified billing support policy evidence for the durable smoke path.",
            source_type="url",
            url=f"https://example.test/cyg111/{run_id}",
            status="ready",
            progress=100,
            freshness_state="fresh",
            freshness_actor_id=admin.id,
            freshness_reason="Attested fresh for the durable golden-path smoke.",
            freshness_attested_at=datetime.now(timezone.utc) + timedelta(seconds=2),
            freshness_expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
        session.add(source)
        await session.flush()

        draft = await create_wiki_draft(
            session,
            page_id=None,
            author_id=admin.id,
            content_md=(
                "# Durable billing support policy\n\n"
                "Use verified source evidence and the governed audience binding."
            ),
            note="CYG-111 durable golden-path review",
            source="compose_smoke",
            draft_kind="create",
            source_metadata={"source_ids": [str(source.id)]},
            suggested_metadata={
                "slug": slug,
                "title": f"CYG-111 Durable Billing Policy {run_id}",
                "page_type": "concept",
                "knowledge_type_slugs": ["answer_card"],
                "scope_type": "global",
                "scope_id": None,
            },
        )
        page = await approve_wiki_draft(
            session,
            draft,
            reviewer_id=admin.id,
            reviewer_note="Evidence, scope, and audience binding verified by compose smoke.",
        )
        _require(
            page.source_ids == [source.id],
            "approved page did not carry the reviewed evidence source",
        )
        object_ref = governed_object_ref(page.id)

        audience = AudienceFilter(
            visibility=Visibility.INTERNAL,
            product_lines=("billing",),
            regions=("global",),
            languages=("zh", "en"),
        )
        binding_keys: list[str] = []
        for channel in _TARGET_CHANNELS:
            binding, replayed = await create_audience_binding(
                session,
                command=AudienceBindingCreate(
                    page_id=page.id,
                    object_ref=object_ref,
                    variant_ref="internal-governed",
                    channel=channel,
                    audience_filter=audience,
                ),
                actor_id=admin.id,
            )
            _require(
                not replayed, f"fresh smoke binding unexpectedly replayed: {channel}"
            )
            binding_keys.append(binding.binding_key)

        signal = await create_governance_signal(
            session,
            GovernanceSignalInput(
                signal_ref=signal_ref,
                signal_type=PressureSignalType.TICKET_CLUSTER,
                object_ref=object_ref,
                title=f"CYG-111 billing pressure {run_id}",
                object_type=KnowledgeObjectType.ANSWER_CARD,
                page_id=page.id,
                source_id=source.id,
                audience_filter=audience,
                affected_surfaces=_TARGET_CHANNELS,
                trigger_signals=("ticket_volume:12", "rewrite_count:4"),
                freshness=FreshnessState.FRESH,
                summary="Repeated billing tickets require a governed policy publication.",
                reason="Persisted ticket pressure crossed the review threshold.",
                evidence_excerpt="Twelve verified tickets repeat the same billing policy gap.",
            ),
            created_by_id=admin.id,
        )

        notifications: list[Notification] = []
        for index, notification_type in enumerate(_NOTIFICATION_TYPES, start=1):
            notifications.append(
                await notify(
                    session,
                    recipient_id=admin.id,
                    type=notification_type,
                    subject=f"CYG-111 revision {index} · {run_id}",
                    target_type="wiki_draft",
                    target_id=object_ref,
                    body=f"Persisted governance lifecycle record {index} for browser cloud proof.",
                    actor_id=admin.id,
                )
            )
        await session.flush()
        await session.commit()

        return {
            "run_id": run_id,
            "admin_email": admin_email,
            "object_ref": object_ref,
            "signal_ref": signal.signal_ref,
            "page_id": str(page.id),
            "draft_id": str(draft.id),
            "source_id": str(source.id),
            "binding_keys": binding_keys,
            "notification_ids": [str(item.id) for item in notifications],
        }


def _request_json(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    expected_status: int = 200,
    params: dict[str, str] | None = None,
    json_body: dict[str, object] | None = None,
) -> object:
    response = client.request(method, path, params=params, json=json_body)
    if response.status_code != expected_status:
        raise GoldenPathSmokeError(
            f"{method} {path} returned {response.status_code}, "
            + f"expected {expected_status}: {response.text}"
        )
    try:
        return cast(object, response.json())
    except json.JSONDecodeError as exc:
        raise GoldenPathSmokeError(f"{method} {path} returned non-JSON data") from exc


def _authenticated_client(
    *,
    base_url: str,
    admin_email: str,
    admin_password: str,
) -> httpx.Client:
    login_response = httpx.post(
        f"{base_url.rstrip('/')}/api/auth/login",
        json={"email": admin_email, "password": admin_password},
        timeout=20.0,
    )
    if login_response.status_code != 200:
        raise GoldenPathSmokeError(
            f"POST /api/auth/login returned {login_response.status_code}: {login_response.text}"
        )
    login = _mapping(cast(object, login_response.json()), "login response")
    token = login.get("access_token")
    _require(isinstance(token, str) and token, "login response has no access token")
    client = httpx.Client(base_url=base_url, timeout=20.0)
    client.headers["Authorization"] = f"Bearer {token}"
    return client


def _assert_surface_contains_object(
    payload: dict[str, object], object_ref: str
) -> None:
    priority_stack = _items(
        payload.get("priority_stack"), "command-center priority_stack"
    )
    _require(
        any(row.get("object_ref") == object_ref for row in priority_stack),
        f"command center does not contain persisted object {object_ref}",
    )


def _assert_publish_audit(
    client: httpx.Client,
    *,
    draft_id: str,
    command_id: str,
) -> dict[str, object]:
    audit = _mapping(
        _request_json(
            client,
            "GET",
            "/api/governance/audit",
            params={"phase": "publish", "draft_id": draft_id},
        ),
        "publish audit",
    )
    _require(audit.get("persisted") is True, "publish audit is not persisted truth")
    _require(audit.get("rehearsal") is False, "publish audit is marked as rehearsal")
    events = _items(audit.get("items"), "publish audit items")
    _require(
        any(
            row.get("event_type") == "published"
            and _mapping(row.get("details"), "publish event details").get("command_id")
            == command_id
            for row in events
        ),
        f"publish audit has no event for command {command_id}",
    )
    return audit


def _exercise_api(
    receipt: dict[str, object],
    *,
    base_url: str,
    admin_password: str,
) -> dict[str, object]:
    object_ref = cast(str, receipt["object_ref"])
    signal_ref = cast(str, receipt["signal_ref"])
    with _authenticated_client(
        base_url=base_url,
        admin_email=cast(str, receipt["admin_email"]),
        admin_password=admin_password,
    ) as client:
        command_center = _mapping(
            _request_json(client, "GET", "/api/command-center"),
            "command center",
        )
        _assert_surface_contains_object(command_center, object_ref)

        review_intake = _mapping(
            _request_json(client, "GET", "/api/review-intake"),
            "review intake",
        )
        bundles = _items(review_intake.get("bundles"), "review intake bundles")
        _require(
            any(row.get("proposal_id") == object_ref for row in bundles),
            f"review intake does not contain persisted object {object_ref}",
        )

        assignment = _mapping(
            _request_json(
                client,
                "POST",
                f"/api/review-assignments/{quote(signal_ref, safe='')}/commands",
                json_body={
                    "command_id": f"assign:{receipt['run_id']}",
                    "action": "assign",
                    "owner_ref": "support-governance",
                    "reason": "CYG-111 durable golden-path owner assignment.",
                    "expected_version": 1,
                },
            ),
            "review assignment",
        )
        assignment_record = _mapping(assignment.get("assignment"), "assignment record")
        _require(
            assignment_record.get("persisted") is True, "assignment was not persisted"
        )
        _require(
            assignment_record.get("lifecycle_state") == "assigned",
            "assignment did not enter assigned state",
        )

        preview = _mapping(
            _request_json(
                client,
                "GET",
                "/api/publish-preview",
                params={"object_ref": object_ref, "action_key": "publish"},
            ),
            "publish preview",
        )
        _require(
            preview.get("persisted") is True,
            "publish preview lacks persisted input truth",
        )
        _require(
            preview.get("rehearsal") is False, "publish preview is marked as rehearsal"
        )
        durable_command = _mapping(preview.get("durable_command"), "durable command")
        _require(
            durable_command.get("action_key") == "publish",
            "publish preview did not qualify the durable publish action",
        )

        apply_result = _mapping(
            _request_json(
                client,
                "POST",
                "/api/publish/apply",
                json_body=durable_command,
            ),
            "durable publish apply",
        )
        _require(
            apply_result.get("persisted") is True, "publish apply was not persisted"
        )
        _require(
            apply_result.get("rehearsal") is False,
            "publish apply is marked as rehearsal",
        )
        _require(
            apply_result.get("replayed") is False,
            "first publish apply unexpectedly replayed",
        )
        publication_id = apply_result.get("publication_record_id")
        command_id = apply_result.get("command_id")
        _require(
            isinstance(publication_id, str) and publication_id,
            "publish receipt lacks publication_record_id",
        )
        _require(
            isinstance(command_id, str) and command_id,
            "publish receipt lacks command_id",
        )

        propagation = _mapping(
            _request_json(
                client,
                "GET",
                "/api/publish-propagation",
                params={"publication_id": cast(str, publication_id)},
            ),
            "publish propagation",
        )
        _require(
            propagation.get("persisted") is True, "propagation is not persisted truth"
        )
        _require(
            propagation.get("rehearsal") is False, "propagation is marked as rehearsal"
        )
        ledger = _mapping(propagation.get("propagation_ledger"), "propagation ledger")
        summary = _mapping(ledger.get("summary"), "propagation summary")
        _require(
            summary.get("pending") == len(_TARGET_CHANNELS),
            "initial propagation is not pending on both target channels",
        )
        # The initial smoke stages one pending delivery per surface with a
        # canonical desired digest. Persisted domain certification drives these
        # rows through the real production delivery consumer.
        records = _items(ledger.get("records"), "propagation records")
        _require(len(records) == len(_TARGET_CHANNELS), "propagation record count")
        delivery_ids: list[object] = []
        for record in records:
            desired_digest = record.get("desired_digest")
            _require(
                isinstance(desired_digest, str) and len(desired_digest) == 64,
                "propagation record lacks a canonical desired digest",
            )
            int(cast(str, desired_digest), 16)
            delivery = _mapping(record.get("delivery"), "delivery receipt")
            _require(
                delivery.get("status") == "pending",
                "fresh delivery receipt is not pending",
            )
            _require(
                delivery.get("desired_digest") == desired_digest,
                "delivery receipt digest does not match the propagation digest",
            )
            _require(
                isinstance(delivery.get("delivery_id"), str)
                and delivery.get("delivery_id"),
                "delivery receipt lacks a durable identity",
            )
            delivery_ids.append(delivery.get("delivery_id"))
        if len(set(delivery_ids)) != len(_TARGET_CHANNELS):
            raise GoldenPathSmokeError(
                "delivery receipts are not one identity per surface"
            )
        delivery_ids.sort()

        recovery = _mapping(
            _request_json(
                client,
                "GET",
                f"/api/recovery/window/{quote(cast(str, command_id), safe='')}",
            ),
            "recovery window",
        )
        _require(
            recovery.get("persisted") is True, "recovery window is not persisted truth"
        )
        _require(
            recovery.get("rehearsal") is False, "recovery window is marked as rehearsal"
        )

        _ = _assert_publish_audit(
            client,
            draft_id=cast(str, receipt["draft_id"]),
            command_id=cast(str, command_id),
        )

        traceability = _mapping(
            _request_json(
                client,
                "GET",
                f"/api/traceability/{quote(object_ref, safe='')}",
            ),
            "traceability",
        )
        projection = _mapping(traceability.get("projection"), "traceability projection")
        _require(
            projection.get("persisted") is True,
            "traceability did not prefer durable projection",
        )
        _require(
            projection.get("publication_record_id") == publication_id,
            "traceability projection points at a different publication",
        )
        client.headers["X-Cygnus-Session-Contract-Version"] = "1.0"
        retrieval = _mapping(
            _request_json(
                client,
                "POST",
                "/api/session-bridge/query",
                json_body={
                    "request_ref": f"smoke-query:{receipt['run_id']}",
                    "session_ref": f"smoke-session:{receipt['run_id']}",
                    "query": "durable billing support policy",
                    "channel": "agent-copilot",
                    "audience_context": {
                        "visibility": "internal",
                        "product_line": "billing",
                        "region": "global",
                        "language": "en",
                    },
                },
            ),
            "governed retrieval",
        )
        retrieval_data = _mapping(retrieval.get("data"), "governed retrieval data")
        retrieval_governance = _mapping(
            retrieval_data.get("governance"), "governed retrieval decision"
        )
        retrieval_answer = _mapping(
            retrieval_data.get("answer"), "governed retrieval answer"
        )
        _require(
            retrieval_governance.get("state") == "restricted",
            "pending downstream delivery did not restrict governed retrieval",
        )
        _require(
            retrieval_answer.get("content") is None,
            "restricted governed retrieval exposed answer content",
        )
        retrieval_evidence = {
            "governance_state": retrieval_governance.get("state"),
            "governance_codes": retrieval_governance.get("codes"),
            "answer_content_exposed": False,
        }

        notifications = _items(
            _request_json(client, "GET", "/api/notifications"),
            "notifications",
        )
        seeded_notification_ids = set(cast(list[str], receipt["notification_ids"]))
        returned_notification_ids = {cast(str, row.get("id")) for row in notifications}
        _require(
            seeded_notification_ids <= returned_notification_ids,
            "recipient-scoped notification list lost seeded durable records",
        )
        marked_notification_id = cast(list[str], receipt["notification_ids"])[-1]
        marked = _mapping(
            _request_json(
                client,
                "POST",
                f"/api/notifications/{marked_notification_id}/read",
            ),
            "marked notification",
        )
        _require(
            marked.get("persisted") is True,
            "notification read transition was not persisted",
        )
        _require(
            marked.get("lifecycle_state") == "read",
            "notification did not enter read state",
        )

    return receipt | {
        "durable_command": durable_command,
        "publication_id": publication_id,
        "command_id": command_id,
        "marked_notification_id": marked_notification_id,
        "delivery_ids": delivery_ids,
        "retrieval": retrieval_evidence,
    }


def _verify_after_restart(
    receipt: dict[str, object],
    *,
    base_url: str,
    admin_password: str,
) -> dict[str, object]:
    object_ref = cast(str, receipt["object_ref"])
    publication_id = cast(str, receipt["publication_id"])
    command_id = cast(str, receipt["command_id"])
    durable_command = _mapping(
        receipt.get("durable_command"), "receipt durable_command"
    )

    with _authenticated_client(
        base_url=base_url,
        admin_email=cast(str, receipt["admin_email"]),
        admin_password=admin_password,
    ) as client:
        replay = _mapping(
            _request_json(
                client,
                "POST",
                "/api/publish/apply",
                json_body=durable_command,
            ),
            "publish replay",
        )
        _require(replay.get("persisted") is True, "publish replay lost persisted truth")
        _require(replay.get("rehearsal") is False, "publish replay became a rehearsal")
        _require(replay.get("replayed") is True, "publish replay was not idempotent")
        _require(
            replay.get("publication_record_id") == publication_id,
            "publish replay created or selected a different publication",
        )

        publication = _mapping(
            _request_json(
                client,
                "GET",
                f"/api/governance-publications/{publication_id}",
            ),
            "governance publication",
        )
        _require(
            publication.get("publication_record_id") == publication_id,
            "publication lookup returned a different row",
        )
        _require(
            publication.get("command_id") == command_id,
            "publication command_id changed after restart",
        )

        propagation = _mapping(
            _request_json(
                client,
                "GET",
                "/api/publish-propagation",
                params={"publication_id": publication_id},
            ),
            "restart propagation",
        )
        _require(
            propagation.get("persisted") is True,
            "restart propagation is not persisted truth",
        )
        _require(
            propagation.get("publication_record_id") == publication_id,
            "restart propagation selected another publication",
        )
        # Restart/retry preserves one delivery identity per surface with the
        # same canonical desired digest before real consumer dispatch.
        restart_ledger = _mapping(
            propagation.get("propagation_ledger"), "restart propagation ledger"
        )
        restart_records = _items(
            restart_ledger.get("records"), "restart propagation records"
        )
        restart_delivery_ids: list[object] = []
        for record in restart_records:
            delivery = _mapping(record.get("delivery"), "restart delivery receipt")
            _require(
                isinstance(delivery.get("delivery_id"), str)
                and delivery.get("delivery_id"),
                "restart delivery receipt lost its durable identity",
            )
            restart_delivery_ids.append(delivery.get("delivery_id"))
        restart_delivery_ids.sort()
        _require(
            restart_delivery_ids == cast(list[object], receipt["delivery_ids"]),
            "restart created a second delivery identity for a surface",
        )

        recovery = _mapping(
            _request_json(
                client,
                "GET",
                f"/api/recovery/window/{quote(command_id, safe='')}",
            ),
            "restart recovery window",
        )
        _require(
            recovery.get("persisted") is True, "restart recovery window is not durable"
        )

        overview = _mapping(
            _request_json(client, "GET", "/api/recovery/overview"),
            "restart recovery overview",
        )
        open_loops = _items(overview.get("open_loops"), "recovery open loops")
        _require(
            any(row.get("command_id") == command_id for row in open_loops),
            "recovery overview lost the published command after restart",
        )

        traceability = _mapping(
            _request_json(
                client,
                "GET",
                f"/api/traceability/{quote(object_ref, safe='')}",
            ),
            "restart traceability",
        )
        projection = _mapping(traceability.get("projection"), "restart projection")
        _require(
            projection.get("persisted") is True,
            "restart traceability fell back to rehearsal projection",
        )
        _require(
            projection.get("rehearsal") is False,
            "restart traceability projection is marked rehearsal",
        )
        _require(
            projection.get("publication_record_id") == publication_id,
            "restart traceability lost the durable publication",
        )

        audit = _assert_publish_audit(
            client,
            draft_id=cast(str, receipt["draft_id"]),
            command_id=command_id,
        )

        notifications = _items(
            _request_json(client, "GET", "/api/notifications"),
            "restart notifications",
        )
        by_id = {cast(str, row.get("id")): row for row in notifications}
        marked_notification_id = cast(str, receipt["marked_notification_id"])
        _require(
            marked_notification_id in by_id,
            "marked notification disappeared after restart",
        )
        _require(
            by_id[marked_notification_id].get("lifecycle_state") == "read",
            "notification read state did not survive restart",
        )
        unread_seeded = sum(
            1
            for notification_id in cast(list[str], receipt["notification_ids"])
            if by_id.get(notification_id, {}).get("lifecycle_state") == "unread"
        )
        _require(
            unread_seeded == 5,
            "browser cloud fixture must expose exactly five unread records",
        )

    return {
        "verified": True,
        "run_id": receipt["run_id"],
        "object_ref": object_ref,
        "publication_id": publication_id,
        "command_id": command_id,
        "audit_events": audit["total"],
        "unread_seeded_notifications": unread_seeded,
    }


@dataclass(frozen=True, slots=True)
class SmokeArguments:
    action: str
    base_url: str
    admin_email: str
    admin_password: str
    receipt_path: Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument(
        "action",
        choices=("exercise", "verify"),
        help="exercise writes the receipt; verify must run after the API restart",
    )
    _ = parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8077",
        help="Cygnus API base URL from inside the API container",
    )
    _ = parser.add_argument(
        "--admin-email",
        default=os.getenv("CYGNUS_SMOKE_ADMIN_EMAIL")
        or os.getenv("DEFAULT_ADMIN_EMAIL", "admin@cygnus.local"),
    )
    _ = parser.add_argument(
        "--admin-password",
        default=os.getenv("CYGNUS_SMOKE_ADMIN_PASSWORD")
        or os.getenv("DEFAULT_ADMIN_PASSWORD", "admin123"),
    )
    _ = parser.add_argument(
        "--receipt-path",
        type=Path,
        default=_DEFAULT_RECEIPT_PATH,
    )
    return parser


def _arguments() -> SmokeArguments:
    parsed = _parser().parse_args()
    return SmokeArguments(
        action=cast(str, parsed.action),
        base_url=cast(str, parsed.base_url),
        admin_email=cast(str, parsed.admin_email),
        admin_password=cast(str, parsed.admin_password),
        receipt_path=cast(Path, parsed.receipt_path),
    )


def main() -> None:
    args = _arguments()
    if args.action == "exercise":
        receipt = asyncio.run(_seed_persisted_truth(args.admin_email))
        exercised = _exercise_api(
            receipt,
            base_url=args.base_url,
            admin_password=args.admin_password,
        )
        _write_receipt(args.receipt_path, exercised)
        print(json.dumps(exercised, sort_keys=True))
        return

    receipt = _read_receipt(args.receipt_path)
    verified = _verify_after_restart(
        receipt,
        base_url=args.base_url,
        admin_password=args.admin_password,
    )
    print(json.dumps(verified, sort_keys=True))


if __name__ == "__main__":
    main()
