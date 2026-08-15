"""Focused production receipt-adapter tests for CYG-138.

The PostgreSQL portion follows the repository's integration-test convention:
it is skipped unless ``CYGNUS_GOVERNANCE_TEST_DATABASE_URL`` names an upgraded
database.  It exercises the actual sender against the production ASGI consumer,
including concurrent delivery attempts rather than the verification-only fake.
"""

from __future__ import annotations

import asyncio
import json
import os
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import AsyncMock, patch

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cygnus.integrations import delivery_consumer
from cygnus.publish.delivery import (
    DeliveryCircuitBreaker,
    DeliveryAttemptOutcome,
    build_canonical_delivery_payload,
    canonical_delivery_digest,
    canonical_json,
    send_delivery_request,
    sign_body,
    verify_ack_signature,
)
from cygnus.runtime.database.models import (
    DeliveryConsumerReceipt,
    GovernancePropagationDelivery,
)

_INTEGRATION_DATABASE_URL = os.getenv("CYGNUS_GOVERNANCE_TEST_DATABASE_URL")
_TEST_SECRET = "cyg138-production-delivery-consumer-test-secret"
_CONSUMER_ORIGIN = "http://consumer.test"
_CONSUMER_PATH = "/api/internal/propagation-delivery"
_TARGET_CHANNELS = ("agent-copilot", "internal-search")


def _delivery_id(publication_id: uuid.UUID, surface_id: str) -> str:
    return f"delivery:{publication_id}:{surface_id}"


def _payload(
    publication_id: uuid.UUID,
    *,
    object_version: int = 2,
    target_channels: tuple[str, ...] = _TARGET_CHANNELS,
) -> dict[str, object]:
    return build_canonical_delivery_payload(
        publication_id=publication_id,
        command_id=f"publish:{publication_id}",
        approval_ref=uuid.uuid4(),
        approval_sequence=1,
        object_ref="ko-delivery-consumer-test",
        object_type="answer_card",
        object_version=object_version,
        action_key="publish",
        target_channels=target_channels,
        binding_rows=(),
        source_ids=(),
        content_md="# Delivery consumer test",
    )


def _delivery(
    *,
    publication_id: uuid.UUID,
    surface_id: str,
    delivery_id: str | None = None,
    payload: dict[str, object] | None = None,
    object_version: int = 2,
) -> GovernancePropagationDelivery:
    canonical_payload = payload or _payload(
        publication_id,
        object_version=object_version,
    )
    resolved_delivery_id = delivery_id or _delivery_id(publication_id, surface_id)
    return GovernancePropagationDelivery(
        id=uuid.uuid4(),
        propagation_id=uuid.uuid4(),
        publication_id=publication_id,
        surface_id=surface_id,
        status="pending",
        command_id=resolved_delivery_id,
        idempotency_key=resolved_delivery_id,
        desired_digest=canonical_delivery_digest(canonical_payload),
        canonical_payload=canonical_payload,
        expected_page_version=object_version,
        expected_approval_version=1,
        expected_binding_versions=[],
        attempts=0,
        max_attempts=5,
        correlation_id=str(publication_id),
        traceparent=f"00-{publication_id.hex}-0000000000000001-01",
    )


def _headers(
    *,
    body: bytes,
    delivery_id: str,
    publication_id: uuid.UUID,
    surface_id: str,
    secret: str = _TEST_SECRET,
) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Cygnus-Delivery-Id": delivery_id,
        "X-Cygnus-Publication-Id": str(publication_id),
        "X-Cygnus-Signature": f"sha256={sign_body(body, secret)}",
        "X-Cygnus-Surface": surface_id,
    }


async def _post(body: bytes, headers: dict[str, str]) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=delivery_consumer.app),
        base_url=_CONSUMER_ORIGIN,
    ) as client:
        return await client.post(_CONSUMER_PATH, content=body, headers=headers)


async def _readiness(secret: str) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=delivery_consumer.app),
        base_url=_CONSUMER_ORIGIN,
    ) as client:
        return await client.head(
            _CONSUMER_PATH,
            headers={"X-Cygnus-Signature": f"sha256={sign_body(b'', secret)}"},
        )


