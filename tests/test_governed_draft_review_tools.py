from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TypedDict, cast
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.integrations.governed_draft_review_tools import (
    GovernedDraftReviewTools,
    draft_review_tool_definitions,
)
from cygnus.review.contributions import (
    DraftVersionConflict,
    create_wiki_draft,
    submit_wiki_draft,
    update_wiki_draft,
)
from cygnus.runtime.database.models import Employee, WikiPageDraft


class _ProposalFixturePayload(TypedDict):
    proposed_object_type: str
    title: str
    input_summary: str
    audience_context: dict[str, str]


class _LifecycleSession:
    async def refresh(self, _draft: object) -> None:
        return None

    async def flush(self) -> None:
        return None

    async def get(self, _model: object, _identifier: object) -> None:
        return None

    def add(self, _item: object) -> None:
        return None


def _author(*, department_id: uuid.UUID | None = None) -> Employee:
    department_id = department_id or uuid.uuid4()
    return cast(
        Employee,
        SimpleNamespace(
            id=uuid.uuid4(),
            role="employee",
            name="Draft author",
            email="author@example.test",
            department_ids=[department_id],
        ),
    )


def _department_source(department_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        status="ready",
        scope_type="department",
        scope_id=department_id,
        departments=(SimpleNamespace(department_id=department_id),),
    )


def _draft(
    *, author_id: uuid.UUID | None, status: str = "draft", version: int = 1
) -> WikiPageDraft:
    return cast(
        WikiPageDraft,
        SimpleNamespace(
            id=uuid.uuid4(),
            author_id=author_id,
            page_id=None,
            page=None,
            draft_kind="create",
            status=status,
            version=version,
            revision_round=0,
            content_md="# Billing\n\nDraft content",
            note=None,
            source="mcp_other",
            source_metadata={"review_type": "content"},
            suggested_metadata={"title": "Billing", "slug": "billing"},
            last_returned_note=None,
            ai_check_status="pending",
            ai_check_results=None,
            ai_checked_at=None,
        ),
    )


class DraftLifecycleOwnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_unsubmitted_draft_records_only_a_proposal(self) -> None:
        import cygnus.review.contributions as contributions

        author = _author()
        session = _LifecycleSession()
        with patch.object(
            contributions,
            "record_draft_proposal",
            AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4())),
        ) as proposal:
            draft = await create_wiki_draft(
                cast(AsyncSession, cast(object, session)),
                page_id=None,
                author_id=author.id,
                content_md="# Billing\n\nDraft content",
                source="mcp_other",
                source_metadata={"object_type": "answer_card"},
                draft_kind="create",
                suggested_metadata={"slug": "billing", "title": "Billing"},
                submit_for_review=False,
            )

        self.assertEqual(draft.status, "draft")
        proposal.assert_awaited_once_with(
            cast(AsyncSession, cast(object, session)),
            draft,
        )

    async def test_submit_staged_draft_records_review_transition_and_notifications(
        self,
    ) -> None:
        import cygnus.review.contributions as contributions

        author = _author()
        draft = _draft(author_id=author.id)
        event = SimpleNamespace(id=uuid.uuid4())
        session = _LifecycleSession()
        with (
            patch.object(contributions, "lock_draft_aggregate", AsyncMock()) as lock,
            patch.object(
                contributions,
                "record_draft_review_request",
                AsyncMock(return_value=event),
            ) as record,
            patch.object(contributions, "log_audit", AsyncMock()) as audit,
            patch.object(contributions, "notify_submitted", AsyncMock()) as notify,
        ):
            actual_event, replayed = await submit_wiki_draft(
                cast(AsyncSession, cast(object, session)),
                draft,
                author,
                expected_version=1,
                review_type="content",
                notes="Ready for review",
            )

        self.assertIs(actual_event, event)
        self.assertFalse(replayed)
        self.assertEqual(draft.status, "pending")
        self.assertEqual(draft.note, "Ready for review")
        lock.assert_awaited_once()
        record.assert_awaited_once()
        assert record.await_args is not None
        self.assertEqual(record.await_args.kwargs["expected_version"], 1)
        self.assertEqual(record.await_args.kwargs["review_type"], "content")
        audit.assert_awaited_once()
        notify.assert_awaited_once()

    async def test_repeat_review_request_reuses_ledger_transition_without_duplicate_notification(
        self,
    ) -> None:
        import cygnus.review.contributions as contributions

        author = _author()
        draft = _draft(author_id=author.id, status="pending")
        event = SimpleNamespace(id=uuid.uuid4())
        session = _LifecycleSession()
        with (
            patch.object(contributions, "lock_draft_aggregate", AsyncMock()),
            patch.object(
                contributions,
                "record_draft_review_request",
                AsyncMock(return_value=event),
            ) as record,
            patch.object(contributions, "stage_ai_pre_review", AsyncMock()) as stage,
            patch.object(contributions, "log_audit", AsyncMock()) as audit,
            patch.object(contributions, "notify_submitted", AsyncMock()) as notify,
        ):
            actual_event, replayed = await submit_wiki_draft(
                cast(AsyncSession, cast(object, session)),
                draft,
                author,
                expected_version=1,
                review_type="content",
                notes=None,
            )

        self.assertIs(actual_event, event)
        self.assertTrue(replayed)
        record.assert_awaited_once()
        audit.assert_not_awaited()
        notify.assert_not_awaited()
        stage.assert_awaited_once_with(cast(AsyncSession, cast(object, session)), draft)

    async def test_update_advances_draft_content_version_and_appends_audit_event(
        self,
    ) -> None:
        import cygnus.review.contributions as contributions

        author = _author()
        draft = _draft(author_id=author.id)
        event = SimpleNamespace(id=uuid.uuid4())
        session = _LifecycleSession()
        with (
            patch.object(contributions, "lock_draft_aggregate", AsyncMock()),
            patch.object(
                contributions,
                "record_draft_update",
                AsyncMock(return_value=event),
            ) as record,
            patch.object(contributions, "log_audit", AsyncMock()) as audit,
        ):
            actual_event, replayed = await update_wiki_draft(
                cast(AsyncSession, cast(object, session)),
                draft,
                author,
                expected_version=1,
                content_md="# Billing\n\nUpdated content",
            )

        self.assertIs(actual_event, event)
        self.assertFalse(replayed)
        self.assertEqual(draft.version, 2)
        self.assertEqual(draft.status, "draft")
        assert record.await_args is not None
        self.assertEqual(record.await_args.args[1].version, 2)
        self.assertEqual(record.await_args.kwargs["previous_draft_version"], 1)
        audit.assert_awaited_once()

    async def test_wrong_state_review_request_is_rejected(self) -> None:
        import cygnus.review.contributions as contributions

        author = _author()
        draft = _draft(author_id=author.id, status="approved")
        with patch.object(contributions, "lock_draft_aggregate", AsyncMock()):
            with self.assertRaises(contributions.InvalidTransition):
                await submit_wiki_draft(
                    cast(AsyncSession, cast(object, _LifecycleSession())),
                    draft,
                    author,
                    expected_version=1,
                    review_type="content",
                    notes=None,
                )

    async def test_update_rejects_stale_draft_version(self) -> None:
        import cygnus.review.contributions as contributions

        author = _author()
        draft = _draft(author_id=author.id, version=2)
        with patch.object(contributions, "lock_draft_aggregate", AsyncMock()):
            with self.assertRaises(DraftVersionConflict):
                await update_wiki_draft(
                    cast(AsyncSession, cast(object, _LifecycleSession())),
                    draft,
                    author,
                    expected_version=1,
                    content_md="# Billing\n\nStale update",
                )

    async def test_update_rejects_orphaned_draft_for_non_admin(self) -> None:
        import cygnus.review.contributions as contributions

        author = _author()
        draft = _draft(author_id=None)
        with patch.object(contributions, "lock_draft_aggregate", AsyncMock()):
            with self.assertRaises(contributions.InvalidTransition):
                await update_wiki_draft(
                    cast(AsyncSession, cast(object, _LifecycleSession())),
                    draft,
                    author,
                    expected_version=1,
                    content_md="# Billing\n\nOrphaned update",
                )

    async def test_admin_may_update_an_orphaned_draft(self) -> None:
        import cygnus.review.contributions as contributions

        admin = _author()
        admin.role = "admin"
        draft = _draft(author_id=None)
        event = SimpleNamespace(id=uuid.uuid4())
        session = _LifecycleSession()
        with (
            patch.object(contributions, "lock_draft_aggregate", AsyncMock()),
            patch.object(
                contributions,
                "record_draft_update",
                AsyncMock(return_value=event),
            ),
            patch.object(contributions, "log_audit", AsyncMock()),
        ):
            actual_event, replayed = await update_wiki_draft(
                cast(AsyncSession, cast(object, session)),
                draft,
                admin,
                expected_version=1,
                content_md="# Billing\n\nAdmin recovery",
            )

        self.assertIs(actual_event, event)
        self.assertFalse(replayed)
        self.assertEqual(draft.version, 2)
        self.assertEqual(draft.content_md, "# Billing\n\nAdmin recovery")

    async def test_review_request_rejects_orphaned_draft_for_non_admin(self) -> None:
        import cygnus.review.contributions as contributions

        author = _author()
        draft = _draft(author_id=None)
        with patch.object(contributions, "lock_draft_aggregate", AsyncMock()):
            with self.assertRaises(contributions.InvalidTransition):
                await submit_wiki_draft(
                    cast(AsyncSession, cast(object, _LifecycleSession())),
                    draft,
                    author,
                    expected_version=1,
                    review_type="content",
                    notes=None,
                )

    async def test_admin_may_submit_an_orphaned_draft(self) -> None:
        import cygnus.review.contributions as contributions

        admin = _author()
        admin.role = "admin"
        draft = _draft(author_id=None)
        event = SimpleNamespace(id=uuid.uuid4())
        session = _LifecycleSession()
        with (
            patch.object(contributions, "lock_draft_aggregate", AsyncMock()),
            patch.object(
                contributions,
                "record_draft_review_request",
                AsyncMock(return_value=event),
            ),
            patch.object(contributions, "log_audit", AsyncMock()),
            patch.object(contributions, "notify_submitted", AsyncMock()),
        ):
            actual_event, replayed = await submit_wiki_draft(
                cast(AsyncSession, cast(object, session)),
                draft,
                admin,
                expected_version=1,
                review_type="content",
                notes="Admin recovery",
            )

        self.assertIs(actual_event, event)
        self.assertFalse(replayed)
        self.assertEqual(draft.status, "pending")

    async def test_withdraw_rejects_orphaned_draft_for_non_admin(self) -> None:
        import cygnus.review.contributions as contributions

        author = _author()
        draft = _draft(author_id=None, status="draft")
        with self.assertRaises(contributions.InvalidTransition) as raised:
            await contributions.withdraw(
                cast(AsyncSession, cast(object, _LifecycleSession())),
                contributions.wiki_draft_adapter,
                draft,
                author,
            )

        self.assertIn("original author", str(raised.exception))
        self.assertEqual(draft.status, "draft")

    async def test_admin_can_withdraw_orphaned_draft(self) -> None:
        import cygnus.review.contributions as contributions

        admin = _author()
        admin.role = "admin"
        draft = WikiPageDraft(
            id=uuid.uuid4(),
            author_id=None,
            page_id=None,
            draft_kind="create",
            suggested_metadata={"title": "Billing", "slug": "billing"},
            content_md="# Billing\n\nDraft content",
            revision_round=0,
            status="draft",
            source="mcp_other",
            source_metadata={"review_type": "content"},
        )
        session = _LifecycleSession()
        with (
            patch.object(contributions, "log_audit", AsyncMock()) as audit,
            patch.object(contributions, "append_draft_event", AsyncMock()) as append,
            patch.object(
                contributions.wiki_draft_adapter,
                "reviewers",
                AsyncMock(return_value=[]),
            ),
            patch.object(
                contributions.notification_service, "notify_many", AsyncMock()
            ),
        ):
            await contributions.withdraw(
                cast(AsyncSession, cast(object, session)),
                contributions.wiki_draft_adapter,
                draft,
                admin,
            )

        self.assertEqual(draft.status, "withdrawn")
        audit.assert_awaited_once()
        append.assert_awaited_once()
        self.assertIsInstance(draft, WikiPageDraft)
        assert append.await_args is not None
        self.assertEqual(
            append.await_args.kwargs["event_type"],
            contributions.GovernanceEventType.WITHDRAWN,
        )
        self.assertEqual(append.await_args.kwargs["draft_id"], draft.id)
        self.assertEqual(append.await_args.kwargs["from_state"], "draft")
        self.assertEqual(append.await_args.kwargs["to_state"], "withdrawn")

    async def test_resubmit_locks_versions_ledgers_and_stages_ai_review(self) -> None:
        import cygnus.review.contributions as contributions

        author = _author()
        draft = _draft(author_id=author.id, status="needs_revision")
        session = _LifecycleSession()
        with (
            patch.object(contributions, "lock_draft_aggregate", AsyncMock()) as lock,
            patch.object(contributions, "record_draft_update", AsyncMock()) as record,
            patch.object(contributions, "append_draft_event", AsyncMock()) as append,
            patch.object(contributions, "stage_ai_pre_review", AsyncMock()) as stage,
            patch.object(contributions, "log_audit", AsyncMock()) as audit,
            patch.object(
                contributions.wiki_draft_adapter,
                "reviewers",
                AsyncMock(return_value=[]),
            ),
            patch.object(
                contributions.notification_service, "notify_many", AsyncMock()
            ),
        ):
            await contributions.resubmit_wiki_draft(
                cast(AsyncSession, cast(object, session)),
                draft,
                author,
                "# Billing\n\nRebased content",
                author_note="Resolved page conflict",
            )

        self.assertEqual(draft.content_md, "# Billing\n\nRebased content")
        self.assertEqual(draft.version, 2)
        self.assertEqual(draft.revision_round, 1)
        self.assertEqual(draft.status, "pending")
        lock.assert_awaited_once_with(
            cast(AsyncSession, cast(object, session)), draft.id
        )
        assert record.await_args is not None
        assert append.await_args is not None
        self.assertEqual(record.await_args.kwargs["action"], "resubmit")
        self.assertEqual(record.await_args.kwargs["previous_draft_version"], 1)
        self.assertEqual(append.await_args.kwargs["from_state"], "draft")
        self.assertFalse(append.await_args.kwargs["lock"])
        stage.assert_awaited_once_with(cast(AsyncSession, cast(object, session)), draft)
        audit.assert_awaited_once()


