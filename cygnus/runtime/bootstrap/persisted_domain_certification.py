"""Certification-only persisted governance truth exercise.

This module runs only inside the isolated candidate API container. It creates
real signed delivery acknowledgements through the production transition,
queries the database-backed session bridge, and verifies restart/freshness
behavior without entering runtime request handlers.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import cast
import uuid

from sqlalchemy import select

from cygnus.publish.delivery import acknowledge_propagation_delivery
from cygnus.runtime.bootstrap.governance_smoke import (
    GoldenPathSmokeError,
    _authenticated_client,
    _mapping,
    _request_json,
    _require,
)
from cygnus.runtime.config import get_settings
from cygnus.runtime.database import get_async_session_factory
from cygnus.runtime.database.models import GovernancePropagationDelivery, Source


def _read(path: Path, label: str) -> dict[str, object]:
    try:
        payload = cast(object, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        raise GoldenPathSmokeError(f"cannot read {label}: {exc}") from exc
    return _mapping(payload, label)


def _write(path: Path, payload: dict[str, object]) -> None:
    _ = path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _query(client, *, run_id: str, visibility: str, turn: str) -> dict[str, object]:
    client.headers["X-Cygnus-Session-Contract-Version"] = "1.0"
    payload = _mapping(
        _request_json(
            client,
            "POST",
            "/api/session-bridge/query",
            json_body={
                "request_ref": f"domain-cert:{run_id}:{turn}",
                "session_ref": f"domain-cert:{run_id}",
                "query": "durable billing support policy",
                "channel": "agent-copilot",
                "audience_context": {
                    "visibility": visibility,
                    "product_line": "billing",
                    "region": "global",
                    "language": "en",
                },
            },
        ),
        f"{turn} governed query",
    )
    return _mapping(payload.get("data"), f"{turn} governed query data")


async def _acknowledge_deliveries(
    receipt: dict[str, object],
) -> list[dict[str, object]]:
    raw_ids = receipt.get("delivery_ids")
    _require(
        isinstance(raw_ids, list) and raw_ids, "governance receipt has no deliveries"
    )
    delivery_ids = [uuid.UUID(cast(str, item)) for item in cast(list[object], raw_ids)]
    secret = get_settings().delivery_hmac_secret
    session_factory = get_async_session_factory()
    results: list[dict[str, object]] = []
    async with session_factory() as session:
        deliveries = (
            (
                await session.execute(
                    select(GovernancePropagationDelivery).where(
                        GovernancePropagationDelivery.id.in_(delivery_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        _require(
            len(deliveries) == len(delivery_ids),
            "one or more delivery rows are missing",
        )
        for delivery in deliveries:
            payload = {
                "publication_id": str(delivery.publication_id),
                "surface_id": delivery.surface_id,
                "version": delivery.expected_page_version,
                "digest": delivery.desired_digest,
                "receipt_ref": f"certification://{delivery.id}",
            }
            body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            signature = (
                "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            )
            results.append(
                await acknowledge_propagation_delivery(
                    session,
                    delivery_id=delivery.id,
                    ack_body=body,
                    signature=signature,
                    secret=secret,
                    correlation_id=str(uuid.uuid4()),
                )
            )
        await session.commit()
    return results


async def _mark_source_stale(source_id: str) -> None:
    session_factory = get_async_session_factory()
    async with session_factory() as session:
        source = await session.get(Source, uuid.UUID(source_id))
        _require(
            source is not None,
            "persisted source disappeared before freshness invalidation",
        )
        assert source is not None
        source.freshness_state = "stale"
        source.freshness_reason = (
            "Certification invalidated the evidence after restart."
        )
        source.freshness_attested_at = datetime.now(timezone.utc)
        source.freshness_expires_at = datetime.now(timezone.utc)
        await session.commit()


def prepare(receipt_path: Path, state_path: Path) -> None:
    receipt = _read(receipt_path, "governance smoke receipt")
    run_id = cast(str, receipt["run_id"])
    admin_email = cast(str, receipt["admin_email"])
    admin_password = os.environ.get("DEFAULT_ADMIN_PASSWORD", "")
    _require(admin_password, "DEFAULT_ADMIN_PASSWORD is required")
    before = _mapping(receipt.get("retrieval"), "pre-ack retrieval")
    _require(
        before.get("governance_state") == "restricted",
        "pre-ack query was not restricted",
    )
    acknowledgements = asyncio.run(_acknowledge_deliveries(receipt))
    with _authenticated_client(
        base_url="http://127.0.0.1:8077",
        admin_email=admin_email,
        admin_password=admin_password,
    ) as client:
        allowed = _query(client, run_id=run_id, visibility="internal", turn="after-ack")
        allowed_governance = _mapping(allowed.get("governance"), "allowed governance")
        allowed_answer = _mapping(allowed.get("answer"), "allowed answer")
        _require(
            allowed_governance.get("state") == "answerable",
            "signed ack did not authorize internal retrieval",
        )
        _require(
            allowed_answer.get("content") is not None, "answerable query has no content"
        )
        denied = _query(
            client, run_id=run_id, visibility="external", turn="denied-audience"
        )
        denied_governance = _mapping(denied.get("governance"), "denied governance")
        _require(
            denied_governance.get("state") == "restricted",
            "external audience crossed the binding",
        )
        denied_answer = denied.get("answer")
        if isinstance(denied_answer, dict):
            _require(
                denied_answer.get("content") is None, "denied audience received content"
            )
        else:
            _require(denied_answer is None, "denied audience received an answer")
    state = {
        "run_id": run_id,
        "object_ref": receipt["object_ref"],
        "page_id": receipt["page_id"],
        "source_id": receipt["source_id"],
        "draft_id": receipt["draft_id"],
        "publication_id": receipt["publication_id"],
        "delivery_ids": receipt["delivery_ids"],
        "pre_ack": before,
        "acknowledgements": acknowledgements,
        "allowed_after_ack": {
            "governance": allowed_governance,
            "content_exposed": True,
        },
        "denied_audience": {
            "governance": denied_governance,
            "content_exposed": False,
        },
    }
    _write(state_path, state)
    print(json.dumps(state, sort_keys=True))


def verify(state_path: Path, result_path: Path) -> None:
    state = _read(state_path, "persisted domain state")
    run_id = cast(str, state["run_id"])
    admin_email = os.environ.get("DEFAULT_ADMIN_EMAIL", "")
    admin_password = os.environ.get("DEFAULT_ADMIN_PASSWORD", "")
    _require(admin_email and admin_password, "admin credentials are required")
    with _authenticated_client(
        base_url="http://127.0.0.1:8077",
        admin_email=admin_email,
        admin_password=admin_password,
    ) as client:
        after_restart = _query(
            client, run_id=run_id, visibility="internal", turn="after-restart"
        )
        restart_governance = _mapping(
            after_restart.get("governance"), "restart governance"
        )
        restart_answer = _mapping(after_restart.get("answer"), "restart answer")
        _require(
            restart_governance.get("state") == "answerable",
            "signed delivery truth did not survive restart",
        )
        _require(
            restart_answer.get("content") is not None, "restart lost answer content"
        )
    asyncio.run(_mark_source_stale(cast(str, state["source_id"])))
    with _authenticated_client(
        base_url="http://127.0.0.1:8077",
        admin_email=admin_email,
        admin_password=admin_password,
    ) as client:
        stale = _query(client, run_id=run_id, visibility="internal", turn="after-stale")
        stale_governance = _mapping(stale.get("governance"), "stale governance")
        stale_answer = _mapping(stale.get("answer"), "stale answer")
        _require(
            stale_governance.get("state") == "restricted",
            "stale evidence remained answerable",
        )
        _require(
            stale_answer.get("content") is None, "stale evidence leaked answer content"
        )
    result = state | {
        "restart_persistence": {
            "governance": restart_governance,
            "content_exposed": True,
        },
        "freshness_invalidation": {
            "governance": stale_governance,
            "content_exposed": False,
        },
    }
    _write(result_path, result)
    print(json.dumps(result, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("action", choices=("prepare", "verify"))
    _ = parser.add_argument("--receipt-path", type=Path, required=True)
    _ = parser.add_argument("--state-path", type=Path, required=True)
    _ = parser.add_argument("--result-path", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(cast(Path, args.receipt_path), cast(Path, args.state_path))
        return
    result_path = cast(Path | None, args.result_path)
    _require(result_path is not None, "--result-path is required for verify")
    assert result_path is not None
    verify(cast(Path, args.state_path), result_path)


if __name__ == "__main__":
    main()
