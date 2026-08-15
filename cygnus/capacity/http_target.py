"""HTTP route targets for live staging runs of the capacity gate.

Every request is bounded (connect/read/write/pool timeouts capped) and the
fault endpoints are opt-in deployment wiring: without a declared fault
endpoint the target refuses injection, which the gate maps to
``injection_not_exercised`` (NOT_CERTIFIED) rather than a silent pass.
"""

from __future__ import annotations

import re
import time
from typing import Mapping

import httpx

from cygnus.capacity.inject import InjectionNotSupported
from cygnus.capacity.schema import InjectionTarget, Outcome

_MAX_REQUEST_TIMEOUT_SECONDS = 60.0
_MAX_FAULT_TIMEOUT_SECONDS = 10.0
_MAX_RETRIES = 3

_PROM_LINE_RE = re.compile(
    r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)"
    r"(?:\{(?P<labels>[^}]*)\})?\s+(?P<value>[-+0-9.eE]+)\s*$"
)
_LABEL_RE = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="([^"]*)"')


def _parse_prometheus_metrics(
    text: str,
) -> tuple[float | None, float | None, float | None]:
    """Extract queue age and DB pool saturation from Prometheus text.

    Only the fixed Cygnus metric families are recognized.  Unknown series and
    labels are ignored, so support content cannot become load evidence.
    """
    queue_age: float | None = None
    checked_out: float | None = None
    checked_in: float | None = None
    for line in text.splitlines():
        match = _PROM_LINE_RE.match(line.strip())
        if match is None:
            continue
        name = match.group("name")
        try:
            value = float(match.group("value"))
        except (TypeError, ValueError):
            continue
        if value < 0 or value != value or value in (float("inf"), float("-inf")):
            continue
        labels = {
            key: val for key, val in _LABEL_RE.findall(match.group("labels") or "")
        }
        if name == "cygnus_queue_job_age_seconds":
            queue_age = value if queue_age is None else max(queue_age, value)
        elif name == "cygnus_db_pool_connections":
            state = labels.get("state")
            if state == "checked_out":
                checked_out = value if checked_out is None else max(checked_out, value)
            elif state == "checked_in":
                checked_in = value if checked_in is None else max(checked_in, value)
    if checked_out is None or checked_in is None:
        return queue_age, None, None
    pool_size = checked_out + checked_in
    if pool_size <= 0:
        return queue_age, None, None
    return queue_age, checked_out, pool_size


class HttpRouteTarget:
    """Bounded HTTP driver for one staging route surface."""

    def __init__(
        self,
        *,
        url: str,
        method: str = "POST",
        headers: Mapping[str, str] | None = None,
        payload: object | None = None,
        timeout_seconds: float = 30.0,
        retries: int = 1,
        metrics_url: str | None = None,
        metrics_headers: Mapping[str, str] | None = None,
        fault_endpoints: Mapping[InjectionTarget, str] | None = None,
        fault_timeout_seconds: float = 10.0,
    ) -> None:
        if not url.strip():
            raise ValueError("url must not be blank")
        if not 0.0 < timeout_seconds <= _MAX_REQUEST_TIMEOUT_SECONDS:
            raise ValueError(
                f"timeout_seconds must be in (0, {_MAX_REQUEST_TIMEOUT_SECONDS:g}]"
            )
        if not 0 <= retries <= _MAX_RETRIES:
            raise ValueError(f"retries must be in [0, {_MAX_RETRIES}]")
        if not 0.0 < fault_timeout_seconds <= _MAX_FAULT_TIMEOUT_SECONDS:
            raise ValueError(
                f"fault_timeout_seconds must be in (0, {_MAX_FAULT_TIMEOUT_SECONDS:g}]"
            )
        self._url = url
        self._method = method
        self._headers = dict(headers or {})
        self._payload = payload
        self._timeout = httpx.Timeout(timeout_seconds)
        self._retries = retries
        self._metrics_url = metrics_url
        self._metrics_headers = dict(metrics_headers or {})
        self._fault_endpoints = dict(fault_endpoints or {})
        self._fault_timeout = httpx.Timeout(fault_timeout_seconds)
        self._client = httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=8),
        )

    async def close(self) -> None:
        await self._client.aclose()

    def supports_injection(self, target: InjectionTarget) -> bool:
        endpoint = self._fault_endpoints.get(target)
        return bool(endpoint and endpoint.strip())

    async def enable_failure(self, target: InjectionTarget) -> None:
        await self._toggle_fault(target, "on")

    async def disable_failure(self, target: InjectionTarget) -> None:
        await self._toggle_fault(target, "off")

    async def _toggle_fault(self, target: InjectionTarget, state: str) -> None:
        endpoint = self._fault_endpoints.get(target)
        if not endpoint or not endpoint.strip():
            raise InjectionNotSupported(f"no fault endpoint for target {target}")
        try:
            response = await self._client.request(
                "POST",
                endpoint,
                json={"target": target, "state": state},
                timeout=self._fault_timeout,
            )
        except httpx.HTTPError as exc:
            raise InjectionNotSupported(
                f"fault endpoint for {target} unreachable: {type(exc).__name__}"
            ) from exc
        if response.status_code >= 400:
            raise InjectionNotSupported(
                f"fault endpoint for {target} returned {response.status_code}"
            )

    async def _sample_metrics(self) -> tuple[float | None, float | None, float | None]:
        """Read JSON adapter metrics or the shipped Prometheus text surface."""
        if not self._metrics_url:
            return None, None, None
        try:
            response = await self._client.get(
                self._metrics_url, headers=self._metrics_headers
            )
            if not 200 <= response.status_code < 300:
                return None, None, None
            try:
                payload = response.json()
            except ValueError:
                return _parse_prometheus_metrics(response.text)
        except httpx.HTTPError:
            return None, None, None
        if not isinstance(payload, dict):
            return _parse_prometheus_metrics(str(payload))
        try:
            queue_age = float(payload["queue_age_seconds"])
            saturation = float(payload["pool_saturation"])
        except (KeyError, TypeError, ValueError):
            return None, None, None
        if (
            queue_age < 0
            or saturation < 0.0
            or saturation > 1.0
            or queue_age != queue_age
            or saturation != saturation
        ):
            return None, None, None
        # RouteSample stores saturation as in_use/size; keep the fraction with size 1.
        return queue_age, saturation, 1.0

    async def execute(
        self,
    ) -> tuple[float, Outcome, float | None, float | None, float | None]:
        started = time.monotonic()
        outcome: Outcome = "error"
        status: int | None = None
        for attempt in range(self._retries + 1):
            try:
                response = await self._client.request(
                    self._method,
                    self._url,
                    headers=self._headers,
                    json=self._payload,
                )
                status = response.status_code
            except httpx.HTTPError:
                status = None
            if status is not None and 200 <= status < 300:
                outcome = "retry" if attempt > 0 else "success"
                break
            if attempt >= self._retries:
                outcome = "denied" if status == 429 else "error"
                break
            if status in (429, None) or (status is not None and status >= 500):
                continue
            outcome = "denied" if status == 429 else "error"
            break
        duration_ms = (time.monotonic() - started) * 1000.0
        queue_age, pool_in_use, pool_size = await self._sample_metrics()
        return duration_ms, outcome, queue_age, pool_in_use, pool_size