class GovernedDraftReviewToolContractTests(unittest.TestCase):
    def _tools(self) -> GovernedDraftReviewTools:
        actor = _author()
        actor.global_role = "contributor"
        return GovernedDraftReviewTools(
            cast(AsyncSession, cast(object, _LifecycleSession())),
            actor=actor,
        )

    def test_definitions_cover_the_four_ready_lifecycle_tools(self) -> None:
        definitions = draft_review_tool_definitions()
        self.assertEqual(
            [(definition.name, definition.risk_level) for definition in definitions],
            [
                ("propose_knowledge_object", "R1"),
                ("update_draft_object", "R1"),
                ("request_review", "R1"),
                ("read_review_feedback", "R0"),
            ],
        )
        self.assertIn("expected_version", definitions[1].parameters["required"])
        self.assertIn("expected_version", definitions[2].parameters["required"])
        proposal_schema = definitions[0].parameters
        self.assertIn("scope_type", proposal_schema["properties"])
        self.assertIn("scope_id", proposal_schema["properties"])
        self.assertNotIn("scope_type", proposal_schema["required"])
        self.assertNotIn("scope_id", proposal_schema["required"])

    def test_invalid_schema_returns_the_governed_envelope(self) -> None:
        result = asyncio.run(
            self._tools().propose_knowledge_object(
                command_id="propose:test-invalid-1",
                proposed_object_type="answer_card",
                title="Billing policy",
                input_summary="Use the approved policy.",
                audience_context={},
            )
        )

        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["errors"], ["invalid_arguments"])
        self.assertEqual(
            set(result), {"status", "summary", "data", "warnings", "errors"}
        )

    def test_proposal_preserves_typed_audience_and_source_trace_metadata(self) -> None:
        import cygnus.integrations.governed_draft_review_tools as draft_tools

        actor = _author()
        actor.global_role = "contributor"
        tools = GovernedDraftReviewTools(
            cast(AsyncSession, cast(object, _LifecycleSession())),
            actor=actor,
        )
        source_id = uuid.uuid4()
        draft = _draft(author_id=actor.id)
        with (
            patch.object(
                GovernedDraftReviewTools,
                "_visible_sources",
                AsyncMock(
                    return_value={
                        source_id: _department_source(actor.department_ids[0])
                    }
                ),
            ),
            patch.object(
                draft_tools,
                "create_wiki_draft",
                AsyncMock(return_value=draft),
            ) as create,
            patch.object(draft_tools, "log_audit", AsyncMock()),
            patch.object(
                draft_tools,
                "replay_tool_command_receipt",
                AsyncMock(return_value=None),
            ),
            patch.object(
                draft_tools,
                "create_tool_command_receipt",
                AsyncMock(
                    return_value=SimpleNamespace(
                        receipt_ref="tool-command-receipt:test-propose"
                    )
                ),
            ) as receipt,
        ):
            result = asyncio.run(
                tools.propose_knowledge_object(
                    command_id="propose:test-metadata-1",
                    proposed_object_type="answer_card",
                    title="Billing policy",
                    input_summary="Use the approved policy.",
                    audience_context={
                        "visibility": "external",
                        "product_line": "billing",
                    },
                    source_refs=[
                        {
                            "source_id": str(source_id),
                            "source_type": "wiki",
                            "locator": "page:1",
                        }
                    ],
                    evidence_refs=[
                        {
                            "evidence_id": "ev-1",
                            "source_id": str(source_id),
                            "excerpt_ref": "page:1#billing",
                            "confidence": 0.9,
                            "freshness": "fresh",
                        }
                    ],
                )
            )

        receipt.assert_awaited_once()
        assert receipt.await_args is not None
        self.assertEqual(
            receipt.await_args.kwargs["command_id"],
            "propose:test-metadata-1",
        )
        self.assertEqual(
            receipt.await_args.kwargs["tool_name"],
            "propose_knowledge_object",
        )
        self.assertEqual(result["receipt_ref"], "tool-command-receipt:test-propose")

        assert create.await_args is not None
        metadata = create.await_args.kwargs["source_metadata"]
        self.assertEqual(metadata["object_type"], "answer_card")
        self.assertEqual(metadata["audience_context"]["product_line"], "billing")
        self.assertEqual(metadata["source_ids"], [str(source_id)])
        self.assertEqual(
            create.await_args.kwargs["suggested_metadata"]["knowledge_type_slugs"],
            ["answer_card"],
        )
        self.assertEqual(
            create.await_args.kwargs["suggested_metadata"]["scope_type"],
            "department",
        )
        self.assertEqual(
            create.await_args.kwargs["suggested_metadata"]["scope_id"],
            str(actor.department_ids[0]),
        )
        self.assertTrue(result["persisted"])

    def test_own_department_contributor_cannot_propose_global_or_cross_scope(
        self,
    ) -> None:
        import cygnus.integrations.governed_draft_review_tools as draft_tools

        actor = _author()
        actor.global_role = "contributor"
        tools = GovernedDraftReviewTools(
            cast(AsyncSession, cast(object, _LifecycleSession())),
            actor=actor,
        )
        own_department_id = actor.department_ids[0]
        other_department_id = uuid.uuid4()
        source_id = uuid.uuid4()

        async def visible_sources(
            source_ids: tuple[uuid.UUID, ...],
        ) -> dict[uuid.UUID, object]:
            if not source_ids:
                return {}
            return {source_id: _department_source(other_department_id)}

        common: _ProposalFixturePayload = {
            "proposed_object_type": "answer_card",
            "title": "Billing policy",
            "input_summary": "Use the approved policy.",
            "audience_context": {"visibility": "external"},
        }
        with (
            patch.object(
                GovernedDraftReviewTools,
                "_visible_sources",
                AsyncMock(side_effect=visible_sources),
            ),
            patch.object(
                draft_tools,
                "replay_tool_command_receipt",
                AsyncMock(return_value=None),
            ) as replay,
        ):
            implicit_global = asyncio.run(
                tools.propose_knowledge_object(
                    command_id="propose:implicit-global",
                    **common,
                )
            )
            explicit_global = asyncio.run(
                tools.propose_knowledge_object(
                    command_id="propose:explicit-global",
                    scope_type="global",
                    **common,
                )
            )
            cross_department = asyncio.run(
                tools.propose_knowledge_object(
                    command_id="propose:cross-department",
                    source_refs=[
                        {
                            "source_id": str(source_id),
                            "source_type": "wiki",
                            "locator": "page:other",
                        }
                    ],
                    **common,
                )
            )

        self.assertEqual(str(own_department_id), str(actor.department_ids[0]))
        for result in (implicit_global, explicit_global, cross_department):
            self.assertEqual(result["status"], "invalid")
            self.assertEqual(result["errors"], ["invalid_arguments"])
        self.assertEqual(replay.await_count, 3)

    def test_direct_adapter_denies_proposal_without_write_permission(self) -> None:
        actor = _author()
        actor.global_role = "viewer"
        tools = GovernedDraftReviewTools(
            cast(AsyncSession, cast(object, _LifecycleSession())),
            actor=actor,
        )

        result = asyncio.run(
            tools.propose_knowledge_object(
                command_id="propose:test-denied-1",
                proposed_object_type="answer_card",
                title="Billing policy",
                input_summary="Use the approved policy.",
                audience_context={"visibility": "external"},
            )
        )

        self.assertEqual(result["status"], "denied")
        self.assertEqual(result["errors"], ["permission_denied"])

    def test_stale_update_returns_a_governed_conflict(self) -> None:
        import cygnus.integrations.governed_draft_review_tools as draft_tools

        actor = _author()
        tools = GovernedDraftReviewTools(
            cast(AsyncSession, cast(object, _LifecycleSession())),
            actor=actor,
        )
        draft = _draft(author_id=actor.id)
        with (
            patch.object(
                GovernedDraftReviewTools,
                "_scoped_draft",
                AsyncMock(return_value=draft),
            ),
            patch.object(
                draft_tools,
                "replay_tool_command_receipt",
                AsyncMock(return_value=None),
            ),
            patch.object(
                draft_tools,
                "update_wiki_draft",
                AsyncMock(side_effect=DraftVersionConflict(1, 2)),
            ),
        ):
            result = asyncio.run(
                tools.update_draft_object(
                    command_id="update:test-stale-1",
                    draft_id=str(draft.id),
                    expected_version=1,
                    patch={"content": "# Billing\n\nUpdated content"},
                )
            )

        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["errors"], ["stale_draft"])

    def test_update_linked_evidence_resolves_stored_source_refs(self) -> None:
        import cygnus.integrations.governed_draft_review_tools as draft_tools

        actor = _author()
        tools = GovernedDraftReviewTools(
            cast(AsyncSession, cast(object, _LifecycleSession())),
            actor=actor,
        )
        stored_source_id = uuid.uuid4()
        evidence_source_id = uuid.uuid4()
        draft = _draft(author_id=actor.id)
        draft.suggested_metadata = {
            "title": "Billing",
            "slug": "billing",
            "scope_type": "department",
            "scope_id": str(actor.department_ids[0]),
        }
        stored_source_refs = [
            {
                "source_id": str(stored_source_id),
                "source_type": "wiki",
                "locator": "page:billing",
            }
        ]
        draft.source_metadata = {
            "source_refs": stored_source_refs,
            "evidence_refs": [],
            "source_ids": [str(stored_source_id)],
        }
        evidence_ref = {
            "evidence_id": "evidence:billing-policy",
            "source_id": str(evidence_source_id),
            "excerpt_ref": "page:policy#billing",
            "confidence": 0.9,
            "freshness": "fresh",
        }
        source_rows = {
            stored_source_id: _department_source(actor.department_ids[0]),
            evidence_source_id: _department_source(actor.department_ids[0]),
        }

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
                GovernedDraftReviewTools,
                "_visible_sources",
                AsyncMock(return_value=source_rows),
            ) as visible_sources,
            patch.object(
                draft_tools,
                "update_wiki_draft",
                AsyncMock(return_value=(None, False)),
            ) as update,
            patch.object(
                draft_tools,
                "create_tool_command_receipt",
                AsyncMock(
                    return_value=SimpleNamespace(
                        receipt_ref="tool-command-receipt:test-linked-evidence"
                    )
                ),
            ),
        ):
            result = asyncio.run(
                tools.update_draft_object(
                    command_id="update:test-linked-evidence",
                    draft_id=str(draft.id),
                    expected_version=1,
                    patch={"linked_evidence_refs": [evidence_ref]},
                )
            )

        self.assertEqual(result["status"], "success")
        visible_sources.assert_awaited_once_with((stored_source_id, evidence_source_id))
        update.assert_awaited_once()
        assert update.await_args is not None
        source_metadata = update.await_args.kwargs["source_metadata"]
        self.assertEqual(source_metadata["source_refs"], stored_source_refs)
        self.assertEqual(source_metadata["evidence_refs"], [evidence_ref])
        self.assertEqual(
            source_metadata["source_ids"],
            [str(stored_source_id), str(evidence_source_id)],
        )

    def test_wrong_state_review_request_returns_a_governed_conflict(self) -> None:
        import cygnus.integrations.governed_draft_review_tools as draft_tools

        actor = _author()
        tools = GovernedDraftReviewTools(
            cast(AsyncSession, cast(object, _LifecycleSession())),
            actor=actor,
        )
        draft = _draft(author_id=actor.id, status="approved")
        with (
            patch.object(
                GovernedDraftReviewTools,
                "_scoped_draft",
                AsyncMock(return_value=draft),
            ),
            patch.object(
                draft_tools,
                "submit_wiki_draft",
                AsyncMock(
                    side_effect=draft_tools.InvalidTransition(
                        "Draft cannot be submitted from approved."
                    )
                ),
            ),
        ):
            result = asyncio.run(
                tools.request_review(
                    draft_id=str(draft.id),
                    review_type="content",
                    expected_version=1,
                )
            )

        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["errors"], ["invalid_transition"])

    def test_hidden_and_missing_drafts_share_the_same_not_found_response(self) -> None:
        tools = self._tools()
        draft_id = str(uuid.uuid4())
        with patch.object(
            GovernedDraftReviewTools,
            "_scoped_draft",
            AsyncMock(return_value=None),
        ):
            hidden = asyncio.run(tools.read_review_feedback(draft_id=draft_id))
            missing = asyncio.run(
                tools.read_review_feedback(draft_id=str(uuid.uuid4()))
            )

        self.assertEqual(hidden, missing)
        self.assertEqual(hidden["status"], "not_found")
        self.assertEqual(hidden["data"], {})
        self.assertNotIn(draft_id, hidden["summary"])

    def test_non_author_cannot_read_scoped_feedback(self) -> None:
        tools = self._tools()
        draft = _draft(author_id=uuid.uuid4(), status="pending")
        with patch.object(
            GovernedDraftReviewTools,
            "_scoped_draft",
            AsyncMock(return_value=draft),
        ):
            result = asyncio.run(tools.read_review_feedback(draft_id=str(draft.id)))

        self.assertEqual(result["status"], "not_found")
        self.assertEqual(result["errors"], ["not_found"])
        self.assertEqual(result["data"], {})


if __name__ == "__main__":
    unittest.main()
