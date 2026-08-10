from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import cast
import unittest
from unittest.mock import AsyncMock, patch
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.governance.audience_bindings import AudienceBindingLifecycle
from cygnus.governance.drift_signals import (
    DRIFT_SIGNAL_TYPES,
    DriftSignalProviderResult,
    compile_drift_signal_bundles,
    load_drift_signal_provider,
)
from cygnus.governance.signals import GovernanceSignalStatus
from cygnus.integrations.governed_drift_tools import GovernedDriftTools
from cygnus.integrations.mcp_auth import ResolvedIdentity
from cygnus.runtime.database.models import GovernanceAudienceBinding, GovernanceSignal
from cygnus.runtime.mcp import tools as mcp_tools
from cygnus.runtime.mcp.server import create_mcp_server
from cygnus.substrate.compilation_plan import UrgencyLevel


_NOW = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
_ACTOR_ID = uuid.uuid4()


def _audience_payload() -> dict[str, object]:
    return {
        "visibility": "external",
        "brands": [],
        "product_lines": ["billing"],
        "plans": ["enterprise"],
        "regions": ["eu"],
        "languages": [],
        "product_versions": [],
    }


def _signal(
    *,
    signal_ref: str,
    signal_type: str,
    object_ref: str,
    object_type: str,
    observed_at: datetime,
    affected_surfaces: tuple[str, ...],
    page_id: uuid.UUID | None = None,
    audience_binding_ref: str | None = None,
    use_inline_audience: bool = True,
    audience_filter: dict[str, object] | None = None,
) -> GovernanceSignal:
    return GovernanceSignal(
        id=uuid.uuid4(),
        signal_ref=signal_ref,
        signal_type=signal_type,
        object_ref=object_ref,
        title=f"Governed {signal_ref}",
        object_type=object_type,
        page_id=page_id,
        source_id=None,
        audience_binding_ref=audience_binding_ref,
        audience_filter=(
            _audience_payload() if use_inline_audience else audience_filter
        ),
        affected_surfaces=list(affected_surfaces),
        trigger_signals=[signal_type],
        evidence_source_type=(
            "release_note" if signal_type == "release_delta" else "incident_update"
        ),
        freshness="stale",
        summary=f"Summary for {signal_ref}",
        reason=f"Reason for {signal_ref}",
        evidence_excerpt=f"Evidence for {signal_ref}",
        status="active",
        observed_at=observed_at,
        resolved_at=None,
        created_by_id=_ACTOR_ID,
        created_at=observed_at,
        updated_at=observed_at,
        version=1,
    )


def _binding(
    *,
    binding_key: str,
    page_id: uuid.UUID,
    object_ref: str,
) -> GovernanceAudienceBinding:
    return GovernanceAudienceBinding(
        id=uuid.uuid4(),
        page_id=page_id,
        object_ref=object_ref,
        variant_ref="enterprise-eu",
        channel="copilot",
        visibility="external",
        brands=[],
        product_lines=["billing"],
        plans=["enterprise"],
        regions=["eu"],
        languages=[],
        product_versions=[],
        lifecycle_state="active",
        binding_key=binding_key,
        created_by_id=_ACTOR_ID,
        created_at=_NOW,
        updated_at=_NOW,
        version=1,
    )


class GovernedDriftToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.newest = _signal(
            signal_ref="release:newest",
            signal_type="release_delta",
            object_ref="ko-release-newest",
            object_type="answer_card",
            observed_at=_NOW,
            affected_surfaces=("queue-sidebar",),
        )
        self.urgent = _signal(
            signal_ref="incident:urgent",
            signal_type="incident_delta",
            object_ref="ko-incident-urgent",
            object_type="known_issue_page",
            observed_at=_NOW - timedelta(minutes=1),
            affected_surfaces=("copilot", "help_center"),
        )
        self.oldest = _signal(
            signal_ref="release:oldest",
            signal_type="release_delta",
            object_ref="ko-release-oldest",
            object_type="policy_rule",
            observed_at=_NOW - timedelta(minutes=2),
            affected_surfaces=("copilot",),
        )
        signals = (self.newest, self.urgent, self.oldest)
        bundles = list(compile_drift_signal_bundles(signals))
        bundles[1] = replace(
            bundles[1],
            proposal=replace(bundles[1].proposal, urgency=UrgencyLevel.URGENT),
        )
        self.tools = GovernedDriftTools(
            DriftSignalProviderResult(signals=signals, bundles=tuple(bundles))
        )

    def test_filters_preserve_provider_order_and_apply_limit_after_filtering(
        self,
    ) -> None:
        filtered = self.tools.list_drift_alerts(filters={"channel": "copilot"}, limit=1)
        ordered = self.tools.list_drift_alerts(filters={"channel": "copilot"}, limit=2)
        all_filters = self.tools.list_drift_alerts(
            filters={
                "object_type": "known_issue_page",
                "severity": "urgent",
                "channel": "copilot",
            }
        )

        self.assertEqual(filtered["status"], "success")
        self.assertEqual(
            [alert["signal_ref"] for alert in ordered["data"]["alerts"]],
            ["incident:urgent", "release:oldest"],
        )
        self.assertEqual(
            [alert["signal_ref"] for alert in filtered["data"]["alerts"]],
            ["incident:urgent"],
        )
        self.assertEqual(filtered["data"]["observation"]["observed_count"], 2)
        self.assertEqual(
            filtered["data"]["alerts"][0]["severity"],
            "urgent",
        )
        self.assertTrue(
            {
                "signal_ref",
                "signal_type",
                "object_ref",
                "object_type",
                "title",
                "severity",
                "reason",
                "summary",
                "affected_audiences",
                "affected_surfaces",
                "suggested_actions",
                "freshness",
                "observed_at",
                "trace_ref",
            }.issubset(filtered["data"]["alerts"][0])
        )
        self.assertEqual(
            all_filters["data"]["filters"],
            {
                "object_type": "known_issue_page",
                "severity": "urgent",
                "channel": "copilot",
            },
        )
        self.assertEqual(
            [alert["signal_ref"] for alert in all_filters["data"]["alerts"]],
            ["incident:urgent"],
        )

    def test_ready_empty_is_not_unavailable(self) -> None:
        payload = self.tools.list_drift_alerts(filters={"severity": "medium"})

        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["data"]["alerts"], [])
        self.assertEqual(payload["data"]["observation"]["state"], "ready")
        self.assertEqual(payload["data"]["observation"]["observed_count"], 0)

    def test_partial_omits_unresolved_rows_without_leaking_them(self) -> None:
        visible_bundle = compile_drift_signal_bundles((self.urgent,))[0]
        payload = GovernedDriftTools(
            DriftSignalProviderResult(
                signals=(self.urgent, self.oldest),
                bundles=(visible_bundle,),
                missing_signals=("audience_binding_resolution",),
            )
        ).list_drift_alerts()

        self.assertEqual(payload["status"], "partial")
        self.assertEqual(payload["warnings"], ["audience_binding_resolution"])
        self.assertEqual(
            [alert["signal_ref"] for alert in payload["data"]["alerts"]],
            ["incident:urgent"],
        )
        self.assertEqual(
            payload["data"]["observation"]["missing_signals"],
            ["audience_binding_resolution"],
        )

    def test_explicit_no_coverage_is_unavailable(self) -> None:
        payload = GovernedDriftTools(
            DriftSignalProviderResult(signals=(), bundles=(), covered_signals=())
        ).list_drift_alerts()

        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["data"]["alerts"], [])
        self.assertEqual(payload["data"]["observation"]["state"], "unavailable")
        self.assertEqual(
            payload["data"]["observation"]["missing_signals"],
            ["release_delta", "incident_delta"],
        )

    def test_invalid_arguments_return_structured_invalid_envelopes(self) -> None:
        invalid_calls = (
            {"filters": True},
            {"filters": {"unknown": "value"}},
            {"filters": {"channel": "  "}},
            {"filters": {"object_type": "article"}},
            {"filters": {"severity": "low"}},
            {"filters": {"severity": True}},
            {"limit": True},
            {"limit": 0},
            {"limit": 51},
            {"limit": "20"},
        )

        for arguments in invalid_calls:
            with self.subTest(arguments=arguments):
                payload = self.tools.list_drift_alerts(**arguments)
                self.assertEqual(payload["status"], "invalid")
                self.assertEqual(payload["warnings"], [])
                self.assertEqual(payload["errors"], ["invalid_arguments"])


