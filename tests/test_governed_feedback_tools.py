from __future__ import annotations

import asyncio
from contextlib import contextmanager
import json
import unittest
import uuid
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.governance.feedback import (
    FeedbackCommandConflict,
    FeedbackSignalInput,
    GovernanceFeedbackSignal,
    create_feedback_signal,
)
from cygnus.governance.feedback_routing import (
    FeedbackRouteConflict,
    project_feedback_route,
)
from cygnus.integrations.governed_feedback_tools import (
    GovernedFeedbackTools,
    feedback_tool_bindings,
    feedback_tool_definitions,
)
from cygnus.runtime.database.models import (
    AuditLog,
    Employee,
    GovernanceFeedbackRoute,
    WikiPage,
    WikiPageDraft,
)
from cygnus.runtime.mcp.permissions import ANY_AUTHENTICATED, requirement_for
from cygnus.runtime.mcp.server import create_mcp_server
import cygnus.runtime.mcp.tools as mcp_tools


class _Result:
    def __init__(self, value: object | tuple[object, ...] | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object | None:
        if isinstance(self._value, tuple):
            values = list(self._value)
            if not values:
                return None
            if len(values) > 1:
                raise AssertionError("scalar_one_or_none received multiple rows")
            return values[0]
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
        signal: object | None = None,
        route: object | None = None,
        execute_error_entity: type[object] | None = None,
        flush_error_at: int | None = None,
    ) -> None:
        self.page = page
        self.draft = draft
        self.signal = signal
        self.route = route
        self.execute_error_entity = execute_error_entity
        self.flush_error_at = flush_error_at
        self.added: list[object] = []
        self.operations: list[str] = []
        self.flush_count = 0
        self.execute_count = 0
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.exited_with: type[BaseException] | None = None

    async def execute(self, statement: object) -> _Result:
        self.execute_count += 1
        descriptions = getattr(statement, "column_descriptions", ())
        entity = descriptions[0].get("entity") if descriptions else None
        if (
            self.execute_error_entity is not None
            and self.execute_error_entity is entity
        ):
            name = getattr(entity, "__name__", "statement")
            raise RuntimeError(f"{name} select failed")
        if entity is WikiPage:
            return _Result(self.page)
        if entity is WikiPageDraft:
            return _Result(self.draft)
        if entity is GovernanceFeedbackSignal:
            return _Result(self.signal)
        if entity is GovernanceFeedbackRoute:
            return _Result(self.route)
        if entity is None:
            self.operations.append("lock")
            return _Result(None)
        raise AssertionError(f"unexpected SQL entity: {entity}")

    def add(self, item: object) -> None:
        self.added.append(item)
        self.operations.append("add")
        if isinstance(item, GovernanceFeedbackSignal):
            self.signal = item
        elif isinstance(item, GovernanceFeedbackRoute):
            self.route = item

    async def flush(self) -> None:
        self.flush_count += 1
        self.operations.append("flush")
        if self.flush_error_at == self.flush_count:
            raise RuntimeError("feedback flush failed")


class _SessionContext:
    def __init__(self, session: object) -> None:
        self.session = session

    async def __aenter__(self) -> object:
        return self.session

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        *_args: object,
    ) -> None:
        setattr(self.session, "exited_with", exc_type)
        if exc_type is not None:
            rollback = getattr(self.session, "rollback", None)
            if rollback is not None:
                await rollback()
        return None


def _actor() -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        role="admin",
        global_role="admin",
        employee_departments=[],
    )


