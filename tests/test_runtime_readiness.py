"""Focused CYG-132 readiness tests: livez/readyz separation, worker
heartbeat lifecycle, graceful drain runner wiring, and probe failure modes.

These tests never start Redis/MinIO/PostgreSQL; every dependency is faked so
the checks are deterministic.  The Alembic graph is owned by other slices in
flight, so schema assertions always inject fake migration heads.
"""

from __future__ import annotations

import json
import signal
import unittest
from datetime import timedelta
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


def _heartbeat_payload(role, queue, state="ready", identity="i1", age=0.0):
    from cygnus.runtime import readiness as r

    timestamp = (r._utc_now() - timedelta(seconds=age)).isoformat()
    return json.dumps(
        {
            "schema_version": 1,
            "identity": identity,
            "role": role,
            "queue": queue,
            "state": state,
            "current_jobs": [],
            "timestamp": timestamp,
        }
    )


def _payloads_for(role, queue, **kwargs):
    from cygnus.runtime import readiness as r

    return {
        r.worker_heartbeat_key(role=role, identity="i1"): _heartbeat_payload(
            role, queue, **kwargs
        )
    }


class _ScalarRows:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return self

    def all(self):
        return list(self._values)


class _FakeProbeSession:
    def __init__(self, versions=None, fail_db=False, fail_schema=False):
        self.versions = versions
        self.fail_db = fail_db
        self.fail_schema = fail_schema

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def execute(self, statement):
        if "alembic_version" in str(statement):
            if self.fail_schema:
                raise RuntimeError("schema query failed")
            return _ScalarRows(self.versions)
        if self.fail_db:
            raise RuntimeError("db unavailable")
        return object()


class _FakeProbeSessionFactory:
    def __init__(self, versions=None, fail_db=False, fail_schema=False):
        self.versions = versions
        self.fail_db = fail_db
        self.fail_schema = fail_schema

    def __call__(self):
        return _FakeProbeSession(
            versions=self.versions,
            fail_db=self.fail_db,
            fail_schema=self.fail_schema,
        )


class _FakeProbeRedis:
    def __init__(self, payloads=None, ping_fails=False):
        self.payloads = dict(payloads or {})
        self.ping_fails = ping_fails
        self.closed = False

    async def ping(self):
        if self.ping_fails:
            raise ConnectionError("redis down")
        return True

    async def scan_iter(self, match=None, count=None):
        for key in sorted(self.payloads):
            yield key

    async def get(self, key):
        return self.payloads.get(key)

    async def aclose(self):
        self.closed = True


class _RecordingRedis:
    """Redis fake that appends every SET so heartbeat state sequences are observable."""

    def __init__(self):
        self.sets: list[tuple[str, str, int | None]] = []

    async def set(self, key, value, ex=None):
        self.sets.append((key, value, ex))


def _fake_redis_factory(payloads=None, ping_fails=False):
    redis = _FakeProbeRedis(payloads=payloads, ping_fails=ping_fails)

    def factory(settings, timeout_seconds):
        return redis

    return factory


class ProbeReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_dependencies_ready(self) -> None:
        from cygnus.runtime import readiness as r
        from cygnus.runtime.config import Settings

        heads = frozenset({"abc123"})
        payloads = {}
        for role, queue in r.REQUIRED_WORKERS.items():
            payloads.update(_payloads_for(role, queue))

        with patch.object(r, "_probe_minio", AsyncMock(return_value={})):
            report = await r.probe_readiness(
                settings=Settings(),
                session_factory=_FakeProbeSessionFactory(versions=list(heads)),
                startup_complete=True,
                redis_factory=_fake_redis_factory(payloads),
                migration_heads=lambda: heads,
            )

        self.assertTrue(report.ready)
        self.assertEqual(report.to_dict()["status"], "ready")
        workers_details = cast(dict[str, Any], report.checks["workers"].details)
        self.assertEqual(
            workers_details["workers"]["default"]["status"],
            "ready",
        )
        self.assertEqual(
            workers_details["workers"]["skills"]["status"],
            "ready",
        )
        self.assertEqual(report.checks["database"].status, "ready")
        self.assertEqual(report.checks["schema"].status, "ready")
        self.assertEqual(report.checks["redis"].status, "ready")
        self.assertEqual(report.checks["minio"].status, "ready")

    async def test_schema_mismatch_fails_schema_check_only(self) -> None:
        from cygnus.runtime import readiness as r
        from cygnus.runtime.config import Settings

        heads = frozenset({"abc123"})

        with patch.object(r, "_probe_minio", AsyncMock(return_value={})):
            report = await r.probe_readiness(
                settings=Settings(),
                session_factory=_FakeProbeSessionFactory(versions=["other-head"]),
                startup_complete=True,
                redis_factory=_fake_redis_factory({}),
                migration_heads=lambda: heads,
            )

        self.assertFalse(report.ready)
        self.assertEqual(report.checks["schema"].status, "failed")
        self.assertEqual(report.checks["schema"].reason, "migration_head_mismatch")
        self.assertEqual(report.checks["database"].status, "ready")

    async def test_database_failure_fails_database_and_schema(self) -> None:
        from cygnus.runtime import readiness as r
        from cygnus.runtime.config import Settings

        with patch.object(r, "_probe_minio", AsyncMock(return_value={})):
            report = await r.probe_readiness(
                settings=Settings(),
                session_factory=_FakeProbeSessionFactory(fail_db=True),
                startup_complete=True,
                redis_factory=_fake_redis_factory({}),
                migration_heads=lambda: frozenset({"abc123"}),
            )

        self.assertFalse(report.ready)
        self.assertEqual(report.checks["database"].status, "failed")
        self.assertEqual(report.checks["database"].reason, "RuntimeError")

    async def test_redis_failure_fails_redis_and_workers(self) -> None:
        from cygnus.runtime import readiness as r
        from cygnus.runtime.config import Settings

        with patch.object(r, "_probe_minio", AsyncMock(return_value={})):
            report = await r.probe_readiness(
                settings=Settings(),
                session_factory=_FakeProbeSessionFactory(versions=["abc123"]),
                startup_complete=True,
                redis_factory=_fake_redis_factory({}, ping_fails=True),
                migration_heads=lambda: frozenset({"abc123"}),
            )

        self.assertFalse(report.ready)
        self.assertEqual(report.checks["redis"].status, "failed")
        self.assertEqual(report.checks["redis"].reason, "ConnectionError")
        self.assertEqual(report.checks["workers"].status, "failed")
        self.assertEqual(report.checks["workers"].reason, "redis_unavailable")

    async def test_missing_worker_heartbeat_fails_workers_but_not_redis(self) -> None:
        from cygnus.runtime import readiness as r
        from cygnus.runtime.config import Settings

        with patch.object(r, "_probe_minio", AsyncMock(return_value={})):
            report = await r.probe_readiness(
                settings=Settings(),
                session_factory=_FakeProbeSessionFactory(versions=["abc123"]),
                startup_complete=True,
                redis_factory=_fake_redis_factory({}),
                migration_heads=lambda: frozenset({"abc123"}),
            )

        self.assertFalse(report.ready)
        self.assertEqual(report.checks["redis"].status, "ready")
        self.assertEqual(report.checks["workers"].status, "failed")
        self.assertEqual(
            report.checks["workers"].reason,
            "worker_heartbeat_missing_or_unready:default,skills",
        )

    async def test_draining_worker_is_visible_as_unready(self) -> None:
        from cygnus.runtime import readiness as r
        from cygnus.runtime.config import Settings

        payloads = _payloads_for("default", r.DEFAULT_WORKER_QUEUE, state="ready")
        payloads.update(
            _payloads_for("skills", r.SKILLS_WORKER_QUEUE, state="draining")
        )

        with patch.object(r, "_probe_minio", AsyncMock(return_value={})):
            report = await r.probe_readiness(
                settings=Settings(),
                session_factory=_FakeProbeSessionFactory(versions=["abc123"]),
                startup_complete=True,
                redis_factory=_fake_redis_factory(payloads),
                migration_heads=lambda: frozenset({"abc123"}),
            )

        self.assertFalse(report.ready)
        self.assertEqual(report.checks["workers"].status, "failed")
        self.assertEqual(
            report.checks["workers"].reason,
            "worker_heartbeat_missing_or_unready:skills",
        )
        workers_details = cast(dict[str, Any], report.checks["workers"].details)
        self.assertEqual(
            workers_details["workers"]["skills"]["status"],
            "unready",
        )

    async def test_stale_worker_heartbeat_fails_workers(self) -> None:
        from cygnus.runtime import readiness as r
        from cygnus.runtime.config import Settings

        payloads = _payloads_for("default", r.DEFAULT_WORKER_QUEUE, state="ready")
        payloads.update(
            _payloads_for("skills", r.SKILLS_WORKER_QUEUE, state="ready", age=90)
        )

        with patch.object(r, "_probe_minio", AsyncMock(return_value={})):
            report = await r.probe_readiness(
                settings=Settings(),
                session_factory=_FakeProbeSessionFactory(versions=["abc123"]),
                startup_complete=True,
                redis_factory=_fake_redis_factory(payloads),
                migration_heads=lambda: frozenset({"abc123"}),
            )

        self.assertFalse(report.ready)
        self.assertEqual(report.checks["workers"].status, "failed")

    async def test_startup_incomplete_fails_readyz(self) -> None:
        from cygnus.runtime import readiness as r
        from cygnus.runtime.config import Settings

        with patch.object(r, "_probe_minio", AsyncMock(return_value={})):
            report = await r.probe_readiness(
                settings=Settings(),
                session_factory=_FakeProbeSessionFactory(versions=["abc123"]),
                startup_complete=False,
                redis_factory=_fake_redis_factory({}),
                migration_heads=lambda: frozenset({"abc123"}),
            )

        self.assertFalse(report.ready)
        self.assertEqual(report.checks["startup"].status, "failed")
        self.assertEqual(report.checks["startup"].reason, "startup_incomplete")

    async def test_invalid_configuration_fails_readyz(self) -> None:
        from cygnus.runtime import readiness as r
        from cygnus.runtime.config import Settings

        bad = Settings(
            worker_heartbeat_interval_seconds=60,
            worker_heartbeat_timeout_seconds=30,
        )

        with patch.object(r, "_probe_minio", AsyncMock(return_value={})):
            report = await r.probe_readiness(
                settings=bad,
                session_factory=_FakeProbeSessionFactory(versions=["abc123"]),
                startup_complete=True,
                redis_factory=_fake_redis_factory({}),
                migration_heads=lambda: frozenset({"abc123"}),
            )

        self.assertFalse(report.ready)
        self.assertEqual(report.checks["configuration"].status, "failed")
        self.assertEqual(report.checks["configuration"].reason, "configuration_invalid")
        invalid_fields = cast(
            list[str], report.checks["configuration"].details["invalid_fields"]
        )
        self.assertIn(
            "worker_heartbeat_timeout_seconds",
            invalid_fields,
        )

    async def test_minio_missing_bucket_fails_minio_check(self) -> None:
        from cygnus.runtime import readiness as r
        from cygnus.runtime.config import Settings

        class _FakeClient:
            _http = None

            def bucket_exists(self, bucket):
                return False

        with patch.object(r, "build_minio_probe_client", return_value=_FakeClient()):
            with self.assertRaises(r.ReadinessProbeFailure) as cm:
                await r._probe_minio(Settings(), 5.0)

        self.assertEqual(cm.exception.reason, "bucket_missing_or_not_authorized")

    def test_probe_liveness_is_side_effect_free(self) -> None:
        from cygnus.runtime import readiness as r

        self.assertEqual(
            r.probe_liveness(startup_complete=True).to_dict(),
            {"status": "alive", "startup": "complete"},
        )
        self.assertEqual(
            r.probe_liveness(startup_complete=False).to_dict(),
            {"status": "alive", "startup": "in_progress"},
        )

    def test_worker_heartbeat_key_and_pattern_formats(self) -> None:
        from cygnus.runtime import readiness as r

        self.assertEqual(
            r.worker_heartbeat_key(role="skills", identity="i1"),
            "cygnus:runtime:worker-heartbeat:v1:skills:i1",
        )
        self.assertEqual(
            r.worker_heartbeat_pattern(role="default"),
            "cygnus:runtime:worker-heartbeat:v1:default:*",
        )


class WorkerHeartbeatLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_heartbeat_publishes_distinct_states(self) -> None:
        from cygnus.runtime import readiness as r
        from cygnus.runtime.config import Settings

        redis = _RecordingRedis()
        heartbeat = await r.start_worker_heartbeat(
            {"redis": redis},
            role="default",
            queue="arq:queue",
            settings=Settings(),
        )
        await heartbeat.mark_ready()
        await heartbeat.mark_draining()
        await heartbeat.mark_stopped()

        states = [json.loads(value)["state"] for _key, value, _ex in redis.sets]
        self.assertEqual(states, ["starting", "ready", "draining", "stopped"])
        keys = {key for key, _value, _ex in redis.sets}
        self.assertEqual(keys, {heartbeat.key})
        ttl = {ex for _key, _value, ex in redis.sets}
        self.assertNotIn(None, ttl)

    async def test_job_tracking_updates_current_jobs(self) -> None:
        from cygnus.runtime import readiness as r
        from cygnus.runtime.config import Settings

        redis = _RecordingRedis()
        heartbeat = await r.start_worker_heartbeat(
            {"redis": redis},
            role="default",
            queue="arq:queue",
            settings=Settings(),
        )
        await heartbeat.mark_ready()

        job_ctx = {"job_id": "job-1", "job_try": 2, "enqueue_time": 123456.0}
        await heartbeat.mark_job_started(job_ctx)
        payload = json.loads(redis.sets[-1][1])
        self.assertEqual(payload["state"], "ready")
        self.assertEqual([job["job_id"] for job in payload["current_jobs"]], ["job-1"])
        self.assertEqual(payload["current_jobs"][0]["attempt"], "2")

        await heartbeat.mark_job_finished(job_ctx)
        payload = json.loads(redis.sets[-1][1])
        self.assertEqual(payload["current_jobs"], [])

    async def test_parse_heartbeat_rejects_stale_and_malformed(self) -> None:
        from cygnus.runtime import readiness as r

        now = r._utc_now()
        good = json.dumps(
            {
                "schema_version": 1,
                "identity": "i1",
                "role": "default",
                "queue": "arq:queue",
                "state": "ready",
                "current_jobs": [],
                "timestamp": now.isoformat(),
            }
        )
        parsed = r._parse_heartbeat(good.encode(), now=now, timeout_seconds=30)
        assert parsed is not None
        self.assertEqual(parsed["state"], "ready")

        stale = json.dumps(
            {
                "state": "ready",
                "timestamp": (now - timedelta(seconds=60)).isoformat(),
            }
        )
        self.assertIsNone(r._parse_heartbeat(stale, now=now, timeout_seconds=30))
        self.assertIsNone(r._parse_heartbeat("not-json", now=now, timeout_seconds=30))
        self.assertIsNone(
            r._parse_heartbeat(
                json.dumps({"state": "ready"}),
                now=now,
                timeout_seconds=30,
            )
        )
        self.assertIsNone(
            r._parse_heartbeat(
                json.dumps({"state": "bogus", "timestamp": now.isoformat()}),
                now=now,
                timeout_seconds=30,
            )
        )


