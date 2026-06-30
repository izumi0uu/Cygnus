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
    def __init__(self, *, count: int | None = 0, drafts=None, page_by_id=None):
        self._count = count
        self._drafts = list(drafts or [])
        self._page_by_id = dict(page_by_id or {})
        self._execute_calls = 0

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
    async def test_submit_wiki_branch_promotes_branch_and_notifies_reviewers(self) -> None:
        import cygnus.review.branches as branch_module

        branch = types.SimpleNamespace(id=uuid.uuid4(), author_id=uuid.uuid4(), status="draft")
        author = types.SimpleNamespace(id=branch.author_id, role="member", name="Author", email="author@example.com")
        drafts = [
            types.SimpleNamespace(id=uuid.uuid4(), status="draft"),
            types.SimpleNamespace(id=uuid.uuid4(), status="needs_revision"),
        ]
        db = _FakeDB(count=2, drafts=drafts)

        with (
            patch.object(branch_module, "notify_submitted", AsyncMock()) as notify_submitted,
            patch.object(branch_module, "log_audit", AsyncMock()) as log_audit,
        ):
            result = await branch_module.submit_wiki_branch(db, branch, author)

        self.assertEqual(branch.status, "pending_merge")
        self.assertEqual([draft.status for draft in drafts], ["pending", "pending"])
        self.assertEqual(result, drafts)
        self.assertEqual(notify_submitted.await_count, 2)
        log_audit.assert_awaited_once()

    async def test_close_wiki_branch_withdraws_open_drafts_and_marks_closed(self) -> None:
        import cygnus.review.branches as branch_module

        branch = types.SimpleNamespace(id=uuid.uuid4(), author_id=uuid.uuid4(), status="pending_merge")
        author = types.SimpleNamespace(id=branch.author_id, role="member", name="Author", email="author@example.com")
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
        page = types.SimpleNamespace(id=draft.page_id, title="Billing", slug="billing", version=5)
        branch = types.SimpleNamespace(
            id=uuid.uuid4(),
            author_id=uuid.uuid4(),
            status="pending_merge",
            has_conflict=True,
            reviewer_id=None,
            reviewed_at=None,
            reviewer_note=None,
        )
        reviewer = types.SimpleNamespace(id=uuid.uuid4(), role="admin", name="Reviewer", email="reviewer@example.com")
        db = _FakeDB(count=None, drafts=[draft], page_by_id={draft.page_id: page})

        with (
            patch.object(branch_module, "approve_wiki_draft", AsyncMock(return_value=page)) as approve_wiki_draft,
            patch.object(branch_module, "notify_approved", AsyncMock()) as notify_approved,
            patch.object(branch_module, "log_audit", AsyncMock()) as log_audit,
        ):
            result = await branch_module.merge_wiki_branch(db, branch, reviewer, reviewer_note="Ship it")

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
        page = types.SimpleNamespace(id=draft.page_id, title="Billing", slug="billing", version=2)
        branch = types.SimpleNamespace(id=uuid.uuid4(), author_id=uuid.uuid4(), status="pending_merge", has_conflict=False)
        reviewer = types.SimpleNamespace(id=uuid.uuid4(), role="admin", name="Reviewer", email="reviewer@example.com")
        db = _FakeDB(count=None, drafts=[draft], page_by_id={draft.page_id: page})

        with self.assertRaises(branch_module.BranchMergeConflict) as exc:
            await branch_module.merge_wiki_branch(db, branch, reviewer)

        self.assertTrue(branch.has_conflict)
        self.assertEqual(exc.exception.page_slug, "billing")
        self.assertEqual(exc.exception.current_version, 2)
        self.assertEqual(exc.exception.base_version, 1)

    async def test_rebase_wiki_branch_draft_refreshes_base_version_and_conflict_flag(self) -> None:
        import cygnus.review.branches as branch_module

        draft = types.SimpleNamespace(
            id=uuid.uuid4(),
            page_id=uuid.uuid4(),
            branch_id=uuid.uuid4(),
            draft_kind="edit",
            base_version=1,
            status="needs_revision",
            content_md="old",
        )
        branch = types.SimpleNamespace(id=draft.branch_id, author_id=uuid.uuid4(), has_conflict=True)
        author = types.SimpleNamespace(id=branch.author_id, role="member", name="Author", email="author@example.com")
        page = types.SimpleNamespace(id=draft.page_id, version=3, title="Billing", slug="billing")
        db = _FakeDB(count=None, drafts=[draft], page_by_id={draft.page_id: page})

        with (
            patch.object(branch_module, "_enqueue_ai_review", AsyncMock()) as enqueue,
            patch.object(branch_module, "log_audit", AsyncMock()) as log_audit,
        ):
            result = await branch_module.rebase_wiki_branch_draft(db, branch, draft, author, "resolved")

        self.assertIs(result, draft)
        self.assertEqual(draft.content_md, "resolved")
        self.assertEqual(draft.base_version, 3)
        self.assertEqual(draft.status, "pending")
        self.assertFalse(branch.has_conflict)
        enqueue.assert_awaited_once()
        log_audit.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
