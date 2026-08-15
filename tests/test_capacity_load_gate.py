"""Deterministic report-shape tests for the CYG-142 capacity load gate.

These tests never execute load and never contact staging: they exercise
the pure metric/threshold/report logic with synthetic samples and replay
files, so the machine-readable report shape is pinned exactly as CI will
retain it. Threshold values here are test fixtures, not gate defaults --
the gate itself never invents pass numbers.
"""

from __future__ import annotations

import asyncio
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from typing import cast
from unittest.mock import AsyncMock, patch

import httpx

from cygnus.capacity.gate import build_blocked_report, build_route_result, run_load_gate
from cygnus.capacity.http_target import HttpRouteTarget
from cygnus.capacity.inject import RecoveryEvidence
from cygnus.capacity.load import PhaseResult
from cygnus.capacity.metrics import RouteSample, percentile, summarize_samples
from cygnus.capacity.report import EvidenceRefs, ReleaseRefs
from cygnus.capacity.schema import (
    APPROVAL_REFS_MISMATCH,
    APPROVAL_REFS_MISSING,
    GATE_FAIL,
    GATE_NOT_CERTIFIED,
    GATE_PASS,
    INJECTION_NOT_EXERCISED,
    InjectionTarget,
    METRICS,
    Outcome,
    RECOVERY_NOT_OBSERVED,
    RELEASE_REFS_MISSING,
    ROUTE_NOT_MEASURED,
    ROUTES,
    RouteId,
    THRESHOLDS_MISSING,
    THRESHOLD_VIOLATION,
)
from cygnus.capacity.thresholds import (
    CapacityThresholds,
    ThresholdInputError,
    threshold_schema,
)

RELEASED_AT = "2026-08-12T00:00:00+00:00"
UNSET_RUNTIME_IDENTITY_ENV = {
    "APP_COMMIT_SHA": "",
    "CYGNUS_COMMIT_SHA": "",
    "GIT_SHA": "",
    "APP_IMAGE_REF": "",
    "CYGNUS_IMAGE_REF": "",
    "IMAGE_REF": "",
    "EXPECTED_ALEMBIC_HEAD": "",
}


def _thresholds_dict(**overrides):
    base = {
        "environment": "staging",
        "approval": {
            "approval_ref": "cyg-144:capacity-approval:test",
            "thresholds_ref": "cyg-144:capacity-thresholds:test",
            "targets_ref": "cyg-144:capacity-targets:test",
        },
        "thresholds": {
            route: {
                metric: (
                    {"value": 1.0} if metric == "throughput_rps" else {"value": 1000.0}
                )
                for metric in METRICS
            }
            for route in ROUTES
        },
        "alert_rule_mappings": {
            f"{route}.{metric}": f"ALERT-142-{route.upper()}-{metric.upper()}"
            for route in ROUTES
            for metric in METRICS
        },
        "failure_injection": {"enabled": False},
        "load_profile": {
            "routes": {
                route: {
                    "concurrency": 2,
                    "duration_seconds": 20.0,
                    "max_requests": 100,
                }
                for route in ROUTES
            }
        },
    }
    base.update(overrides)
    return base


def _thresholds(**overrides) -> CapacityThresholds:
    return CapacityThresholds.model_validate(_thresholds_dict(**overrides))


def _injection_thresholds_dict() -> dict:
    base = _thresholds_dict()
    base["failure_injection"] = {
        "enabled": True,
        "route_targets": {
            "publish": "provider",
            "ticket_import": "db",
            "ingestion": "queue",
            "worker": "tool",
        },
        "duration_seconds": 5.0,
        "post_recovery_seconds": 3.0,
        "max_recovery_seconds": 30.0,
    }
    return base


def _injection_thresholds(**overrides) -> CapacityThresholds:
    base = _injection_thresholds_dict()
    base.update(overrides)
    return CapacityThresholds.model_validate(base)


def _release() -> ReleaseRefs:
    return ReleaseRefs(
        commit_sha="a" * 40,
        image_tag="cygnus:test",
        alembic_revision="rev1",
        app_version="0.1.0-test",
    )


def _evidence() -> EvidenceRefs:
    return EvidenceRefs(
        run_id="test-run",
        report_path="report.json",
        samples_path="samples.json",
    )