class _FakeDrainLoop:
    def __init__(self):
        self.handlers = {}
        self.tasks = []

    def add_signal_handler(self, signum, callback):
        self.handlers[signum] = callback

    def create_task(self, coro):
        self.tasks.append(coro)
        return object()


class _FakeDrainHeartbeat:
    def __init__(self):
        self.state = "ready"
        self.marked = False

    async def mark_draining(self):
        self.marked = True
        self.state = "draining"


class _FakeDrainWorker:
    def __init__(self, heartbeat=None, completion_wait=30):
        self.loop = _FakeDrainLoop()
        self.ctx = {}
        if heartbeat is not None:
            self.ctx["cygnus_runtime_worker_heartbeat"] = heartbeat
        self._job_completion_wait = completion_wait
        self.calls = []

    def handle_sig_wait_for_completion(self, signum):
        self.calls.append(("wait", signum))

    def handle_sig(self, signum):
        self.calls.append(("cancel", signum))


class DrainRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_signal_handler_marks_draining_then_delegates(self) -> None:
        from cygnus.runtime import drain

        heartbeat = _FakeDrainHeartbeat()
        worker = _FakeDrainWorker(heartbeat=heartbeat, completion_wait=30)

        drain._install_drain_signal_handlers(cast(Any, worker))
        worker.loop.handlers[signal.SIGTERM]()

        self.assertEqual(worker.calls, [("wait", signal.SIGTERM)])
        self.assertEqual(len(worker.loop.tasks), 1)
        await worker.loop.tasks[0]
        self.assertTrue(heartbeat.marked)
        self.assertEqual(heartbeat.state, "draining")

    def test_signal_handler_delegates_without_heartbeat(self) -> None:
        from cygnus.runtime import drain

        worker = _FakeDrainWorker(heartbeat=None, completion_wait=30)

        drain._install_drain_signal_handlers(cast(Any, worker))
        worker.loop.handlers[signal.SIGINT]()

        self.assertEqual(worker.calls, [("wait", signal.SIGINT)])
        self.assertEqual(worker.loop.tasks, [])

    async def test_signal_handler_uses_cancel_path_without_grace(self) -> None:
        from cygnus.runtime import drain

        heartbeat = _FakeDrainHeartbeat()
        worker = _FakeDrainWorker(heartbeat=heartbeat, completion_wait=0)

        drain._install_drain_signal_handlers(cast(Any, worker))
        worker.loop.handlers[signal.SIGTERM]()

        self.assertEqual(worker.calls, [("cancel", signal.SIGTERM)])
        self.assertEqual(len(worker.loop.tasks), 1)
        await worker.loop.tasks[0]
        self.assertTrue(heartbeat.marked)

    def test_run_worker_dispatches_to_graceful_runner(self) -> None:
        import cygnus.runtime.worker as worker_module

        with patch("cygnus.runtime.drain.run_graceful_worker") as runner:
            worker_module.run_worker("SkillWorkerSettings")
        runner.assert_called_once_with(worker_module.SkillWorkerSettings)

        with patch("cygnus.runtime.drain.run_graceful_worker") as runner:
            worker_module.run_worker()
        runner.assert_called_once_with(worker_module.WorkerSettings)

        with self.assertRaises(KeyError):
            worker_module.run_worker("NoSuchSettings")

    def test_worker_settings_wire_drain_grace_into_arq_worker(self) -> None:
        from arq.cli import create_worker
        from arq.typing import WorkerSettingsBase
        from cygnus.runtime.config import Settings
        from cygnus.runtime.worker import SkillWorkerSettings, WorkerSettings

        expected = Settings().worker_drain_grace_seconds
        for settings_cls in (WorkerSettings, SkillWorkerSettings):
            worker = create_worker(cast(type[WorkerSettingsBase], settings_cls))
            self.assertEqual(worker._job_completion_wait, expected)
            self.assertTrue(worker._handle_signals)


