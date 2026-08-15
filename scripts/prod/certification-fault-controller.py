#!/usr/bin/env python3
"""Loopback-only controller for isolated candidate dependency faults."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import os
import subprocess
import time
import threading
from typing import ClassVar, Protocol, cast
from typing_extensions import override
import httpx
import redis

from cygnus.capacity.http_target import parse_prometheus_metrics
from cygnus.capacity.schema import ROUTES, RouteId

TARGETS = frozenset({"db", "queue", "tool", "provider"})


class QueueRedis(Protocol):
    def zrange(
        self, name: str, start: int, end: int, *, withscores: bool
    ) -> list[tuple[bytes, float]]: ...

    def close(self) -> None: ...


class Controller(ThreadingHTTPServer):
    stack: Path = Path()
    release: str = ""
    origin: str = ""
    ca_file: Path = Path()
    receipt_path: Path = Path()
    redis_port: int = 0
    _token: str | None = None
    _token_lock: ClassVar[threading.Lock] = threading.Lock()

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.origin,
            verify=str(self.ca_file),
            timeout=10.0,
        )

    def _authorization(self, client: httpx.Client) -> str:
        with self._token_lock:
            if self._token is None:
                response = client.post(
                    "/api/auth/login",
                    json={
                        "email": os.environ.get("DEFAULT_ADMIN_EMAIL", ""),
                        "password": os.environ.get("DEFAULT_ADMIN_PASSWORD", ""),
                    },
                )
                _ = response.raise_for_status()
                decoded = cast(object, response.json())
                if not isinstance(decoded, dict):
                    raise RuntimeError("candidate login returned a non-object")
                login = cast(dict[str, object], decoded)
                token = login.get("access_token")
                if not isinstance(token, str) or not token:
                    raise RuntimeError("candidate login returned no access token")
                self._token = token
            return f"Bearer {self._token}"

    def exercise_route(self, route: RouteId) -> int:
        decoded = cast(
            object, json.loads(self.receipt_path.read_text(encoding="utf-8"))
        )
        if not isinstance(decoded, dict):
            raise RuntimeError("governance receipt is not an object")
        receipt = cast(dict[str, object], decoded)
        with self._client() as client:
            readiness = client.get("/readyz")
            if not 200 <= readiness.status_code < 300:
                return readiness.status_code
            headers = {"Authorization": self._authorization(client)}
            if route == "publish":
                response = client.get(
                    "/api/publish-propagation",
                    params={"publication_id": str(receipt["publication_id"])},
                    headers=headers,
                )
            elif route == "ticket_import":
                response = client.get(
                    "/api/governance/ticket-pilot",
                    params={"source_ref": f"certification:{receipt['run_id']}"},
                    headers=headers,
                )
            elif route == "ingestion":
                response = client.get(
                    f"/api/sources/{receipt['source_id']}", headers=headers
                )
            elif route == "worker":
                response = client.get(
                    f"/api/recovery/{receipt['command_id']}", headers=headers
                )
            else:
                response = client.post(
                    "/api/session-bridge/query",
                    headers={
                        **headers,
                        "X-Cygnus-Session-Contract-Version": "1.0",
                    },
                    json={
                        "request_ref": f"capacity:{time.time_ns()}",
                        "session_ref": f"capacity:{receipt['run_id']}",
                        "query": "durable billing support policy",
                        "channel": "agent-copilot",
                        "audience_context": {
                            "visibility": "internal",
                            "product_line": "billing",
                            "region": "global",
                            "language": "en",
                        },
                    },
                )
            return response.status_code

    def capacity_metrics(self) -> dict[str, float]:
        with self._client() as candidate:
            response = candidate.get("/metrics")
        _ = response.raise_for_status()
        _, pool_in_use, pool_size = parse_prometheus_metrics(response.text)
        if pool_in_use is None or pool_size is None or pool_size <= 0:
            raise RuntimeError("candidate did not expose measured database pool state")
        client = cast(
            QueueRedis,
            cast(
                object,
                redis.Redis(
                    host="127.0.0.1",
                    port=self.redis_port,
                    password=os.environ.get("REDIS_PASSWORD") or None,
                    db=0,
                    socket_timeout=3,
                ),
            ),
        )
        oldest_age = 0.0
        now_ms = time.time() * 1000.0
        for queue in ("arq:queue", "skills_queue"):
            entries = client.zrange(queue, 0, 0, withscores=True)
            if entries:
                oldest_age = max(
                    oldest_age,
                    max((now_ms - entries[0][1]) / 1000.0, 0.0),
                )
        client.close()
        return {
            "queue_age_seconds": oldest_age,
            "pool_saturation": pool_in_use / pool_size,
        }


class Handler(BaseHTTPRequestHandler):
    @property
    def controller(self) -> Controller:
        if not isinstance(self.server, Controller):
            raise RuntimeError("fault handler is not bound to a Controller")
        return self.server

    @override
    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        if self.path.startswith("/route/"):
            route_name = self.path.removeprefix("/route/")
            if route_name not in ROUTES:
                self.send_error(404)
                return
            try:
                status_code = self.controller.exercise_route(route_name)
            except (
                OSError,
                KeyError,
                json.JSONDecodeError,
                httpx.HTTPError,
                RuntimeError,
                ValueError,
            ):
                status_code = 503
            body = json.dumps(
                {"route": route_name, "candidate_status": status_code}, sort_keys=True
            ).encode()
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            _ = self.wfile.write(body)
            return
        if self.path != "/metrics":
            self.send_error(404)
            return
        try:
            payload = self.controller.capacity_metrics()
        except (httpx.HTTPError, redis.RedisError, RuntimeError, ValueError):
            self.send_error(503)
            return
        body = json.dumps(payload, sort_keys=True).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        _ = self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path != "/fault":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(400)
            return
        if length < 2 or length > 1024:
            self.send_error(400)
            return
        try:
            decoded = cast(object, json.loads(self.rfile.read(length)))
        except json.JSONDecodeError:
            self.send_error(400)
            return
        if not isinstance(decoded, dict):
            self.send_error(400)
            return
        payload = cast(dict[str, object], decoded)
        target = payload.get("target")
        state = payload.get("state")
        if target not in TARGETS or state not in {"on", "off"}:
            self.send_error(400)
            return
        action = "fault-on" if state == "on" else "fault-off"
        result = subprocess.run(
            [
                str(self.controller.stack),
                action,
                "--release",
                self.controller.release,
                "--target",
                target,
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            _ = self.wfile.write(
                json.dumps({"status": "failed", "target": target}).encode()
            )
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        _ = self.wfile.write(json.dumps({"status": state, "target": target}).encode())


class Args(argparse.Namespace):
    def __init__(self) -> None:
        super().__init__()
        self.port: int = 19090
        self.stack: Path = Path()
        self.release: str = ""
        self.origin: str = ""
        self.ca_file: Path = Path()
        self.receipt_path: Path = Path()
        self.redis_port: int = 16379


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--port", type=int, default=19090)
    _ = parser.add_argument("--stack", type=Path, required=True)
    _ = parser.add_argument("--release", required=True)
    _ = parser.add_argument("--origin", required=True)
    _ = parser.add_argument("--ca-file", type=Path, required=True)
    _ = parser.add_argument("--receipt-path", type=Path, required=True)
    _ = parser.add_argument("--redis-port", type=int, default=16379)
    args = parser.parse_args(namespace=Args())
    server = Controller(("127.0.0.1", args.port), Handler)
    server.stack = args.stack
    server.release = args.release
    server.origin = args.origin.rstrip("/")
    server.ca_file = args.ca_file
    server.receipt_path = args.receipt_path
    server.redis_port = args.redis_port
    server.serve_forever()


if __name__ == "__main__":
    main()
