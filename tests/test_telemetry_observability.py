"""Focused tests for the CYG-142 telemetry/migration baseline.

Covers:
- one correlation ID propagates through request context and outbound headers
- malformed inbound correlation headers are rejected, valid ones echoed
- bounded RED metrics render as Prometheus text with sanitized labels
- telemetry failures degrade explicitly instead of raising
- runtime release identity is sanitized and env-driven
- alert rules are machine-readable with owner/runbook/recovery semantics
- the correlation migration is the linear successor of 20260812_06
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import yaml

from cygnus.observability import (
    configure_observability,
    current_request_id,
    current_traceparent,
    outbound_trace_headers,
    record_http_request,
    record_mcp_tool,
    record_propagation_mismatch,
    record_readiness_dependency,
    record_telemetry_failure,
    render_prometheus_metrics,
    request_correlation,
    resolve_request_id_header,
    runtime_identity,
    sanitize_error,
)

_VALID_UUID = "550e8400-e29b-41d4-a716-446655440000"


class CorrelationContextTest(unittest.TestCase):
    def test_generates_request_id_when_absent(self) -> None:
        with request_correlation() as request_id:
            self.assertIsNotNone(request_id)
            self.assertEqual(request_id, current_request_id())
            self.assertEqual(
                request_id,
                resolve_request_id_header(outbound_trace_headers()["X-Request-ID"]),
            )

    def test_echoes_valid_inbound_request_id(self) -> None:
        with request_correlation(_VALID_UUID) as request_id:
            self.assertEqual(request_id, _VALID_UUID)
            self.assertEqual(current_request_id(), _VALID_UUID)

    def test_rejects_malformed_inbound_request_id(self) -> None:
        for malformed in (
            "not-a-uuid",
            "DROP TABLE audit_log;",
            "x" * 65,
            "../../etc/passwd",
        ):
            with self.subTest(value=malformed):
                self.assertIsNone(resolve_request_id_header(malformed))

    def test_context_does_not_leak_outside_scope(self) -> None:
        with request_correlation(_VALID_UUID):
            self.assertEqual(current_request_id(), _VALID_UUID)
        self.assertIsNone(current_request_id())

    def test_traceparent_is_w3c_shaped_and_derived_from_request_id(self) -> None:
        with request_correlation(_VALID_UUID):
            traceparent = current_traceparent()
            assert traceparent is not None
            parts = traceparent.split("-")
            self.assertEqual(len(parts), 4)
            self.assertEqual(parts[0], "00")
            self.assertEqual(len(parts[1]), 32)
            self.assertEqual(len(parts[2]), 16)
            self.assertEqual(len(parts[3]), 2)
            self.assertEqual(parts[1], _VALID_UUID.replace("-", ""))

    def test_outbound_headers_contain_only_bounded_fields(self) -> None:
        with request_correlation(_VALID_UUID):
            headers = outbound_trace_headers()
        self.assertEqual(
            set(headers),
            {"X-Request-ID", "traceparent"},
        )


class MetricsTest(unittest.TestCase):
    def setUp(self) -> None:
        # Isolate registry state: counters accumulate across the full suite
        # (other modules record into the shared registry), so exact-value
        # assertions need a fresh registry per test.
        from cygnus.observability._metrics import reset_registry_for_tests

        reset_registry_for_tests()

    def test_red_metrics_render_as_prometheus_text(self) -> None:
        record_http_request(
            route="/api/sources/{source_id}",
            method="GET",
            status=200,
            duration_ms=25.0,
        )
        record_http_request(
            route="/api/sources/{source_id}",
            method="GET",
            status=500,
            duration_ms=25.0,
        )
        rendered = render_prometheus_metrics()
        self.assertIn("cygnus_http_requests_total", rendered)
        self.assertIn('status="200"', rendered)
        self.assertIn('status="500"', rendered)
        self.assertIn("cygnus_http_request_duration_seconds_bucket", rendered)

    def test_labels_are_sanitized_and_bounded(self) -> None:
        record_mcp_tool(
            tool="search_wiki;DROP TABLE x",
            status="ok",
            duration_ms=10.0,
        )
        rendered = render_prometheus_metrics()
        # Tool labels come from an allowlisted identifier vocabulary: raw
        # tool/query content (here an injected SQL fragment) never reaches
        # the exposition — the label collapses to the bounded placeholder.
        self.assertNotIn("DROP", rendered)
        self.assertIn(
            'cygnus_mcp_tool_calls_total{tool="unknown",status="ok"} 1', rendered
        )

    def test_telemetry_failure_counter_degrades_explicitly(self) -> None:
        record_telemetry_failure("otlp_unavailable")
        rendered = render_prometheus_metrics()
        self.assertIn("cygnus_telemetry_failures_total", rendered)

    def test_disabled_telemetry_renders_nothing(self) -> None:
        config = configure_observability(None, telemetry_enabled=False)
        with patch("cygnus.observability._metrics._config", config):
            record_http_request(
                route="/disabled-probe", method="GET", status=200, duration_ms=1.0
            )
            rendered = render_prometheus_metrics()
        # The registry may hold samples from earlier tests, but the sample
        # recorded while telemetry was disabled must not appear.
        self.assertNotIn('route="/disabled-probe"', rendered)

    def test_propagation_mismatch_records_bounded_kind(self) -> None:
        record_propagation_mismatch(kind="mismatch", count=2)
        rendered = render_prometheus_metrics()
        self.assertIn('cygnus_propagation_mismatch_total{kind="mismatch"} 2', rendered)

    def test_readiness_dependency_records_ready_and_failed(self) -> None:
        record_readiness_dependency(dependency="database", status="ready")
        record_readiness_dependency(dependency="redis", status="failed")
        rendered = render_prometheus_metrics()
        self.assertIn('cygnus_readiness_dependency{dependency="database"} 1', rendered)
        self.assertIn('cygnus_readiness_dependency{dependency="redis"} 0', rendered)

    def test_provider_observation_records_model_outcome_latency_and_tokens(
        self,
    ) -> None:
        from cygnus.runtime.ai.providers.base import observe_provider_call

        response = SimpleNamespace(
            usage=SimpleNamespace(
                prompt_tokens=7,
                completion_tokens=3,
                total_tokens=10,
            )
        )
        with observe_provider_call(
            provider="openai",
            model="gpt-4o-mini",
            operation="generate",
        ) as observation:
            observation.success(response)

        rendered = render_prometheus_metrics()
        self.assertIn(
            'cygnus_provider_calls_total{provider="openai",model="gpt-4o-mini",operation="generate",status="ok"} 1',
            rendered,
        )
        self.assertIn('direction="input"} 7', rendered)
        self.assertIn('direction="output"} 3', rendered)
        self.assertIn('direction="total"} 10', rendered)

    def test_provider_observation_records_error_in_finally_and_redacts_model(
        self,
    ) -> None:
        from cygnus.runtime.ai.providers.base import observe_provider_call

        with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
            with observe_provider_call(
                provider="anthropic",
                model="claude;api_key=sk-1234567890abcdef",
                operation="generate",
            ):
                raise RuntimeError("provider unavailable")

        rendered = render_prometheus_metrics()
        self.assertNotIn("sk-1234567890abcdef", rendered)
        self.assertIn('model="redacted"', rendered)
        self.assertIn('status="error"', rendered)


class ProviderAdapterTelemetryTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        from cygnus.observability._metrics import reset_registry_for_tests

        reset_registry_for_tests()

    async def test_openai_boundary_records_success_latency_and_usage(self) -> None:
        from cygnus.runtime.ai.providers.base import ProviderConfig, ProviderType
        from cygnus.runtime.ai.providers.openai_provider import OpenAILLM

        response = SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=4, completion_tokens=2),
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
        )
        create = AsyncMock(return_value=response)
        provider = OpenAILLM(
            ProviderConfig(provider=ProviderType.OPENAI, model_id="gpt-test")
        )
        provider._client = SimpleNamespace(  # type: ignore[assignment]
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )

        self.assertEqual(await provider.generate("private prompt"), "ok")

        rendered = render_prometheus_metrics()
        self.assertIn('provider="openai",model="gpt-test"', rendered)
        self.assertIn('operation="generate",status="ok"', rendered)
        self.assertIn('direction="input"} 4', rendered)
        self.assertNotIn("private prompt", rendered)

    async def test_anthropic_boundary_records_failed_outcome(self) -> None:
        from cygnus.runtime.ai.providers.anthropic_provider import AnthropicLLM
        from cygnus.runtime.ai.providers.base import ProviderConfig, ProviderType

        provider = AnthropicLLM(
            ProviderConfig(provider=ProviderType.ANTHROPIC, model_id="claude-test")
        )
        provider._client = SimpleNamespace(  # type: ignore[assignment]
            messages=SimpleNamespace(
                create=AsyncMock(side_effect=RuntimeError("provider unavailable"))
            )
        )

        with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
            await provider.generate("private prompt")

        rendered = render_prometheus_metrics()
        self.assertIn('provider="anthropic",model="claude-test"', rendered)
        self.assertIn('operation="generate",status="error"', rendered)
        self.assertNotIn("provider unavailable", rendered)

    async def test_google_boundary_records_usage_metadata(self) -> None:
        from cygnus.runtime.ai.providers.base import ProviderConfig, ProviderType
        from cygnus.runtime.ai.providers.google import GoogleLLM

        response = SimpleNamespace(
            text="ok",
            usage_metadata=SimpleNamespace(
                prompt_token_count=5,
                candidates_token_count=3,
                total_token_count=8,
            ),
        )
        provider = GoogleLLM(
            ProviderConfig(provider=ProviderType.GOOGLE, model_id="gemini-test")
        )
        provider._client = SimpleNamespace(  # type: ignore[assignment]
            models=SimpleNamespace(generate_content=lambda **_kwargs: response)
        )

        self.assertEqual(await provider.generate("private prompt"), "ok")

        rendered = render_prometheus_metrics()
        self.assertIn('provider="google",model="gemini-test"', rendered)
        self.assertIn('operation="generate",status="ok"', rendered)
        self.assertIn('direction="total"} 8', rendered)


class SanitizationTest(unittest.TestCase):
    def test_sanitize_error_redacts_secret_shaped_messages(self) -> None:
        err = ValueError("api_key=sk-1234567890abcdef connection failed")
        sanitized = sanitize_error(err)
        self.assertNotIn("sk-1234567890abcdef", sanitized)
        self.assertIn("<redacted>", sanitized)

    def test_sanitize_error_keeps_type_and_bounded_message(self) -> None:
        err = RuntimeError("worker died")
        self.assertEqual(sanitize_error(err), "RuntimeError: worker died")


class RuntimeIdentityTest(unittest.TestCase):
    def test_identity_comes_from_env_and_is_sanitized(self) -> None:
        env = {
            "APP_RELEASE": "v2.3.4",
            "APP_ENVIRONMENT": "production",
            "APP_COMMIT_SHA": "0123456789abcdef0123456789abcdef01234567",
        }
        with patch.dict(os.environ, env, clear=False):
            identity = runtime_identity(refresh=True)
        self.assertEqual(identity["release"], "v2.3.4")
        self.assertEqual(identity["environment"], "production")
        self.assertEqual(
            identity["commit_sha"], "0123456789abcdef0123456789abcdef01234567"
        )
        # Unknowns are bounded placeholders, never raw env values.
        self.assertEqual(identity["image_ref"], "unknown")

    def test_identity_is_bounded_and_secret_free(self) -> None:
        env = {"APP_RELEASE": "v1;secret=abc"}
        with patch.dict(os.environ, env, clear=False):
            identity = runtime_identity(refresh=True)
        self.assertNotIn("secret=abc", identity["release"])
        self.assertLessEqual(len(identity["release"]), 64)


class AlertRuleRenderingTest(unittest.TestCase):
    def _external_thresholds(self) -> dict[str, object]:
        from cygnus.observability.alert_rules import ALERT_THRESHOLD_KEYS

        values = {key: 2.0 for key in ALERT_THRESHOLD_KEYS}
        for key in (
            "http_error_rate",
            "mcp_error_rate",
            "http_denial_rate",
            "db_pool_saturation",
        ):
            values[key] = 0.25
        return {
            "approval": {
                "approval_ref": "approval://cyg-144-alerts-test",
                "thresholds_ref": "observability-config://cyg-144-alerts-test",
            },
            "thresholds": values,
        }

    def _load_inputs(self, directory: str, payload: dict[str, object]):
        from cygnus.observability.alert_rules import load_alert_threshold_inputs

        path = Path(directory) / "alerts.json"
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        path.write_bytes(encoded)
        digest = f"sha256:{hashlib.sha256(encoded).hexdigest()}"
        return load_alert_threshold_inputs(
            path,
            expected_approval_ref="approval://cyg-144-alerts-test",
            expected_thresholds_ref="observability-config://cyg-144-alerts-test",
            expected_thresholds_sha256=digest,
        )

    def test_renderer_substitutes_only_approved_values_and_binds_each_rule(
        self,
    ) -> None:
        from cygnus.observability.alert_rules import render_alert_rules

        with tempfile.TemporaryDirectory() as tmp:
            inputs = self._load_inputs(tmp, self._external_thresholds())
            rendered_text = render_alert_rules(
                Path("config/observability/alert_rules.yml"), inputs
            )

        self.assertNotIn("{{alert.", rendered_text)
        self.assertIn("> 0.25", rendered_text)
        rendered = yaml.safe_load(rendered_text)
        for group in rendered["groups"]:
            for rule in group["rules"]:
                self.assertEqual(rule["labels"]["approval_ref"], inputs.approval_ref)
                self.assertEqual(
                    rule["labels"]["thresholds_sha256"],
                    inputs.thresholds_sha256,
                )

    def test_threshold_schema_matches_renderer_contract(self) -> None:
        from cygnus.observability.alert_rules import ALERT_THRESHOLD_KEYS

        schema = json.loads(
            Path("config/observability/alert_thresholds.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            set(schema["properties"]["thresholds"]["required"]),
            set(ALERT_THRESHOLD_KEYS),
        )

    def test_renderer_rejects_missing_external_threshold(self) -> None:
        from cygnus.observability.alert_rules import AlertThresholdInputError

        payload = self._external_thresholds()
        thresholds = payload["thresholds"]
        assert isinstance(thresholds, dict)
        del thresholds["http_error_rate"]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(AlertThresholdInputError, "missing"):
                self._load_inputs(tmp, payload)

    def test_renderer_rejects_hash_or_approval_mismatch(self) -> None:
        from cygnus.observability.alert_rules import (
            AlertThresholdInputError,
            load_alert_threshold_inputs,
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "alerts.json"
            path.write_text(json.dumps(self._external_thresholds()), encoding="utf-8")
            with self.assertRaisesRegex(AlertThresholdInputError, "hash"):
                load_alert_threshold_inputs(
                    path,
                    expected_approval_ref="approval://cyg-144-alerts-test",
                    expected_thresholds_ref="observability-config://cyg-144-alerts-test",
                    expected_thresholds_sha256="sha256:" + "0" * 64,
                )


class ProductionAlertInputGateTest(unittest.TestCase):
    gate: Any

    @classmethod
    def setUpClass(cls) -> None:
        module_path = Path("scripts/production_inputs_gate.py").resolve()
        spec = importlib.util.spec_from_file_location(
            "production_inputs_gate_observability_test", module_path
        )
        assert spec is not None and spec.loader is not None
        cls.gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.gate)

    def test_alert_threshold_refs_and_hash_must_match_deploy_inputs(self) -> None:
        failures: list[str] = []
        checks: dict[str, object] = {}
        self.gate._validate_alert_inputs(
            {
                "approval_ref": "approval://wrong",
                "alert_thresholds_ref": "observability-config://approved",
                "alert_thresholds_sha256": "sha256:" + "a" * 64,
            },
            alert_approval_ref="approval://approved",
            alert_thresholds_ref="observability-config://approved",
            alert_thresholds_sha256="sha256:" + "a" * 64,
            failures=failures,
            checks=checks,
        )
        self.assertFalse(checks["alert_threshold_binding"])
        self.assertTrue(any("approval_ref" in failure for failure in failures))

    def test_alert_threshold_refs_and_hash_bind_when_exact(self) -> None:
        failures: list[str] = []
        checks: dict[str, object] = {}
        self.gate._validate_alert_inputs(
            {
                "approval_ref": "approval://approved",
                "alert_thresholds_ref": "observability-config://approved",
                "alert_thresholds_sha256": "sha256:" + "a" * 64,
            },
            alert_approval_ref="approval://approved",
            alert_thresholds_ref="observability-config://approved",
            alert_thresholds_sha256="sha256:" + "a" * 64,
            failures=failures,
            checks=checks,
        )
        self.assertEqual(failures, [])
        self.assertTrue(checks["alert_threshold_binding"])

    def test_public_origin_accepts_approved_nonstandard_tls_port(self) -> None:
        failures: list[str] = []
        domain = self.gate._domain(
            "vm-0-7-ubuntu.tailc9ec74.ts.net", "public_endpoint.domain", failures
        )
        origin = self.gate._origin(
            "https://vm-0-7-ubuntu.tailc9ec74.ts.net:8443",
            domain=domain,
            path="public_endpoint.origin",
            failures=failures,
        )

        self.assertEqual(failures, [])
        self.assertEqual(origin, "https://vm-0-7-ubuntu.tailc9ec74.ts.net:8443")

    def test_public_origin_rejects_reserved_domain_and_host_mismatch(self) -> None:
        failures: list[str] = []
        self.gate._domain(
            "cygnus-certification.local", "public_endpoint.domain", failures
        )
        self.gate._origin(
            "https://other.tailc9ec74.ts.net:8443",
            domain="vm-0-7-ubuntu.tailc9ec74.ts.net",
            path="public_endpoint.origin",
            failures=failures,
        )

        self.assertTrue(any("public FQDN" in failure for failure in failures))
        self.assertTrue(
            any("canonical HTTPS origin" in failure for failure in failures)
        )


class AlertRulesTest(unittest.TestCase):
    def test_alert_rules_are_machine_readable_with_owner_runbook_recovery(self) -> None:
        rules_path = Path("config/observability/alert_rules.yml")
        self.assertTrue(rules_path.exists(), "alert rules file missing")
        data = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
        groups = data["groups"]
        self.assertTrue(groups)
        rules = [rule for group in groups for rule in group["rules"]]
        self.assertTrue(rules)
        for rule in rules:
            with self.subTest(alert=rule.get("alert")):
                self.assertIn("alert", rule)
                self.assertIn("expr", rule)
                self.assertIn("for", rule)
                self.assertIn("severity", rule["labels"])
                self.assertIn("owner", rule["labels"])
                self.assertIn("summary", rule["annotations"])
                self.assertIn("runbook", rule["annotations"])
                self.assertIn("recovery", rule["annotations"])

    def test_live_numeric_limits_are_external_template_inputs(self) -> None:
        from cygnus.observability.alert_rules import ALERT_THRESHOLD_KEYS

        text = Path("config/observability/alert_rules.yml").read_text(encoding="utf-8")
        referenced = set(re.findall(r"\{\{alert\.([a-z0-9_]+)\}\}", text))
        self.assertEqual(referenced, set(ALERT_THRESHOLD_KEYS))
        for removed_literal in (
            "> 0.05",
            "> 0.10",
            "> 2.0",
            "> 1800",
            "> 0.85",
        ):
            self.assertNotIn(removed_literal, text)

    def test_capacity_alerts_require_complete_approval_bound_series(self) -> None:
        data = yaml.safe_load(
            Path("config/observability/alert_rules.yml").read_text(encoding="utf-8")
        )
        group = next(
            group for group in data["groups"] if group["name"] == "cygnus_capacity_gate"
        )
        mapped_rules = [
            rule
            for rule in group["rules"]
            if rule["alert"] != "ALERT-142-CAPACITY-INPUTS-MISSING"
        ]
        self.assertEqual(len(mapped_rules), 45)
        for rule in mapped_rules:
            expression = rule["expr"]
            self.assertIn("cygnus_capacity_gate_breach", expression)
            for label in (
                "approval_ref",
                "thresholds_ref",
                "targets_ref",
                "thresholds_fingerprint",
            ):
                self.assertIn(label, expression)

    def test_capacity_alert_rule_mappings_cover_all_45_keys(self) -> None:
        """The 45 <route>.<metric> keys consumed by CapacityThresholds
        alert_rule_mappings resolve to rule IDs defined in this file."""
        routes = ("publish", "ticket_import", "ingestion", "worker", "query")
        metrics = (
            "p50_ms",
            "p95_ms",
            "p99_ms",
            "throughput_rps",
            "error_rate",
            "denial_rate",
            "retry_rate",
            "queue_age_seconds",
            "pool_saturation",
        )
        data = yaml.safe_load(
            Path("config/observability/alert_rules.yml").read_text(encoding="utf-8")
        )
        ids = {rule["alert"] for group in data["groups"] for rule in group["rules"]}
        expected = {
            f"ALERT-142-{route.upper()}-{metric.upper()}"
            for route in routes
            for metric in metrics
        }
        missing = expected - ids
        self.assertEqual(missing, set(), f"missing capacity rule ids: {missing}")

    def test_alert_expressions_reference_real_metric_names(self) -> None:
        from cygnus.observability._metrics import _registry

        data = yaml.safe_load(
            Path("config/observability/alert_rules.yml").read_text(encoding="utf-8")
        )
        registered = set(_registry.metric_names())
        expressions = " ".join(
            str(rule.get("expr", ""))
            for group in data["groups"]
            for rule in group["rules"]
        )
        referenced = set(re.findall(r"\bcygnus_[a-z0-9_]+\b", expressions))
        for metric in referenced:
            with self.subTest(metric=metric):
                self.assertIn(metric, registered, f"{metric} not registered")


class MigrationTest(unittest.TestCase):
    def test_correlation_migration_chains_after_20260812_06(self) -> None:
        migration = Path("migrations/versions/20260812_07_telemetry_correlation.py")
        self.assertTrue(migration.exists(), "correlation migration missing")
        text = migration.read_text(encoding="utf-8")
        self.assertIn('revision: str = "20260812_07"', text)
        self.assertIn('down_revision: str | None = "20260812_06"', text)
        # The migration adds both bounded columns; the calls are multi-line,
        # so assert on the op + table pair rather than a single-line call.
        self.assertTrue(
            re.search(r'op\.add_column\(\s*"audit_log"', text),
            "migration must add columns to audit_log",
        )
        self.assertTrue(
            re.search(r'op\.add_column\(\s*"mcp_query_log"', text),
            "migration must add columns to mcp_query_log",
        )
        self.assertIn('"correlation_id"', text)
        self.assertIn('"traceparent"', text)

    def test_orm_models_expose_correlation_columns(self) -> None:
        models_path = Path("cygnus/runtime/database/models.py")
        text = models_path.read_text(encoding="utf-8")
        self.assertIn("correlation_id", text)
        self.assertIn("ix_audit_log_correlation_id", text)
        self.assertIn("ix_mcp_query_log_correlation_id", text)


class ArqCorrelationTest(unittest.IsolatedAsyncioTestCase):
    """One correlation ID flows into ARQ jobs and back out in the worker."""

    def _enqueue_kwargs(self) -> dict[str, str]:
        from cygnus.runtime.worker import _correlation_enqueue_kwargs

        return _correlation_enqueue_kwargs()

    async def test_enqueue_kwargs_empty_outside_request_scope(self) -> None:
        self.assertEqual(self._enqueue_kwargs(), {})

    async def test_enqueue_kwargs_carry_active_correlation(self) -> None:
        with request_correlation(_VALID_UUID):
            kwargs = self._enqueue_kwargs()
        self.assertEqual(kwargs, {"_cygnus_correlation_id": _VALID_UUID})

    async def test_enqueue_kwargs_reject_malformed_ids(self) -> None:
        with request_correlation("DROP TABLE x"):
            kwargs = self._enqueue_kwargs()
        self.assertEqual(kwargs, {})

    async def test_job_wrapper_pops_and_rebinds_correlation(self) -> None:
        from cygnus.runtime.worker import _CORRELATION_KWARG, _track_heartbeat_job

        seen: list[str | None] = []

        async def business(ctx, source_id: str) -> str:
            seen.append(current_request_id())
            return source_id

        wrapped = _track_heartbeat_job(business)
        result = await wrapped(
            {"job_id": "job-1", "job_try": 1, "enqueue_time": 0},
            "src-1",
            **{_CORRELATION_KWARG: _VALID_UUID},
        )
        self.assertEqual(result, "src-1")
        # The business function saw the rebound correlation inside its scope.
        self.assertEqual(seen, [_VALID_UUID])
        # And the context does not leak past the job.
        self.assertIsNone(current_request_id())

    async def test_job_wrapper_without_correlation_stays_unbound(self) -> None:
        from cygnus.runtime.worker import _track_heartbeat_job

        seen: list[str | None] = []

        async def business(ctx, source_id: str) -> str:
            seen.append(current_request_id())
            return source_id

        wrapped = _track_heartbeat_job(business)
        await wrapped({"job_id": "job-2"}, "src-2")
        self.assertEqual(seen, [None])


if __name__ == "__main__":
    unittest.main()
