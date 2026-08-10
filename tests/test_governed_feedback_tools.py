from __future__ import annotations

import asyncio
import json
import unittest
import uuid
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.governance.feedback import (
    FeedbackSignalInput,
    GovernanceFeedbackSignal,
    create_feedback_signal,
)
from cygnus.integrations.governed_feedback_tools import (
    GovernedFeedbackTools,
    feedback_tool_bindings,
    feedback_tool_definitions,
)
from cygnus.runtime.database.models import AuditLog, Employee, WikiPage, WikiPageDraft
from cygnus.runtime.mcp.permissions import ANY_AUTHENTICATED, requirement_for
from cygnus.runtime.mcp.server import create_mcp_server
import cygnus.runtime.mcp.tools as mcp_tools


class _Result:
    def __init__(self, value: object | tuple[object, ...] | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object | None:
        if isinstance(self._value, tuple):
            if not self._value:
                return None
            if len(self._value) > 1:
                raise AssertionError("scalar_one_or_none received multiple rows")
            return self._value[0]
        return self._value

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[object]:
        if isinstance(self._value, tuple):
            return list(self._value)
        if self._value is None:
            return []
        return [self._value]


class _FeedbackSession:
    def __init__(
        self,
        *,
        page: object | None = None,
        draft: object | None = None,
    ) -> None:
        self.page = page
        self.draft = draft
        self.added: list[object] = []
        self.operations: list[str] = []
        self.flush_count = 0
        self.execute_count = 0
        self.commit = AsyncMock()

    async def execute(self, statement: object) -> _Result:
        self.execute_count += 1
        descriptions = getattr(statement, "column_descriptions", ())
        entity = descriptions[0].get("entity") if descriptions else None
        if entity is WikiPage:
            return _Result(self.page)
        if entity is WikiPageDraft:
            return _Result(self.draft)
        raise AssertionError(f"unexpected SQL entity: {entity}")

    def add(self, item: object) -> None:
        self.added.append(item)
        self.operations.append("add")

    async def flush(self) -> None:
        self.flush_count += 1
        self.operations.append("flush")


class _SessionContext:
    def __init__(self, session: object) -> None:
        self.session = session

    async def __aenter__(self) -> object:
        return self.session

    async def __aexit__(self, *_args: object) -> None:
        return None


def _actor() -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        role="admin",
        global_role="admin",
        employee_departments=[],
    )


def _page(*, page_id: uuid.UUID | None = None, slug: str = "visible") -> Any:
    return SimpleNamespace(
        id=page_id or uuid.uuid4(),
        slug=slug,
        title="Visible answer",
        summary="A governed answer.",
        content_md="# Visible answer\n\nA governed answer.",
        status="mature",
        knowledge_type_slugs=["answer_card"],
        source_ids=[],
    )


def _draft(*, draft_id: uuid.UUID, page_id: uuid.UUID | None) -> Any:
    return SimpleNamespace(
        id=draft_id,
        page_id=page_id,
        suggested_metadata=None if page_id is not None else {"slug": "new-answer"},
    )


def _payload(result: object) -> dict[str, Any]:
    content = getattr(result, "content", None)
    if not content:
        raise AssertionError("MCP result had no content")
    return json.loads(content[0].text)


