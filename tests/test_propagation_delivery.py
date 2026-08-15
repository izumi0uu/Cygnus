"""Focused receipt tests for CYG-138 outbound propagation delivery.

Unit tests (no database) cover the pure adapter contract: canonical digest
determinism, request signing/ack verification, destination/DNS/HTTPS policy,
circuit breaker, and the signed request -> signed ack loop through the
deterministic fake consumer harness.

Postgres-backed tests (skipped unless ``CYGNUS_GOVERNANCE_TEST_DATABASE_URL``
is configured) cover the durable receipt contract: publish stages pending
deliveries with one identity and a desired digest, exact signed ack syncs once,
drift/forged/stale acks are denied, manual mutation cannot set synced, bounded
retries dead-letter, and the worker sweep dispatches through the fake consumer.

The fake consumer harness is verification-only: real Production V1 acceptance
still requires an external internal-copilot endpoint.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, cast
import unittest
import uuid
from unittest.mock import patch

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cygnus.domain.audience import AudienceFilter, Visibility
from cygnus.domain.objects import KnowledgeObjectType, governed_object_ref
from cygnus.evidence.records import FreshnessState
from cygnus.governance.audience_bindings import (
    AudienceBindingCreate,
    create_audience_binding,
)
from cygnus.governance.signals import GovernanceSignalInput, create_governance_signal
from cygnus.publish import (
    DeliveryAckConflict,
    DeliveryStatus,
    DeliveryVerificationError,
    DurablePublishCommand,
    DurablePublishDenied,
    PropagationStatus,
    PropagationUpdateCommand,
    acknowledge_propagation_delivery,
    apply_durable_publish,
    durable_publish_command_for_signal,
    list_propagation_deliveries,
    list_publication_propagations,
    update_propagation,
)
from cygnus.publish.delivery import (
    DeliveryAttemptOutcome,
    DeliveryCircuitBreaker,
    DeliveryPolicyError,
    build_canonical_delivery_payload,
    canonical_delivery_digest,
    canonical_json,
    delivery_endpoint_url,
    delivery_request_headers,
    delivery_to_dict,
    drain_propagation_deliveries,
    parse_ack_body,
    reset_delivery_circuit,
    sign_body,
    validate_delivery_destination,
    verify_ack_signature,
)
from cygnus.review.contributions import approve_wiki_draft, create_wiki_draft
from cygnus.review.intake import PressureSignalType
from cygnus.runtime.config import Settings
from cygnus.runtime.database.models import (
    Employee,
    GovernanceAudienceBinding,
    GovernancePropagation,
    GovernancePropagationDelivery,
    Source,
)
from tests.fixtures.fake_consumer import FakeConsumer

_INTEGRATION_DATABASE_URL = os.getenv("CYGNUS_GOVERNANCE_TEST_DATABASE_URL")
_TEST_SECRET = "cyg138-test-delivery-hmac-secret"
_CONSUMER_ORIGIN = "http://consumer.test"
_CONSUMER_PATH = "/api/internal/propagation-delivery"


def _binding(
    *,
    key: str = "binding-1",
    version: int = 1,
    channel: str = "agent-copilot",
    visibility: str = "internal",
) -> GovernanceAudienceBinding:
    return GovernanceAudienceBinding(
        id=uuid.uuid4(),
        page_id=uuid.uuid4(),
        object_ref="ko-object",
        variant_ref="internal-governed",
        channel=channel,
        visibility=visibility,
        brands=[],
        product_lines=["billing"],
        plans=[],
        regions=["global"],
        languages=["en"],
        product_versions=[],
        lifecycle_state="active",
        binding_key=key,
        created_by_id=uuid.uuid4(),
        version=version,
    )


def _delivery_row(
    *,
    surface_id: str = "agent-copilot",
    digest: str | None = None,
    payload: dict[str, object] | None = None,
    expected_page_version: int = 2,
) -> GovernancePropagationDelivery:
    canonical = payload or {
        "publication_id": str(uuid.uuid4()),
        "command_id": "publish-1",
        "approval_ref": str(uuid.uuid4()),
        "approval_sequence": 3,
        "object_ref": "ko-object",
        "object_type": "answer_card",
        "object_version": expected_page_version,
        "action_key": "publish",
        "target_channels": ["agent-copilot", "internal-search"],
        "bindings": [
            {
                "binding_key": "binding-1",
                "version": 1,
                "channel": surface_id,
                "visibility": "internal",
                "audience": {
                    "brands": [],
                    "product_lines": ["billing"],
                    "plans": [],
                    "regions": ["global"],
                    "languages": ["en"],
                    "product_versions": [],
                },
            }
        ],
        "source_evidence_refs": ["ev-src-00000000-0000-0000-0000-000000000001"],
        "content_sha256": "a" * 64,
    }
    return GovernancePropagationDelivery(
        id=uuid.uuid4(),
        propagation_id=uuid.uuid4(),
        publication_id=uuid.uuid4(),
        surface_id=surface_id,
        status=DeliveryStatus.PENDING.value,
        command_id=f"delivery:{uuid.uuid4()}:{surface_id}",
        idempotency_key=f"delivery:{uuid.uuid4()}:{surface_id}",
        desired_digest=digest or canonical_delivery_digest(canonical),
        canonical_payload=canonical,
        expected_page_version=expected_page_version,
        expected_approval_version=3,
        expected_binding_versions=[{"binding_key": "binding-1", "version": 1}],
        attempts=0,
        max_attempts=5,
        actor_id=uuid.uuid4(),
        correlation_id="corr-1",
        traceparent="00-abc",
    )


def _ack_body(
    delivery: GovernancePropagationDelivery,
    *,
    digest: str | None = None,
    version: int | None = None,
    surface_id: str | None = None,
    publication_id: uuid.UUID | None = None,
) -> bytes:
    payload = {
        "publication_id": str(publication_id or delivery.publication_id),
        "surface_id": surface_id or delivery.surface_id,
        "version": version or delivery.expected_page_version,
        "digest": digest or delivery.desired_digest,
        "receipt_ref": "test-receipt",
    }
    return canonical_json(payload)


def _signed_ack_header(ack_body: bytes, secret: str = _TEST_SECRET) -> str:
    return f"sha256={sign_body(ack_body, secret)}"


class CanonicalPayloadTests(unittest.TestCase):
    def test_digest_is_deterministic_and_binds_approved_truth(self) -> None:
        first = build_canonical_delivery_payload(
            publication_id=uuid.uuid4(),
            command_id="publish-1",
            approval_ref=uuid.uuid4(),
            approval_sequence=3,
            object_ref="ko-object",
            object_type="answer_card",
            object_version=2,
            action_key="publish",
            target_channels=("agent-copilot", "internal-search"),
            binding_rows=(_binding(),),
            source_ids=(uuid.UUID("00000000-0000-0000-0000-000000000001"),),
            content_md="# Billing policy",
        )
        second = build_canonical_delivery_payload(
            publication_id=cast(uuid.UUID, first["publication_id"]),
            command_id="publish-1",
            approval_ref=cast(uuid.UUID, first["approval_ref"]),
            approval_sequence=3,
            object_ref="ko-object",
            object_type="answer_card",
            object_version=2,
            action_key="publish",
            target_channels=("agent-copilot", "internal-search"),
            binding_rows=(_binding(),),
            source_ids=(uuid.UUID("00000000-0000-0000-0000-000000000001"),),
            content_md="# Billing policy",
        )
        self.assertEqual(
            canonical_delivery_digest(first), canonical_delivery_digest(second)
        )
        # Correlation metadata must never enter the digest payload (exact replay).
        self.assertNotIn("correlation_id", first)
        self.assertNotIn("traceparent", first)
        self.assertEqual(
            first["source_evidence_refs"],
            ["ev-src-00000000-0000-0000-0000-000000000001"],
        )
        self.assertEqual(first["object_version"], 2)
        self.assertEqual(
            cast(list[dict[str, object]], first["bindings"])[0]["binding_key"],
            "binding-1",
        )

    def test_drift_changes_the_digest(self) -> None:
        base = {
            "publication_id": str(uuid.uuid4()),
            "command_id": "publish-1",
            "approval_ref": str(uuid.uuid4()),
            "approval_sequence": 3,
            "object_ref": "ko-object",
            "object_type": "answer_card",
            "object_version": 2,
            "action_key": "publish",
            "target_channels": ["agent-copilot"],
            "bindings": [
                {
                    "binding_key": "binding-1",
                    "version": 1,
                    "channel": "agent-copilot",
                    "visibility": "internal",
                    "audience": {
                        "brands": [],
                        "product_lines": ["billing"],
                        "plans": [],
                        "regions": ["global"],
                        "languages": ["en"],
                        "product_versions": [],
                    },
                }
            ],
            "source_evidence_refs": ["ev-src-1"],
            "content_sha256": "a" * 64,
        }
        drifted = dict(base)
        drifted["object_version"] = 3
        self.assertNotEqual(
            canonical_delivery_digest(base), canonical_delivery_digest(drifted)
        )
        drifted = dict(base)
        drifted["bindings"] = [
            {**cast(list[dict[str, object]], base["bindings"])[0], "version": 2}
        ]
        self.assertNotEqual(
            canonical_delivery_digest(base), canonical_delivery_digest(drifted)
        )


class SignatureTests(unittest.TestCase):
    def test_sign_and_verify_roundtrip(self) -> None:
        body = b'{"hello": "world"}'
        signature = sign_body(body, _TEST_SECRET)
        self.assertTrue(verify_ack_signature(body, f"sha256={signature}", _TEST_SECRET))

    def test_tampered_body_or_wrong_secret_fails(self) -> None:
        body = b'{"hello": "world"}'
        signature = sign_body(body, _TEST_SECRET)
        self.assertFalse(
            verify_ack_signature(
                b'{"hello": "world!"}', f"sha256={signature}", _TEST_SECRET
            )
        )
        self.assertFalse(
            verify_ack_signature(body, f"sha256={signature}", "other-secret")
        )
        self.assertFalse(verify_ack_signature(body, "", _TEST_SECRET))
        self.assertFalse(verify_ack_signature(body, f"md5={signature}", _TEST_SECRET))

    def test_headers_carry_identity_without_bodies(self) -> None:
        delivery = _delivery_row()
        headers = delivery_request_headers(delivery, "sig")
        self.assertEqual(headers["X-Cygnus-Delivery-Id"], delivery.idempotency_key)
        self.assertEqual(
            headers["X-Cygnus-Publication-Id"], str(delivery.publication_id)
        )
        self.assertEqual(headers["X-Cygnus-Surface"], delivery.surface_id)
        self.assertEqual(headers["X-Cygnus-Correlation-Id"], "corr-1")
        self.assertNotIn("body", headers)


class DestinationPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.allowed = {"consumer.test"}

    def test_https_allowed_outside_test(self) -> None:
        url = validate_delivery_destination(
            "https://consumer.test/api/internal/propagation-delivery",
            self.allowed,
            allow_insecure_http=False,
        )
        self.assertTrue(url.startswith("https://consumer.test/"))

    def test_http_rejected_outside_test(self) -> None:
        with self.assertRaises(DeliveryPolicyError):
            _ = validate_delivery_destination(
                _CONSUMER_ORIGIN + _CONSUMER_PATH,
                self.allowed,
                allow_insecure_http=False,
            )

    def test_http_allowed_in_test(self) -> None:
        url = validate_delivery_destination(
            _CONSUMER_ORIGIN + _CONSUMER_PATH,
            self.allowed,
            allow_insecure_http=True,
        )
        self.assertEqual(url, _CONSUMER_ORIGIN + _CONSUMER_PATH)

    def test_non_allowlisted_host_rejected(self) -> None:
        with self.assertRaises(DeliveryPolicyError):
            _ = validate_delivery_destination(
                "https://evil.test/api/internal/propagation-delivery",
                self.allowed,
                allow_insecure_http=False,
            )

    def test_credentials_query_and_fragment_rejected(self) -> None:
        with self.assertRaises(DeliveryPolicyError):
            _ = validate_delivery_destination(
                "https://user:pass@consumer.test/x",
                self.allowed,
                allow_insecure_http=False,
            )
        with self.assertRaises(DeliveryPolicyError):
            _ = validate_delivery_destination(
                "https://consumer.test/x?token=1",
                self.allowed,
                allow_insecure_http=False,
            )
        with self.assertRaises(DeliveryPolicyError):
            _ = validate_delivery_destination(
                "https://consumer.test/x#frag", self.allowed, allow_insecure_http=False
            )

    def test_invalid_dns_name_rejected(self) -> None:
        with self.assertRaises(DeliveryPolicyError):
            _ = validate_delivery_destination(
                "https://bad_host name/x", self.allowed, allow_insecure_http=False
            )

    def test_redirect_target_validation_is_per_hop(self) -> None:
        # A redirect Location is validated with the same policy before it is
        # followed: allowlisted same-origin hop passes, external hop is denied.
        ok = validate_delivery_destination(
            "https://consumer.test/api/internal/propagation-delivery",
            self.allowed,
            allow_insecure_http=False,
        )
        self.assertTrue(ok)
        with self.assertRaises(DeliveryPolicyError):
            _ = validate_delivery_destination(
                "https://evil.test/redirect-target",
                self.allowed,
                allow_insecure_http=False,
            )

    def test_endpoint_url_joins_base_path(self) -> None:
        self.assertEqual(
            delivery_endpoint_url("http://consumer.test"),
            _CONSUMER_ORIGIN + _CONSUMER_PATH,
        )
        self.assertEqual(
            delivery_endpoint_url("http://consumer.test/ingest"),
            "http://consumer.test/ingest" + _CONSUMER_PATH,
        )


class AckParsingTests(unittest.TestCase):
    def test_parse_ack_validation(self) -> None:
        delivery = _delivery_row()
        body = _ack_body(delivery)
        parsed = parse_ack_body(body)
        self.assertEqual(parsed["digest"], delivery.desired_digest)
        self.assertEqual(parsed["version"], delivery.expected_page_version)
        with self.assertRaises(DeliveryVerificationError):
            _ = parse_ack_body(b"not json")
        with self.assertRaises(DeliveryVerificationError):
            _ = parse_ack_body(b'{"digest": "short"}')
        missing_digest = json.dumps(
            {
                "publication_id": str(uuid.uuid4()),
                "surface_id": "agent-copilot",
                "version": 1,
            },
            sort_keys=True,
        ).encode()
        with self.assertRaises(DeliveryVerificationError):
            _ = parse_ack_body(missing_digest)


class CircuitBreakerTests(unittest.TestCase):
    def test_trips_after_threshold_and_recovers(self) -> None:
        circuit = DeliveryCircuitBreaker(threshold=2, cooldown_seconds=0.01)
        host = "consumer.test"
        self.assertTrue(circuit.allow(host))
        circuit.record_failure(host)
        self.assertTrue(circuit.allow(host))
        circuit.record_failure(host)
        self.assertFalse(circuit.allow(host))
        circuit.record_success(host)
        self.assertTrue(circuit.allow(host))

    def test_reset_clears_state(self) -> None:
        circuit = DeliveryCircuitBreaker(threshold=1, cooldown_seconds=60)
        circuit.record_failure("consumer.test")
        self.assertFalse(circuit.allow("consumer.test"))
        circuit.reset()
        self.assertTrue(circuit.allow("consumer.test"))


class FakeConsumerTransportTests(unittest.TestCase):
    def _client(self, consumer: FakeConsumer) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=cast(Any, consumer)),
            timeout=5.0,
        )

    def _send(
        self,
        consumer: FakeConsumer,
        delivery: GovernancePropagationDelivery,
    ) -> DeliveryAttemptOutcome:
        from cygnus.publish.delivery import send_delivery_request

        allowed = {"consumer.test"}
        return asyncio.run(
            send_delivery_request(
                delivery,
                secret=_TEST_SECRET,
                request_url=_CONSUMER_ORIGIN + _CONSUMER_PATH,
                timeout_seconds=5.0,
                allowed_origins=allowed,
                allow_insecure_http=True,
                circuit=DeliveryCircuitBreaker(threshold=10),
                client=self._client(consumer),
            )
        )

    def test_signed_request_syncs_through_fake_consumer(self) -> None:
        delivery = _delivery_row()
        consumer = FakeConsumer(_TEST_SECRET)
        outcome = self._send(consumer, delivery)
        self.assertTrue(outcome.delivered)
        self.assertTrue(outcome.synced)
        self.assertEqual(outcome.acknowledged_digest, delivery.desired_digest)
        self.assertIsNotNone(outcome.ack_body)
        self.assertTrue(outcome.ack_signature)
        # The consumer verified the outbound signature and saw the identity.
        self.assertTrue(consumer.received_bodies)
        headers = consumer.received_headers[0]
        self.assertEqual(headers["x-cygnus-surface"], delivery.surface_id)
        self.assertEqual(headers["x-cygnus-delivery-id"], delivery.idempotency_key)

    def test_tampered_ack_digest_is_denied(self) -> None:
        delivery = _delivery_row()
        consumer = FakeConsumer(_TEST_SECRET, tamper_ack=True)
        outcome = self._send(consumer, delivery)
        self.assertTrue(outcome.delivered)
        self.assertFalse(outcome.synced)
        self.assertFalse(outcome.retryable)
        self.assertIn("digest", cast(str, outcome.error))

    def test_server_error_is_retryable(self) -> None:
        delivery = _delivery_row()
        consumer = FakeConsumer(_TEST_SECRET, fail_with=500)
        outcome = self._send(consumer, delivery)
        self.assertFalse(outcome.delivered)
        self.assertFalse(outcome.synced)
        self.assertTrue(outcome.retryable)
        self.assertEqual(outcome.status_code, 500)

    def test_redirect_to_allowlisted_host_syncs(self) -> None:
        delivery = _delivery_row()
        consumer = FakeConsumer(
            _TEST_SECRET,
            redirect_to=_CONSUMER_ORIGIN + _CONSUMER_PATH,
        )
        outcome = self._send(consumer, delivery)
        self.assertTrue(outcome.synced)

    def test_redirect_to_non_allowlisted_host_denied(self) -> None:
        delivery = _delivery_row()
        consumer = FakeConsumer(_TEST_SECRET, redirect_to="https://evil.test/x")
        outcome = self._send(consumer, delivery)
        self.assertFalse(outcome.synced)
        self.assertFalse(outcome.retryable)
        self.assertIn("not allowlisted", cast(str, outcome.error))

    def test_serialization_surfaces_reconciliation_truth(self) -> None:
        delivery = _delivery_row()
        payload = delivery_to_dict(delivery, include_payload=True)
        self.assertEqual(payload["status"], "pending")
        self.assertEqual(payload["desired_digest"], delivery.desired_digest)
        self.assertIsNotNone(payload["canonical_payload"])
        self.assertEqual(payload["expected_page_version"], 2)
        self.assertIsNone(payload["acknowledged_digest"])
        slim = delivery_to_dict(delivery)
        self.assertIsNone(slim["canonical_payload"])


_INTEGRATION_DATABASE_URL = os.getenv("CYGNUS_GOVERNANCE_TEST_DATABASE_URL")


@unittest.skipUnless(
    _INTEGRATION_DATABASE_URL,
    "CYGNUS_GOVERNANCE_TEST_DATABASE_URL is not configured",
)
class PropagationDeliveryPostgresTests(unittest.TestCase):
    def test_publish_stages_delivery_receipts_and_replay_preserves_identity(
        self,
    ) -> None:
        asyncio.run(self._exercise_publish_stages_and_replay())

    async def _exercise_publish_stages_and_replay(self) -> None:
        if _INTEGRATION_DATABASE_URL is None:
            raise AssertionError("integration database URL unexpectedly absent")
        engine = create_async_engine(_INTEGRATION_DATABASE_URL)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        unique = uuid.uuid4().hex
        seeded = await _seed_publication(sessions, unique)
        try:
            async with sessions() as session:
                command = _command_from_envelope(
                    cast(dict[str, object], seeded["envelope"]),
                    unique,
                )
                result = await apply_durable_publish(
                    session,
                    command=command,
                    actor_id=cast(uuid.UUID, seeded["actor_id"]),
                    correlation_id=f"corr-{unique}",
                    traceparent="00-4bf92f3577b34da6a3ce929d0e0e4736",
                )
                await session.commit()
                self.assertTrue(result["persisted"])
                self.assertFalse(result["replayed"])
                propagation = cast(dict[str, object], result["propagation"])
                records = cast(list[dict[str, object]], propagation["records"])
                self.assertEqual(len(records), 2)
                for record in records:
                    digest = cast(str, record["desired_digest"])
                    self.assertEqual(len(digest), 64)
                    int(digest, 16)
                    delivery = cast(dict[str, object], record["delivery"])
                    self.assertEqual(delivery["status"], "pending")
                    self.assertEqual(delivery["desired_digest"], digest)
                    self.assertEqual(delivery["attempts"], 0)
                    self.assertEqual(delivery["correlation_id"], f"corr-{unique}")
                publication_id = cast(str, result["publication_record_id"])
                command_id = cast(str, result["command_id"])

                replay = await apply_durable_publish(
                    session,
                    command=command,
                    actor_id=cast(uuid.UUID, seeded["actor_id"]),
                )
                await session.commit()
                self.assertTrue(replay["replayed"])
                self.assertEqual(replay["publication_record_id"], publication_id)
                replay_records = cast(
                    list[dict[str, object]],
                    cast(dict[str, object], replay["propagation"])["records"],
                )
                self.assertEqual(
                    {
                        cast(
                            str,
                            cast(dict[str, object], row["delivery"])["delivery_id"],
                        )
                        for row in replay_records
                    },
                    {
                        cast(
                            str,
                            cast(dict[str, object], row["delivery"])["delivery_id"],
                        )
                        for row in records
                    },
                )
                self.assertEqual(cast(str, replay["command_id"]), command_id)
        finally:
            await engine.dispose()

    def test_ack_contract_syncs_once_and_denies_drift_forgery_stale(self) -> None:
        asyncio.run(self._exercise_ack_contract())

    async def _exercise_ack_contract(self) -> None:
        if _INTEGRATION_DATABASE_URL is None:
            raise AssertionError("integration database URL unexpectedly absent")
        engine = create_async_engine(_INTEGRATION_DATABASE_URL)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        unique = uuid.uuid4().hex
        seeded = await _seed_publication(sessions, unique)
        try:
            async with sessions() as session:
                command = _command_from_envelope(
                    cast(dict[str, object], seeded["envelope"]),
                    unique,
                )
                result = await apply_durable_publish(
                    session,
                    command=command,
                    actor_id=cast(uuid.UUID, seeded["actor_id"]),
                )
                await session.commit()
                publication_id = uuid.UUID(cast(str, result["publication_record_id"]))
                propagations = await list_publication_propagations(
                    session, publication_id
                )
                deliveries = await list_propagation_deliveries(
                    session, tuple(item.id for item in propagations)
                )
                self.assertEqual(len(deliveries), 2)
                delivery = deliveries[0]

                # Manual mutation may not set synced.
                with self.assertRaises(DurablePublishDenied):
                    _ = await update_propagation(
                        session,
                        command=PropagationUpdateCommand(
                            publication_id=publication_id,
                            surface_id=delivery.surface_id,
                            status=PropagationStatus.SYNCED,
                            expected_version=1,
                            command_id=f"propagation-forbidden-{unique}",
                            reason="attempted manual sync",
                        ),
                        actor_id=cast(uuid.UUID, seeded["actor_id"]),
                    )
                await session.rollback()

                # Exact signed ack syncs once.
                ack_body = _ack_body(delivery)
                receipt = await acknowledge_propagation_delivery(
                    session,
                    delivery_id=delivery.id,
                    ack_body=ack_body,
                    signature=_signed_ack_header(ack_body),
                    secret=_TEST_SECRET,
                    correlation_id="ack-corr",
                )
                await session.commit()
                self.assertFalse(receipt["replayed"])
                self.assertEqual(receipt["status"], "synced")
                self.assertEqual(
                    receipt["acknowledged_digest"], delivery.desired_digest
                )
                refreshed = await session.get(
                    GovernancePropagation, delivery.propagation_id
                )
                self.assertIsNotNone(refreshed)
                assert refreshed is not None
                self.assertEqual(refreshed.status, "synced")
                self.assertEqual(refreshed.version, 2)

                # Exact replay of the same ack returns the same receipt.
                replay_receipt = await acknowledge_propagation_delivery(
                    session,
                    delivery_id=delivery.id,
                    ack_body=ack_body,
                    signature=_signed_ack_header(ack_body),
                    secret=_TEST_SECRET,
                )
                await session.commit()
                self.assertTrue(replay_receipt["replayed"])
                self.assertEqual(replay_receipt["delivery_id"], receipt["delivery_id"])

                # Forged signature is denied.
                forged_body = _ack_body(delivery)
                with self.assertRaises(DeliveryVerificationError):
                    _ = await acknowledge_propagation_delivery(
                        session,
                        delivery_id=delivery.id,
                        ack_body=forged_body,
                        signature=_signed_ack_header(forged_body, "wrong-secret"),
                        secret=_TEST_SECRET,
                    )
                await session.rollback()

                # Drift (different digest) is denied as a conflict.
                drifted_body = _ack_body(delivery, digest="b" * 64)
                with self.assertRaises(DeliveryAckConflict):
                    _ = await acknowledge_propagation_delivery(
                        session,
                        delivery_id=delivery.id,
                        ack_body=drifted_body,
                        signature=_signed_ack_header(drifted_body),
                        secret=_TEST_SECRET,
                    )
                await session.rollback()

                # Stale version is denied.
                stale_body = _ack_body(delivery, version=999)
                with self.assertRaises(DeliveryAckConflict):
                    _ = await acknowledge_propagation_delivery(
                        session,
                        delivery_id=delivery.id,
                        ack_body=stale_body,
                        signature=_signed_ack_header(stale_body),
                        secret=_TEST_SECRET,
                    )
                await session.rollback()

                # Wrong channel binding is denied.
                wrong_surface_body = _ack_body(delivery, surface_id="internal-search")
                with self.assertRaises(DeliveryAckConflict):
                    _ = await acknowledge_propagation_delivery(
                        session,
                        delivery_id=delivery.id,
                        ack_body=wrong_surface_body,
                        signature=_signed_ack_header(wrong_surface_body),
                        secret=_TEST_SECRET,
                    )
                await session.rollback()
        finally:
            await engine.dispose()

    def test_sweep_dispatches_through_fake_consumer_and_dead_letters(self) -> None:
        asyncio.run(self._exercise_sweep())

    async def _exercise_sweep(self) -> None:
        if _INTEGRATION_DATABASE_URL is None:
            raise AssertionError("integration database URL unexpectedly absent")
        engine = create_async_engine(_INTEGRATION_DATABASE_URL)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        unique = uuid.uuid4().hex
        seeded = await _seed_publication(sessions, unique)
        try:
            with patch(
                "cygnus.publish.durable.get_settings",
                return_value=Settings(
                    delivery_targets_json=json.dumps(
                        {"agent-copilot": _CONSUMER_ORIGIN}
                    ),
                    delivery_hmac_secret=_TEST_SECRET,
                    delivery_timeout_seconds=5.0,
                    delivery_max_attempts=2,
                    environment="test",
                ),
            ):
                async with sessions() as session:
                    command = _command_from_envelope(
                        cast(dict[str, object], seeded["envelope"]),
                        unique,
                    )
                    result = await apply_durable_publish(
                        session,
                        command=command,
                        actor_id=cast(uuid.UUID, seeded["actor_id"]),
                    )
                    await session.commit()
                    publication_id = uuid.UUID(
                        cast(str, result["publication_record_id"])
                    )

            sweep_settings = Settings(
                delivery_targets_json=json.dumps({"agent-copilot": _CONSUMER_ORIGIN}),
                delivery_hmac_secret=_TEST_SECRET,
                delivery_timeout_seconds=5.0,
                delivery_max_attempts=2,
                environment="test",
            )
            reset_delivery_circuit()

            consumer = FakeConsumer(_TEST_SECRET)

            def client_factory() -> httpx.AsyncClient:
                return httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=cast(Any, consumer)),
                    timeout=5.0,
                )

            count = await drain_propagation_deliveries(
                settings=sweep_settings,
                session_factory=sessions,
                client_factory=client_factory,
            )
            self.assertEqual(count, 2)
            async with sessions() as session:
                propagations = await list_publication_propagations(
                    session, publication_id
                )
                by_surface = {item.surface_id: item for item in propagations}
                deliveries = {
                    item.surface_id: item
                    for item in await list_propagation_deliveries(
                        session, tuple(item.id for item in propagations)
                    )
                }
                self.assertEqual(by_surface["agent-copilot"].status, "synced")
                self.assertEqual(deliveries["agent-copilot"].status, "synced")
                self.assertIsNotNone(deliveries["agent-copilot"].acknowledged_digest)
                # The unconfigured surface stays pending with no fabricated truth.
                self.assertEqual(by_surface["internal-search"].status, "pending")
                self.assertEqual(deliveries["internal-search"].status, "pending")
                self.assertEqual(
                    deliveries["internal-search"].last_error,
                    "no_configured_delivery_target",
                )
                truth = delivery_to_dict(
                    deliveries["agent-copilot"], include_payload=True
                )
                self.assertEqual(truth["attempts"], 1)
                self.assertEqual(truth["status"], "synced")
                self.assertIsNotNone(truth["acknowledged_digest"])
                self.assertIsNotNone(truth["acknowledged_at"])
        finally:
            await engine.dispose()

    def test_bounded_retries_dead_letter_with_durable_evidence(self) -> None:
        asyncio.run(self._exercise_dead_letter())

    async def _exercise_dead_letter(self) -> None:
        if _INTEGRATION_DATABASE_URL is None:
            raise AssertionError("integration database URL unexpectedly absent")
        engine = create_async_engine(_INTEGRATION_DATABASE_URL)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        unique = uuid.uuid4().hex
        seeded = await _seed_publication(sessions, unique)
        try:
            with patch(
                "cygnus.publish.durable.get_settings",
                return_value=Settings(
                    delivery_targets_json=json.dumps(
                        {"agent-copilot": _CONSUMER_ORIGIN}
                    ),
                    delivery_hmac_secret=_TEST_SECRET,
                    delivery_timeout_seconds=5.0,
                    delivery_max_attempts=2,
                    environment="test",
                ),
            ):
                async with sessions() as session:
                    command = _command_from_envelope(
                        cast(dict[str, object], seeded["envelope"]),
                        unique,
                    )
                    result = await apply_durable_publish(
                        session,
                        command=command,
                        actor_id=cast(uuid.UUID, seeded["actor_id"]),
                    )
                    await session.commit()
                    publication_id = uuid.UUID(
                        cast(str, result["publication_record_id"])
                    )

            sweep_settings = Settings(
                delivery_targets_json=json.dumps({"agent-copilot": _CONSUMER_ORIGIN}),
                delivery_hmac_secret=_TEST_SECRET,
                delivery_timeout_seconds=5.0,
                delivery_max_attempts=2,
                environment="test",
            )
            reset_delivery_circuit()
            failing_consumer = FakeConsumer(_TEST_SECRET, fail_with=503)

            def failing_client() -> httpx.AsyncClient:
                return httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=cast(Any, failing_consumer)),
                    timeout=5.0,
                )

            first = await drain_propagation_deliveries(
                settings=sweep_settings,
                session_factory=sessions,
                client_factory=failing_client,
            )
            self.assertEqual(first, 2)
            async with sessions() as session:
                propagations = await list_publication_propagations(
                    session, publication_id
                )
                deliveries = {
                    item.surface_id: item
                    for item in await list_propagation_deliveries(
                        session, tuple(item.id for item in propagations)
                    )
                }
                # Retryable failure keeps both surfaces pending after attempt 1.
                self.assertEqual(deliveries["agent-copilot"].status, "pending")
                self.assertEqual(deliveries["agent-copilot"].attempts, 1)
                self.assertIn("http_503", deliveries["agent-copilot"].last_error or "")

            second = await drain_propagation_deliveries(
                settings=sweep_settings,
                session_factory=sessions,
                client_factory=failing_client,
            )
            self.assertEqual(second, 2)
            async with sessions() as session:
                propagations = await list_publication_propagations(
                    session, publication_id
                )
                by_surface = {item.surface_id: item for item in propagations}
                deliveries = {
                    item.surface_id: item
                    for item in await list_propagation_deliveries(
                        session, tuple(item.id for item in propagations)
                    )
                }
                # Exhaustion dead-letters the delivery and fails the propagation
                # with durable attempt evidence.
                self.assertEqual(deliveries["agent-copilot"].status, "dead_letter")
                self.assertEqual(deliveries["agent-copilot"].attempts, 2)
                self.assertEqual(by_surface["agent-copilot"].status, "failed")
                evidence = cast(
                    dict[str, object],
                    deliveries["agent-copilot"].attempt_evidence or {},
                )
                attempts = cast(list[object], evidence.get("attempts") or ())
                self.assertEqual(len(attempts), 2)
                self.assertEqual(
                    cast(dict[str, object], attempts[-1])["outcome"],
                    "dead_letter",
                )
        finally:
            await engine.dispose()


async def _seed_publication(
    sessions: async_sessionmaker[AsyncSession],
    unique: str,
) -> dict[str, object]:
    actor_id = uuid.uuid4()
    source_id = uuid.uuid4()
    async with sessions() as session:
        actor = Employee(
            id=actor_id,
            name="CYG-138 delivery reviewer",
            email=f"cyg138-{unique}@example.test",
            role="admin",
            global_role="admin",
            is_active=True,
        )
        source = Source(
            id=source_id,
            title=f"CYG-138 delivery evidence {unique}",
            full_text="Verified billing support policy evidence for delivery receipts.",
            source_type="url",
            language="en",
            url=f"https://example.test/cyg138/{unique}",
            status="ready",
            progress=100,
            contributed_by_employee_id=actor_id,
        )
        session.add_all((actor, source))
        await session.flush()
        attested_at = source.updated_at or datetime.now(timezone.utc)
        source.freshness_state = FreshnessState.FRESH.value
        source.freshness_actor_id = actor_id
        source.freshness_reason = (
            "Attested fresh for the CYG-138 delivery receipt test."
        )
        source.freshness_attested_at = attested_at
        source.freshness_expires_at = attested_at + timedelta(days=1)

        slug = f"cyg138-delivery-{unique}"
        signal_ref = f"ticket:cyg138:{unique}"
        draft = await create_wiki_draft(
            session,
            page_id=None,
            author_id=actor_id,
            content_md=(
                "# Delivery receipt policy\n\n"
                "Use verified source evidence and the governed audience binding."
            ),
            note="CYG-138 delivery receipt review",
            source="receipt_test",
            source_metadata={"source_ids": [str(source_id)]},
            draft_kind="create",
            suggested_metadata={
                "slug": slug,
                "title": f"CYG-138 Delivery Policy {unique}",
                "page_type": "concept",
                "knowledge_type_slugs": ["answer_card"],
                "scope_type": "global",
                "scope_id": None,
            },
        )
        page = await approve_wiki_draft(
            session,
            draft,
            reviewer_id=actor_id,
            reviewer_note="Evidence, scope, and audience binding verified by receipt test.",
        )
        object_ref = governed_object_ref(page.id)
        audience = AudienceFilter(
            visibility=Visibility.INTERNAL,
            product_lines=("billing",),
            regions=("global",),
            languages=("en",),
        )
        for channel in ("agent-copilot", "internal-search"):
            _ = await create_audience_binding(
                session,
                command=AudienceBindingCreate(
                    page_id=page.id,
                    object_ref=object_ref,
                    variant_ref="internal-governed",
                    channel=channel,
                    audience_filter=audience,
                ),
                actor_id=actor_id,
            )
        signal = await create_governance_signal(
            session,
            GovernanceSignalInput(
                signal_ref=signal_ref,
                signal_type=PressureSignalType.TICKET_CLUSTER,
                object_ref=object_ref,
                title=f"CYG-138 billing pressure {unique}",
                object_type=KnowledgeObjectType.ANSWER_CARD,
                page_id=page.id,
                source_id=source_id,
                audience_filter=audience,
                affected_surfaces=("agent-copilot", "internal-search"),
                trigger_signals=("ticket_volume:12",),
                freshness=FreshnessState.FRESH,
                summary="Repeated billing tickets require a governed policy publication.",
                reason="Persisted ticket pressure crossed the review threshold.",
                evidence_excerpt="Twelve verified tickets repeat the same billing policy gap.",
            ),
            created_by_id=actor_id,
        )
        await session.commit()

        async with sessions() as session:
            envelope = await durable_publish_command_for_signal(
                session,
                signal=signal,
                action_key="publish",
            )
            if envelope is None:
                raise AssertionError("durable publish command did not qualify")
            await session.commit()

    return {
        "actor_id": actor_id,
        "source_id": source_id,
        "envelope": envelope,
    }


def _command_from_envelope(
    envelope: dict[str, object],
    unique: str,
) -> DurablePublishCommand:
    return DurablePublishCommand(
        draft_id=uuid.UUID(cast(str, envelope["draft_id"])),
        approval_ref=uuid.UUID(cast(str, envelope["approval_ref"])),
        approval_digest=cast(str, envelope["approval_digest"]),
        scope_digest=cast(str, envelope["scope_digest"]),
        signal_id=uuid.UUID(cast(str, envelope["signal_id"])),
        signal_freshness=cast(str, envelope["signal_freshness"]),
        command_id=f"publish-{unique}-{cast(str, envelope['command_id'])[-12:]}",
        action_key=cast(str, envelope["action_key"]),
        target_channels=tuple(cast(list[str], envelope["target_channels"])),
        expected_version=cast(int, envelope["expected_version"]),
        reason=cast(str, envelope["reason"]),
    )


if __name__ == "__main__":
    _ = unittest.main()