class ReadinessEndpointSeparationTests(unittest.TestCase):
    _CHECK_NAMES = (
        "startup",
        "configuration",
        "database",
        "schema",
        "redis",
        "minio",
        "workers",
    )

    def _boot(self):
        from cygnus.runtime import main as app_main

        return (
            patch.object(app_main, "seed_default_admin", AsyncMock(return_value=None)),
            patch(
                "cygnus.runtime.services.storage_service.storage_service.ensure_bucket",
                AsyncMock(return_value=None),
            ),
            patch(
                "cygnus.runtime.bootstrap.seed_builtin_skills.seed_builtin_skills",
                AsyncMock(return_value=None),
            ),
        )

    def _report(self, *, ready: bool):
        from cygnus.runtime.readiness import ReadinessCheck, ReadinessReport

        checks = {name: ReadinessCheck(status="ready") for name in self._CHECK_NAMES}
        if not ready:
            checks["workers"] = ReadinessCheck(
                status="failed",
                reason="worker_heartbeat_missing_or_unready:skills",
            )
        return ReadinessReport(checks=checks)

    def test_livez_stays_200_while_readyz_fails(self) -> None:
        from cygnus.runtime import main as app_main

        boot = self._boot()
        with (
            boot[0],
            boot[1],
            boot[2],
            patch(
                "cygnus.runtime.readiness.probe_readiness",
                AsyncMock(return_value=self._report(ready=False)),
            ),
        ):
            with TestClient(app_main.app) as client:
                livez = client.get("/livez")
                readyz = client.get("/readyz")

        self.assertEqual(livez.status_code, 200)
        self.assertEqual(livez.json()["status"], "alive")
        self.assertEqual(readyz.status_code, 503)
        self.assertEqual(readyz.json()["status"], "not_ready")
        self.assertEqual(
            readyz.json()["checks"]["workers"]["reason"],
            "worker_heartbeat_missing_or_unready:skills",
        )

    def test_readyz_returns_200_when_all_checks_ready(self) -> None:
        from cygnus.runtime import main as app_main

        boot = self._boot()
        with (
            boot[0],
            boot[1],
            boot[2],
            patch(
                "cygnus.runtime.readiness.probe_readiness",
                AsyncMock(return_value=self._report(ready=True)),
            ),
        ):
            with TestClient(app_main.app) as client:
                livez = client.get("/livez")
                readyz = client.get("/readyz")

        self.assertEqual(livez.status_code, 200)
        self.assertEqual(readyz.status_code, 200)
        self.assertEqual(readyz.json()["status"], "ready")


if __name__ == "__main__":
    unittest.main()