class FeedbackPersistenceTests(unittest.TestCase):
    def test_input_normalizes_context_and_persists_actor_and_refs(self) -> None:
        actor_id = uuid.uuid4()
        draft_id = uuid.uuid4()
        session = _FeedbackSession()
        signal_input = FeedbackSignalInput(
            signal_type="human_rewrite",
            audience_context={"visibility": "internal", "plan": "enterprise"},
            object_id="ko-visible",
            draft_id=draft_id,
            source_context_ref="turn:42",
            notes="Rewrite was required.",
        )

        signal = asyncio.run(
            create_feedback_signal(
                cast(AsyncSession, cast(object, session)),
                signal_input,
                actor_id=actor_id,
            )
        )

        self.assertIsInstance(signal, GovernanceFeedbackSignal)
        self.assertEqual(signal.signal_type, "human_rewrite")
        self.assertEqual(signal.actor_id, actor_id)
        self.assertEqual(signal.audience_context["plan_tier"], "enterprise")
        self.assertEqual(signal.draft_id, draft_id)
        self.assertIs(session.added[0], signal)
        session.commit.assert_not_awaited()

    def test_persistence_revalidates_mutated_input_before_write(self) -> None:
        session = _FeedbackSession()
        signal_input = FeedbackSignalInput(
            signal_type="answer_accepted",
            audience_context={"visibility": "internal", "region": "us"},
        )
        mutable_context = cast(dict[str, object], signal_input.audience_context)
        mutable_context["region"] = " "

        with self.assertRaisesRegex(ValueError, "audience_context.region"):
            asyncio.run(
                create_feedback_signal(
                    cast(AsyncSession, cast(object, session)),
                    signal_input,
                    actor_id=uuid.uuid4(),
                )
            )

        self.assertEqual(session.added, [])
        self.assertEqual(session.flush_count, 0)
        session.commit.assert_not_awaited()

    def test_definition_is_one_strict_r1_tool(self) -> None:
        definitions = feedback_tool_definitions()
        self.assertEqual(len(definitions), 1)
        definition = definitions[0]
        self.assertEqual(definition.name, "record_feedback_signal")
        self.assertEqual(definition.risk_level, "R1")
        self.assertEqual(
            definition.parameters["required"], ["signal_type", "audience_context"]
        )
        self.assertFalse(definition.parameters["additionalProperties"])
        self.assertEqual(
            set(definition.parameters["properties"]["signal_type"]["enum"]),
            {
                "answer_accepted",
                "human_rewrite",
                "escalated",
                "low_rating",
                "unsupported_answer",
                "stale_answer",
            },
        )
        binding_tools = GovernedFeedbackTools(
            cast(AsyncSession, cast(object, _FeedbackSession())),
            actor=cast(Employee, cast(object, _actor())),
        )
        self.assertEqual(
            [item[0] for item in feedback_tool_bindings(binding_tools)],
            [definition],
        )