def _recovery(
    target: InjectionTarget,
    *,
    recovered: bool = True,
    recovery_seconds: float | None = 0.5,
    post_error: float = 0.0,
    failures: int = 2,
) -> RecoveryEvidence:
    return RecoveryEvidence(
        target=target,
        injected=True,
        window_seconds=5.0,
        failures_during_window=failures,
        recovery_seconds=recovery_seconds,
        post_recovery_error_rate=post_error,
        recovered=recovered,
        detail=f"observed fault on {target}",
    )


def _phase(
    route: RouteId,
    *,
    recovery: RecoveryEvidence | None = None,
    outcomes: tuple[Outcome, ...] | None = None,
    with_queue_pool: bool = True,
) -> PhaseResult:
    outcomes = outcomes or ("success",) * 10
    samples = tuple(
        RouteSample(
            started_at=index * 0.1,
            duration_ms=10.0 + index,
            outcome=outcome,
            queue_age_seconds=0.1 if with_queue_pool else None,
            pool_in_use=2 if with_queue_pool else None,
            pool_size=10 if with_queue_pool else None,
        )
        for index, outcome in enumerate(outcomes)
    )
    return PhaseResult(
        route=route,
        wall_seconds=1.0,
        samples=samples,
        recovery=recovery,
    )


def _pass_phases() -> dict[RouteId, PhaseResult]:
    return {
        "publish": _phase("publish", recovery=_recovery("provider")),
        "ticket_import": _phase("ticket_import", recovery=_recovery("db")),
        "ingestion": _phase("ingestion", recovery=_recovery("queue")),
        "worker": _phase("worker", recovery=_recovery("tool")),
        "query": _phase("query"),
    }


def _run(
    thresholds: CapacityThresholds | None,
    phases: dict[RouteId, PhaseResult] | None,
    *,
    confirmed: bool = True,
    released_at: str = RELEASED_AT,
):
    report, _ = asyncio.run(
        run_load_gate(
            thresholds=thresholds,
            thresholds_path="thresholds.json",
            thresholds_sha256="0" * 64,
            release=_release(),
            evidence=_evidence(),
            replay_phases=phases,
            injection_confirmed=confirmed,
            released_at=released_at,
        )
    )
    return report