class DeliveryConsumerBoundaryTests(unittest.TestCase):
    def test_invalid_signature_is_denied_without_a_receipt_write(self) -> None:
        publication_id = uuid.uuid4()
        body = canonical_json(_payload(publication_id))
        headers = _headers(
            body=body,
            delivery_id=_delivery_id(publication_id, "agent-copilot"),
            publication_id=publication_id,
            surface_id="agent-copilot",
        )
        headers["X-Cygnus-Signature"] = "sha256=not-a-valid-signature"

        with (
            patch.object(
                delivery_consumer,
                "get_settings",
                return_value=SimpleNamespace(delivery_hmac_secret=_TEST_SECRET),
            ),
            patch.object(
                delivery_consumer,
                "get_async_session_factory",
                side_effect=AssertionError("invalid signatures must not reach storage"),
            ),
        ):
            response = asyncio.run(_post(body, headers))

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "delivery signature is invalid"})

    def test_malformed_and_boundary_delivery_bodies_are_denied(self) -> None:
        publication_id = uuid.uuid4()
        delivery_id = _delivery_id(publication_id, "agent-copilot")
        malformed_body = b"{not-json"
        malformed_headers = _headers(
            body=malformed_body,
            delivery_id=delivery_id,
            publication_id=publication_id,
            surface_id="agent-copilot",
        )

        invalid_version_payload = _payload(publication_id, object_version=0)
        invalid_version_body = canonical_json(invalid_version_payload)
        invalid_version_headers = _headers(
            body=invalid_version_body,
            delivery_id=_delivery_id(publication_id, "agent-copilot"),
            publication_id=publication_id,
            surface_id="agent-copilot",
        )
        identity_body = canonical_json(_payload(publication_id))
        mismatched_publication_id = uuid.uuid4()
        mismatched_publication_headers = _headers(
            body=identity_body,
            delivery_id=_delivery_id(mismatched_publication_id, "agent-copilot"),
            publication_id=mismatched_publication_id,
            surface_id="agent-copilot",
        )
        mismatched_surface_headers = _headers(
            body=identity_body,
            delivery_id=_delivery_id(publication_id, "missing-target"),
            publication_id=publication_id,
            surface_id="missing-target",
        )
        noncanonical_body = json.dumps(_payload(publication_id), sort_keys=True).encode(
            "utf-8"
        )
        noncanonical_headers = _headers(
            body=noncanonical_body,
            delivery_id=_delivery_id(publication_id, "agent-copilot"),
            publication_id=publication_id,
            surface_id="agent-copilot",
        )

        oversized_body = b"x" * (delivery_consumer._MAX_DELIVERY_BODY_BYTES + 1)
        oversized_headers = {
            "Content-Type": "application/json",
            "X-Cygnus-Signature": "sha256=ignored-before-size-check",
        }

        with (
            patch.object(
                delivery_consumer,
                "get_settings",
                return_value=SimpleNamespace(delivery_hmac_secret=_TEST_SECRET),
            ),
            patch.object(
                delivery_consumer,
                "get_async_session_factory",
                side_effect=AssertionError("invalid deliveries must not reach storage"),
            ),
        ):
            malformed = asyncio.run(_post(malformed_body, malformed_headers))
            invalid_version = asyncio.run(
                _post(invalid_version_body, invalid_version_headers)
            )
            mismatched_publication = asyncio.run(
                _post(identity_body, mismatched_publication_headers)
            )
            mismatched_surface = asyncio.run(
                _post(identity_body, mismatched_surface_headers)
            )
            oversized = asyncio.run(_post(oversized_body, oversized_headers))
            noncanonical = asyncio.run(_post(noncanonical_body, noncanonical_headers))

        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(invalid_version.status_code, 400)
        self.assertEqual(oversized.status_code, 413)
        self.assertEqual(mismatched_publication.status_code, 400)
        self.assertEqual(mismatched_surface.status_code, 400)
        self.assertEqual(noncanonical.status_code, 400)
        forged_delivery_headers = _headers(
            body=identity_body,
            delivery_id="delivery:forged:agent-copilot",
            publication_id=publication_id,
            surface_id="agent-copilot",
        )
        with (
            patch.object(
                delivery_consumer,
                "get_settings",
                return_value=SimpleNamespace(delivery_hmac_secret=_TEST_SECRET),
            ),
            patch.object(
                delivery_consumer,
                "get_async_session_factory",
                side_effect=AssertionError(
                    "forged receipt keys must not reach storage"
                ),
            ),
        ):
            forged_delivery = asyncio.run(_post(identity_body, forged_delivery_headers))
        self.assertEqual(forged_delivery.status_code, 400)
        self.assertEqual(
            forged_delivery.json(),
            {"detail": "delivery receipt identity does not match"},
        )

    def test_readiness_requires_signature_and_receipt_store(self) -> None:
        with (
            patch.object(
                delivery_consumer,
                "get_settings",
                return_value=SimpleNamespace(delivery_hmac_secret=_TEST_SECRET),
            ),
            patch.object(
                delivery_consumer,
                "get_async_session_factory",
                side_effect=AssertionError(
                    "invalid readiness signatures must not reach storage"
                ),
            ),
        ):
            invalid = asyncio.run(_readiness("wrong-secret"))

        with (
            patch.object(
                delivery_consumer,
                "get_settings",
                return_value=SimpleNamespace(delivery_hmac_secret=_TEST_SECRET),
            ),
            patch.object(
                delivery_consumer,
                "_receipt_store_ready",
                AsyncMock(return_value=False),
            ),
        ):
            unavailable = asyncio.run(_readiness(_TEST_SECRET))

        with (
            patch.object(
                delivery_consumer,
                "get_settings",
                return_value=SimpleNamespace(delivery_hmac_secret=_TEST_SECRET),
            ),
            patch.object(
                delivery_consumer,
                "_receipt_store_ready",
                AsyncMock(return_value=True),
            ),
        ):
            ready = asyncio.run(_readiness(_TEST_SECRET))

        self.assertEqual(invalid.status_code, 401)
        self.assertEqual(unavailable.status_code, 503)
        self.assertEqual(ready.status_code, 204)

    def test_missing_secret_and_database_failure_are_unavailable(self) -> None:
        publication_id = uuid.uuid4()
        body = canonical_json(_payload(publication_id))
        headers = _headers(
            body=body,
            delivery_id=_delivery_id(publication_id, "agent-copilot"),
            publication_id=publication_id,
            surface_id="agent-copilot",
        )

        with patch.object(
            delivery_consumer,
            "get_settings",
            return_value=SimpleNamespace(delivery_hmac_secret=""),
        ):
            missing_secret = asyncio.run(_post(body, headers))

        with (
            patch.object(
                delivery_consumer,
                "get_settings",
                return_value=SimpleNamespace(delivery_hmac_secret=_TEST_SECRET),
            ),
            patch.object(
                delivery_consumer,
                "get_async_session_factory",
                side_effect=RuntimeError("database unavailable"),
            ),
        ):
            database_failure = asyncio.run(_post(body, headers))
            health = asyncio.run(_health())

        self.assertEqual(missing_secret.status_code, 503)
        self.assertEqual(database_failure.status_code, 503)
        self.assertEqual(health.status_code, 503)