class GovernedFeedbackAdapterTests(unittest.TestCase):
    def test_generic_feedback_is_durable_and_recorded_only(self) -> None:
        actor = _actor()
        session = _FeedbackSession()
        tools = GovernedFeedbackTools(
            cast(AsyncSession, cast(object, session)), actor=cast(object, actor)
        )
        result = asyncio.run(
            tools.record_feedback_signal(
                signal_type="answer_accepted",
                audience_context={"visibility": "external"},
            )
        )

        self.assertEqual(result["status"], "success")
        self.assertTrue(result["persisted"])
        self.assertFalse(result["rehearsal"])
        self.assertEqual(result["routing_state"], "recorded_only")
        self.assertFalse(result["review_queued"])
        self.assertFalse(result["refresh_queued"])
        self.assertTrue(str(result["trace_ref"]).startswith("feedback-signal:"))
        self.assertEqual(len(session.added), 2)
        signal, audit_entry = session.added
        self.assertIsInstance(signal, GovernanceFeedbackSignal)
        self.assertIsInstance(audit_entry, AuditLog)
        self.assertEqual(audit_entry.resource_id, str(signal.id))
        self.assertEqual(audit_entry.action, "record_feedback_signal")
        self.assertEqual(audit_entry.resource_type, "governance_feedback_signal")
        self.assertEqual(
            session.operations,
            ["add", "flush", "add", "flush"],
        )
        self.assertEqual(session.flush_count, 2)
        session.commit.assert_not_awaited()
        self.assertEqual(session.execute_count, 0)

    def test_linked_object_and_materialized_draft_write_fact_and_audit(self) -> None:
        actor = _actor()
        page = _page(slug="linked-answer")
        draft_id = uuid.uuid4()
        draft = _draft(draft_id=draft_id, page_id=page.id)
        session = _FeedbackSession(page=page, draft=draft)
        tools = GovernedFeedbackTools(
            cast(AsyncSession, cast(object, session)), actor=cast(object, actor)
        )

        result = asyncio.run(
            tools.record_feedback_signal(
                signal_type="human_rewrite",
                audience_context={"visibility": "internal"},
                object_id="ko-linked-answer",
                draft_id=str(draft_id),
                notes="Linked correction.",
            )
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["object_id"], "ko-linked-answer")
        self.assertEqual(result["draft_id"], str(draft_id))
        data = cast(dict[str, Any], result["data"])
        self.assertEqual(data["object_id"], "ko-linked-answer")
        self.assertEqual(data["page_id"], str(page.id))
        self.assertEqual(data["draft_id"], str(draft_id))
        self.assertEqual(result["routing_state"], "recorded_only")
        self.assertFalse(result["review_queued"])
        self.assertFalse(result["refresh_queued"])
        signal, audit_entry = session.added
        self.assertIsInstance(signal, GovernanceFeedbackSignal)
        self.assertEqual(signal.object_id, "ko-linked-answer")
        self.assertEqual(signal.page_id, page.id)
        self.assertEqual(signal.draft_id, draft_id)
        self.assertIsInstance(audit_entry, AuditLog)
        self.assertEqual(audit_entry.resource_id, str(signal.id))
        self.assertEqual(
            session.operations,
            ["add", "flush", "add", "flush"],
        )
        self.assertEqual(session.execute_count, 3)
        session.commit.assert_not_awaited()

    def test_duplicate_visible_object_slug_is_safe_not_found_without_write(
        self,
    ) -> None:
        actor = _actor()
        first = _page(slug="duplicate")
        second = _page(slug="duplicate")
        duplicate_session = _FeedbackSession(page=(first, second))
        duplicate_tools = GovernedFeedbackTools(
            cast(AsyncSession, cast(object, duplicate_session)),
            actor=cast(object, actor),
        )
        with (
            patch(
                "cygnus.integrations.governed_feedback_tools.create_feedback_signal",
                new=AsyncMock(),
            ) as create,
            patch(
                "cygnus.integrations.governed_feedback_tools.log_audit",
                new=AsyncMock(),
            ) as audit,
        ):
            duplicate = asyncio.run(
                duplicate_tools.record_feedback_signal(
                    signal_type="unsupported_answer",
                    audience_context={"visibility": "internal"},
                    object_id="ko-duplicate",
                )
            )

        absent_session = _FeedbackSession()
        absent_tools = GovernedFeedbackTools(
            cast(AsyncSession, cast(object, absent_session)),
            actor=cast(object, actor),
        )
        absent = asyncio.run(
            absent_tools.record_feedback_signal(
                signal_type="unsupported_answer",
                audience_context={"visibility": "internal"},
                object_id="ko-duplicate",
            )
        )

        self.assertEqual(duplicate, absent)
        self.assertEqual(duplicate["status"], "not_found")
        self.assertEqual(duplicate["data"], {})
        self.assertNotIn("ko-duplicate", duplicate["summary"])
        create.assert_not_awaited()
        audit.assert_not_awaited()
        self.assertEqual(duplicate_session.added, [])
        duplicate_session.commit.assert_not_awaited()

    def test_invalid_arguments_are_rejected_before_resource_lookup(self) -> None:
        actor = _actor()
        session = _FeedbackSession()
        tools = GovernedFeedbackTools(
            cast(AsyncSession, cast(object, session)), actor=cast(object, actor)
        )

        result = asyncio.run(
            tools.record_feedback_signal(
                signal_type="answer_accepted",
                audience_context={"visibility": "internal"},
                object_id="ko-hidden",
                notes=" ",
            )
        )

        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["errors"], ["invalid_arguments"])
        self.assertEqual(session.execute_count, 0)

    def test_hidden_and_absent_object_refs_share_safe_not_found_shape(self) -> None:
        actor = _actor()
        session = _FeedbackSession()
        tools = GovernedFeedbackTools(
            cast(AsyncSession, cast(object, session)), actor=cast(object, actor)
        )
        with patch.object(
            GovernedFeedbackTools,
            "_scoped_object",
            new=AsyncMock(return_value=None),
        ):
            hidden = asyncio.run(
                tools.record_feedback_signal(
                    signal_type="low_rating",
                    audience_context={"visibility": "internal"},
                    object_id="ko-hidden",
                )
            )
            absent = asyncio.run(
                tools.record_feedback_signal(
                    signal_type="low_rating",
                    audience_context={"visibility": "internal"},
                    object_id="ko-absent",
                )
            )

        self.assertEqual(hidden, absent)
        self.assertEqual(hidden["status"], "not_found")
        self.assertEqual(hidden["data"], {})
        self.assertNotIn("ko-hidden", hidden["summary"])
        self.assertEqual(session.added, [])
        self.assertEqual(session.flush_count, 0)
        session.commit.assert_not_awaited()


    def test_hidden_and_absent_draft_refs_share_safe_not_found_shape(self) -> None:
        actor = _actor()
        session = _FeedbackSession()
        tools = GovernedFeedbackTools(
            cast(AsyncSession, cast(object, session)), actor=cast(object, actor)
        )
        hidden_id = uuid.uuid4()
        absent_id = uuid.uuid4()
        with patch.object(
            GovernedFeedbackTools,
            "_scoped_draft",
            new=AsyncMock(return_value=(None, None)),
        ):
            hidden = asyncio.run(
                tools.record_feedback_signal(
                    signal_type="low_rating",
                    audience_context={"visibility": "internal"},
                    draft_id=str(hidden_id),
                )
            )
            absent = asyncio.run(
                tools.record_feedback_signal(
                    signal_type="low_rating",
                    audience_context={"visibility": "internal"},
                    draft_id=str(absent_id),
                )
            )

        self.assertEqual(hidden, absent)
        self.assertEqual(hidden["status"], "not_found")
        self.assertEqual(hidden["data"], {})
        self.assertNotIn(str(hidden_id), hidden["summary"])
        self.assertEqual(session.added, [])
        self.assertEqual(session.flush_count, 0)
        session.commit.assert_not_awaited()

    def test_conflicting_object_and_draft_refs_do_not_write(self) -> None:
        actor = _actor()
        page = _page(slug="one")
        other_page = _page(slug="two")
        draft_id = uuid.uuid4()
        draft = _draft(draft_id=draft_id, page_id=other_page.id)
        session = _FeedbackSession()
        tools = GovernedFeedbackTools(
            cast(AsyncSession, cast(object, session)), actor=cast(object, actor)
        )
        with (
            patch.object(
                GovernedFeedbackTools,
                "_scoped_object",
                new=AsyncMock(return_value=page),
            ),
            patch.object(
                GovernedFeedbackTools,
                "_scoped_draft",
                new=AsyncMock(return_value=(draft, other_page)),
            ),
            patch(
                "cygnus.integrations.governed_feedback_tools.create_feedback_signal",
                new=AsyncMock(),
            ) as create,
            patch(
                "cygnus.integrations.governed_feedback_tools.log_audit",
                new=AsyncMock(),
            ) as audit,
        ):
            result = asyncio.run(
                tools.record_feedback_signal(
                    signal_type="escalated",
                    audience_context={"visibility": "internal"},
                    object_id="ko-one",
                    draft_id=str(draft_id),
                )
            )

        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["errors"], ["reference_mismatch"])
        create.assert_not_awaited()
        audit.assert_not_awaited()
        self.assertEqual(session.added, [])
        self.assertEqual(session.flush_count, 0)
        session.commit.assert_not_awaited()


    def test_object_and_unmaterialized_draft_refs_do_not_write(self) -> None:
        actor = _actor()
        page = _page(slug="new-answer")
        draft_id = uuid.uuid4()
        draft = _draft(draft_id=draft_id, page_id=None)
        session = _FeedbackSession()
        tools = GovernedFeedbackTools(
            cast(AsyncSession, cast(object, session)), actor=cast(object, actor)
        )
        with (
            patch.object(
                GovernedFeedbackTools,
                "_scoped_object",
                new=AsyncMock(return_value=page),
            ),
            patch.object(
                GovernedFeedbackTools,
                "_scoped_draft",
                new=AsyncMock(return_value=(draft, None)),
            ),
            patch(
                "cygnus.integrations.governed_feedback_tools.create_feedback_signal",
                new=AsyncMock(),
            ) as create,
            patch(
                "cygnus.integrations.governed_feedback_tools.log_audit",
                new=AsyncMock(),
            ) as audit,
        ):
            result = asyncio.run(
                tools.record_feedback_signal(
                    signal_type="escalated",
                    audience_context={"visibility": "internal"},
                    object_id="ko-new-answer",
                    draft_id=str(draft_id),
                )
            )

        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["errors"], ["reference_mismatch"])
        create.assert_not_awaited()
        audit.assert_not_awaited()
        self.assertEqual(session.added, [])
        self.assertEqual(session.flush_count, 0)
        session.commit.assert_not_awaited()


