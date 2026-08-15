"""CYG-140 actor-bound tool command receipt tests.

Covers: exact replay returns the stored durable result with one identity and
never creates a second draft/event/audit; reusing the command id with changed
normalized input or a different actor conflicts without writes; a failed write
never persists a receipt; and the MCP propose/update bodies pass command_id
into the shared adapter path.
"""

from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.governance.tool_command_receipts import (
    ToolCommandReceiptConflict,
    ToolCommandReceiptWrite,
    create_tool_command_receipt,
    replay_tool_command_receipt,
    tool_command_receipt_ref,
    tool_command_request_fingerprint,
)
from cygnus.integrations.governed_draft_review_tools import (
    GovernedDraftReviewTools,
)
from cygnus.runtime.database.models import (
    Employee,
    GovernanceToolCommandReceipt,
)


class _ReceiptSession:
    """Minimal async session double returning no durable receipt rows."""

    def __init__(self) -> None:
        self.added: list[object] = []
        self.flushed = 0
        self._existing: dict[tuple[object, str, str], object] = {}

    def seed(self, receipt: object) -> None:
        self._existing[("receipt", "any", "any")] = receipt

    async def execute(self, statement: object) -> object:
        existing = self._existing.get(("receipt", "any", "any"))
        return SimpleNamespace(scalar_one_or_none=lambda: existing)

    def add(self, item: object) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        self.flushed += 1


def _receipt(
    *,
    command_id: str,
    request_fingerprint: str,
    result_payload: dict[str, Any],
    actor_id: uuid.UUID,
) -> GovernanceToolCommandReceipt:
    return cast(
        GovernanceToolCommandReceipt,
        SimpleNamespace(
            id=uuid.uuid4(),
            actor_id=actor_id,
            tool_name="propose_knowledge_object",
            command_id=command_id,
            request_fingerprint=request_fingerprint,
            result_payload=result_payload,
            correlation_id=None,
            traceparent=None,
        ),
    )


def _actor() -> Employee:
    department_id = uuid.uuid4()
    return cast(
        Employee,
        SimpleNamespace(
            id=uuid.uuid4(),
            role="employee",
            global_role="contributor",
            name="Draft author",
            email="author@example.test",
            permissions=(),
            is_admin=False,
            department_ids=[department_id],
        ),
    )


class ToolCommandFingerprintTests(unittest.TestCase):
    def test_fingerprint_is_deterministic_for_identical_input(self) -> None:
        actor_id = uuid.uuid4()
        arguments = {
            "proposed_object_type": "answer_card",
            "title": "Billing policy",
            "audience_context": {"visibility": "internal"},
        }
        first = tool_command_request_fingerprint(
            actor_id=actor_id,
            tool_name="propose_knowledge_object",
            command_id="propose:fp-1",
            normalized_arguments=arguments,
        )
        second = tool_command_request_fingerprint(
            actor_id=actor_id,
            tool_name="propose_knowledge_object",
            command_id="propose:fp-1",
            normalized_arguments=dict(arguments),
        )

        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_fingerprint_changes_on_payload_actor_or_command_drift(self) -> None:
        actor_id = uuid.uuid4()
        base = tool_command_request_fingerprint(
            actor_id=actor_id,
            tool_name="propose_knowledge_object",
            command_id="propose:fp-2",
            normalized_arguments={"title": "Billing"},
        )
        changed_payload = tool_command_request_fingerprint(
            actor_id=actor_id,
            tool_name="propose_knowledge_object",
            command_id="propose:fp-2",
            normalized_arguments={"title": "Billing v2"},
        )
        changed_actor = tool_command_request_fingerprint(
            actor_id=uuid.uuid4(),
            tool_name="propose_knowledge_object",
            command_id="propose:fp-2",
            normalized_arguments={"title": "Billing"},
        )
        changed_command = tool_command_request_fingerprint(
            actor_id=actor_id,
            tool_name="propose_knowledge_object",
            command_id="propose:fp-3",
            normalized_arguments={"title": "Billing"},
        )

        self.assertNotEqual(base, changed_payload)
        self.assertNotEqual(base, changed_actor)
        self.assertNotEqual(base, changed_command)


class ToolCommandReceiptServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_persists_a_fresh_receipt_and_flushes_only(self) -> None:
        actor_id = uuid.uuid4()
        session = _ReceiptSession()
        write = await create_tool_command_receipt(
            cast(AsyncSession, cast(object, session)),
            actor_id=actor_id,
            tool_name="propose_knowledge_object",
            command_id="propose:create-1",
            request_fingerprint="a" * 64,
            result_payload={"status": "success", "persisted": True},
        )

        self.assertFalse(write.replayed)
        self.assertEqual(len(session.added), 1)
        self.assertEqual(session.flushed, 1)
        self.assertTrue(write.receipt_ref.startswith("tool-command-receipt:"))

    async def test_create_binds_active_request_correlation_to_durable_receipt(
        self,
    ) -> None:
        from cygnus.observability import current_traceparent, request_correlation

        actor_id = uuid.uuid4()
        session = _ReceiptSession()
        correlation_id = "550e8400-e29b-41d4-a716-446655440000"
        with request_correlation(correlation_id):
            expected_traceparent = current_traceparent()
            write = await create_tool_command_receipt(
                cast(AsyncSession, cast(object, session)),
                actor_id=actor_id,
                tool_name="propose_knowledge_object",
                command_id="propose:correlation-1",
                request_fingerprint="c" * 64,
                result_payload={"status": "success"},
            )

        self.assertEqual(write.receipt.correlation_id, uuid.UUID(correlation_id))
        self.assertEqual(write.receipt.traceparent, expected_traceparent)
        self.assertEqual(
            write.to_dict()["correlation_id"],
            correlation_id,
        )

    async def test_exact_replay_returns_one_durable_identity(self) -> None:
        actor_id = uuid.uuid4()
        stored = {"status": "success", "persisted": True, "summary": "created"}
        receipt = _receipt(
            command_id="propose:replay-1",
            request_fingerprint="b" * 64,
            result_payload=stored,
            actor_id=actor_id,
        )
        session = _ReceiptSession()
        session.seed(receipt)

        write = await replay_tool_command_receipt(
            cast(AsyncSession, cast(object, session)),
            actor_id=actor_id,
            tool_name="propose_knowledge_object",
            command_id="propose:replay-1",
            request_fingerprint="b" * 64,
        )

        self.assertIsNotNone(write)
        assert write is not None
        self.assertTrue(write.replayed)
        self.assertEqual(write.receipt_ref, tool_command_receipt_ref(receipt))

    async def test_drift_conflicts_without_writes(self) -> None:
        actor_id = uuid.uuid4()
        receipt = _receipt(
            command_id="propose:drift-1",
            request_fingerprint="c" * 64,
            result_payload={"status": "success"},
            actor_id=actor_id,
        )
        session = _ReceiptSession()
        session.seed(receipt)

        with self.assertRaises(ToolCommandReceiptConflict):
            await replay_tool_command_receipt(
                cast(AsyncSession, cast(object, session)),
                actor_id=actor_id,
                tool_name="propose_knowledge_object",
                command_id="propose:drift-1",
                request_fingerprint="d" * 64,
            )
        self.assertEqual(len(session.added), 0)

    async def test_missing_receipt_returns_none(self) -> None:
        session = _ReceiptSession()
        write = await replay_tool_command_receipt(
            cast(AsyncSession, cast(object, session)),
            actor_id=uuid.uuid4(),
            tool_name="propose_knowledge_object",
            command_id="propose:missing-1",
            request_fingerprint="e" * 64,
        )
        self.assertIsNone(write)


