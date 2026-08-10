from __future__ import annotations

import types
import unittest
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one(self):
        return self._value


class _ListResult:
    def __init__(self, values):
        self._values = list(values)

    def scalars(self):
        return self

    def all(self):
        return list(self._values)


class _FakeDB:
    def __init__(
        self, *, count: int | None = 0, drafts=None, page_by_id=None, on_refresh=None
    ):
        self._count = count
        self._drafts = list(drafts or [])
        self._page_by_id = dict(page_by_id or {})
        self._on_refresh = on_refresh
        self._execute_calls = 0
        self.refreshed: list[object] = []

    async def refresh(self, obj) -> None:
        self.refreshed.append(obj)
        if self._on_refresh is not None:
            self._on_refresh(obj)

    async def flush(self) -> None:
        return None

    async def execute(self, stmt):
        self._execute_calls += 1
        if self._execute_calls == 1 and self._count is not None:
            return _ScalarResult(self._count)
        return _ListResult(self._drafts)

    async def get(self, model, key):
        return self._page_by_id.get(key)

    @asynccontextmanager
    async def begin_nested(self):
        yield


class WikiBranchLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_submit_wiki_branch_promotes_branch_and_notifies_reviewers(
        self,
    ) -> None:
        import cygnus.review.branches as branch_module

        branch = types.SimpleNamespace(
            id=uuid.uuid4(), author_id=uuid.uuid4(), status="draft"
        )
        author = types.SimpleNamespace(
            id=branch.author_id,
            role="member",
            name="Author",
            email="author@example.com",
        )
        drafts = [
            types.SimpleNamespace(id=uuid.uuid4(), status="draft"),
            types.SimpleNamespace(id=uuid.uuid4(), status="needs_revision"),
        ]
        db = _FakeDB(count=2, drafts=drafts)

        with (
            patch.object(
                branch_module, "notify_submitted", AsyncMock()
            ) as notify_submitted,
            patch.object(branch_module, "log_audit", AsyncMock()) as log_audit,
        ):
            result = await branch_module.submit_wiki_branch(db, branch, author)

        self.assertEqual(branch.status, "pending_merge")
        self.assertEqual([draft.status for draft in drafts], ["pending", "pending"])
        self.assertEqual(result, drafts)
        self.assertEqual(notify_submitted.await_count, 2)
        log_audit.assert_awaited_once()

    async def test_close_wiki_branch_withdraws_open_drafts_and_marks_closed(
        self,
    ) -> None:
        import cygnus.review.branches as branch_module

        branch = types.SimpleNamespace(
            id=uuid.uuid4(), author_id=uuid.uuid4(), status="pending_merge"
        )
        author = types.SimpleNamespace(
            id=branch.author_id,
            role="member",
            name="Author",
            email="author@example.com",
        )
        drafts = [
            types.SimpleNamespace(id=uuid.uuid4(), status="pending"),
            types.SimpleNamespace(id=uuid.uuid4(), status="needs_revision"),
            types.SimpleNamespace(id=uuid.uuid4(), status="approved"),
        ]
        db = _FakeDB(count=None, drafts=drafts)

        with (
            patch.object(branch_module, "withdraw", AsyncMock()) as withdraw,
            patch.object(branch_module, "log_audit", AsyncMock()) as log_audit,
        ):
            await branch_module.close_wiki_branch(db, branch, author)

        self.assertEqual(branch.status, "closed")
        self.assertEqual(withdraw.await_count, 2)
        log_audit.assert_awaited_once()

    async def test_merge_wiki_branch_marks_terminal_merged(self) -> None:
        import cygnus.review.branches as branch_module

        draft = types.SimpleNamespace(
            id=uuid.uuid4(),
            page_id=uuid.uuid4(),
            draft_kind="edit",
            base_version=5,
            status="pending",
            page=None,
        )
        page = types.SimpleNamespace(
            id=draft.page_id, title="Billing", slug="billing", version=5
        )
        branch = types.SimpleNamespace(
            id=uuid.uuid4(),
            author_id=uuid.uuid4(),
            status="pending_merge",
            has_conflict=True,
            reviewer_id=None,
            reviewed_at=None,
            reviewer_note=None,
        )
        reviewer = types.SimpleNamespace(
            id=uuid.uuid4(), role="admin", name="Reviewer", email="reviewer@example.com"
        )
        db = _FakeDB(count=None, drafts=[draft], page_by_id={draft.page_id: page})

        with (
            patch.object(
                branch_module, "approve_wiki_draft", AsyncMock(return_value=page)
            ) as approve_wiki_draft,
            patch.object(
                branch_module, "notify_approved", AsyncMock()
            ) as notify_approved,
            patch.object(branch_module, "log_audit", AsyncMock()) as log_audit,
        ):
            result = await branch_module.merge_wiki_branch(
                db, branch, reviewer, reviewer_note="Ship it"
            )

        self.assertEqual(result, [draft])
        self.assertEqual(branch.status, "merged")
        self.assertEqual(branch.reviewer_id, reviewer.id)
        self.assertEqual(branch.reviewer_note, "Ship it")
        self.assertFalse(branch.has_conflict)
        self.assertIs(draft.page, page)
        approve_wiki_draft.assert_awaited_once()
        notify_approved.assert_awaited_once()
        log_audit.assert_awaited_once()

    async def test_merge_wiki_branch_raises_conflict_and_flags_branch(self) -> None:
        import cygnus.review.branches as branch_module

        draft = types.SimpleNamespace(
            id=uuid.uuid4(),
            page_id=uuid.uuid4(),
            draft_kind="edit",
            base_version=1,
            status="pending",
            page=None,
        )
        page = types.SimpleNamespace(
            id=draft.page_id, title="Billing", slug="billing", version=2
        )
        branch = types.SimpleNamespace(
            id=uuid.uuid4(),
            author_id=uuid.uuid4(),
            status="pending_merge",
            has_conflict=False,
        )
        reviewer = types.SimpleNamespace(
            id=uuid.uuid4(), role="admin", name="Reviewer", email="reviewer@example.com"
        )
        db = _FakeDB(count=None, drafts=[draft], page_by_id={draft.page_id: page})

        with self.assertRaises(branch_module.BranchMergeConflict) as exc:
            await branch_module.merge_wiki_branch(db, branch, reviewer)

        self.assertTrue(branch.has_conflict)
        self.assertEqual(exc.exception.page_slug, "billing")
        self.assertEqual(exc.exception.current_version, 2)
        self.assertEqual(exc.exception.base_version, 1)

    async def test_rebase_wiki_branch_draft_refreshes_base_version_and_conflict_flag(
        self,
    ) -> None:
        import cygnus.review.branches as branch_module

        branch_id = uuid.uuid4()
        author_id = uuid.uuid4()
        draft = types.SimpleNamespace(
            id=uuid.uuid4(),
            page_id=uuid.uuid4(),
            branch_id=branch_id,
            author_id=author_id,
            draft_kind="edit",
            base_version=1,
            status="pending",
            version=1,
            content_md="old",
            ai_check_status="failed",
            ai_check_results={"old": True},
            ai_checked_at=object(),
        )
        branch = types.SimpleNamespace(
            id=branch_id,
            author_id=author_id,
            status="pending_merge",
            has_conflict=True,
        )
        author = types.SimpleNamespace(
            id=author_id, role="member", name="Author", email="author@example.com"
        )
        page = types.SimpleNamespace(
            id=draft.page_id, version=3, title="Billing", slug="billing"
        )
        db = _FakeDB(count=None, drafts=[draft], page_by_id={draft.page_id: page})

        with (
            patch.object(branch_module, "lock_draft_aggregate", AsyncMock()) as lock,
            patch.object(
                branch_module,
                "record_draft_update",
                AsyncMock(return_value=types.SimpleNamespace(id=uuid.uuid4())),
            ) as record,
            patch.object(branch_module, "stage_ai_pre_review", AsyncMock()) as stage,
            patch.object(branch_module, "log_audit", AsyncMock()) as log_audit,
        ):
            result = await branch_module.rebase_wiki_branch_draft(
                db, branch, draft, author, "resolved"
            )

        self.assertIs(result, draft)
        self.assertEqual(draft.content_md, "resolved")
        self.assertEqual(draft.base_version, 3)
        self.assertEqual(draft.status, "pending")
        self.assertEqual(draft.version, 2)
        self.assertEqual(draft.ai_check_status, "pending")
        self.assertIsNone(draft.ai_check_results)
        self.assertIsNone(draft.ai_checked_at)
        self.assertFalse(branch.has_conflict)
        lock.assert_awaited_once_with(db, draft.id)
        self.assertIn(draft, db.refreshed)
        record.assert_awaited_once()
        self.assertEqual(record.await_args.kwargs["action"], "branch_rebase")
        self.assertEqual(record.await_args.kwargs["previous_draft_version"], 1)
        self.assertEqual(record.await_args.args[1].version, 2)
        stage.assert_awaited_once_with(db, draft)
        log_audit.assert_awaited_once()

    async def test_rebase_rejects_a_conflict_already_resolved_while_waiting_for_lock(
        self,
    ) -> None:
        import cygnus.review.branches as branch_module

        branch_id = uuid.uuid4()
        author_id = uuid.uuid4()
        draft = types.SimpleNamespace(
            id=uuid.uuid4(),
            page_id=uuid.uuid4(),
            branch_id=branch_id,
            author_id=author_id,
            draft_kind="edit",
            base_version=1,
            status="pending",
            version=1,
            content_md="old",
            ai_check_status="pending",
            ai_check_results=None,
            ai_checked_at=None,
        )
        branch = types.SimpleNamespace(
            id=branch_id,
            author_id=author_id,
            status="pending_merge",
            has_conflict=True,
        )
        author = types.SimpleNamespace(
            id=author_id, role="member", name="Author", email="author@example.com"
        )
        page = types.SimpleNamespace(
            id=draft.page_id, version=3, title="Billing", slug="billing"
        )

        def refresh_to_committed_state(obj) -> None:
            if obj is draft:
                draft.content_md = "already rebased"
                draft.base_version = page.version
                draft.version = 2

        db = _FakeDB(
            count=None,
            drafts=[draft],
            page_by_id={draft.page_id: page},
            on_refresh=refresh_to_committed_state,
        )
        with (
            patch.object(branch_module, "lock_draft_aggregate", AsyncMock()),
            patch.object(branch_module, "record_draft_update", AsyncMock()) as record,
            patch.object(branch_module, "stage_ai_pre_review") as stage,
            patch.object(branch_module, "log_audit", AsyncMock()) as log_audit,
        ):
            with self.assertRaises(branch_module.InvalidTransition):
                await branch_module.rebase_wiki_branch_draft(
                    db,
                    branch,
                    draft,
                    author,
                    "lost concurrent overwrite",
                )

        self.assertEqual(draft.content_md, "already rebased")
        self.assertEqual(draft.version, 2)
        record.assert_not_awaited()
        stage.assert_not_called()
        log_audit.assert_not_awaited()

    async def test_rebase_rejects_orphaned_draft_for_non_admin(self) -> None:
        import cygnus.review.branches as branch_module

        branch_id = uuid.uuid4()
        author_id = uuid.uuid4()
        draft = types.SimpleNamespace(
            id=uuid.uuid4(),
            page_id=uuid.uuid4(),
            branch_id=branch_id,
            author_id=None,
            draft_kind="edit",
            base_version=1,
            status="pending",
            version=1,
            content_md="old",
            ai_check_status="pending",
            ai_check_results=None,
            ai_checked_at=None,
        )
        branch = types.SimpleNamespace(
            id=branch_id,
            author_id=author_id,
            status="pending_merge",
            has_conflict=True,
        )
        author = types.SimpleNamespace(
            id=author_id, role="member", name="Author", email="author@example.com"
        )
        page = types.SimpleNamespace(
            id=draft.page_id, version=3, title="Billing", slug="billing"
        )
        db = _FakeDB(count=None, drafts=[draft], page_by_id={draft.page_id: page})

        with (
            patch.object(branch_module, "lock_draft_aggregate", AsyncMock()),
            patch.object(branch_module, "record_draft_update", AsyncMock()) as record,
            patch.object(branch_module, "stage_ai_pre_review") as stage,
        ):
            with self.assertRaises(branch_module.InvalidTransition):
                await branch_module.rebase_wiki_branch_draft(
                    db,
                    branch,
                    draft,
                    author,
                    "unauthorized overwrite",
                )

        self.assertEqual(draft.content_md, "old")
        self.assertEqual(draft.version, 1)
        record.assert_not_awaited()
        stage.assert_not_called()


if __name__ == "__main__":
    unittest.main()