class GovernedFeedbackMCPTests(unittest.TestCase):
    def test_wrong_json_type_is_invalid_before_authentication(self) -> None:
        tool = asyncio.run(create_mcp_server().get_tool("record_feedback_signal"))
        if tool is None:
            raise AssertionError("feedback MCP tool was not registered")
        with (
            patch.object(
                mcp_tools,
                "_get_identity",
                new=AsyncMock(side_effect=AssertionError("auth must not run")),
            ) as get_identity,
            patch(
                "cygnus.runtime.mcp.logging._persist_log",
                new=AsyncMock(return_value=None),
            ),
        ):
            result = asyncio.run(
                tool.run(
                    {
                        "signal_type": "answer_accepted",
                        "audience_context": True,
                    }
                )
            )

        payload = _payload(result)
        self.assertEqual(payload["status"], "invalid")
        self.assertEqual(payload["errors"], ["invalid_arguments"])
        get_identity.assert_not_awaited()

    def test_mcp_commits_only_persisted_success_and_uses_any_authenticated(self) -> None:
        tool = asyncio.run(create_mcp_server().get_tool("record_feedback_signal"))
        if tool is None:
            raise AssertionError("feedback MCP tool was not registered")
        self.assertIs(requirement_for(tool.fn), ANY_AUTHENTICATED)

        actor = _actor()
        identity = SimpleNamespace(employee_id=actor.id)
        session = _FeedbackSession()
        adapter = SimpleNamespace(
            record_feedback_signal=AsyncMock(
                return_value={"status": "success", "persisted": True}
            )
        )
        with (
            patch.object(
                mcp_tools,
                "_get_identity",
                new=AsyncMock(return_value=(identity, None)),
            ),
            patch.object(
                mcp_tools,
                "_get_governed_feedback_tools",
                new=AsyncMock(return_value=(adapter, None)),
            ),
            patch(
                "cygnus.runtime.database.async_session_factory",
                return_value=_SessionContext(session),
            ),
            patch(
                "cygnus.runtime.mcp.logging._persist_log",
                new=AsyncMock(return_value=None),
            ),
        ):
            result = asyncio.run(
                tool.run(
                    {
                        "signal_type": "stale_answer",
                        "audience_context": {"visibility": "external"},
                    }
                )
            )

        self.assertEqual(_payload(result)["status"], "success")
        session.commit.assert_awaited_once()
        adapter.record_feedback_signal.assert_awaited_once()

    def test_mcp_does_not_commit_non_success_even_if_persisted(self) -> None:
        tool = asyncio.run(create_mcp_server().get_tool("record_feedback_signal"))
        if tool is None:
            raise AssertionError("feedback MCP tool was not registered")
        actor = _actor()
        identity = SimpleNamespace(employee_id=actor.id)
        session = _FeedbackSession()
        adapter = SimpleNamespace(
            record_feedback_signal=AsyncMock(
                return_value={"status": "conflict", "persisted": True}
            )
        )
        with (
            patch.object(
                mcp_tools,
                "_get_identity",
                new=AsyncMock(return_value=(identity, None)),
            ),
            patch.object(
                mcp_tools,
                "_get_governed_feedback_tools",
                new=AsyncMock(return_value=(adapter, None)),
            ),
            patch(
                "cygnus.runtime.database.async_session_factory",
                return_value=_SessionContext(session),
            ),
            patch(
                "cygnus.runtime.mcp.logging._persist_log",
                new=AsyncMock(return_value=None),
            ),
        ):
            result = asyncio.run(
                tool.run(
                    {
                        "signal_type": "stale_answer",
                        "audience_context": {"visibility": "external"},
                    }
                )
            )

        self.assertEqual(_payload(result)["status"], "conflict")
        session.commit.assert_not_awaited()
        adapter.record_feedback_signal.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