def _load_gate_cli():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "load_gate.py"
    spec = importlib.util.spec_from_file_location("load_gate", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ThresholdsTests(unittest.TestCase):
    def test_valid_config_round_trips_through_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "thresholds.json")
            Path(path).write_text(
                json.dumps(_injection_thresholds().model_dump(mode="json")),
                encoding="utf-8",
            )
            loaded = CapacityThresholds.from_file(path)
            self.assertEqual(
                loaded.fingerprint(), _injection_thresholds().fingerprint()
            )

    def test_fingerprint_is_stable(self) -> None:
        thresholds = _thresholds()
        self.assertEqual(thresholds.fingerprint(), thresholds.fingerprint())

    def test_missing_thresholds_section_is_blocked(self) -> None:
        config = _thresholds_dict()
        del config["thresholds"]
        with self.assertRaises(ThresholdInputError):
            _thresholds_from(config)

    def test_missing_cyg_144_approval_binding_is_blocked(self) -> None:
        config = _thresholds_dict()
        del config["approval"]
        with self.assertRaises(ThresholdInputError):
            _thresholds_from(config)

    def test_unknown_metric_is_blocked(self) -> None:
        config = _thresholds_dict()
        config["thresholds"]["query"]["p999_ms"] = {"value": 1.0}
        with self.assertRaises(ThresholdInputError):
            _thresholds_from(config)

    def test_missing_alert_mapping_is_blocked(self) -> None:
        config = _thresholds_dict()
        del config["alert_rule_mappings"]["query.p95_ms"]
        with self.assertRaises(ThresholdInputError):
            _thresholds_from(config)

    def test_unknown_alert_mapping_is_blocked(self) -> None:
        config = _thresholds_dict()
        config["alert_rule_mappings"]["query.p999_ms"] = "ALERT-142-bogus"
        with self.assertRaises(ThresholdInputError):
            _thresholds_from(config)

    def test_blank_alert_rule_id_is_blocked(self) -> None:
        config = _thresholds_dict()
        config["alert_rule_mappings"]["query.p95_ms"] = "  "
        with self.assertRaises(ThresholdInputError):
            _thresholds_from(config)

    def test_throughput_defaults_to_gte_and_latency_to_lte(self) -> None:
        thresholds = _thresholds()
        self.assertEqual(
            thresholds.thresholds["query"]
            .threshold_for("throughput_rps")
            .resolved_comparator("throughput_rps"),
            "gte",
        )
        self.assertEqual(
            thresholds.thresholds["query"]
            .threshold_for("p95_ms")
            .resolved_comparator("p95_ms"),
            "lte",
        )

    def test_explicit_comparator_override(self) -> None:
        config = _thresholds_dict()
        config["thresholds"]["query"]["p95_ms"] = {"value": 50.0, "comparator": "gte"}
        thresholds = _thresholds_from(config)
        self.assertEqual(
            thresholds.thresholds["query"]
            .threshold_for("p95_ms")
            .resolved_comparator("p95_ms"),
            "gte",
        )

    def test_injection_requires_recovery_slo(self) -> None:
        config = _thresholds_dict()
        config["failure_injection"] = {
            "enabled": True,
            "route_targets": {
                "publish": "provider",
                "ticket_import": "db",
                "ingestion": "queue",
                "worker": "tool",
            },
        }
        with self.assertRaises(ThresholdInputError):
            _thresholds_from(config)

    def test_injection_requires_all_targets(self) -> None:
        config = _thresholds_dict()
        config["failure_injection"] = {
            "enabled": True,
            "route_targets": {
                "publish": "provider",
                "ticket_import": "db",
                "ingestion": "queue",
            },
            "duration_seconds": 5.0,
            "post_recovery_seconds": 3.0,
            "max_recovery_seconds": 30.0,
        }
        with self.assertRaises(ThresholdInputError):
            _thresholds_from(config)

    def test_short_route_duration_for_injection_is_blocked(self) -> None:
        config = _thresholds_dict()
        config["load_profile"]["routes"]["publish"]["duration_seconds"] = 5.0
        config["failure_injection"] = {
            "enabled": True,
            "route_targets": {
                "publish": "provider",
                "ticket_import": "db",
                "ingestion": "queue",
                "worker": "tool",
            },
            "duration_seconds": 5.0,
            "post_recovery_seconds": 3.0,
            "max_recovery_seconds": 30.0,
        }
        with self.assertRaises(ThresholdInputError):
            _thresholds_from(config)

    def test_load_budget_over_hard_cap_is_blocked(self) -> None:
        config = _thresholds_dict()
        for route in ROUTES:
            config["load_profile"]["routes"][route]["duration_seconds"] = 300.0
        with self.assertRaises(ThresholdInputError):
            _thresholds_from(config)

    def test_non_staging_environment_is_blocked(self) -> None:
        config = _thresholds_dict()
        config["environment"] = "production"
        with self.assertRaises(ThresholdInputError):
            _thresholds_from(config)

    def test_threshold_schema_is_machine_readable(self) -> None:
        schema = threshold_schema()
        self.assertIsInstance(schema, dict)
        properties = schema["properties"]
        for section in (
            "thresholds",
            "alert_rule_mappings",
            "failure_injection",
            "load_profile",
        ):
            self.assertIn(section, properties)
        self.assertEqual(schema["properties"]["environment"]["default"], "staging")


