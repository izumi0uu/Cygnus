"""Bounded, read-only runtime liveness and readiness contracts.

Readiness is intentionally stricter than process liveness.  It verifies the
runtime dependencies that make Cygnus safe to serve and requires one current,
ready heartbeat for each independently deployed ARQ worker role.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import socket
import uuid
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from alembic.config import Config
from alembic.script import ScriptDirectory
from loguru import logger
from sqlalchemy import text

from cygnus.runtime.config import Settings

DEFAULT_WORKER_ROLE = "default"
SKILLS_WORKER_ROLE = "skills"
DEFAULT_WORKER_QUEUE = "arq:queue"
SKILLS_WORKER_QUEUE = "skills_queue"
REQUIRED_WORKERS = {
    DEFAULT_WORKER_ROLE: DEFAULT_WORKER_QUEUE,
    SKILLS_WORKER_ROLE: SKILLS_WORKER_QUEUE,
}

WORKER_HEARTBEAT_PREFIX = "cygnus:runtime:worker-heartbeat:v1"
WORKER_HEARTBEAT_CONTEXT_KEY = "cygnus_runtime_worker_heartbeat"
_HEARTBEAT_STATES = frozenset({"starting", "ready", "draining", "stopped"})


class ReadinessProbeFailure(RuntimeError):
    """A probe failed for a safe-to-return operational reason."""

    def __init__(
        self,
        reason: str,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        #: Optional partial probe results (e.g. the per-role worker breakdown)
        #: that the failed check still surfaces in the readiness report.
        self.details = details


@dataclass(frozen=True, slots=True)
class ReadinessCheck:
    """One non-secret readiness result."""

    status: str
    reason: str | None = None
    details: dict[str, object] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"status": self.status}
        if self.reason is not None:
            payload["reason"] = self.reason
        if self.details:
            payload["details"] = self.details
        return payload


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    """The canonical response body shared by readiness and legacy endpoints."""

    checks: dict[str, ReadinessCheck]

    @property
    def ready(self) -> bool:
        return all(check.ready for check in self.checks.values())

    def to_dict(self) -> dict[str, object]:
        return {
            "status": "ready" if self.ready else "not_ready",
            "checks": {name: check.to_dict() for name, check in self.checks.items()},
        }


@dataclass(frozen=True, slots=True)
class LivenessReport:
    """Side-effect-free process liveness; never touches runtime dependencies."""

    status: str
    startup_complete: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "startup": "complete" if self.startup_complete else "in_progress",
        }


def probe_liveness(*, startup_complete: bool) -> LivenessReport:
    """Return process liveness without any I/O or dependency probes.

    Liveness answers only "is this process serving requests".  It never opens
    a database, Redis, or object-storage connection, so a dependency or worker
    failure can never flip livez away from 200 while readyz reports it.
    """
    return LivenessReport(status="alive", startup_complete=startup_complete)


def worker_heartbeat_key(*, role: str, identity: str) -> str:
    """Return the Redis key for one process-unique worker heartbeat."""
    return f"{WORKER_HEARTBEAT_PREFIX}:{role}:{identity}"


def worker_heartbeat_pattern(*, role: str) -> str:
    """Return the read-only Redis scan pattern for one worker role."""
    return f"{WORKER_HEARTBEAT_PREFIX}:{role}:*"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _utc_now().isoformat()


def _heartbeat_ttl_seconds(settings: Settings) -> int:
    return max(
        int(settings.worker_heartbeat_timeout_seconds) * 2,
        int(settings.worker_heartbeat_interval_seconds) * 3,
        30,
    )


def _job_metadata(ctx: dict[str, object]) -> dict[str, object]:
    """Project only ARQ-provided job metadata; do not inspect job payloads."""
    metadata: dict[str, object] = {}
    for source_name, target_name in (
        ("job_id", "job_id"),
        ("job_try", "attempt"),
        ("enqueue_time", "enqueued_at"),
    ):
        value = ctx.get(source_name)
        if value is not None:
            metadata[target_name] = str(value)
    return metadata


class WorkerHeartbeat:
    """Refresh a distinct, bounded-TTL worker heartbeat without job payload data."""

    def __init__(
        self,
        *,
        redis: object,
        role: str,
        queue: str,
        identity: str,
        interval_seconds: int,
        ttl_seconds: int,
    ) -> None:
        self._redis = redis
        self._role = role
        self._queue = queue
        self._identity = identity
        self._interval_seconds = interval_seconds
        self._ttl_seconds = ttl_seconds
        self._state = "starting"
        self._current_jobs: dict[str, dict[str, object]] = {}
        self._lock = asyncio.Lock()
        self._refresh_task: asyncio.Task[None] | None = None

    @property
    def role(self) -> str:
        return self._role

    @property
    def state(self) -> str:
        return self._state

    @property
    def key(self) -> str:
        return worker_heartbeat_key(role=self._role, identity=self._identity)

    @classmethod
    async def start(
        cls,
        ctx: dict[str, object],
        *,
        role: str,
        queue: str,
        settings: Settings,
    ) -> "WorkerHeartbeat":
        redis = ctx.get("redis")
        if redis is None:
            raise RuntimeError("ARQ startup did not provide a Redis context")

        identity = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex}"
        heartbeat = cls(
            redis=redis,
            role=role,
            queue=queue,
            identity=identity,
            interval_seconds=int(settings.worker_heartbeat_interval_seconds),
            ttl_seconds=_heartbeat_ttl_seconds(settings),
        )
        ctx[WORKER_HEARTBEAT_CONTEXT_KEY] = heartbeat
        await heartbeat._publish()
        heartbeat._refresh_task = asyncio.create_task(
            heartbeat._refresh_loop(),
            name=f"cygnus-worker-heartbeat:{role}",
        )
        return heartbeat

    async def mark_ready(self) -> None:
        await self._set_state("ready")

    async def mark_draining(self) -> None:
        if self._state != "stopped":
            await self._set_state("draining")

    async def mark_stopped(self) -> None:
        refresh_task = self._refresh_task
        self._refresh_task = None
        if refresh_task is not None:
            refresh_task.cancel()
            try:
                await refresh_task
            except asyncio.CancelledError:
                pass
        await self._set_state("stopped")

    async def mark_job_started(self, ctx: dict[str, object]) -> None:
        metadata = _job_metadata(ctx)
        job_id = str(metadata.get("job_id", "unknown"))
        async with self._lock:
            self._current_jobs[job_id] = metadata
            await self._publish_locked()

    async def mark_job_finished(self, ctx: dict[str, object]) -> None:
        metadata = _job_metadata(ctx)
        job_id = str(metadata.get("job_id", "unknown"))
        async with self._lock:
            self._current_jobs.pop(job_id, None)
            await self._publish_locked()

    async def _set_state(self, state: str) -> None:
        if state not in _HEARTBEAT_STATES:
            raise ValueError(f"unsupported worker heartbeat state: {state}")
        async with self._lock:
            self._state = state
            await self._publish_locked()

    async def _publish(self) -> None:
        async with self._lock:
            await self._publish_locked()

    async def _publish_locked(self) -> None:
        payload = {
            "schema_version": 1,
            "identity": self._identity,
            "role": self._role,
            "queue": self._queue,
            "state": self._state,
            "current_jobs": list(self._current_jobs.values()),
            "timestamp": _iso_now(),
        }
        setter = getattr(self._redis, "set")
        await setter(
            self.key,
            json.dumps(payload, separators=(",", ":"), sort_keys=True),
            ex=self._ttl_seconds,
        )

    async def _refresh_loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval_seconds)
            try:
                await self._publish()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - depends on live Redis faults
                logger.warning(
                    "Worker heartbeat refresh failed role={} class={}",
                    self._role,
                    type(exc).__name__,
                )


async def start_worker_heartbeat(
    ctx: dict[str, object],
    *,
    role: str,
    queue: str,
    settings: Settings,
) -> WorkerHeartbeat:
    """Publish ``starting`` before a worker performs startup recovery."""
    return await WorkerHeartbeat.start(
        ctx,
        role=role,
        queue=queue,
        settings=settings,
    )


def worker_heartbeat_from_context(ctx: dict[str, object]) -> WorkerHeartbeat | None:
    heartbeat = ctx.get(WORKER_HEARTBEAT_CONTEXT_KEY)
    return heartbeat if isinstance(heartbeat, WorkerHeartbeat) else None


async def mark_worker_job_started(ctx: dict[str, object]) -> None:
    heartbeat = worker_heartbeat_from_context(ctx)
    if heartbeat is None:
        return
    try:
        await heartbeat.mark_job_started(ctx)
    except Exception as exc:  # pragma: no cover - Redis outage is integration-owned
        logger.warning(
            "Worker heartbeat job-start update failed role={} class={}",
            heartbeat.role,
            type(exc).__name__,
        )


async def mark_worker_job_finished(ctx: dict[str, object]) -> None:
    heartbeat = worker_heartbeat_from_context(ctx)
    if heartbeat is None:
        return
    try:
        await heartbeat.mark_job_finished(ctx)
    except Exception as exc:  # pragma: no cover - Redis outage is integration-owned
        logger.warning(
            "Worker heartbeat job-end update failed role={} class={}",
            heartbeat.role,
            type(exc).__name__,
        )


async def mark_worker_draining(ctx: dict[str, object]) -> None:
    heartbeat = worker_heartbeat_from_context(ctx)
    if heartbeat is None:
        return
    try:
        await heartbeat.mark_draining()
    except Exception as exc:  # pragma: no cover - Redis outage is integration-owned
        logger.warning(
            "Worker drain heartbeat update failed role={} class={}",
            heartbeat.role,
            type(exc).__name__,
        )


async def stop_worker_heartbeat(ctx: dict[str, object]) -> None:
    heartbeat = worker_heartbeat_from_context(ctx)
    if heartbeat is None:
        return
    try:
        await heartbeat.mark_stopped()
    except Exception as exc:  # pragma: no cover - Redis outage is integration-owned
        logger.warning(
            "Worker stopped heartbeat update failed role={} class={}",
            heartbeat.role,
            type(exc).__name__,
        )


def validate_readiness_configuration(settings: Settings) -> ReadinessCheck:
    """Validate probe-critical config without revealing values or secrets."""
    missing = [
        field_name
        for field_name in (
            "database_url",
            "redis_host",
            "minio_endpoint",
            "minio_access_key",
            "minio_secret_key",
            "minio_bucket",
        )
        if not str(getattr(settings, field_name, "")).strip()
    ]
    invalid: list[str] = []
    for field_name in (
        "health_probe_timeout_seconds",
        "worker_heartbeat_interval_seconds",
        "worker_heartbeat_timeout_seconds",
        "worker_drain_grace_seconds",
    ):
        value = getattr(settings, field_name, None)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            invalid.append(field_name)

    heartbeat_interval = getattr(settings, "worker_heartbeat_interval_seconds", 0)
    heartbeat_timeout = getattr(settings, "worker_heartbeat_timeout_seconds", 0)
    if (
        isinstance(heartbeat_interval, (int, float))
        and not isinstance(heartbeat_interval, bool)
        and isinstance(heartbeat_timeout, (int, float))
        and not isinstance(heartbeat_timeout, bool)
        and heartbeat_timeout <= heartbeat_interval
    ):
        invalid.append("worker_heartbeat_timeout_seconds")

    if missing or invalid:
        return ReadinessCheck(
            status="failed",
            reason="configuration_invalid",
            details={
                "missing_fields": sorted(missing),
                "invalid_fields": sorted(set(invalid)),
            },
        )
    return ReadinessCheck(status="ready")


@lru_cache(maxsize=1)
def expected_alembic_heads() -> frozenset[str]:
    """Read the immutable application migration graph without touching a database."""
    runtime_root = Path.cwd()
    source_root = Path(__file__).resolve().parents[2]
    for root in (runtime_root, source_root):
        config_path = root / "alembic.ini"
        migrations_path = root / "migrations"
        if not config_path.is_file() or not migrations_path.is_dir():
            continue
        config = Config(str(config_path))
        config.set_main_option("script_location", str(migrations_path))
        return frozenset(ScriptDirectory.from_config(config).get_heads())
    raise RuntimeError("Cygnus Alembic runtime assets are unavailable")


class _ProbeSession(Protocol):
    """Minimal async-session surface the readiness probes execute against.

    Deliberately duck-typed so production ``AsyncSession`` factories and the
    deterministic test doubles both satisfy it without coupling readiness to
    a concrete SQLAlchemy wiring.
    """

    async def execute(self, statement: Any) -> Any: ...


#: A callable returning an async context manager that yields a probe session.
_ProbeSessionFactory = Callable[[], AbstractAsyncContextManager[_ProbeSession]]


class _BucketProbeClient(Protocol):
    """Minimal synchronous MinIO surface readiness probes need."""

    def bucket_exists(self, bucket_name: str) -> bool: ...


async def _probe_database(session_factory: _ProbeSessionFactory) -> dict[str, object]:
    async with session_factory() as session:
        await session.execute(text("SELECT 1"))
    return {}


async def _probe_schema(
    session_factory: _ProbeSessionFactory,
    expected_heads: Callable[[], frozenset[str]],
) -> dict[str, object]:
    expected = expected_heads()
    if not expected:
        raise ReadinessProbeFailure("migration_head_unavailable")

    async with session_factory() as session:
        result = await session.execute(text("SELECT version_num FROM alembic_version"))
        actual = frozenset(str(version) for version in result.scalars().all())

    if actual != expected:
        raise ReadinessProbeFailure("migration_head_mismatch")
    return {"heads": len(expected)}


def build_minio_probe_client(
    settings: Settings, timeout_seconds: float
) -> _BucketProbeClient:
    """Build a short-lived MinIO client with bounded connect and read timeouts."""
    from minio import Minio
    from urllib3 import PoolManager, Timeout

    http_client = PoolManager(
        timeout=Timeout(connect=timeout_seconds, read=timeout_seconds),
        retries=False,
    )
    return Minio(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
        http_client=http_client,
    )


async def _probe_minio(settings: Settings, timeout_seconds: float) -> dict[str, object]:
    client = build_minio_probe_client(settings, timeout_seconds)
    try:
        exists = await asyncio.to_thread(client.bucket_exists, settings.minio_bucket)
    finally:
        http_client = getattr(client, "_http", None)
        if http_client is not None:
            clear = getattr(http_client, "clear", None)
            if clear is not None:
                clear()
    if not exists:
        raise ReadinessProbeFailure("bucket_missing_or_not_authorized")
    return {}


def build_readiness_redis(settings: Settings, timeout_seconds: float) -> object:
    """Create a request-local Redis client so readiness never uses queue state."""
    import redis.asyncio as aioredis

    return aioredis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password or None,
        db=settings.redis_db,
        socket_connect_timeout=timeout_seconds,
        socket_timeout=timeout_seconds,
        decode_responses=True,
    )


async def _close_client(client: object) -> None:
    close = getattr(client, "aclose", None)
    if close is None:
        close = getattr(client, "close", None)
    if close is None:
        return
    result = close()
    if inspect.isawaitable(result):
        await result


def _parse_heartbeat(
    payload: object, *, now: datetime, timeout_seconds: float
) -> dict[str, object] | None:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")
    if not isinstance(payload, str):
        return None
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, dict):
        return None

    state = decoded.get("state")
    timestamp = decoded.get("timestamp")
    if state not in _HEARTBEAT_STATES or not isinstance(timestamp, str):
        return None
    try:
        observed_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if observed_at.tzinfo is None:
        return None
    age_seconds = max(0.0, (now - observed_at.astimezone(timezone.utc)).total_seconds())
    if age_seconds > timeout_seconds:
        return None
    return decoded


async def _probe_workers(
    redis: object,
    *,
    timeout_seconds: float,
) -> dict[str, object]:
    now = _utc_now()
    workers: dict[str, dict[str, object]] = {}
    for role, queue in REQUIRED_WORKERS.items():
        found_states: list[str] = []
        ready_identities: list[str] = []
        scan_iter = getattr(redis, "scan_iter")
        async for key in scan_iter(match=worker_heartbeat_pattern(role=role), count=25):
            getter = getattr(redis, "get")
            payload = _parse_heartbeat(
                await getter(key),
                now=now,
                timeout_seconds=timeout_seconds,
            )
            if payload is None:
                continue
            if payload.get("role") != role or payload.get("queue") != queue:
                continue
            state = payload["state"]
            found_states.append(str(state))
            identity = payload.get("identity")
            if state == "ready" and isinstance(identity, str):
                ready_identities.append(identity)

        if ready_identities:
            workers[role] = {
                "status": "ready",
                "ready_instances": len(ready_identities),
            }
        elif found_states:
            workers[role] = {
                "status": "unready",
                "states": sorted(set(found_states)),
            }
        else:
            workers[role] = {"status": "missing"}

    unavailable = [
        role for role, details in workers.items() if details["status"] != "ready"
    ]
    if unavailable:
        raise ReadinessProbeFailure(
            "worker_heartbeat_missing_or_unready:" + ",".join(sorted(unavailable)),
            details={"workers": workers},
        )
    return {"workers": workers}


async def _probe_redis_and_workers(
    settings: Settings,
    timeout_seconds: float,
    redis_factory: Callable[[Settings, float], object],
) -> tuple[ReadinessCheck, ReadinessCheck]:
    redis = redis_factory(settings, timeout_seconds)
    try:
        try:
            await getattr(redis, "ping")()
        except Exception as exc:
            return (
                ReadinessCheck(status="failed", reason=type(exc).__name__),
                ReadinessCheck(status="failed", reason="redis_unavailable"),
            )

        try:
            worker_details = await _probe_workers(
                redis,
                timeout_seconds=float(settings.worker_heartbeat_timeout_seconds),
            )
        except ReadinessProbeFailure as exc:
            return (
                ReadinessCheck(status="ready"),
                ReadinessCheck(
                    status="failed",
                    reason=exc.reason,
                    details=exc.details or {},
                ),
            )
        except Exception as exc:
            return (
                ReadinessCheck(status="ready"),
                ReadinessCheck(status="failed", reason=type(exc).__name__),
            )
        return ReadinessCheck(status="ready"), ReadinessCheck(
            status="ready",
            details=worker_details,
        )
    finally:
        await _close_client(redis)


async def _bounded_check(
    probe: Callable[[], Awaitable[dict[str, object]]],
    *,
    timeout_seconds: float,
) -> ReadinessCheck:
    try:
        details = await asyncio.wait_for(probe(), timeout=timeout_seconds)
    except TimeoutError:
        return ReadinessCheck(status="failed", reason="timeout")
    except ReadinessProbeFailure as exc:
        return ReadinessCheck(status="failed", reason=exc.reason)
    except Exception as exc:
        return ReadinessCheck(status="failed", reason=type(exc).__name__)
    return ReadinessCheck(status="ready", details=details)


async def _record_readiness_metrics(report: ReadinessReport) -> None:
    """Publish per-dependency readiness metrics when the telemetry plane exists.

    The telemetry module is optional: if it is not importable or its helper
    raises, probes still return normally.  The helper is called with keyword
    args ``dependency`` and ``status`` and may be sync or async; its failures
    never fail probes.
    """
    try:
        from cygnus.observability import record_readiness_dependency
    except Exception:  # pragma: no cover - telemetry plane is optional
        return
    for name, check in report.checks.items():
        try:
            if inspect.iscoroutinefunction(record_readiness_dependency):
                await record_readiness_dependency(
                    dependency=name,
                    status=check.status,
                )
            else:
                record_readiness_dependency(
                    dependency=name,
                    status=check.status,
                )
        except Exception:  # pragma: no cover - metric emission must not fail probes
            continue


def _readiness_check(
    result: ReadinessCheck | tuple[ReadinessCheck, ReadinessCheck] | BaseException,
) -> ReadinessCheck:
    """Normalize one ``asyncio.gather`` slot back to a ReadinessCheck.

    Only the redis/workers slot ever carries the ``(redis, workers)`` pair;
    the database/schema/minio slots carry a plain check.  Exceptions surfaced
    by ``gather(return_exceptions=True)`` become failed checks.
    """
    if isinstance(result, BaseException):
        return ReadinessCheck(status="failed", reason=type(result).__name__)
    if isinstance(result, tuple):
        return result[
            0
        ]  # pragma: no cover - only the redis/workers slot returns a pair
    return result


async def probe_readiness(
    *,
    settings: Settings,
    session_factory: _ProbeSessionFactory,
    startup_complete: bool,
    redis_factory: Callable[[Settings, float], object] = build_readiness_redis,
    migration_heads: Callable[[], frozenset[str]] = expected_alembic_heads,
) -> ReadinessReport:
    """Run every dependency probe under the configured deadline, without writes."""
    timeout_seconds = float(settings.health_probe_timeout_seconds)
    configuration = validate_readiness_configuration(settings)
    startup = (
        ReadinessCheck(status="ready")
        if startup_complete
        else ReadinessCheck(
            status="failed",
            reason="startup_incomplete",
        )
    )

    database_task = _bounded_check(
        lambda: _probe_database(session_factory),
        timeout_seconds=timeout_seconds,
    )
    schema_task = _bounded_check(
        lambda: _probe_schema(session_factory, migration_heads),
        timeout_seconds=timeout_seconds,
    )
    minio_task = _bounded_check(
        lambda: _probe_minio(settings, timeout_seconds),
        timeout_seconds=timeout_seconds,
    )
    redis_workers_task = asyncio.wait_for(
        _probe_redis_and_workers(settings, timeout_seconds, redis_factory),
        timeout=timeout_seconds,
    )

    database, schema, minio, redis_workers = await asyncio.gather(
        database_task,
        schema_task,
        minio_task,
        redis_workers_task,
        return_exceptions=True,
    )
    database = _readiness_check(database)
    schema = _readiness_check(schema)
    minio = _readiness_check(minio)
    if isinstance(redis_workers, tuple):
        redis, workers = redis_workers
    elif isinstance(redis_workers, TimeoutError):
        redis = ReadinessCheck(status="failed", reason="timeout")
        workers = ReadinessCheck(status="failed", reason="redis_unavailable")
    else:
        redis = ReadinessCheck(status="failed", reason=type(redis_workers).__name__)
        workers = ReadinessCheck(status="failed", reason="redis_unavailable")

    report = ReadinessReport(
        checks={
            "startup": startup,
            "configuration": configuration,
            "database": database,
            "schema": schema,
            "redis": redis,
            "minio": minio,
            "workers": workers,
        }
    )
    await _record_readiness_metrics(report)
    return report