class DriftSignalProviderTests(unittest.TestCase):
    def test_batch_resolves_visible_active_bindings_and_marks_mismatch_partial(
        self,
    ) -> None:
        page_id = uuid.uuid4()
        mismatch_page_id = uuid.uuid4()
        inline = _signal(
            signal_ref="release:inline",
            signal_type="release_delta",
            object_ref="ko-inline",
            object_type="answer_card",
            observed_at=_NOW,
            affected_surfaces=("copilot",),
        )
        bound = _signal(
            signal_ref="incident:bound",
            signal_type="incident_delta",
            object_ref="ko-bound",
            object_type="known_issue_page",
            observed_at=_NOW - timedelta(minutes=1),
            affected_surfaces=("copilot",),
            page_id=page_id,
            audience_binding_ref="binding:bound",
            audience_filter=None,
            use_inline_audience=False,
        )
        mismatch = _signal(
            signal_ref="release:mismatch",
            signal_type="release_delta",
            object_ref="ko-mismatch",
            object_type="policy_rule",
            observed_at=_NOW - timedelta(minutes=2),
            affected_surfaces=("copilot",),
            page_id=mismatch_page_id,
            audience_binding_ref="binding:mismatch",
            audience_filter=None,
            use_inline_audience=False,
        )
        scope_clause = object()
        session = cast(AsyncSession, cast(object, SimpleNamespace()))
        user = cast(
            object,
            SimpleNamespace(role="admin", department_ids=()),
        )
        good_binding = _binding(
            binding_key="binding:bound",
            page_id=page_id,
            object_ref="ko-bound",
        )
        mismatched_binding = _binding(
            binding_key="binding:mismatch",
            page_id=mismatch_page_id,
            object_ref="ko-other",
        )

        with (
            patch(
                "cygnus.governance.drift_signals.list_governance_signals",
                AsyncMock(return_value=(inline, bound, mismatch)),
            ) as list_signals,
            patch(
                "cygnus.governance.drift_signals.build_wiki_scope_clause",
                return_value=scope_clause,
            ),
            patch(
                "cygnus.governance.drift_signals.list_audience_bindings",
                AsyncMock(return_value=(good_binding, mismatched_binding)),
            ) as list_bindings,
        ):
            provider = asyncio.run(
                load_drift_signal_provider(
                    session,
                    current_user=cast(object, user),
                )
            )

        list_signals.assert_awaited_once_with(
            session,
            current_user=cast(object, user),
            status=GovernanceSignalStatus.ACTIVE,
            signal_types=DRIFT_SIGNAL_TYPES,
        )
        list_bindings.assert_awaited_once_with(
            session,
            binding_keys=("binding:bound", "binding:mismatch"),
            lifecycle_state=AudienceBindingLifecycle.ACTIVE,
            page_scope_clause=scope_clause,
        )
        self.assertEqual(
            [bundle.signal.signal_ref for bundle in provider.bundles],
            ["release:inline", "incident:bound"],
        )
        self.assertEqual(
            provider.bundles[1].signal.affected_audiences[0].plans,
            ("enterprise",),
        )
        self.assertEqual(provider.missing_signals, ("audience_binding_resolution",))

    def test_provider_exception_propagates(self) -> None:
        session = cast(AsyncSession, cast(object, SimpleNamespace()))
        user = cast(object, SimpleNamespace(role="admin", department_ids=()))
        with patch(
            "cygnus.governance.drift_signals.list_governance_signals",
            AsyncMock(side_effect=RuntimeError("database unavailable")),
        ):
            with self.assertRaisesRegex(RuntimeError, "database unavailable"):
                asyncio.run(
                    load_drift_signal_provider(
                        session,
                        current_user=cast(object, user),
                    )
                )


class MCPDriftResolverTests(unittest.TestCase):
    def test_mcp_resolves_current_employee_then_loads_provider_in_request_session(
        self,
    ) -> None:
        identity = ResolvedIdentity(
            employee_id=uuid.uuid4(),
            employee_name="Drift reader",
        )
        employee = SimpleNamespace(id=identity.employee_id, role="admin")
        session = cast(AsyncSession, cast(object, SimpleNamespace()))
        provider = DriftSignalProviderResult(signals=(), bundles=())
        with (
            patch.object(
                mcp_tools,
                "_load_identity_employee",
                AsyncMock(return_value=employee),
            ) as load_employee,
            patch(
                "cygnus.governance.drift_signals.load_drift_signal_provider",
                AsyncMock(return_value=provider),
            ) as load_provider,
        ):
            tools, error = asyncio.run(
                mcp_tools._get_governed_drift_tools(identity, session)
            )

        self.assertIsNone(error)
        self.assertIsInstance(tools, GovernedDriftTools)
        load_employee.assert_awaited_once_with(identity, session)
        load_provider.assert_awaited_once_with(session, current_user=employee)

    def test_mcp_returns_structured_invalid_before_auth_or_provider_load(self) -> None:
        tool = asyncio.run(create_mcp_server().get_tool("list_drift_alerts"))
        if tool is None:
            raise AssertionError("list_drift_alerts was not registered")

        with (
            patch.object(
                mcp_tools,
                "_get_identity",
                AsyncMock(side_effect=AssertionError("identity must not load")),
            ) as get_identity,
            patch(
                "cygnus.runtime.mcp.logging._persist_log",
                AsyncMock(return_value=None),
            ),
        ):
            results = [
                asyncio.run(tool.run(arguments))
                for arguments in ({"filters": True}, {"limit": "20"})
            ]

        get_identity.assert_not_awaited()
        for result in results:
            payload = json.loads(result.content[0].text)
            self.assertEqual(payload["status"], "invalid")
            self.assertEqual(payload["errors"], ["invalid_arguments"])

        limit_schema = tool.parameters["properties"]["limit"]
        self.assertEqual(limit_schema["type"], "integer")
        self.assertEqual(limit_schema["minimum"], 1)
        self.assertEqual(limit_schema["maximum"], 50)

    def test_mcp_provider_failure_propagates_without_empty_success(self) -> None:
        identity = ResolvedIdentity(
            employee_id=uuid.uuid4(),
            employee_name="Drift reader",
        )
        session = cast(AsyncSession, cast(object, SimpleNamespace()))
        with (
            patch.object(
                mcp_tools,
                "_load_identity_employee",
                AsyncMock(return_value=SimpleNamespace(role="admin")),
            ),
            patch(
                "cygnus.governance.drift_signals.load_drift_signal_provider",
                AsyncMock(side_effect=RuntimeError("provider failed")),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "provider failed"):
                asyncio.run(mcp_tools._get_governed_drift_tools(identity, session))


if __name__ == "__main__":
    unittest.main()