class HttpTargetMetricsTests(unittest.IsolatedAsyncioTestCase):
    async def test_shipped_prometheus_text_yields_queue_and_pool_measurements(
        self,
    ) -> None:
        target = HttpRouteTarget(
            url="https://staging.example.test/api/query",
            metrics_url="https://staging.example.test/metrics",
        )
        response = httpx.Response(
            200,
            text=(
                "# HELP cygnus_queue_job_age_seconds Oldest queue age.\n"
                'cygnus_queue_job_age_seconds{queue="source_dispatch"} 12.5\n'
                'cygnus_queue_job_age_seconds{queue="arq:queue"} 4\n'
                'cygnus_db_pool_connections{pool="primary",state="checked_out"} 6\n'
                'cygnus_db_pool_connections{pool="primary",state="checked_in"} 14\n'
            ),
            headers={"content-type": "text/plain; version=0.0.4"},
            request=httpx.Request("GET", "https://staging.example.test/metrics"),
        )
        target._client.get = AsyncMock(return_value=response)  # type: ignore[method-assign]

        queue_age, pool_in_use, pool_size = await target._sample_metrics()

        self.assertEqual(queue_age, 12.5)
        self.assertEqual(pool_in_use, 6.0)
        self.assertEqual(pool_size, 20.0)
        await target.close()

    async def test_failed_metrics_scrape_is_unmeasured(self) -> None:
        target = HttpRouteTarget(
            url="https://staging.example.test/api/query",
            metrics_url="https://staging.example.test/metrics",
        )
        response = httpx.Response(
            503,
            text='cygnus_queue_job_age_seconds{queue="source_dispatch"} 12.5\n',
            request=httpx.Request("GET", "https://staging.example.test/metrics"),
        )
        target._client.get = AsyncMock(return_value=response)  # type: ignore[method-assign]

        self.assertEqual(await target._sample_metrics(), (None, None, None))
        await target.close()


class MetricsTests(unittest.TestCase):
    def test_percentile_nearest_rank(self) -> None:
        values = [10.0, 20.0, 30.0, 40.0, 50.0]
        self.assertEqual(percentile(values, 50.0), 30.0)
        self.assertEqual(percentile(values, 95.0), 50.0)
        self.assertEqual(percentile(values, 99.0), 50.0)
        self.assertEqual(percentile([1.0, 2.0, 3.0], 95.0), 3.0)

    def test_percentile_single_sample(self) -> None:
        self.assertEqual(percentile([7.0], 50.0), 7.0)

    def test_percentile_empty_raises(self) -> None:
        with self.assertRaises(ValueError):
            percentile([], 50.0)

    def test_summarize_rates_and_throughput(self) -> None:
        outcomes: tuple[Outcome, ...] = (
            "success",
            "success",
            "success",
            "success",
            "success",
            "success",
            "success",
            "error",
            "denied",
            "retry",
        )
        summary = summarize_samples(
            [
                RouteSample(started_at=i, duration_ms=10.0, outcome=outcome)
                for i, outcome in enumerate(outcomes)
            ],
            wall_seconds=10.0,
        )
        self.assertEqual(summary.samples, 10)
        self.assertEqual(summary.error_rate, 0.1)
        self.assertEqual(summary.denial_rate, 0.1)
        self.assertEqual(summary.retry_rate, 0.1)
        self.assertEqual(summary.throughput_rps, 1.0)
        self.assertEqual(summary.p50_ms, 10.0)

    def test_summarize_queue_age_and_pool_saturation(self) -> None:
        samples = tuple(
            RouteSample(
                started_at=i,
                duration_ms=10.0,
                outcome="success",
                queue_age_seconds=0.2,
                pool_in_use=2.0,
                pool_size=10.0,
            )
            for i in range(5)
        )
        summary = summarize_samples(samples, wall_seconds=1.0)
        self.assertEqual(summary.queue_age_seconds, 0.2)
        self.assertEqual(summary.pool_saturation, 0.2)
        self.assertEqual(summary.recovery_seconds, None)

    def test_summarize_absent_queue_pool_is_none(self) -> None:
        samples = (RouteSample(started_at=0.0, duration_ms=10.0, outcome="success"),)
        summary = summarize_samples(samples, wall_seconds=1.0)
        self.assertIsNone(summary.queue_age_seconds)
        self.assertIsNone(summary.pool_saturation)

    def test_summarize_empty_raises(self) -> None:
        with self.assertRaises(ValueError):
            summarize_samples([], wall_seconds=1.0)

    def test_route_sample_validation(self) -> None:
        with self.assertRaises(ValueError):
            RouteSample(started_at=0.0, duration_ms=-1.0, outcome="success")
        with self.assertRaises(ValueError):
            RouteSample(
                started_at=0.0,
                duration_ms=1.0,
                outcome=cast(Outcome, "bogus"),
            )
        with self.assertRaises(ValueError):
            RouteSample(
                started_at=0.0,
                duration_ms=1.0,
                outcome=cast(Outcome, "bogus"),
                pool_in_use=1.0,
            )

    def test_route_sample_round_trip(self) -> None:
        sample = RouteSample(
            started_at=0.5,
            duration_ms=12.5,
            outcome="retry",
            queue_age_seconds=0.3,
            pool_in_use=1.0,
            pool_size=4.0,
        )
        self.assertEqual(sample, RouteSample.from_dict(sample.to_dict()))