def _page(
    *,
    page_id: uuid.UUID | None = None,
    slug: str = "visible",
    orphaned: bool = False,
) -> Any:
    return SimpleNamespace(
        id=page_id or uuid.uuid4(),
        slug=slug,
        title="Visible answer",
        summary="A governed answer.",
        content_md="# Visible answer\n\nA governed answer.",
        status="mature",
        knowledge_type_slugs=["answer_card"],
        source_ids=[],
        orphaned=orphaned,
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


def _items(session: _FeedbackSession, item_type: type[Any]) -> list[Any]:
    return [item for item in session.added if isinstance(item, item_type)]


def _assert_routing(
    test: unittest.TestCase,
    result: dict[str, Any],
    *,
    route_kind: str | None,
) -> None:
    data = cast(dict[str, Any], result["data"])
    for payload in (result, data):
        if route_kind is None:
            test.assertIsNone(payload["route_id"])
            test.assertIsNone(payload["route_ref"])
            test.assertIsNone(payload["route_kind"])
            test.assertIsNone(payload["route_state"])
            test.assertEqual(payload["routing_state"], "recorded_only")
            test.assertFalse(payload["review_queued"])
            test.assertFalse(payload["refresh_queued"])
            continue

        route_id = payload["route_id"]
        test.assertIsInstance(route_id, str)
        test.assertEqual(payload["route_ref"], f"feedback-route:{route_id}")
        test.assertEqual(payload["route_kind"], route_kind)
        test.assertEqual(payload["route_state"], "queued")
        test.assertEqual(payload["routing_state"], f"{route_kind}_queued")
        test.assertEqual(payload["review_queued"], route_kind == "review")
        test.assertEqual(payload["refresh_queued"], route_kind == "refresh")
        test.assertEqual(
            int(payload["review_queued"]) + int(payload["refresh_queued"]),
            1,
        )


@contextmanager
def _command_locks():
    with (
        patch(
            "cygnus.governance.feedback.lock_governance_command",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "cygnus.governance.feedback_routing.lock_governance_command",
            new=AsyncMock(return_value=None),
        ),
    ):
        yield


class FeedbackPersistenceTests(unittest.TestCase):
    def test_input_normalizes_command_context_and_persists_actor_and_refs(self) -> None:
        actor_id = uuid.uuid4()
        draft_id = uuid.uuid4()
        session = _FeedbackSession()
        signal_input = FeedbackSignalInput(
            command_id=" feedback-command:rewrite-1 ",
            signal_type="human_rewrite",
            audience_context={"visibility": "internal", "plan": "enterprise"},
            object_id="ko-visible",
            draft_id=draft_id,
            source_context_ref="turn:42",
            notes="Rewrite was required.",
        )

        with _command_locks():
            write = asyncio.run(
                create_feedback_signal(
                    cast(AsyncSession, cast(object, session)),
                    signal_input,
                    actor_id=actor_id,
                )
            )
        signal = write.signal

        self.assertFalse(write.replayed)
        self.assertIsInstance(signal, GovernanceFeedbackSignal)
        self.assertEqual(signal.command_id, "feedback-command:rewrite-1")
        self.assertEqual(len(signal.request_fingerprint), 64)
        self.assertEqual(signal.signal_type, "human_rewrite")
        self.assertEqual(signal.actor_id, actor_id)
        self.assertEqual(signal.audience_context["plan_tier"], "enterprise")
        self.assertEqual(signal.draft_id, draft_id)
        self.assertIs(session.added[0], signal)
        session.commit.assert_not_awaited()

    def test_exact_command_replay_returns_existing_signal_without_write(self) -> None:
        actor_id = uuid.uuid4()
        session = _FeedbackSession()
        signal_input = FeedbackSignalInput(
            command_id="feedback-command:replay-1",
            signal_type="answer_accepted",
            audience_context={"visibility": "external", "region": "us"},
        )

        with _command_locks():
            first = asyncio.run(
                create_feedback_signal(
                    cast(AsyncSession, cast(object, session)),
                    signal_input,
                    actor_id=actor_id,
                )
            )
            replay = asyncio.run(
                create_feedback_signal(
                    cast(AsyncSession, cast(object, session)),
                    signal_input,
                    actor_id=actor_id,
                )
            )

        self.assertFalse(first.replayed)
        self.assertTrue(replay.replayed)
        self.assertIs(replay.signal, first.signal)
        self.assertEqual(len(_items(session, GovernanceFeedbackSignal)), 1)
        self.assertEqual(session.flush_count, 1)
        session.commit.assert_not_awaited()

    def test_changed_payload_or_actor_with_same_command_conflicts_without_write(
        self,
    ) -> None:
        original_actor_id = uuid.uuid4()
        cases = (
            (
                "payload",
                FeedbackSignalInput(
                    command_id="feedback-command:conflict-1",
                    signal_type="answer_accepted",
                    audience_context={"visibility": "internal"},
                    notes="Changed payload.",
                ),
                original_actor_id,
            ),
            (
                "actor",
                FeedbackSignalInput(
                    command_id="feedback-command:conflict-1",
                    signal_type="answer_accepted",
                    audience_context={"visibility": "internal"},
                ),
                uuid.uuid4(),
            ),
        )
        for label, conflicting_input, actor_id in cases:
            with self.subTest(label=label):
                session = _FeedbackSession()
                original_input = FeedbackSignalInput(
                    command_id="feedback-command:conflict-1",
                    signal_type="answer_accepted",
                    audience_context={"visibility": "internal"},
                )
                with _command_locks():
                    asyncio.run(
                        create_feedback_signal(
                            cast(AsyncSession, cast(object, session)),
                            original_input,
                            actor_id=original_actor_id,
                        )
                    )
                    added_before = tuple(session.added)
                    flushes_before = session.flush_count

                    with self.assertRaises(FeedbackCommandConflict):
                        asyncio.run(
                            create_feedback_signal(
                                cast(AsyncSession, cast(object, session)),
                                conflicting_input,
                                actor_id=actor_id,
                            )
                        )

                self.assertEqual(tuple(session.added), added_before)
                self.assertEqual(session.flush_count, flushes_before)
                session.commit.assert_not_awaited()

    def test_persistence_revalidates_mutated_input_before_write(self) -> None:
        session = _FeedbackSession()
        signal_input = FeedbackSignalInput(
            command_id="feedback-command:mutated-1",
            signal_type="answer_accepted",
            audience_context={"visibility": "internal", "region": "us"},
        )
        mutable_context = cast(dict[str, object], signal_input.audience_context)
        mutable_context["region"] = " "

        with (
            _command_locks(),
            self.assertRaisesRegex(
                ValueError,
                "audience_context.region",
            ),
        ):
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

    def test_route_projection_requires_a_durable_route_row(self) -> None:
        self.assertEqual(
            project_feedback_route(None).to_dict(),
            {
                "route_id": None,
                "route_ref": None,
                "route_kind": None,
                "route_state": None,
                "outcome_signal_id": None,
                "outcome_signal_ref": None,
                "terminal_reason": None,
                "routing_state": "recorded_only",
                "review_queued": False,
                "refresh_queued": False,
            }
        )

    def test_definition_is_one_strict_r1_tool(self) -> None:
        definitions = feedback_tool_definitions()
        self.assertEqual(len(definitions), 1)
        definition = definitions[0]
        self.assertEqual(definition.name, "record_feedback_signal")
        self.assertEqual(definition.risk_level, "R1")
        self.assertEqual(
            definition.parameters["required"],
            ["command_id", "signal_type", "audience_context"],
        )
        self.assertFalse(definition.parameters["additionalProperties"])
        self.assertEqual(
            definition.parameters["properties"]["command_id"],
            {"type": "string", "minLength": 1, "maxLength": 220},
        )
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
    def _record(
        self,
        session: _FeedbackSession,
        *,
        command_id: str,
        signal_type: str,
        actor: Any | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        tools = GovernedFeedbackTools(
            cast(AsyncSession, cast(object, session)),
            actor=cast(Employee, cast(object, actor or _actor())),
        )
        with _command_locks():
            return asyncio.run(
                tools.record_feedback_signal(
                    command_id=command_id,
                    signal_type=signal_type,
                    audience_context=cast(
                        dict[str, Any],
                        kwargs.pop("audience_context", {"visibility": "internal"}),
                    ),
                    **kwargs,
                )
            )

    def test_all_non_routed_types_persist_without_route(self) -> None:
        for signal_type in (
            "answer_accepted",
            "human_rewrite",
            "escalated",
            "unsupported_answer",
        ):
            with self.subTest(signal_type=signal_type):
                session = _FeedbackSession()
                result = self._record(
                    session,
                    command_id=f"feedback:{signal_type}",
                    signal_type=signal_type,
                    audience_context={"visibility": "external"},
                )

                self.assertEqual(result["status"], "success")
                self.assertTrue(result["persisted"])
                self.assertFalse(result["rehearsal"])
                self.assertFalse(result["replayed"])
                _assert_routing(self, result, route_kind=None)
                self.assertEqual(len(_items(session, GovernanceFeedbackSignal)), 1)
                self.assertEqual(_items(session, GovernanceFeedbackRoute), [])
                audits = _items(session, AuditLog)
                self.assertEqual(len(audits), 1)
                self.assertEqual(audits[0].action, "record_feedback_signal")
                self.assertIn("routing_state=recorded_only", audits[0].reason or "")
                session.commit.assert_not_awaited()

    def test_low_rating_persists_one_review_route_and_truthful_audit(self) -> None:
        session = _FeedbackSession()
        result = self._record(
            session,
            command_id="feedback:review-1",
            signal_type="low_rating",
        )

        self.assertEqual(result["status"], "success")
        _assert_routing(self, result, route_kind="review")
        routes = _items(session, GovernanceFeedbackRoute)
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0].route_kind, "review")
        self.assertEqual(routes[0].lifecycle_state, "queued")
        audits = _items(session, AuditLog)
        self.assertEqual(len(audits), 1)
        self.assertIn(str(result["route_ref"]), audits[0].reason or "")

    def test_stale_answer_persists_one_refresh_route(self) -> None:
        session = _FeedbackSession()
        result = self._record(
            session,
            command_id="feedback:refresh-1",
            signal_type="stale_answer",
        )

        self.assertEqual(result["status"], "success")
        _assert_routing(self, result, route_kind="refresh")
        routes = _items(session, GovernanceFeedbackRoute)
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0].route_kind, "refresh")

    def test_exact_routed_replay_returns_same_truth_without_duplicate_rows(
        self,
    ) -> None:
        actor = _actor()
        session = _FeedbackSession()
        first = self._record(
            session,
            actor=actor,
            command_id="feedback:replay-1",
            signal_type="low_rating",
        )
        replay = self._record(
            session,
            actor=actor,
            command_id="feedback:replay-1",
            signal_type="low_rating",
        )

        self.assertFalse(first["replayed"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["signal_id"], first["signal_id"])
        self.assertEqual(replay["route_id"], first["route_id"])
        self.assertEqual(len(_items(session, GovernanceFeedbackSignal)), 1)
        self.assertEqual(len(_items(session, GovernanceFeedbackRoute)), 1)
        self.assertEqual(len(_items(session, AuditLog)), 1)

    def test_changed_command_payload_conflicts_without_new_truth(self) -> None:
        actor = _actor()
        session = _FeedbackSession()
        self._record(
            session,
            actor=actor,
            command_id="feedback:conflict-1",
            signal_type="low_rating",
        )
        added_before = tuple(session.added)
        flushes_before = session.flush_count

        result = self._record(
            session,
            actor=actor,
            command_id="feedback:conflict-1",
            signal_type="low_rating",
            notes="different payload",
        )

        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["errors"], ["idempotency_conflict"])
        self.assertEqual(tuple(session.added), added_before)
        self.assertEqual(session.flush_count, flushes_before)

    def test_exact_replay_precedes_resource_visibility_lookup(self) -> None:
        actor = _actor()
        page = _page(slug="replayable")
        session = _FeedbackSession(page=page)
        first = self._record(
            session,
            actor=actor,
            command_id="feedback:visibility-replay-1",
            signal_type="low_rating",
            object_id="ko-replayable",
        )
        session.page = None

        replay = self._record(
            session,
            actor=actor,
            command_id="feedback:visibility-replay-1",
            signal_type="low_rating",
            object_id="ko-replayable",
        )

        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["signal_id"], first["signal_id"])
        self.assertEqual(replay["route_id"], first["route_id"])

    def test_exact_draft_replay_uses_persisted_canonical_refs(self) -> None:
        actor = _actor()
        page = _page(slug="draft-replay")
        draft_id = uuid.uuid4()
        draft = _draft(draft_id=draft_id, page_id=page.id)
        session = _FeedbackSession(page=page, draft=draft)
        first = self._record(
            session,
            actor=actor,
            command_id="feedback:draft-replay-1",
            signal_type="stale_answer",
            draft_id=str(draft_id),
        )
        session.page = None
        session.draft = None

        replay = self._record(
            session,
            actor=actor,
            command_id="feedback:draft-replay-1",
            signal_type="stale_answer",
            draft_id=str(draft_id),
        )

        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["signal_id"], first["signal_id"])
        self.assertEqual(replay["object_id"], "ko-draft-replay")
        self.assertEqual(replay["route_id"], first["route_id"])

    def test_bound_command_conflicts_before_changed_hidden_ref_lookup(self) -> None:
        actor = _actor()
        session = _FeedbackSession()
        self._record(
            session,
            actor=actor,
            command_id="feedback:hidden-conflict-1",
            signal_type="low_rating",
        )

        with patch.object(
            GovernedFeedbackTools,
            "_scoped_object",
            new=AsyncMock(side_effect=AssertionError("bound command must preflight")),
        ) as scoped_object:
            result = self._record(
                session,
                actor=actor,
                command_id="feedback:hidden-conflict-1",
                signal_type="low_rating",
                object_id="ko-hidden",
            )

        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["errors"], ["idempotency_conflict"])
        scoped_object.assert_not_awaited()
        self.assertEqual(len(_items(session, GovernanceFeedbackSignal)), 1)
        self.assertEqual(len(_items(session, GovernanceFeedbackRoute)), 1)

    def test_hidden_and_absent_refs_create_neither_signal_nor_route(self) -> None:
        for label, kwargs in (
            ("object", {"object_id": "ko-hidden"}),
            ("draft", {"draft_id": str(uuid.uuid4())}),
        ):
            with self.subTest(label=label):
                session = _FeedbackSession()
                tools = GovernedFeedbackTools(
                    cast(AsyncSession, cast(object, session)),
                    actor=cast(Employee, cast(object, _actor())),
                )
                patch_target = (
                    "_scoped_object" if label == "object" else "_scoped_draft"
                )
                patch_value: object = None if label == "object" else (None, None)
                with patch.object(
                    GovernedFeedbackTools,
                    patch_target,
                    new=AsyncMock(return_value=patch_value),
                ):
                    result = asyncio.run(
                        tools.record_feedback_signal(
                            command_id=f"feedback:hidden-{label}",
                            signal_type="low_rating",
                            audience_context={"visibility": "internal"},
                            **kwargs,
                        )
                    )

                self.assertEqual(result["status"], "not_found")
                self.assertEqual(session.added, [])
                self.assertEqual(session.flush_count, 0)

    def test_reserved_orphaned_and_source_refs_create_no_feedback_truth(self) -> None:
        for page in (
            _page(slug="_index"),
            _page(slug="source/billing-sop"),
            _page(slug="orphan", orphaned=True),
        ):
            with self.subTest(slug=page.slug):
                session = _FeedbackSession(page=page)
                tools = GovernedFeedbackTools(
                    cast(AsyncSession, cast(object, session)),
                    actor=cast(Employee, cast(object, _actor())),
                )

                result = asyncio.run(
                    tools.record_feedback_signal(
                        command_id=f"feedback:excluded:{page.slug}",
                        signal_type="low_rating",
                        audience_context={"visibility": "internal"},
                        object_id=f"ko-{page.slug}",
                    )
                )

                self.assertEqual(result["status"], "not_found")
                self.assertEqual(session.added, [])
                self.assertEqual(session.flush_count, 0)

    def test_drafts_for_excluded_pages_create_no_feedback_truth(self) -> None:
        for page in (
            _page(slug="_index"),
            _page(slug="source/billing-sop"),
            _page(slug="orphan", orphaned=True),
        ):
            with self.subTest(slug=page.slug):
                draft_id = uuid.uuid4()
                session = _FeedbackSession(
                    page=page,
                    draft=_draft(draft_id=draft_id, page_id=page.id),
                )
                tools = GovernedFeedbackTools(
                    cast(AsyncSession, cast(object, session)),
                    actor=cast(Employee, cast(object, _actor())),
                )

                result = asyncio.run(
                    tools.record_feedback_signal(
                        command_id=f"feedback:excluded-draft:{page.slug}",
                        signal_type="stale_answer",
                        audience_context={"visibility": "internal"},
                        draft_id=str(draft_id),
                    )
                )

                self.assertEqual(result["status"], "not_found")
                self.assertEqual(session.added, [])
                self.assertEqual(session.flush_count, 0)

    def test_mismatched_refs_create_neither_signal_nor_route(self) -> None:
        page = _page(slug="one")
        other_page = _page(slug="two")
        draft_id = uuid.uuid4()
        draft = _draft(draft_id=draft_id, page_id=other_page.id)
        session = _FeedbackSession()
        tools = GovernedFeedbackTools(
            cast(AsyncSession, cast(object, session)),
            actor=cast(Employee, cast(object, _actor())),
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
        ):
            result = asyncio.run(
                tools.record_feedback_signal(
                    command_id="feedback:mismatch-1",
                    signal_type="escalated",
                    audience_context={"visibility": "internal"},
                    object_id="ko-one",
                    draft_id=str(draft_id),
                )
            )

        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["errors"], ["reference_mismatch"])
        self.assertEqual(session.added, [])
        self.assertEqual(session.flush_count, 0)

    def test_linked_object_and_draft_persist_resolved_foreign_keys(self) -> None:
        page = _page(slug="linked-answer")
        draft_id = uuid.uuid4()
        draft = _draft(draft_id=draft_id, page_id=page.id)
        session = _FeedbackSession(page=page, draft=draft)

        result = self._record(
            session,
            command_id="feedback:linked-1",
            signal_type="human_rewrite",
            object_id="ko-linked-answer",
            draft_id=str(draft_id),
            notes="Linked correction.",
        )

        self.assertEqual(result["status"], "success")
        signal = _items(session, GovernanceFeedbackSignal)[0]
        self.assertEqual(signal.object_id, "ko-linked-answer")
        self.assertEqual(signal.page_id, page.id)
        self.assertEqual(signal.draft_id, draft_id)
        self.assertEqual(_items(session, GovernanceFeedbackRoute), [])

    def test_ambiguous_object_slug_is_safe_not_found_without_write(self) -> None:
        session = _FeedbackSession(
            page=(_page(slug="duplicate"), _page(slug="duplicate"))
        )

        result = self._record(
            session,
            command_id="feedback:ambiguous-1",
            signal_type="unsupported_answer",
            object_id="ko-duplicate",
        )

        self.assertEqual(result["status"], "not_found")
        self.assertEqual(result["data"], {})
        self.assertNotIn("ko-duplicate", result["summary"])
        self.assertEqual(session.added, [])

    def test_object_and_unmaterialized_draft_conflict_without_write(self) -> None:
        page = _page(slug="new-answer")
        draft_id = uuid.uuid4()
        draft = _draft(draft_id=draft_id, page_id=None)
        session = _FeedbackSession()
        tools = GovernedFeedbackTools(
            cast(AsyncSession, cast(object, session)),
            actor=cast(Employee, cast(object, _actor())),
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
        ):
            result = asyncio.run(
                tools.record_feedback_signal(
                    command_id="feedback:unmaterialized-1",
                    signal_type="escalated",
                    audience_context={"visibility": "internal"},
                    object_id="ko-new-answer",
                    draft_id=str(draft_id),
                )
            )

        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["errors"], ["reference_mismatch"])
        self.assertEqual(session.added, [])

    def test_invalid_arguments_reject_before_resource_lookup(self) -> None:
        session = _FeedbackSession()
        tools = GovernedFeedbackTools(
            cast(AsyncSession, cast(object, session)),
            actor=cast(Employee, cast(object, _actor())),
        )
        with patch.object(
            GovernedFeedbackTools,
            "_scoped_object",
            new=AsyncMock(side_effect=AssertionError("resource lookup must not run")),
        ) as scoped_object:
            result = asyncio.run(
                tools.record_feedback_signal(
                    command_id=" ",
                    signal_type="low_rating",
                    audience_context={"visibility": "internal"},
                    object_id="ko-hidden",
                )
            )

        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["errors"], ["invalid_arguments"])
        scoped_object.assert_not_awaited()
        self.assertEqual(session.added, [])

    def test_route_write_failure_propagates_without_success_projection(self) -> None:
        session = _FeedbackSession(flush_error_at=2)
        with self.assertRaisesRegex(RuntimeError, "feedback flush failed"):
            self._record(
                session,
                command_id="feedback:route-failure-1",
                signal_type="low_rating",
            )

        self.assertEqual(_items(session, AuditLog), [])
        session.commit.assert_not_awaited()

    def test_routed_replay_missing_route_fails_closed(self) -> None:
        actor = _actor()
        session = _FeedbackSession()
        self._record(
            session,
            actor=actor,
            command_id="feedback:missing-route-1",
            signal_type="low_rating",
        )
        session.route = None

        with self.assertRaises(FeedbackRouteConflict):
            self._record(
                session,
                actor=actor,
                command_id="feedback:missing-route-1",
                signal_type="low_rating",
            )


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
                        "command_id": "feedback:mcp-invalid-1",
                        "signal_type": "answer_accepted",
                        "audience_context": True,
                    }
                )
            )

        payload = _payload(result)
        self.assertEqual(payload["status"], "invalid")
        self.assertEqual(payload["errors"], ["invalid_arguments"])
        get_identity.assert_not_awaited()

    def test_mcp_commits_only_persisted_success_and_uses_any_authenticated(
        self,
    ) -> None:
        tool = asyncio.run(create_mcp_server().get_tool("record_feedback_signal"))
        if tool is None:
            raise AssertionError("feedback MCP tool was not registered")
        self.assertIs(requirement_for(getattr(tool, "fn")), ANY_AUTHENTICATED)

        actor = _actor()
        identity = SimpleNamespace(employee_id=actor.id)
        session = _FeedbackSession()
        adapter = SimpleNamespace(
            record_feedback_signal=AsyncMock(
                return_value={
                    "status": "success",
                    "persisted": True,
                    "replayed": False,
                }
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
                        "command_id": "feedback:mcp-refresh-1",
                        "signal_type": "stale_answer",
                        "audience_context": {"visibility": "external"},
                    }
                )
            )

        self.assertEqual(_payload(result)["status"], "success")
        session.commit.assert_awaited_once()
        adapter.record_feedback_signal.assert_awaited_once()
        adapter.record_feedback_signal.assert_awaited_once_with(
            command_id="feedback:mcp-refresh-1",
            signal_type="stale_answer",
            audience_context={
                "visibility": "external",
                "brand": None,
                "product_line": None,
                "plan_tier": None,
                "region": None,
                "language": None,
                "product_version": None,
            },
            object_id=None,
            draft_id=None,
            notes=None,
            source_context_ref=None,
        )

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
                        "command_id": "feedback:mcp-conflict-1",
                        "signal_type": "stale_answer",
                        "audience_context": {"visibility": "external"},
                    }
                )
            )

        self.assertEqual(_payload(result)["status"], "conflict")
        session.commit.assert_not_awaited()
        adapter.record_feedback_signal.assert_awaited_once()

    def test_mcp_does_not_commit_exact_replay(self) -> None:
        tool = asyncio.run(create_mcp_server().get_tool("record_feedback_signal"))
        if tool is None:
            raise AssertionError("feedback MCP tool was not registered")
        actor = _actor()
        identity = SimpleNamespace(employee_id=actor.id)
        session = _FeedbackSession()
        adapter = SimpleNamespace(
            record_feedback_signal=AsyncMock(
                return_value={
                    "status": "success",
                    "persisted": True,
                    "replayed": True,
                }
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
                        "command_id": "feedback:mcp-replay-1",
                        "signal_type": "low_rating",
                        "audience_context": {"visibility": "internal"},
                    }
                )
            )

        self.assertEqual(_payload(result)["status"], "success")
        session.commit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
