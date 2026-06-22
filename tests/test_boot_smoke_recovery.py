from __future__ import annotations

import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


class _HealthySession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, *_args, **_kwargs):
        return object()


class _HealthySessionFactory:
    def __call__(self):
        return _HealthySession()


class _HealthyArqPool:
    async def ping(self):
        return True


class _HealthyRedis:
    def __init__(self, *args, **kwargs):
        pass

    async def ping(self):
        return True

    async def aclose(self):
        return None


class ApiBootSmokeTests(unittest.TestCase):
    def test_fastapi_app_can_boot_with_stubbed_infra_dependencies(self) -> None:
        from cygnus.backend import main as app_main

        with (
            patch.object(app_main, "seed_default_admin", AsyncMock(return_value=None)) as seed_admin,
            patch("cygnus.backend.services.storage_service.storage_service.ensure_bucket", AsyncMock(return_value=None)) as ensure_bucket,
            patch("cygnus.backend.scripts.seed_skills.seed_builtin_skills", AsyncMock(return_value=None)) as seed_skills,
        ):
            with TestClient(app_main.app) as client:
                response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Cygnus")
        seed_admin.assert_awaited_once()
        ensure_bucket.assert_awaited()
        seed_skills.assert_awaited()

    def test_health_routes_have_minimal_smoke_path_when_services_are_stubbed(self) -> None:
        from cygnus.backend import main as app_main

        with (
            patch.object(app_main, "seed_default_admin", AsyncMock(return_value=None)),
            patch("cygnus.backend.services.storage_service.storage_service.ensure_bucket", AsyncMock(return_value=None)),
            patch("cygnus.backend.scripts.seed_skills.seed_builtin_skills", AsyncMock(return_value=None)),
            patch("cygnus.backend.database.async_session_factory", new=_HealthySessionFactory()),
            patch("cygnus.backend.routers.sources.get_arq_pool", new=AsyncMock(return_value=_HealthyArqPool())),
            patch("redis.asyncio.Redis", new=_HealthyRedis),
        ):
            with TestClient(app_main.app) as client:
                health = client.get("/health")
                api_health = client.get("/api/health")

        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "healthy")
        self.assertEqual(
            api_health.json(),
            {"api": "healthy", "database": "healthy", "worker": "healthy"},
        )


class WorkerBootSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_hooks_expose_a_bootable_contract(self) -> None:
        from cygnus.backend.worker import WorkerSettings

        await WorkerSettings.on_startup({})
        await WorkerSettings.on_shutdown({})

        self.assertGreaterEqual(len(WorkerSettings.functions), 1)
        self.assertGreaterEqual(len(WorkerSettings.cron_jobs), 1)

    async def test_arq_pool_lazy_init_only_calls_factory_once(self) -> None:
        import cygnus.backend.worker as worker_module

        fake_pool = object()
        fake_create_pool = AsyncMock(return_value=fake_pool)

        with (
            patch.object(worker_module, "_arq_pool", None),
            patch.object(worker_module, "create_pool", fake_create_pool),
        ):
            first = await worker_module.get_arq_pool()
            second = await worker_module.get_arq_pool()

        self.assertIs(first, fake_pool)
        self.assertIs(second, fake_pool)
        fake_create_pool.assert_awaited_once()


class MrpResumeSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_map_reduce_reenters_plan_review_without_rerunning_extract_phases(self) -> None:
        import cygnus.backend.ai.mrp.pipeline as pipeline_module

        source_id = uuid.uuid4()
        source = types.SimpleNamespace(id=source_id, pipeline_phase="plan_review")
        plan = types.SimpleNamespace(id=uuid.uuid4(), status="pending_review")

        with (
            patch.object(pipeline_module, "_load_plan", AsyncMock(return_value=plan)) as load_plan,
            patch.object(pipeline_module, "run_map_phase", AsyncMock()) as map_phase,
            patch.object(pipeline_module, "run_reduce_phase", AsyncMock()) as reduce_phase,
        ):
            result = await pipeline_module.run_mrp_pipeline(
                session=object(),
                source=source,
                full_text="full text",
                tracker=object(),
                registry=object(),
                kt_slug=None,
                kt_name=None,
                kt_desc=None,
            )

        self.assertEqual(result, {"status": "plan_ready", "plan_id": str(plan.id)})
        load_plan.assert_awaited_once()
        map_phase.assert_not_called()
        reduce_phase.assert_not_called()

    async def test_refine_pipeline_resumes_from_verify_using_persisted_page_drafts(self) -> None:
        import cygnus.backend.ai.mrp.pipeline as pipeline_module

        source_id = uuid.uuid4()
        source = types.SimpleNamespace(id=source_id, pipeline_phase="verify")
        plan = types.SimpleNamespace(
            status="approved",
            plan_json={
                "_page_drafts": [
                    {
                        "slug": "billing-export-answer",
                        "title": "Billing export answer",
                        "page_type": "answer_card",
                        "action": "CREATE",
                        "content_md": "Resolved draft content",
                        "summary": "Resume from persisted draft.",
                    }
                ]
            },
        )

        class _FakeSession:
            async def get(self, _model, _source_id):
                return source

            async def commit(self):
                return None

        class _FakeRegistry:
            async def get_llm(self):
                return object()

        verify_phase = AsyncMock(side_effect=lambda **kwargs: kwargs["page_results"])
        commit_phase = AsyncMock(return_value={"pages_created": 1, "pages_updated": 0})

        with (
            patch.object(pipeline_module, "_load_plan", AsyncMock(return_value=plan)),
            patch.object(pipeline_module, "_load_chunk_extracts", AsyncMock(return_value=[])),
            patch.object(pipeline_module, "_get_embedding_spec", AsyncMock(return_value=(None, None))),
            patch.object(pipeline_module, "run_refine_phase", AsyncMock()) as refine_phase,
            patch.object(pipeline_module, "run_verify_phase", verify_phase),
            patch.object(pipeline_module, "run_commit_phase", commit_phase),
        ):
            result = await pipeline_module.run_refine_pipeline(
                session=_FakeSession(),
                source=source,
                full_text="full text",
                tracker=object(),
                registry=_FakeRegistry(),
                kt_slug=None,
                kt_name=None,
                kt_desc=None,
            )

        refine_phase.assert_not_called()
        verify_phase.assert_awaited_once()
        commit_phase.assert_awaited_once()
        self.assertEqual(result["pages_created"], 1)