class ReportShapeTests(unittest.TestCase):
    def test_pass_report_shape(self) -> None:
        report = _run(_injection_thresholds(), _pass_phases())
        self.assertEqual(report.status, GATE_PASS)
        self.assertEqual(report.reasons, ())
        payload = json.loads(json.dumps(report.to_dict()))
        self.assertEqual(
            set(payload),
            {
                "suite_name",
                "status",
                "environment",
                "released_at",
                "application",
                "release",
                "config",
                "evidence",
                "alert_rule_mappings",
                "totals",
                "routes",
                "failure_injection",
                "reasons",
            },
        )
        self.assertEqual(payload["suite_name"], "cygnus-production-capacity-gate")
        self.assertEqual(payload["application"]["name"], "cygnus")
        self.assertEqual(payload["release"]["commit_sha"], "a" * 40)
        self.assertEqual(payload["config"]["thresholds_sha256"], "0" * 64)
        self.assertEqual(payload["totals"]["routes"], 5)
        self.assertEqual(payload["totals"]["measured_routes"], 5)
        self.assertEqual(payload["totals"]["passed_routes"], 5)
        self.assertEqual(payload["totals"]["failed_checks"], 0)
        self.assertEqual(payload["totals"]["unmeasured_checks"], 0)
        self.assertEqual(
            [route["route"] for route in payload["routes"]],
            ["ingestion", "publish", "query", "ticket_import", "worker"],
        )
        for route in payload["routes"]:
            self.assertEqual(route["status"], GATE_PASS)
            self.assertEqual(len(route["checks"]), 9)
            self.assertEqual(
                [check["metric"] for check in route["checks"]],
                sorted(check["metric"] for check in route["checks"]),
            )
            self.assertTrue(all(check["passed"] for check in route["checks"]))
            self.assertTrue(
                all(
                    check["alert_rule"].startswith("ALERT-142-")
                    for check in route["checks"]
                )
            )
        self.assertEqual(
            payload["failure_injection"]["exercised_targets"],
            ["db", "provider", "queue", "tool"],
        )
        self.assertTrue(payload["failure_injection"]["recovered_all"])
        self.assertEqual(payload["reasons"], [])

    def test_measured_checks_emit_approval_bound_breach_metrics(self) -> None:
        thresholds = _injection_thresholds()
        with patch("cygnus.capacity.gate.record_capacity_gate_breach") as record:
            report = _run(thresholds, _pass_phases())

        self.assertEqual(report.status, GATE_PASS)
        self.assertEqual(record.call_count, len(ROUTES) * len(METRICS))
        first = record.call_args_list[0].kwargs
        self.assertEqual(first["approval_ref"], thresholds.approval.approval_ref)
        self.assertEqual(first["thresholds_ref"], thresholds.approval.thresholds_ref)
        self.assertEqual(first["targets_ref"], thresholds.approval.targets_ref)
        self.assertEqual(
            first["thresholds_fingerprint"],
            thresholds.fingerprint(),
        )

    def test_report_is_replay_deterministic(self) -> None:
        first = _run(_injection_thresholds(), _pass_phases())
        second = _run(_injection_thresholds(), _pass_phases())
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(
            json.dumps(first.to_dict(), sort_keys=False),
            json.dumps(second.to_dict(), sort_keys=False),
        )

    def test_threshold_violation_fails(self) -> None:
        config = _injection_thresholds_dict()
        config["thresholds"]["query"]["p95_ms"] = {"value": 5.0}
        thresholds = _thresholds_from(config)
        report = _run(thresholds, _pass_phases())
        self.assertEqual(report.status, GATE_FAIL)
        self.assertIn(f"{THRESHOLD_VIOLATION}:query.p95_ms", report.reasons)
        query = next(route for route in report.routes if route.route == "query")
        p95_check = next(check for check in query.checks if check.metric == "p95_ms")
        self.assertFalse(p95_check.passed)
        self.assertEqual(p95_check.value, 19.0)
        self.assertEqual(p95_check.alert_rule, "ALERT-142-QUERY-P95_MS")
        self.assertEqual(report.totals["failed_routes"], 1)
        self.assertGreaterEqual(report.totals["failed_checks"], 1)

    def test_unmeasured_route_is_not_certified(self) -> None:
        phases = _pass_phases()
        del phases["query"]
        report = _run(_injection_thresholds(), phases)
        self.assertEqual(report.status, GATE_NOT_CERTIFIED)
        self.assertIn(f"{ROUTE_NOT_MEASURED}:query", report.reasons)
        self.assertEqual(report.totals["measured_routes"], 4)
        self.assertEqual(report.totals["not_certified_routes"], 1)

    def test_injection_without_runtime_confirmation_is_not_certified(self) -> None:
        report = _run(_injection_thresholds(), _pass_phases(), confirmed=False)
        self.assertEqual(report.status, GATE_NOT_CERTIFIED)
        self.assertIn(INJECTION_NOT_EXERCISED, report.reasons)
        self.assertFalse(report.failure_injection.guard_allowed)

    def test_unexercised_injection_target_is_not_certified(self) -> None:
        phases = _pass_phases()
        phases["worker"] = _phase("worker")  # drop the tool recovery evidence
        report = _run(_injection_thresholds(), phases)
        self.assertEqual(report.status, GATE_NOT_CERTIFIED)
        self.assertIn(f"{INJECTION_NOT_EXERCISED}:tool", report.reasons)

    def test_unrecovered_dependency_fails(self) -> None:
        phases = _pass_phases()
        phases["ticket_import"] = _phase(
            "ticket_import",
            recovery=_recovery("db", recovered=False, recovery_seconds=None),
        )
        report = _run(_injection_thresholds(), phases)
        self.assertEqual(report.status, GATE_FAIL)
        self.assertIn(f"{RECOVERY_NOT_OBSERVED}:db", report.reasons)

    def test_injection_without_observed_impact_fails(self) -> None:
        phases = _pass_phases()
        phases["ticket_import"] = _phase(
            "ticket_import",
            recovery=_recovery("db", failures=0),
        )
        report = _run(_injection_thresholds(), phases)
        self.assertEqual(report.status, GATE_FAIL)
        self.assertIn(f"{RECOVERY_NOT_OBSERVED}:db", report.reasons)

    def test_recovery_slo_exceeded_fails(self) -> None:
        phases = _pass_phases()
        phases["ingestion"] = _phase(
            "ingestion",
            recovery=_recovery("queue", recovered=True, recovery_seconds=45.0),
        )
        report = _run(_injection_thresholds(), phases)
        self.assertEqual(report.status, GATE_FAIL)
        self.assertIn(f"{RECOVERY_NOT_OBSERVED}:queue", report.reasons)

    def test_missing_release_refs_blocked(self) -> None:
        report = build_blocked_report(
            reasons=[RELEASE_REFS_MISSING],
            environment="staging",
            released_at=RELEASED_AT,
            release=None,
            config=None,
            evidence=_evidence(),
        )
        self.assertEqual(report.status, GATE_NOT_CERTIFIED)
        self.assertEqual(report.routes, ())
        self.assertIsNone(report.release)
        self.assertIsNone(report.config)
        self.assertEqual(report.totals["routes"], 0)
        self.assertEqual(report.reasons, (RELEASE_REFS_MISSING,))

    def test_missing_thresholds_blocked(self) -> None:
        report = _run(None, None)
        self.assertEqual(report.status, GATE_NOT_CERTIFIED)
        self.assertIn(THRESHOLDS_MISSING, report.reasons)

    def test_build_route_result_shape(self) -> None:
        thresholds = _injection_thresholds()
        result = build_route_result(
            "query",
            _phase("query"),
            thresholds.thresholds["query"],
            thresholds.alert_rule_mappings,
        )
        self.assertTrue(result.measured)
        self.assertEqual(result.status, GATE_PASS)
        self.assertEqual(len(result.checks), 9)
        unmeasured = build_route_result(
            "query",
            None,
            thresholds.thresholds["query"],
            thresholds.alert_rule_mappings,
        )
        self.assertFalse(unmeasured.measured)
        self.assertEqual(unmeasured.status, GATE_NOT_CERTIFIED)
        self.assertEqual(unmeasured.checks, ())

    def test_json_round_trip_of_pass_report(self) -> None:
        report = _run(_injection_thresholds(), _pass_phases())
        payload = json.loads(json.dumps(report.to_dict()))
        self.assertEqual(payload["status"], GATE_PASS)
        self.assertEqual(len(payload["routes"]), 5)


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.load_gate = _load_gate_cli()

    def test_missing_release_refs_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            thresholds_path = os.path.join(tmp, "thresholds.json")
            Path(thresholds_path).write_text(
                json.dumps(_thresholds_dict()), encoding="utf-8"
            )
            report_path = os.path.join(tmp, "report.json")
            status = self.load_gate.main(
                ["--thresholds", thresholds_path, "--report-out", report_path]
            )
            self.assertEqual(status, self.load_gate.EXIT_BLOCKED)
            report = json.loads(Path(report_path).read_text(encoding="utf-8"))
            self.assertEqual(report["status"], GATE_NOT_CERTIFIED)
            self.assertIn(RELEASE_REFS_MISSING, report["reasons"])
            self.assertIn("run_inputs_missing", report["reasons"])

    def test_missing_thresholds_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_path = os.path.join(tmp, "report.json")
            status = self.load_gate.main(
                [
                    "--commit-sha",
                    "a" * 40,
                    "--image-tag",
                    "cygnus:test",
                    "--alembic-revision",
                    "rev1",
                    "--report-out",
                    report_path,
                ]
            )
            self.assertEqual(status, self.load_gate.EXIT_BLOCKED)
            report = json.loads(Path(report_path).read_text(encoding="utf-8"))
            self.assertIn(THRESHOLDS_MISSING, report["reasons"])

    def test_invalid_thresholds_file_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            thresholds_path = os.path.join(tmp, "thresholds.json")
            Path(thresholds_path).write_text("{not json", encoding="utf-8")
            report_path = os.path.join(tmp, "report.json")
            status = self.load_gate.main(
                [
                    "--thresholds",
                    thresholds_path,
                    "--commit-sha",
                    "a" * 40,
                    "--image-tag",
                    "cygnus:test",
                    "--alembic-revision",
                    "rev1",
                    "--report-out",
                    report_path,
                ]
            )
            self.assertEqual(status, self.load_gate.EXIT_BLOCKED)
            report = json.loads(Path(report_path).read_text(encoding="utf-8"))
            self.assertIn(THRESHOLDS_MISSING, report["reasons"])

    def test_blocked_report_printed_to_stdout_is_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            thresholds_path = os.path.join(tmp, "thresholds.json")
            Path(thresholds_path).write_text(
                json.dumps(_thresholds_dict()), encoding="utf-8"
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                status = self.load_gate.main(["--thresholds", thresholds_path])
            self.assertEqual(status, self.load_gate.EXIT_BLOCKED)
            payload = json.loads(buffer.getvalue())
            self.assertEqual(payload["status"], GATE_NOT_CERTIFIED)

    def test_replay_pass_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            thresholds_path = os.path.join(tmp, "thresholds.json")
            Path(thresholds_path).write_text(
                json.dumps(_injection_thresholds().model_dump(mode="json")),
                encoding="utf-8",
            )
            samples_path = os.path.join(tmp, "samples.json")
            Path(samples_path).write_text(
                json.dumps(
                    {
                        "suite_name": "cygnus-capacity-gate-samples",
                        "phases": {
                            route: phase.to_dict()
                            for route, phase in _pass_phases().items()
                        },
                    }
                ),
                encoding="utf-8",
            )
            report_path = os.path.join(tmp, "report.json")
            with patch.dict(
                os.environ,
                {**UNSET_RUNTIME_IDENTITY_ENV, "CYGNUS_CAPACITY_GATE_INJECTION": "1"},
            ):
                status = self.load_gate.main(
                    [
                        "--thresholds",
                        thresholds_path,
                        "--replay-samples",
                        samples_path,
                        "--commit-sha",
                        "a" * 40,
                        "--image-tag",
                        "cygnus:test",
                        "--alembic-revision",
                        "rev1",
                        "--capacity-approval-ref",
                        "cyg-144:capacity-approval:test",
                        "--capacity-thresholds-ref",
                        "cyg-144:capacity-thresholds:test",
                        "--capacity-targets-ref",
                        "cyg-144:capacity-targets:test",
                        "--report-out",
                        report_path,
                    ]
                )
            self.assertEqual(status, self.load_gate.EXIT_PASS)
            report = json.loads(Path(report_path).read_text(encoding="utf-8"))
            self.assertEqual(report["status"], GATE_PASS)
            self.assertEqual(report["release"]["commit_sha"], "a" * 40)
            self.assertTrue(report["config"]["thresholds_sha256"])
            self.assertEqual(report["totals"]["measured_routes"], 5)
            self.assertEqual(report["totals"]["passed_routes"], 5)
            self.assertEqual(len(report["alert_rule_mappings"]), 5 * 9)

    def test_replay_without_injection_confirmation_not_certified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            thresholds_path = os.path.join(tmp, "thresholds.json")
            Path(thresholds_path).write_text(
                json.dumps(_injection_thresholds().model_dump(mode="json")),
                encoding="utf-8",
            )
            samples_path = os.path.join(tmp, "samples.json")
            Path(samples_path).write_text(
                json.dumps(
                    {
                        "suite_name": "cygnus-capacity-gate-samples",
                        "phases": {
                            route: phase.to_dict()
                            for route, phase in _pass_phases().items()
                        },
                    }
                ),
                encoding="utf-8",
            )
            report_path = os.path.join(tmp, "report.json")
            with patch.dict(os.environ, UNSET_RUNTIME_IDENTITY_ENV):
                status = self.load_gate.main(
                    [
                        "--thresholds",
                        thresholds_path,
                        "--replay-samples",
                        samples_path,
                        "--commit-sha",
                        "a" * 40,
                        "--image-tag",
                        "cygnus:test",
                        "--alembic-revision",
                        "rev1",
                        "--capacity-approval-ref",
                        "cyg-144:capacity-approval:test",
                        "--capacity-thresholds-ref",
                        "cyg-144:capacity-thresholds:test",
                        "--capacity-targets-ref",
                        "cyg-144:capacity-targets:test",
                        "--report-out",
                        report_path,
                    ]
                )
            self.assertEqual(status, self.load_gate.EXIT_NOT_CERTIFIED)
            report = json.loads(Path(report_path).read_text(encoding="utf-8"))
            self.assertEqual(report["status"], GATE_NOT_CERTIFIED)
            self.assertIn(INJECTION_NOT_EXERCISED, report["reasons"])

    def test_cli_rejects_unbound_capacity_approval_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            thresholds_path = os.path.join(tmp, "thresholds.json")
            Path(thresholds_path).write_text(
                json.dumps(_thresholds_dict()), encoding="utf-8"
            )
            report_path = os.path.join(tmp, "report.json")
            status = self.load_gate.main(
                [
                    "--thresholds",
                    thresholds_path,
                    "--capacity-approval-ref",
                    "cyg-144:capacity-approval:other",
                    "--capacity-thresholds-ref",
                    "cyg-144:capacity-thresholds:test",
                    "--capacity-targets-ref",
                    "cyg-144:capacity-targets:test",
                    "--report-out",
                    report_path,
                ]
            )
            self.assertEqual(status, self.load_gate.EXIT_BLOCKED)
            report = json.loads(Path(report_path).read_text(encoding="utf-8"))
            self.assertIn(APPROVAL_REFS_MISMATCH, report["reasons"])

    def test_cli_blocks_absent_capacity_approval_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            thresholds_path = os.path.join(tmp, "thresholds.json")
            Path(thresholds_path).write_text(
                json.dumps(_thresholds_dict()), encoding="utf-8"
            )
            report_path = os.path.join(tmp, "report.json")
            status = self.load_gate.main(
                ["--thresholds", thresholds_path, "--report-out", report_path]
            )
            self.assertEqual(status, self.load_gate.EXIT_BLOCKED)
            report = json.loads(Path(report_path).read_text(encoding="utf-8"))
            self.assertIn(APPROVAL_REFS_MISSING, report["reasons"])


def _thresholds_from(config: dict) -> CapacityThresholds:
    fd, path = tempfile.mkstemp(suffix=".json", prefix="cygnus-gate-test-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(config, handle)
        return CapacityThresholds.from_file(path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


if __name__ == "__main__":
    unittest.main()
