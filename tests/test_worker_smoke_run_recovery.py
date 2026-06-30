from __future__ import annotations

from contextlib import ExitStack
import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch


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
        )
        self.plan = None
        self.enqueued_jobs: list[tuple[str, tuple[object, ...]]] = []
        self.events: list[str] = []
        self.created_pages: list[types.SimpleNamespace] = []


class _FakeSession:
    def __init__(self, repo: _RepoState) -> None:
        self.repo = repo

    async def get(self, model, obj_id):
        model_name = getattr(model, "__name__", str(model))
        if model_name == "Source" and obj_id == self.repo.source.id:
            return self.repo.source
        if (
            model_name == "SourceCompilationPlan"
            and self.repo.plan is not None
            and obj_id == self.repo.plan.id
        ):
            return self.repo.plan
        return None

    async def execute(self, *_args, **_kwargs):
        self.repo.events.append("db.execute")
        return types.SimpleNamespace()

    async def commit(self):
        self.repo.events.append("db.commit")
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

    async def enqueue_job(self, task_name: str, *args):
        self.repo.events.append(f"queue:{task_name}")
        self.repo.enqueued_jobs.append((task_name, args))
        return types.SimpleNamespace(job_id=f"job-{len(self.repo.enqueued_jobs)}-{task_name}")


class WorkerSmokeRunRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_url_ingest_to_wiki_commit_smoke_run_regains_minimal_closure(self) -> None:
        import cygnus.runtime.worker as worker_module
        from cygnus.runtime.ai.mrp.writer import PageWriteResult
        from cygnus.runtime.config import settings as runtime_settings

        repo = _RepoState()
        fake_pool = _FakeArqPool(repo)

        async def _extract_text_from_url(url: str):
            repo.events.append("extract.url")
            self.assertEqual(url, repo.source.url)
            return [{"page": 1, "content": "Billing export is available in Settings > Billing."}]

        def _build_outline(pages):
            repo.events.append("outline.build")
            self.assertEqual(len(pages), 1)
            return [{"title": "Billing export", "level": 1}]

        def _assemble_full_text(pages):
            repo.events.append("outline.assemble")
            return (pages[0]["content"], [{"page": 1, "start": 0, "end": len(pages[0]["content"])}])

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
                plan_json={},
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

        async def _apply_create(*_args, **kwargs):
            repo.events.append("wiki.create")
            page = types.SimpleNamespace(
                id=uuid.uuid4(),
                slug=kwargs["slug"],
                content_md=kwargs["content_md"],
                source_ids=kwargs["source_ids"],
            )
            repo.created_pages.append(page)
            return page

        async def _apply_update(*_args, **_kwargs):
            repo.events.append("wiki.update")
            return None

        async def _regenerate_index(*_args, **_kwargs):
            repo.events.append("wiki.index")
            return None

        async def _append_log(*_args, **_kwargs):
            repo.events.append("wiki.log")
            return None

        with ExitStack() as stack:
            stack.enter_context(patch("cygnus.runtime.database.async_session_factory", new=_SessionFactory(repo)))
            stack.enter_context(patch("cygnus.runtime.ai.registry.ProviderRegistry", new=_FakeRegistry))
            stack.enter_context(patch.object(worker_module, "get_arq_pool", AsyncMock(return_value=fake_pool)))
            stack.enter_context(patch("cygnus.substrate.source_text._extract_text_from_url", side_effect=_extract_text_from_url))
            stack.enter_context(patch("cygnus.substrate.source_outline.build_outline", side_effect=_build_outline))
            stack.enter_context(patch("cygnus.substrate.source_outline.assemble_full_text", side_effect=_assemble_full_text))
            stack.enter_context(patch("cygnus.runtime.utils.tokens.count_tokens", return_value=18))
            stack.enter_context(patch.object(runtime_settings, "mrp_auto_approve_plan", True))
            stack.enter_context(patch("cygnus.runtime.ai.mrp.pipeline.run_map_phase", side_effect=_run_map_phase))
            stack.enter_context(patch("cygnus.runtime.ai.mrp.pipeline.run_reduce_phase", side_effect=_run_reduce_phase))
            stack.enter_context(patch("cygnus.runtime.ai.mrp.pipeline._load_plan", AsyncMock(side_effect=lambda *_args, **_kwargs: repo.plan)))
            stack.enter_context(patch("cygnus.runtime.ai.mrp.pipeline._load_chunk_extracts", AsyncMock(return_value=[{"chunk_id": "chunk-1"}])))
            stack.enter_context(patch("cygnus.runtime.ai.mrp.pipeline._get_embedding_spec", AsyncMock(return_value=(None, None))))
            stack.enter_context(patch("cygnus.runtime.ai.mrp.pipeline._resolve_wiki_scopes", AsyncMock(return_value=[("global", None)])))
            stack.enter_context(patch("cygnus.runtime.ai.mrp.pipeline.run_refine_phase", side_effect=_run_refine_phase))
            stack.enter_context(patch("cygnus.runtime.ai.mrp.pipeline.run_verify_phase", side_effect=_run_verify_phase))
            stack.enter_context(patch("cygnus.runtime.services.wiki_service.get_page_by_slug", side_effect=_get_page_by_slug))
            stack.enter_context(patch("cygnus.runtime.services.wiki_service.apply_create", side_effect=_apply_create))
            stack.enter_context(patch("cygnus.runtime.services.wiki_service.apply_update", side_effect=_apply_update))
            stack.enter_context(patch("cygnus.runtime.services.wiki_service.regenerate_index", side_effect=_regenerate_index))
            stack.enter_context(patch("cygnus.runtime.services.wiki_service.append_log", side_effect=_append_log))
            ingest_result = await worker_module.ingest_url_task({}, str(repo.source.id))
            map_reduce_result = await worker_module.ingest_map_reduce_task({}, str(repo.source.id))
            refine_result = await worker_module.ingest_refine_task({}, str(repo.source.id))

        self.assertEqual(ingest_result["status"], "processing")
        self.assertEqual(map_reduce_result["status"], "plan_auto_approved")
        self.assertEqual(refine_result, {"pages_created": 1, "pages_updated": 0})

        self.assertEqual(
            [task_name for task_name, _args in repo.enqueued_jobs],
            ["ingest_map_reduce_task", "ingest_refine_task"],
        )
        self.assertEqual(repo.source.job_id, "job-2-ingest_refine_task")
        self.assertEqual(repo.source.status, "ready")
        self.assertEqual(repo.source.pipeline_phase, "commit")
        self.assertEqual(repo.source.progress, 100)
        self.assertEqual(repo.source.progress_message, "Done")
        self.assertEqual(repo.source.auto_recover_count, 0)
        self.assertEqual(repo.plan.status, "done")
        self.assertEqual(len(repo.created_pages), 1)

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
                "wiki.create",
                "wiki.index",
                "wiki.log",
            ],
        )

    def _assert_event_subsequence(self, events: list[str], expected: list[str]) -> None:
        cursor = 0
        for marker in expected:
            try:
                cursor = events.index(marker, cursor) + 1
            except ValueError as exc:
                raise AssertionError(f"missing event marker: {marker}\nactual events: {events}") from exc


if __name__ == "__main__":
    unittest.main()
