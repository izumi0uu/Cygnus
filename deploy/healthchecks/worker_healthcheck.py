#!/usr/bin/env python3
"""Compose healthcheck for one Cygnus arq worker role (CYG-128).

Verifies, for the role given as argv[1] ("default" or "skills"):
  1. Redis is reachable (the worker queue dependency), and
  2. at least one live worker heartbeat for the role is fresh: state is not
     "stopped" and its timestamp is within WORKER_HEARTBEAT_TIMEOUT_SECONDS.

The heartbeat contract mirrors cygnus/runtime/readiness.py: keys are
cygnus:runtime:worker-heartbeat:v1:<role>:<identity> holding a JSON payload
with "state" and an ISO-8601 "timestamp". Workers publish "starting" ->
"ready" at startup and "draining"/"stopped" during shutdown, refreshing every
WORKER_HEARTBEAT_INTERVAL_SECONDS with a TTL of ~2x the timeout.

Reads the same settings/env as the runtime (redis_host/redis_port/
redis_password/redis_db/worker_heartbeat_timeout_seconds). Exits 0 when
healthy, 1 otherwise. Never writes anything.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone

import redis.asyncio as aioredis

HEARTBEAT_PREFIX = "cygnus:runtime:worker-heartbeat:v1"
ROLES = frozenset({"default", "skills"})


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value is None:
        value = os.environ.get(name.lower(), default)
    return value or default


async def _role_is_healthy(
    r: aioredis.Redis, role: str, timeout_seconds: float
) -> bool:
    pattern = f"{HEARTBEAT_PREFIX}:{role}:*"
    now = datetime.now(timezone.utc)
    async for key in r.scan_iter(match=pattern, count=100):
        raw = await r.get(key)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if payload.get("state") == "stopped":
            continue
        timestamp = payload.get("timestamp")
        if not timestamp:
            continue
        try:
            age = (now - datetime.fromisoformat(timestamp)).total_seconds()
        except (TypeError, ValueError):
            continue
        if age >= 0 and age <= timeout_seconds:
            return True
    return False


async def main() -> int:
    role = sys.argv[1] if len(sys.argv) > 1 else "default"
    if role not in ROLES:
        return 1

    host = _env("redis_host", "localhost")
    port = int(_env("redis_port", "6379"))
    password = _env("redis_password") or None
    db = int(_env("redis_db", "0"))
    timeout_seconds = float(_env("worker_heartbeat_timeout_seconds", "30"))

    r = aioredis.Redis(
        host=host,
        port=port,
        password=password,
        db=db,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    try:
        await r.ping()
    except Exception:
        return 1
    try:
        return 0 if await _role_is_healthy(r, role, timeout_seconds) else 1
    except Exception:
        return 1
    finally:
        await r.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
