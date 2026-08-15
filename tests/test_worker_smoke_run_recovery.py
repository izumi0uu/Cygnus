from __future__ import annotations

from contextlib import ExitStack
import types
import unittest
import uuid
from typing import Protocol, TypedDict, cast
from unittest.mock import AsyncMock, patch


class _SuggestedMetadata(TypedDict):
    scope_type: str
    scope_id: str | None
    language: str


class _StagedDraft(Protocol):
    id: uuid.UUID
    status: str
    source: str
    suggested_metadata: _SuggestedMetadata


class _RepoState:
    def __init__(self) -> None:
        self.source = types.SimpleNamespace(
            id=uuid.uuid4(),
            title="Billing export guide",
            file_name=None,
            source_type="url",
            url="https://example.com/help/billing-export",
            minio_key=None,
            preserve_verbatim=False,
            knowledge_type_id=None,
            full_text=None,
            outline_json=None,
            page_offsets=None,
            extracted_token_count=None,
            status="pending",
            progress=0,
            progress_message=None,
            error_message=None,
            job_id=None,
            pipeline_phase=None,
            auto_recover_count=1,
            dispatch_generation=0,
            delete_requested_at=None,
            metadata_={},
            scope_type="global",
            scope_id=None,
            language="en",
            contributed_by_employee_id=None,
        )
        self.plan: types.SimpleNamespace | None = None
        self.enqueued_jobs: list[tuple[str, tuple[object, ...], dict[str, object]]] = []
        self.events: list[str] = []
        self.staged_drafts: list[_StagedDraft] = []
        self.governance_events: list[object] = []


class _FakeResult:
    def __init__(self, scalar=None, rows=None) -> None:
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one(self):
        return self._scalar

    def scalar_one_or_none(self):
        return self._scalar

    def one_or_none(self):
        return self._scalar

    def all(self):
        return self._rows

    def scalars(self):
        return types.SimpleNamespace(all=lambda: self._rows)