class GovernedReceiptAdapterTests(unittest.IsolatedAsyncioTestCase):
    def _tools(self, session: object) -> GovernedDraftReviewTools:
        actor = _actor()
        return GovernedDraftReviewTools(
            cast(AsyncSession, session),
            actor=actor,
        )

    async def test_propose_exact_replay_returns_stored_result_without_new_write(
        self,
    ) -> None:
        import cygnus.integrations.governed_draft_review_tools as draft_tools

        actor = _actor()
        session = _ReceiptSession()
        stored: dict[str, Any] = {
            "status": "success",
            "summary": "Durable knowledge-object draft created.",
            "data": {"draft_id": str(uuid.uuid4()), "title": "Billing policy"},
            "trace_ref": f"draft:{uuid.uuid4()}",
            "persisted": True,
            "rehearsal": False,
            "warnings": [],
            "errors": [],
        }
        receipt = _receipt(
            command_id="propose:adapter-replay-1",
            request_fingerprint="f" * 64,
            result_payload=stored,
            actor_id=actor.id,
        )
        replay_write = ToolCommandReceiptWrite(receipt=receipt, replayed=True)
        tools = GovernedDraftReviewTools(
            cast(AsyncSession, cast(object, session)),
            actor=actor,
        )

        with (
            patch.object(
                draft_tools,
                "replay_tool_command_receipt",
                AsyncMock(return_value=replay_write),
            ) as replay,
            patch.object(draft_tools, "create_wiki_draft", AsyncMock()) as create,
            patch.object(draft_tools, "log_audit", AsyncMock()) as audit,
            patch.object(
                GovernedDraftReviewTools,
                "_visible_sources",
                AsyncMock(
                    side_effect=AssertionError("exact replay must not reload sources")
                ),
            ) as visible_sources,
        ):
            result = await tools.propose_knowledge_object(
                command_id="propose:adapter-replay-1",
                proposed_object_type="answer_card",
                title="Billing policy",
                input_summary="Use the approved policy.",
                audience_context={"visibility": "internal"},
                scope_type="department",
                scope_id=str(actor.department_ids[0]),
            )

        self.assertEqual(result["status"], "success")
        self.assertTrue(result["replayed"])
        self.assertEqual(result["receipt_ref"], replay_write.receipt_ref)
        self.assertEqual(result["data"]["draft_id"], stored["data"]["draft_id"])
        replay.assert_awaited_once()
        create.assert_not_awaited()
        audit.assert_not_awaited()
        visible_sources.assert_not_awaited()

    async def test_propose_drift_conflicts_without_writes(self) -> None:
        import cygnus.integrations.governed_draft_review_tools as draft_tools

        actor = _actor()
        tools = GovernedDraftReviewTools(
            cast(AsyncSession, cast(object, _ReceiptSession())),
            actor=actor,
        )

        with (
            patch.object(
                draft_tools,
                "replay_tool_command_receipt",
                AsyncMock(side_effect=ToolCommandReceiptConflict("drift")),
            ),
            patch.object(draft_tools, "create_wiki_draft", AsyncMock()) as create,
        ):
            result = await tools.propose_knowledge_object(
                command_id="propose:adapter-drift-1",
                proposed_object_type="answer_card",
                title="Billing policy",
                input_summary="Use the approved policy.",
                audience_context={"visibility": "internal"},
                scope_type="department",
                scope_id=str(actor.department_ids[0]),
            )

        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["errors"], ["idempotency_conflict"])
        create.assert_not_awaited()

    async def test_update_exact_replay_returns_stored_result(self) -> None:
        import cygnus.integrations.governed_draft_review_tools as draft_tools

        actor = _actor()
        stored = {
            "status": "success",
            "summary": "Durable draft updated.",
            "data": {
                "draft_id": str(uuid.uuid4()),
                "version": 2,
                "changed_fields": ["content"],
            },
            "trace_ref": f"draft:{uuid.uuid4()}",
            "persisted": True,
            "rehearsal": False,
            "warnings": [],
            "errors": [],
        }
        receipt = _receipt(
            command_id="update:adapter-replay-1",
            request_fingerprint="g" * 64,
            result_payload=stored,
            actor_id=actor.id,
        )
        replay_write = ToolCommandReceiptWrite(receipt=receipt, replayed=True)
        tools = GovernedDraftReviewTools(
            cast(AsyncSession, cast(object, _ReceiptSession())),
            actor=actor,
        )

        with (
            patch.object(
                draft_tools,
                "replay_tool_command_receipt",
                AsyncMock(return_value=replay_write),
            ),
            patch.object(
                draft_tools,
                "update_wiki_draft",
                AsyncMock(return_value=(None, False)),
            ) as update,
        ):
            result = await tools.update_draft_object(
                command_id="update:adapter-replay-1",
                draft_id=str(uuid.uuid4()),
                expected_version=2,
                patch={"content": "# Billing\n\nUpdated content"},
            )

        self.assertEqual(result["status"], "success")
        self.assertTrue(result["replayed"])
        self.assertEqual(result["data"]["version"], 2)
        update.assert_not_awaited()

    async def test_failed_update_persists_no_receipt(self) -> None:
        import cygnus.integrations.governed_draft_review_tools as draft_tools

        from cygnus.review.contributions import DraftVersionConflict

        actor = _actor()
        tools = GovernedDraftReviewTools(
            cast(AsyncSession, cast(object, _ReceiptSession())),
            actor=actor,
        )
        draft = SimpleNamespace(id=uuid.uuid4(), author_id=actor.id)

        with (
            patch.object(
                draft_tools,
                "replay_tool_command_receipt",
                AsyncMock(return_value=None),
            ),
            patch.object(
                GovernedDraftReviewTools,
                "_scoped_draft",
                AsyncMock(return_value=draft),
            ),
            patch.object(
                draft_tools,
                "update_wiki_draft",
                AsyncMock(side_effect=DraftVersionConflict(1, 2)),
            ),
            patch.object(
                draft_tools,
                "create_tool_command_receipt",
                AsyncMock(),
            ) as receipt,
        ):
            result = await tools.update_draft_object(
                command_id="update:adapter-fail-1",
                draft_id=str(draft.id),
                expected_version=2,
                patch={"content": "# Billing\n\nNew"},
            )

        self.assertEqual(result["status"], "conflict")
        receipt.assert_not_awaited()


class GovernedMCPCommandIdTests(unittest.TestCase):
    def test_propose_definition_requires_command_id(self) -> None:
        from cygnus.integrations.governed_draft_review_tools import (
            draft_review_tool_definitions,
        )

        propose = draft_review_tool_definitions()[0]
        self.assertIn("command_id", propose.parameters["required"])
        self.assertEqual(
            propose.parameters["properties"]["command_id"]["maxLength"],
            220,
        )
        update = draft_review_tool_definitions()[1]
        self.assertIn("command_id", update.parameters["required"])


if __name__ == "__main__":
    unittest.main()