async def _health() -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=delivery_consumer.app),
        base_url=_CONSUMER_ORIGIN,
    ) as client:
        return await client.get("/health")


@unittest.skipUnless(
    _INTEGRATION_DATABASE_URL,
    "CYGNUS_GOVERNANCE_TEST_DATABASE_URL is not configured",
)
class DeliveryConsumerPostgresTests(unittest.TestCase):
    def test_sender_ack_replay_conflict_and_concurrency_are_durable(self) -> None:
        asyncio.run(self._exercise_durable_contract())

    async def _exercise_durable_contract(self) -> None:
        assert _INTEGRATION_DATABASE_URL is not None
        engine = create_async_engine(_INTEGRATION_DATABASE_URL)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        delivery_ids: list[str] = []
        try:
            publication_id = uuid.uuid4()
            canonical_payload = _payload(publication_id)
            deliveries = tuple(
                _delivery(
                    publication_id=publication_id,
                    surface_id=surface_id,
                    payload=canonical_payload,
                )
                for surface_id in _TARGET_CHANNELS
            )
            delivery_ids.extend(delivery.idempotency_key for delivery in deliveries)

            with (
                patch.object(
                    delivery_consumer,
                    "get_settings",
                    return_value=SimpleNamespace(delivery_hmac_secret=_TEST_SECRET),
                ),
                patch.object(
                    delivery_consumer,
                    "get_async_session_factory",
                    return_value=sessions,
                ),
            ):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=delivery_consumer.app),
                    base_url=_CONSUMER_ORIGIN,
                    timeout=5.0,
                ) as client:
                    health = await client.get("/health")
                    self.assertEqual(health.status_code, 200)
                    self.assertEqual(
                        health.json(),
                        {"status": "ok", "database": "ready"},
                    )
                    readiness = await client.head(
                        _CONSUMER_PATH,
                        headers={
                            "X-Cygnus-Signature": (
                                f"sha256={sign_body(b'', _TEST_SECRET)}"
                            )
                        },
                    )
                    self.assertEqual(readiness.status_code, 204)

                    outcomes = []
                    for delivery in deliveries:
                        outcome = await send_delivery_request(
                            delivery,
                            secret=_TEST_SECRET,
                            request_url=_CONSUMER_ORIGIN + _CONSUMER_PATH,
                            timeout_seconds=5.0,
                            allowed_origins={"consumer.test"},
                            allow_insecure_http=True,
                            circuit=DeliveryCircuitBreaker(threshold=10),
                            client=client,
                        )
                        outcomes.append(outcome)
                        self.assertTrue(outcome.delivered)
                        self.assertTrue(outcome.synced)
                        self.assertIsNotNone(outcome.ack_body)
                        self.assertTrue(
                            verify_ack_signature(
                                outcome.ack_body or b"",
                                outcome.ack_signature or "",
                                _TEST_SECRET,
                            )
                        )
                        self.assertEqual(
                            outcome.ack_correlation_id,
                            str(publication_id),
                        )
                        self.assertEqual(
                            outcome.ack_traceparent,
                            f"00-{publication_id.hex}-0000000000000001-01",
                        )

                    # Sender-compatible exact replay is byte-for-byte stable.
                    replay = await send_delivery_request(
                        deliveries[0],
                        secret=_TEST_SECRET,
                        request_url=_CONSUMER_ORIGIN + _CONSUMER_PATH,
                        timeout_seconds=5.0,
                        allowed_origins={"consumer.test"},
                        allow_insecure_http=True,
                        circuit=DeliveryCircuitBreaker(threshold=10),
                        client=client,
                    )
                    self.assertTrue(replay.synced)
                    self.assertEqual(replay.ack_body, outcomes[0].ack_body)
                    self.assertEqual(replay.ack_signature, outcomes[0].ack_signature)

                    # A correctly signed but changed immutable body under the
                    # same receipt key is denied rather than overwriting it.
                    drifted = _delivery(
                        publication_id=publication_id,
                        surface_id="agent-copilot",
                        delivery_id=deliveries[0].idempotency_key,
                        object_version=3,
                    )
                    conflict = await send_delivery_request(
                        drifted,
                        secret=_TEST_SECRET,
                        request_url=_CONSUMER_ORIGIN + _CONSUMER_PATH,
                        timeout_seconds=5.0,
                        allowed_origins={"consumer.test"},
                        allow_insecure_http=True,
                        circuit=DeliveryCircuitBreaker(threshold=10),
                        client=client,
                    )
                    self.assertFalse(conflict.synced)
                    self.assertEqual(conflict.status_code, 409)

                    # Two simultaneously signed deliveries with one key create
                    # exactly one row and return the same signed receipt.
                    concurrent_publication_id = uuid.uuid4()
                    concurrent = _delivery(
                        publication_id=concurrent_publication_id,
                        surface_id="agent-copilot",
                    )

                    async def send_concurrent() -> DeliveryAttemptOutcome:
                        return await send_delivery_request(
                            concurrent,
                            secret=_TEST_SECRET,
                            request_url=_CONSUMER_ORIGIN + _CONSUMER_PATH,
                            timeout_seconds=5.0,
                            allowed_origins={"consumer.test"},
                            allow_insecure_http=True,
                            circuit=DeliveryCircuitBreaker(threshold=10),
                            client=client,
                        )

                    first, second = await asyncio.gather(
                        send_concurrent(),
                        send_concurrent(),
                    )
                    self.assertTrue(first.synced)
                    self.assertTrue(second.synced)
                    self.assertEqual(first.ack_body, second.ack_body)
                    self.assertEqual(first.ack_signature, second.ack_signature)

            async with sessions() as session:
                rows = (
                    (
                        await session.execute(
                            select(DeliveryConsumerReceipt).where(
                                DeliveryConsumerReceipt.delivery_id.in_(delivery_ids)
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                self.assertEqual(len(rows), len(delivery_ids))
                rows_by_id = {row.delivery_id: row for row in rows}
                accepted = rows_by_id[deliveries[0].idempotency_key]
                self.assertEqual(
                    accepted.body_sha256,
                    canonical_delivery_digest(canonical_payload),
                )
                self.assertEqual(accepted.publication_id, publication_id)
                self.assertEqual(accepted.surface_id, "agent-copilot")
                self.assertEqual(accepted.object_version, 2)
                self.assertTrue(accepted.receipt_ref.startswith("delivery-consumer:"))
                self.assertIsNotNone(accepted.accepted_at)
        finally:
            if delivery_ids:
                async with sessions() as session:
                    await session.execute(
                        delete(DeliveryConsumerReceipt).where(
                            DeliveryConsumerReceipt.delivery_id.in_(delivery_ids)
                        )
                    )
                    await session.commit()
            await engine.dispose()
