from __future__ import annotations

import asyncio
import json
import unittest
import uuid
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from fastmcp.tools.base import Tool
from fastmcp.tools.function_tool import FunctionTool
from mcp.types import TextContent
from pydantic import ValidationError

from cygnus.domain import (
    AnswerCard,
    AudienceContext,
    AudienceFilter,
    LifecycleState,
    Visibility,
    governed_object_ref,
)
from cygnus.evidence.records import (
    EvidenceSourceType,
    FreshnessState,
    SupportEvidence,
)
from cygnus.integrations.governed_feedback_tools import feedback_tool_definitions
from cygnus.integrations.governed_session_tools import (
    governed_session_tool_definition,
    governed_session_tool_definitions,
)
from cygnus.integrations.nanobot_tools import (
    GovernedKnowledgeTools,
    build_governed_tool_registry,
)
from cygnus.integrations.session_bridge import (
    GovernedQueryRequest,
    GovernedSessionBridge,
)
from cygnus.retrieval import (
    PersistedDeliveryRecord,
    PersistedObjectTruth,
    SubstrateKnowledgeSnapshot,
)
from cygnus.retrieval.contracts import PublicationRecord
from cygnus.runtime.mcp import tools as mcp_tools
from cygnus.runtime.mcp.permissions import (
    ADMIN_ONLY,
    ANY_AUTHENTICATED,
    CAN_CONTRIBUTE_WIKI,
    requirement_for,
)
from cygnus.runtime.mcp.server import create_mcp_server
from cygnus.substrate.agent_protocol import SessionActorScope, ToolCall
from cygnus.substrate.tool_runtime import dispatch_tool_calls


def _tool_fn(tool: Tool | None) -> Callable[..., Any]:
    """Callable backing a registered FastMCP tool (FunctionTool.fn)."""
    assert isinstance(tool, FunctionTool)
    return tool.fn


_PAGE_ID = uuid.UUID("00000000-0000-0000-0000-000000000701")
_OBJECT_ID = governed_object_ref(_PAGE_ID)
_PUBLICATION_ID = "publication-current-cancellation"
_PROPAGATION_ID = "propagation-current-cancellation"
_DELIVERY_ID = "delivery-current-cancellation"


def _current_snapshot(
    *,
    freshness: FreshnessState = FreshnessState.FRESH,
    include_delivery: bool = True,
    evidence_binding_key: str = "copilot",
    receipt_page_version: int | None = None,
    receipt_approval_version: int | None = None,
    source_evidence_complete: bool = True,
    publication_delivery_id: str = _DELIVERY_ID,
) -> SubstrateKnowledgeSnapshot:
    audience = AudienceFilter(
        visibility=Visibility.EXTERNAL,
        product_lines=("billing",),
        plans=("free",),
    )
    object_id = _OBJECT_ID
    evidence_id = f"ev-current-cancellation-binding-{evidence_binding_key}"
    object_ = AnswerCard(
        object_id=object_id,
        title="Current cancellation guidance",
        summary="Explains cancellation for free billing plans.",
        lifecycle_state=LifecycleState.PUBLISHED,
        supported_audiences=(audience,),
        evidence_ids=(evidence_id,),
        tags=("billing", "cancel", "subscription"),
        question="How do I cancel my subscription?",
        canonical_answer="Open Billing, choose your plan, then cancel it.",
        publish_targets=("copilot",),
    )
    evidence = SupportEvidence(
        evidence_id=evidence_id,
        source_type=EvidenceSourceType.HELP_CENTER,
        source_ref="help-center/cancellation",
        title="Current cancellation policy",
        content="Free billing plans can be cancelled from the Billing page.",
        audience_filter=audience,
        product_lines=("billing",),
        plans=("free",),
        freshness_state=freshness,
        updated_at="2026-08-15T00:00:00Z",
    )
    truth = PersistedObjectTruth(
        page_id=str(_PAGE_ID),
        page_version=7,
        approval_version=3,
        source_evidence_complete=source_evidence_complete,
        truth_token="truth-current-cancellation-v7",
        publication_records=(
            PublicationRecord(
                channel="copilot",
                publication_state="synced",
                publication_ref=_PUBLICATION_ID,
                propagation_refs=(_PROPAGATION_ID,),
                delivery_refs=(publication_delivery_id,),
            ),
        ),
    )
    delivery = PersistedDeliveryRecord(
        page_id=truth.page_id,
        publication_id=_PUBLICATION_ID,
        propagation_id=_PROPAGATION_ID,
        delivery_id=_DELIVERY_ID,
        channel="copilot",
        binding_key="copilot",
        binding_version=1,
        audience_filter=audience,
        propagation_status="synced",
        delivery_status="synced",
        propagation_digest="digest-current-cancellation",
        desired_digest="digest-current-cancellation",
        acknowledged_digest="digest-current-cancellation",
        expected_page_version=receipt_page_version or truth.page_version,
        acknowledged_version=receipt_page_version or truth.page_version,
        expected_approval_version=receipt_approval_version or truth.approval_version,
    )
    return SubstrateKnowledgeSnapshot(
        objects=(object_,),
        evidence=(evidence,),
        persisted_truth_by_object={object_id: truth},
        delivery_records_by_object={object_id: (delivery,)} if include_delivery else {},
    )


class NanobotToolIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = _current_snapshot()
        self.tools = GovernedKnowledgeTools(self.snapshot)

    def test_current_delivery_succeeds_and_wrong_stale_or_missing_restricts(
        self,
    ) -> None:
        audience_context = {
            "visibility": "external",
            "product_line": "billing",
            "plan_tier": "free",
        }
        success = self.tools.search_knowledge_objects(
            query="cancel subscription",
            audience_context=audience_context,
            channel="copilot",
        )
        loaded = self.tools.read_knowledge_object(
            object_id=_OBJECT_ID,
            audience_context=audience_context,
            channel="copilot",
        )
        evidence = self.tools.search_support_evidence(
            query="cancellation policy",
            audience_context=audience_context,
            channel="copilot",
        )
        trace = self.tools.get_source_trace(
            object_id=_OBJECT_ID,
            audience_context=audience_context,
            channel="copilot",
        )

        self.assertEqual(success["status"], "success")
        self.assertEqual(success["data"]["results"][0]["object_id"], _OBJECT_ID)
        self.assertEqual(loaded["status"], "success")
        self.assertEqual(loaded["data"]["source_trace_summary"]["freshness"], "fresh")
        self.assertEqual(evidence["status"], "success")
        self.assertEqual(trace["status"], "success")

        wrong_channel = self.tools.read_knowledge_object(
            object_id=_OBJECT_ID,
            audience_context=audience_context,
            channel="help_center",
        )
        stale = GovernedKnowledgeTools(
            _current_snapshot(freshness=FreshnessState.STALE)
        ).read_knowledge_object(
            object_id=_OBJECT_ID,
            audience_context=audience_context,
            channel="copilot",
        )
        missing_delivery = GovernedKnowledgeTools(
            _current_snapshot(include_delivery=False)
        ).get_source_trace(
            object_id=_OBJECT_ID,
            audience_context=audience_context,
            channel="copilot",
        )
        wrong_evidence_binding = GovernedKnowledgeTools(
            _current_snapshot(evidence_binding_key="another-channel")
        ).search_support_evidence(
            query="cancellation policy",
            audience_context=audience_context,
            channel="copilot",
        )
        incomplete_source_evidence = GovernedKnowledgeTools(
            _current_snapshot(source_evidence_complete=False)
        ).read_knowledge_object(
            object_id=_OBJECT_ID,
            audience_context=audience_context,
            channel="copilot",
        )

        for result in (
            wrong_channel,
            stale,
            missing_delivery,
            wrong_evidence_binding,
            incomplete_source_evidence,
        ):
            self.assertEqual(result["status"], "restricted")
            self.assertEqual(result["errors"], ["not_currently_deliverable"])

    def test_runtime_session_bridge_rechecks_current_receipt_and_channel(self) -> None:
        audience_context = AudienceContext(
            visibility=Visibility.EXTERNAL,
            product_line="billing",
            plan="free",
        )

        def request(channel: str) -> GovernedQueryRequest:
            return GovernedQueryRequest(
                request_ref=f"session-{channel}",
                query="cancel subscription",
                channel=channel,
                audience_context=audience_context,
            )

        current = GovernedSessionBridge(_current_snapshot()).query(request("copilot"))
        old_ack = GovernedSessionBridge(
            _current_snapshot(receipt_page_version=6)
        ).query(request("copilot"))
        old_approval = GovernedSessionBridge(
            _current_snapshot(receipt_approval_version=2)
        ).query(request("copilot"))
        wrong_channel = GovernedSessionBridge(_current_snapshot()).query(
            request("help_center")
        )
        trace_mismatch = GovernedSessionBridge(
            _current_snapshot(publication_delivery_id="delivery-other")
        ).query(request("copilot"))
        incomplete_sources = GovernedSessionBridge(
            _current_snapshot(source_evidence_complete=False)
        ).query(request("copilot"))

        self.assertEqual(current["status"], "success")
        self.assertEqual(current["data"]["governance"]["state"], "answerable")
        for payload in (old_ack, old_approval, wrong_channel, trace_mismatch):
            self.assertEqual(payload["status"], "denied")
            self.assertEqual(payload["data"]["governance"]["state"], "restricted")
            self.assertIn("propagation_pending", payload["data"]["governance"]["codes"])
            self.assertIsNone(payload["data"]["answer"]["content"])
            self.assertEqual(payload["data"]["answer"]["usage"], "withheld")
        self.assertEqual(incomplete_sources["status"], "denied")
        self.assertEqual(incomplete_sources["data"]["governance"]["state"], "escalate")
        self.assertIn(
            "source_evidence_incomplete",
            incomplete_sources["data"]["governance"]["codes"],
        )
        self.assertIsNone(incomplete_sources["data"]["answer"]["content"])
        self.assertEqual(incomplete_sources["data"]["answer"]["usage"], "withheld")

    def test_runtime_bounds_audience_and_evidence_values(self) -> None:
        oversized_audience = self.tools.search_knowledge_objects(
            query="cancel",
            audience_context={
                "visibility": "external",
                "product_line": "billing",
                "brand": "x" * 201,
            },
            channel="copilot",
        )
        oversized_filter = self.tools.search_support_evidence(
            query="cancellation",
            audience_context={
                "visibility": "external",
                "product_line": "billing",
                "plan_tier": "free",
            },
            channel="copilot",
            filters={"region": "x" * 201},
        )
        for result in (oversized_audience, oversized_filter):
            self.assertEqual(result["status"], "invalid")
            self.assertEqual(result["errors"], ["invalid_arguments"])

    def test_fastmcp_read_adapters_enforce_runtime_dimension_bounds(self) -> None:
        mcp = create_mcp_server()
        search_tool = asyncio.run(mcp.get_tool("search_knowledge_objects"))
        evidence_tool = asyncio.run(mcp.get_tool("search_support_evidence"))
        if search_tool is None or evidence_tool is None:
            raise AssertionError("governed read tools were not registered")
        audience_context = {
            "visibility": "external",
            "product_line": "billing",
            "plan_tier": "free",
        }
        with (
            patch.object(
                mcp_tools,
                "_get_identity",
                AsyncMock(return_value=(SimpleNamespace(), None)),
            ),
            patch.object(
                mcp_tools,
                "_get_governed_knowledge_tools",
                AsyncMock(return_value=(self.tools, None)),
            ),
            patch(
                "cygnus.runtime.mcp.logging._persist_log",
                AsyncMock(return_value=None),
            ),
        ):
            outputs = (
                asyncio.run(
                    search_tool.run(
                        {
                            "query": "cancel",
                            "audience_context": {
                                **audience_context,
                                "brand": "x" * 201,
                            },
                            "channel": "copilot",
                        }
                    )
                ),
                asyncio.run(
                    evidence_tool.run(
                        {
                            "query": "cancellation",
                            "audience_context": audience_context,
                            "channel": "copilot",
                            "filters": {"region": "x" * 201},
                        }
                    )
                ),
            )
        for output in outputs:
            content = output.content[0]
            assert isinstance(content, TextContent)
            payload = json.loads(content.text)
            self.assertEqual(payload["status"], "invalid")
            self.assertEqual(payload["errors"], ["invalid_arguments"])

    def test_fastmcp_current_read_authenticates_before_manifest_policy(self) -> None:
        mcp = create_mcp_server()
        search_tool = asyncio.run(mcp.get_tool("search_knowledge_objects"))
        if search_tool is None:
            raise AssertionError("governed read tool was not registered")
        identity = SimpleNamespace(employee_id=uuid.uuid4())
        get_identity = AsyncMock(return_value=(identity, None))
        with (
            patch.object(mcp_tools, "_get_identity", get_identity),
            patch.object(
                mcp_tools,
                "_get_governed_knowledge_tools",
                AsyncMock(return_value=(self.tools, None)),
            ),
            patch(
                "cygnus.runtime.mcp.logging._persist_log",
                AsyncMock(return_value=None),
            ),
        ):
            output = asyncio.run(
                search_tool.run(
                    {
                        "query": "cancel",
                        "audience_context": {
                            "visibility": "external",
                            "product_line": "billing",
                            "plan_tier": "free",
                        },
                        "channel": "copilot",
                    }
                )
            )

        get_identity.assert_awaited_once()
        content = output.content[0]
        assert isinstance(content, TextContent)
        payload = json.loads(content.text)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["data"]["results"][0]["object_id"], _OBJECT_ID)

    def test_fastmcp_read_schemas_reject_missing_channel_and_legacy_flag(self) -> None:
        mcp = create_mcp_server()
        audience_context = {
            "visibility": "external",
            "product_line": "billing",
            "plan_tier": "free",
        }
        arguments_by_name = {
            "search_knowledge_objects": {
                "query": "cancel",
                "audience_context": audience_context,
            },
            "read_knowledge_object": {
                "object_id": _OBJECT_ID,
                "audience_context": audience_context,
            },
            "search_support_evidence": {
                "query": "cancellation",
                "audience_context": audience_context,
            },
            "get_source_trace": {
                "object_id": _OBJECT_ID,
                "audience_context": audience_context,
            },
        }
        tools = {name: asyncio.run(mcp.get_tool(name)) for name in arguments_by_name}
        if any(tool is None for tool in tools.values()):
            raise AssertionError("governed read tools were not registered")
        with (
            patch.object(
                mcp_tools,
                "_get_identity",
                AsyncMock(
                    side_effect=AssertionError("invalid input must not authenticate")
                ),
            ) as get_identity,
            patch(
                "cygnus.runtime.mcp.logging._persist_log",
                AsyncMock(return_value=None),
            ),
        ):
            for name, arguments in arguments_by_name.items():
                tool = tools[name]
                assert tool is not None
                invalid_calls = (
                    ("missing_channel", arguments),
                    (
                        "legacy_flag",
                        {
                            **arguments,
                            "channel": "copilot",
                            "include_unpublished": True,
                        },
                    ),
                )
                for label, invalid_arguments in invalid_calls:
                    with self.subTest(tool=name, rejection=label):
                        with self.assertRaises(ValidationError):
                            asyncio.run(tool.run(invalid_arguments))
        get_identity.assert_not_awaited()

    def test_tool_instances_do_not_share_governed_truth(self) -> None:
        empty_tools = GovernedKnowledgeTools(
            SubstrateKnowledgeSnapshot(objects=(), evidence=())
        )
        audience_context = {
            "visibility": "external",
            "product_line": "billing",
            "plan_tier": "free",
        }

        self.assertEqual(
            empty_tools.search_knowledge_objects(
                query="cancel",
                audience_context=audience_context,
                channel="copilot",
            )["data"]["results"],
            [],
        )
        self.assertNotEqual(
            self.tools.search_knowledge_objects(
                query="cancel",
                audience_context=audience_context,
                channel="copilot",
            )["data"]["results"],
            [],
        )

    def test_registry_requires_channel_and_rejects_legacy_unpublished_flag(
        self,
    ) -> None:
        registry = build_governed_tool_registry(self.snapshot)
        definitions = {
            definition.name: definition for definition in registry.list_definitions()
        }
        read_names = (
            "search_knowledge_objects",
            "read_knowledge_object",
            "search_support_evidence",
            "get_source_trace",
        )
        self.assertEqual(set(definitions), set(read_names))
        for name in read_names:
            self.assertIn("channel", definitions[name].parameters["required"])
            self.assertNotIn(
                "include_unpublished", definitions[name].parameters["properties"]
            )

        audience_context = {
            "visibility": "external",
            "product_line": "billing",
            "plan_tier": "free",
        }
        missing_channel_calls = (
            ToolCall(
                id="missing-search",
                name="search_knowledge_objects",
                arguments={"query": "cancel", "audience_context": audience_context},
            ),
            ToolCall(
                id="missing-read",
                name="read_knowledge_object",
                arguments={
                    "object_id": _OBJECT_ID,
                    "audience_context": audience_context,
                },
            ),
            ToolCall(
                id="missing-evidence",
                name="search_support_evidence",
                arguments={
                    "query": "cancellation",
                    "audience_context": audience_context,
                },
            ),
            ToolCall(
                id="missing-trace",
                name="get_source_trace",
                arguments={
                    "object_id": _OBJECT_ID,
                    "audience_context": audience_context,
                },
            ),
        )
        legacy_flag_calls = tuple(
            ToolCall(
                id=f"legacy-{call.id}",
                name=call.name,
                arguments={
                    **call.arguments,
                    "channel": "copilot",
                    "include_unpublished": True,
                },
            )
            for call in missing_channel_calls
        )
        results = asyncio.run(
            dispatch_tool_calls(registry, (*missing_channel_calls, *legacy_flag_calls))
        )
        for _, _, result in results:
            self.assertEqual(result["status"], "invalid")
            self.assertEqual(result["errors"], ["invalid_arguments"])

    def test_registry_dispatches_current_channel_bound_read(self) -> None:
        registry = build_governed_tool_registry(self.snapshot)
        audience_context = {
            "visibility": "external",
            "product_line": "billing",
            "plan_tier": "free",
        }
        results = asyncio.run(
            dispatch_tool_calls(
                registry,
                (
                    ToolCall(
                        id="current-search",
                        name="search_knowledge_objects",
                        arguments={
                            "query": "cancel",
                            "audience_context": audience_context,
                            "channel": "copilot",
                        },
                    ),
                    ToolCall(
                        id="current-trace",
                        name="get_source_trace",
                        arguments={
                            "object_id": _OBJECT_ID,
                            "audience_context": audience_context,
                            "channel": "copilot",
                        },
                    ),
                ),
                actor=SessionActorScope(authenticated=True),
            )
        )
        self.assertEqual(results[0][2]["status"], "success")
        self.assertEqual(results[1][2]["status"], "success")

    def test_direct_reads_revalidate_audience_without_slug_fallback(self) -> None:
        external_audience = {
            "visibility": "external",
            "product_line": "billing",
            "plan_tier": "free",
        }
        internal_audience = {"visibility": "internal", "product_line": "billing"}

        hidden_audience = self.tools.read_knowledge_object(
            object_id=_OBJECT_ID,
            audience_context=internal_audience,
            channel="copilot",
        )
        unpublished = self.tools.read_knowledge_object(
            object_id="ko-billing-verification-flow",
            audience_context=internal_audience,
            channel="copilot",
        )
        slug_probe = self.tools.read_knowledge_object(
            object_id="current-cancellation-guidance",
            audience_context=external_audience,
            channel="copilot",
        )
        trace_probe = self.tools.get_source_trace(
            object_id=_OBJECT_ID,
            audience_context=internal_audience,
            channel="copilot",
        )

        for result in (hidden_audience, unpublished, slug_probe, trace_probe):
            self.assertEqual(result["status"], "not_found")
            self.assertEqual(result["errors"], ["not_found"])
            self.assertNotIn("canonical_answer", result["data"])

    def test_missing_or_unknown_audience_fields_are_rejected_before_read_work(
        self,
    ) -> None:
        missing = self.tools.search_support_evidence(
            query="cancellation",
            audience_context={},
            channel="copilot",
        )
        unknown = self.tools.get_source_trace(
            object_id=_OBJECT_ID,
            audience_context={"visibility": "external", "include_unpublished": True},
            channel="copilot",
        )

        self.assertEqual(missing["status"], "invalid")
        self.assertEqual(missing["errors"], ["invalid_arguments"])
        self.assertEqual(unknown["status"], "invalid")
        self.assertEqual(unknown["errors"], ["invalid_arguments"])

    def test_runtime_mcp_registers_governed_tools_as_the_support_default(self) -> None:
        mcp = create_mcp_server()
        tool_names = {tool.name for tool in asyncio.run(mcp.list_tools())}

        governed_tool_names = {
            definition.name for definition in governed_session_tool_definitions()
        }
        registered_tools = {
            name: asyncio.run(mcp.get_tool(name)) for name in governed_tool_names
        }
        unrestricted_governed_names = {
            "get_source_trace",
            "read_knowledge_object",
            "read_review_feedback",
            "search_knowledge_objects",
            "search_support_evidence",
            "validate_publish_policy",
            "list_drift_alerts",
            "record_feedback_signal",
        }
        restricted_writer_names = {
            "propose_knowledge_object",
            "update_draft_object",
            "request_review",
            "publish_knowledge_object",
        }

        self.assertTrue(all(tool is not None for tool in registered_tools.values()))
        self.assertTrue(unrestricted_governed_names.issubset(tool_names))
        self.assertTrue(restricted_writer_names.isdisjoint(tool_names))

        validate_tool = registered_tools["validate_publish_policy"]
        publish_tool = registered_tools["publish_knowledge_object"]
        propose_tool = registered_tools["propose_knowledge_object"]
        update_tool = registered_tools["update_draft_object"]
        review_tool = registered_tools["request_review"]
        feedback_tool = registered_tools["read_review_feedback"]
        record_feedback_tool = registered_tools["record_feedback_signal"]
        drift_tool = registered_tools["list_drift_alerts"]
        if (
            validate_tool is None
            or publish_tool is None
            or propose_tool is None
            or update_tool is None
            or review_tool is None
            or feedback_tool is None
            or record_feedback_tool is None
            or drift_tool is None
        ):
            raise AssertionError("governed session tools were not registered")
        feedback_definition = governed_session_tool_definition("record_feedback_signal")
        self.assertIs(feedback_definition, feedback_tool_definitions()[0])
        self.assertEqual(record_feedback_tool.name, feedback_definition.name)
        self.assertEqual(
            record_feedback_tool.description,
            feedback_definition.description,
        )
        # Callable defaults are FastMCP metadata; all validation constraints
        # must still come from the shared ToolDefinition unchanged.
        runtime_feedback_parameters = dict(record_feedback_tool.parameters)
        runtime_feedback_parameters["properties"] = {
            name: {key: value for key, value in schema.items() if key != "default"}
            for name, schema in record_feedback_tool.parameters["properties"].items()
        }
        self.assertEqual(runtime_feedback_parameters, feedback_definition.parameters)
        self.assertIs(requirement_for(_tool_fn(validate_tool)), ANY_AUTHENTICATED)
        self.assertIs(requirement_for(_tool_fn(publish_tool)), ADMIN_ONLY)
        self.assertIs(requirement_for(_tool_fn(propose_tool)), CAN_CONTRIBUTE_WIKI)
        self.assertIs(requirement_for(_tool_fn(update_tool)), CAN_CONTRIBUTE_WIKI)
        self.assertIs(requirement_for(_tool_fn(review_tool)), CAN_CONTRIBUTE_WIKI)
        self.assertIs(requirement_for(_tool_fn(feedback_tool)), ANY_AUTHENTICATED)
        self.assertIs(
            requirement_for(_tool_fn(record_feedback_tool)), ANY_AUTHENTICATED
        )
        self.assertIs(requirement_for(_tool_fn(drift_tool)), ANY_AUTHENTICATED)
        for name in (
            "search_knowledge_objects",
            "read_knowledge_object",
            "search_support_evidence",
            "get_source_trace",
        ):
            runtime_tool = registered_tools[name]
            if runtime_tool is None:
                raise AssertionError(f"{name} was not registered")
            runtime_parameters = runtime_tool.parameters
            self.assertIn("channel", runtime_parameters["required"])
            self.assertNotIn("include_unpublished", runtime_parameters["properties"])
            self.assertEqual(
                runtime_parameters["properties"]["audience_context"]["properties"][
                    "brand"
                ]["maxLength"],
                200,
            )
        evidence_tool = registered_tools["search_support_evidence"]
        if evidence_tool is None:
            raise AssertionError("search_support_evidence was not registered")
        self.assertEqual(
            evidence_tool.parameters["properties"]["filters"]["properties"]["region"][
                "maxLength"
            ],
            200,
        )
        self.assertIn("Never treat chat history", mcp.instructions or "")