class _FakeSession:
    def __init__(self, repo: _RepoState) -> None:
        self.repo = repo
        self._last_dispatch_row: types.SimpleNamespace | None = None

    async def get(self, model, obj_id, **_kwargs):
        model_name = getattr(model, "__name__", str(model))
        if model_name == "Source" and obj_id == self.repo.source.id:
            return self.repo.source
        if (
            model_name == "SourceCompilationPlan"
            and self.repo.plan is not None
            and obj_id == self.repo.plan.id
        ):
            return self.repo.plan
        if model_name == "WikiPageDraft":
            return next(
                (
                    draft
                    for draft in self.repo.staged_drafts
                    if getattr(draft, "id", None) == obj_id
                ),
                None,
            )
        return None

    def _dispatch_row(self, stmt):
        """A SourceDispatchExecution stand-in for outbox selects.

        Cached per session so the claim (which mutates it to ``running`` with a
        lease token) and the lease-aware fence re-read observe the same row.
        """
        if self._last_dispatch_row is not None:
            return self._last_dispatch_row
        stage = "ingest"

        def _scan_stage(crit) -> None:
            nonlocal stage
            left = getattr(crit, "left", None)
            right = getattr(crit, "right", None)
            if getattr(left, "name", None) == "stage":
                # Literal comparison values arrive as BindParameter wrappers
                # (e.g. col == "refine"); unwrap to the bound value.
                candidate = getattr(right, "value", right)
                if isinstance(candidate, str):
                    stage = candidate
            # select().where(a, b, c) may nest the criteria in a
            # BooleanClauseList (AND); walk into it so the stage predicate is
            # still found.
            for sub in getattr(crit, "clauses", ()) or ():
                _scan_stage(sub)

        for crit in getattr(stmt, "_where_criteria", ()):
            _scan_stage(crit)
        generation = getattr(self.repo.source, "dispatch_generation", 0) or 1
        from cygnus.runtime import source_dispatch as dispatch

        self._last_dispatch_row = types.SimpleNamespace(
            id=uuid.uuid4(),
            source_id=self.repo.source.id,
            generation=generation,
            stage=stage,
            task_name="ingest_map_reduce_task",
            task_args=[str(self.repo.source.id)],
            job_id=dispatch.source_stage_job_id(self.repo.source.id, stage, generation),
            dispatch_status="pending",
            attempt_count=0,
            enqueued_at=None,
            lease_expires_at=None,
            next_attempt_at=None,
            terminal_reason=None,
            last_error=None,
            completed_at=None,
        )
        return self._last_dispatch_row

    async def execute(self, stmt, *_args, **_kwargs):
        self.repo.events.append("db.execute")
        selected = getattr(stmt, "selected_columns", None)
        names = list(selected.keys()) if selected is not None else []
        descriptions = getattr(stmt, "column_descriptions", ())
        entity_names = {
            getattr(description.get("entity"), "__name__", "")
            for description in descriptions
            if isinstance(description, dict)
        }
        if names == ["dispatch_generation", "delete_requested_at"]:
            return _FakeResult(
                scalar=types.SimpleNamespace(
                    dispatch_generation=getattr(
                        self.repo.source, "dispatch_generation", 0
                    ),
                    delete_requested_at=None,
                )
            )
        if names == ["scope_type", "scope_id"]:
            return _FakeResult(
                scalar=(self.repo.source.scope_type, self.repo.source.scope_id)
            )
        if "SourceDepartment" in entity_names or names == ["department_id"]:
            return _FakeResult(rows=[])
        if "GovernanceLedgerEvent" in entity_names:
            return _FakeResult(scalar=None)
        if names == ["dispatch_status", "lease_token", "lease_expires_at"]:
            # Lease-aware fence re-read of the claimed execution.
            return _FakeResult(scalar=self._dispatch_row(None))
        if names == ["dispatch_status"]:
            return _FakeResult(scalar="running")
        if "SourceDispatchExecution" in entity_names:
            return _FakeResult(scalar=self._dispatch_row(stmt))
        return _FakeResult(scalar=None)

    def add(self, obj) -> None:
        model_name = type(obj).__name__
        if model_name == "WikiPageDraft":
            self.repo.staged_drafts.append(cast(_StagedDraft, obj))
            self.repo.events.append("draft.stage")
        elif model_name == "GovernanceLedgerEvent":
            self.repo.governance_events.append(obj)
            self.repo.events.append("draft.ledger")

    async def commit(self):
        self.repo.events.append("db.commit")
        return None

    async def rollback(self):
        self.repo.events.append("db.rollback")
        return None

    async def flush(self):
        self.repo.events.append("db.flush")
        return None

    async def refresh(self, _obj):
        self.repo.events.append("db.refresh")
        return None


class _SessionScope:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _SessionFactory:
    def __init__(self, repo: _RepoState) -> None:
        self.repo = repo

    def __call__(self):
        return _SessionScope(_FakeSession(self.repo))


class _FakeRegistry:
    def __init__(self, session) -> None:
        _ = session

    async def get_llm(self):
        return object()

    async def get_embedding(self, task: str = "document"):
        _ = task
        return None

    async def get_vision(self):
        return None


class _FakeArqPool:
    def __init__(self, repo: _RepoState) -> None:
        self.repo = repo

    async def enqueue_job(
        self, task_name: str, *args, _job_id: str | None = None, **kwargs
    ):
        self.repo.events.append(f"queue:{task_name}")
        self.repo.enqueued_jobs.append((task_name, args, kwargs))
        return types.SimpleNamespace(
            job_id=_job_id or f"job-{len(self.repo.enqueued_jobs)}-{task_name}"
        )


class WorkerSmokeRunRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_url_ingest_to_staged_wiki_draft_regains_minimal_closure(
        self,
    ) -> None:
        import cygnus.runtime.worker as worker_module
        from cygnus.runtime.ai.mrp.writer import PageWriteResult
        from cygnus.runtime.config import settings as runtime_settings

        repo = _RepoState()
        fake_pool = _FakeArqPool(repo)

        async def _extract_text_from_url(url: str):
            repo.events.append("extract.url")
            self.assertEqual(url, repo.source.url)
            return [
                {
                    "page": 1,
                    "content": "Billing export is available in Settings > Billing.",
                }
            ]

        def _build_outline(pages):
            repo.events.append("outline.build")
            self.assertEqual(len(pages), 1)
            return [{"title": "Billing export", "level": 1}]

        def _assemble_full_text(pages):
            repo.events.append("outline.assemble")
            return (
                pages[0]["content"],
                [{"page": 1, "start": 0, "end": len(pages[0]["content"])}],
            )

        async def _run_map_phase(**kwargs):
            repo.events.append("mrp.map")
            repo.source.pipeline_phase = "map"
            return ("map", [{"chunk_id": "chunk-1", "claims": []}])

        async def _run_reduce_phase(**kwargs):
            repo.events.append("mrp.reduce")
            repo.source.pipeline_phase = "plan_review"
            repo.plan = types.SimpleNamespace(
                id=uuid.uuid4(),
                source_id=repo.source.id,
                status="pending_review",
                review_note=None,
                reviewed_at=None,
                plan_json={
                    "pages": [
                        {
                            "slug": "billing-export-answer",
                            "title": "Billing export answer",
                            "page_type": "answer_card",
                            "action": "CREATE",
                            "entity_names": ["billing export"],
                            "priority": 1,
                        }
                    ],
                    "_claims": [
                        {
                            "statement": (
                                "Billing export is available in Settings > Billing."
                            ),
                            "subject": "billing export",
                            "confidence": "explicit",
                            "absolute_offset": 0,
                            "evidence_length": 54,
                        }
                    ],
                },
            )
            return repo.plan

        async def _run_refine_phase(**kwargs):
            repo.events.append("mrp.refine")
            return [
                PageWriteResult(
                    slug="billing-export-answer",
                    title="Billing export answer",
                    page_type="answer_card",
                    action="CREATE",
                    content_md="Customers can export billing data from Settings → Billing → Export.",
                    summary="Explain where billing export lives.",
                )
            ]

        async def _run_verify_phase(**kwargs):
            repo.events.append("mrp.verify")
            return kwargs["page_results"]

        async def _get_page_by_slug(*_args, **_kwargs):
            repo.events.append("wiki.lookup")
            return None

        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "cygnus.runtime.database.async_session_factory",
                    new=_SessionFactory(repo),
                )
            )
            stack.enter_context(
                patch("cygnus.runtime.ai.registry.ProviderRegistry", new=_FakeRegistry)
            )
            stack.enter_context(
                patch.object(
                    worker_module, "get_arq_pool", AsyncMock(return_value=fake_pool)
                )
            )
            stack.enter_context(
                patch(
                    "cygnus.substrate.source_text._extract_text_from_url",
                    side_effect=_extract_text_from_url,
                )
            )
            stack.enter_context(
                patch(
                    "cygnus.substrate.source_outline.build_outline",
                    side_effect=_build_outline,
                )
            )
            stack.enter_context(
                patch(
                    "cygnus.substrate.source_outline.assemble_full_text",
                    side_effect=_assemble_full_text,
                )
            )
            stack.enter_context(
                patch("cygnus.runtime.utils.tokens.count_tokens", return_value=18)
            )
            stack.enter_context(
                patch.object(runtime_settings, "mrp_auto_approve_plan", True)
            )
            stack.enter_context(
                patch(
                    "cygnus.runtime.ai.mrp.pipeline.run_map_phase",
                    side_effect=_run_map_phase,
                )
            )
            stack.enter_context(
                patch(
                    "cygnus.runtime.ai.mrp.pipeline._collect_map_failures",
                    AsyncMock(return_value=[]),
                )
            )
            stack.enter_context(
                patch(
                    "cygnus.runtime.ai.mrp.pipeline.run_reduce_phase",
                    side_effect=_run_reduce_phase,
                )
            )
            stack.enter_context(
                patch(
                    "cygnus.runtime.ai.mrp.pipeline._load_plan",
                    AsyncMock(side_effect=lambda *_args, **_kwargs: repo.plan),
                )
            )
            stack.enter_context(
                patch(
                    "cygnus.runtime.ai.mrp.pipeline._load_chunk_extracts",
                    AsyncMock(return_value=[{"chunk_id": "chunk-1"}]),
                )
            )
            stack.enter_context(
                patch(
                    "cygnus.runtime.ai.mrp.pipeline._get_embedding_spec",
                    AsyncMock(return_value=(None, None)),
                )
            )
            stack.enter_context(
                patch(
                    "cygnus.runtime.ai.mrp.pipeline.run_refine_phase",
                    side_effect=_run_refine_phase,
                )
            )
            stack.enter_context(
                patch(
                    "cygnus.runtime.ai.mrp.pipeline.run_verify_phase",
                    side_effect=_run_verify_phase,
                )
            )
            stack.enter_context(
                patch(
                    "cygnus.runtime.services.wiki_service.get_page_by_slug",
                    side_effect=_get_page_by_slug,
                )
            )
            ingest_result = await worker_module.ingest_url_task({}, str(repo.source.id))
            map_reduce_result = await worker_module.ingest_map_reduce_task(
                {}, str(repo.source.id)
            )
            refine_result = await worker_module.ingest_refine_task(
                {}, str(repo.source.id)
            )

        self.assertEqual(ingest_result["status"], "processing")
        self.assertEqual(map_reduce_result["status"], "plan_auto_approved")
        self.assertEqual(
            refine_result,
            {
                "drafts_created": 1,
                "edit_drafts_created": 0,
                "drafts_replayed": 0,
            },
        )

        self.assertEqual(
            [task_name for task_name, _args, _kwargs in repo.enqueued_jobs],
            ["ingest_map_reduce_task", "ingest_refine_task"],
        )
        from cygnus.runtime import source_dispatch as dispatch

        self.assertEqual(
            repo.source.job_id,
            dispatch.source_stage_job_id(
                repo.source.id, dispatch.DISPATCH_STAGE_REFINE, 1
            ),
        )
        self.assertEqual(repo.source.status, "ready")
        self.assertEqual(repo.source.pipeline_phase, "commit")
        self.assertEqual(repo.source.progress, 100)
        self.assertEqual(repo.source.progress_message, "Done")
        self.assertEqual(repo.source.auto_recover_count, 0)
        assert repo.plan is not None
        self.assertEqual(repo.plan.status, "done")
        self.assertEqual(len(repo.staged_drafts), 1)
        draft = repo.staged_drafts[0]
        self.assertEqual(getattr(draft, "status", None), "draft")
        self.assertEqual(getattr(draft, "source", None), "compiler")
        self.assertEqual(draft.suggested_metadata["scope_type"], "global")
        self.assertIsNone(draft.suggested_metadata["scope_id"])
        self.assertEqual(draft.suggested_metadata["language"], "en")
        self.assertEqual(len(repo.governance_events), 1)

        self._assert_event_subsequence(
            repo.events,
            [
                "extract.url",
                "outline.build",
                "outline.assemble",
                "queue:ingest_map_reduce_task",
                "mrp.map",
                "mrp.reduce",
                "queue:ingest_refine_task",
                "mrp.refine",
                "mrp.verify",
                "wiki.lookup",
                "draft.stage",
                "draft.ledger",
            ],
        )

    def _assert_event_subsequence(self, events: list[str], expected: list[str]) -> None:
        cursor = 0
        for marker in expected:
            try:
                cursor = events.index(marker, cursor) + 1
            except ValueError as exc:
                raise AssertionError(
                    f"missing event marker: {marker}\nactual events: {events}"
                ) from exc


if __name__ == "__main__":
    unittest.main()
