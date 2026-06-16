from __future__ import annotations

from functools import lru_cache
from typing import Any

from cygnus.domain import AudienceContext, LifecycleState, Visibility
from cygnus.domain.objects import AnswerCard, EscalationRoute, KnowledgeObject, KnownIssuePage, PolicyRule, TroubleshootingFlow
from cygnus.recovery import DownstreamRealityCheckQuery, get_downstream_reality_check_surface
from cygnus.retrieval import (
    EvidenceIndex,
    KnowledgeObjectIndex,
    sample_knowledge_objects,
    sample_support_evidence,
    slugify,
)
from cygnus.review.drift import get_drift_governance_surface
from cygnus.review.fixtures import sample_review_bundles
from cygnus.substrate.agent_protocol import ToolDefinition
from cygnus.substrate.tool_runtime import ToolRegistry


@lru_cache(maxsize=1)
def _knowledge_object_index() -> KnowledgeObjectIndex:
    return KnowledgeObjectIndex(sample_knowledge_objects(), sample_support_evidence())


@lru_cache(maxsize=1)
def _evidence_index() -> EvidenceIndex:
    return EvidenceIndex(sample_support_evidence())



def search_knowledge_objects(
    *,
    query: str,
    audience_context: dict[str, Any] | None = None,
    object_types: list[str] | None = None,
    limit: int = 10,
    include_unpublished: bool = False,
) -> dict[str, Any]:
    runtime_context = _audience_context_from_payload(audience_context)
    results = _knowledge_object_index().search(
        query=query,
        audience_context=runtime_context,
        object_types=object_types,
        limit=limit,
        include_unpublished=include_unpublished,
    )
    return {
        "status": "success",
        "summary": f"{len(results)} matching knowledge objects found",
        "data": {
            "query": query,
            "audience_context": audience_context or {},
            "object_types": object_types or [],
            "limit": limit,
            "include_unpublished": include_unpublished,
            "results": [item.to_dict() for item in results],
        },
        "warnings": [],
        "errors": [],
    }



def read_knowledge_object(
    *,
    id_or_slug: str,
    include_variants: bool = True,
    include_trace: bool = True,
) -> dict[str, Any]:
    object_ = _knowledge_object_index().read(id_or_slug)
    if object_ is None:
        return {
            "status": "not_found",
            "summary": f"Knowledge object not found: {id_or_slug}",
            "data": {"id_or_slug": id_or_slug},
            "warnings": [],
            "errors": ["not_found"],
        }

    payload = object_.to_dict()
    if not include_variants and "audience_variants" in payload:
        payload.pop("audience_variants")

    payload.update(
        {
            "slug": slugify(object_.title),
            "version": 1,
            "allowed_channels": list(_allowed_channels_for(object_)),
        }
    )

    if include_trace:
        trace = _knowledge_object_index().trace_resolver.build_trace_for_object(object_)
        payload["source_trace_summary"] = trace.summary()

    return {
        "status": "success",
        "summary": f"Knowledge object loaded: {object_.title}",
        "data": payload,
        "warnings": [],
        "errors": [],
    }



def search_support_evidence(
    *,
    query: str,
    filters: dict[str, Any] | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    results = _evidence_index().search(query=query, filters=filters, limit=limit)
    return {
        "status": "success",
        "summary": f"{len(results)} matching evidence records found",
        "data": {
            "query": query,
            "filters": filters or {},
            "limit": limit,
            "results": [item.to_dict() for item in results],
        },
        "warnings": [],
        "errors": [],
    }



def get_source_trace(*, object_id: str) -> dict[str, Any]:
    trace = _knowledge_object_index().trace_resolver.get_trace(object_id)
    if trace is None:
        return {
            "status": "not_found",
            "summary": f"Source trace not found: {object_id}",
            "data": {"object_id": object_id},
            "warnings": [],
            "errors": ["trace_unavailable"],
        }

    warnings = list(trace.blind_spots)
    return {
        "status": "success",
        "summary": f"Source trace loaded for {object_id}",
        "data": trace.to_dict(),
        "warnings": warnings,
        "errors": [],
    }



def propose_knowledge_object(
    *,
    object_type: str,
    title: str,
    summary: str,
    evidence_ids: list[str],
) -> dict[str, Any]:
    return {
        "status": "success",
        "summary": f"Draft proposal created for {object_type}",
        "data": {
            "draft_id": f"draft:{title.strip().lower().replace(' ', '-')}",
            "object_type": object_type,
            "title": title,
            "summary": summary,
            "evidence_ids": evidence_ids,
            "lifecycle_state": LifecycleState.DRAFT.value,
        },
        "warnings": [],
        "errors": [],
    }



def request_review(*, draft_id: str) -> dict[str, Any]:
    return {
        "status": "success",
        "summary": f"Review requested for {draft_id}",
        "data": {
            "draft_id": draft_id,
            "review_status": "requested",
        },
        "warnings": [],
        "errors": [],
    }



def validate_publish_policy(*, draft_id: str, target_channel: str) -> dict[str, Any]:
    return {
        "status": "success",
        "summary": f"Publish policy validated for {draft_id}",
        "data": {
            "draft_id": draft_id,
            "target_channel": target_channel,
            "approval_required": target_channel != "internal_copilot",
            "policy_status": "ready_for_review",
        },
        "warnings": [],
        "errors": [],
    }



def publish_knowledge_object(*, draft_id: str, target_channel: str) -> dict[str, Any]:
    return {
        "status": "approval_required" if target_channel != "internal_copilot" else "success",
        "summary": f"Publish request recorded for {draft_id}",
        "data": {
            "draft_id": draft_id,
            "target_channel": target_channel,
            "publish_state": "queued_for_approval"
            if target_channel != "internal_copilot"
            else "published_internal",
        },
        "warnings": [],
        "errors": [],
    }



def list_drift_alerts(*, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    surface = get_drift_governance_surface(bundles=sample_review_bundles())
    payload = surface.to_dict()
    return {
        "status": "success",
        "summary": "Drift alerts listed from Cygnus governance surface",
        "data": {
            "filters": filters or {},
            "alert_count": len(payload["contexts"]),
            "alerts": payload["contexts"],
        },
        "warnings": [],
        "errors": [],
    }


def get_downstream_reality_check(*, command_id: str) -> dict[str, Any]:
    surface = get_downstream_reality_check_surface(
        DownstreamRealityCheckQuery(command_id=command_id)
    )
    payload = surface.to_dict()
    return {
        "status": "success",
        "summary": f"Downstream reality check loaded for {command_id}",
        "data": payload,
        "warnings": [],
        "errors": [],
    }



def build_default_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for definition, handler in _tool_bindings():
        registry.register(definition, handler)
    return registry



def _tool_bindings() -> tuple[tuple[ToolDefinition, Any], ...]:
    return (
        (
            ToolDefinition(
                name="search_knowledge_objects",
                description="Search Cygnus knowledge objects with audience-aware filtering.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "audience_context": {"type": "object"},
                        "object_types": {"type": "array", "items": {"type": "string"}},
                        "limit": {"type": "integer"},
                        "include_unpublished": {"type": "boolean"},
                    },
                    "required": ["query"],
                },
                risk_level="R0",
            ),
            search_knowledge_objects,
        ),
        (
            ToolDefinition(
                name="get_downstream_reality_check",
                description="Return frontline recovery feedback for a specific governance command.",
                parameters={
                    "type": "object",
                    "properties": {
                        "command_id": {"type": "string"},
                    },
                    "required": ["command_id"],
                },
                risk_level="R0",
            ),
            get_downstream_reality_check,
        ),
        (
            ToolDefinition(
                name="read_knowledge_object",
                description="Read a single Cygnus knowledge object with optional trace summary.",
                parameters={
                    "type": "object",
                    "properties": {
                        "id_or_slug": {"type": "string"},
                        "include_variants": {"type": "boolean"},
                        "include_trace": {"type": "boolean"},
                    },
                    "required": ["id_or_slug"],
                },
                risk_level="R0",
            ),
            read_knowledge_object,
        ),
        (
            ToolDefinition(
                name="search_support_evidence",
                description="Search support evidence without collapsing to object-level truth.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "filters": {"type": "object"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["query"],
                },
                risk_level="R0",
            ),
            search_support_evidence,
        ),
        (
            ToolDefinition(
                name="get_source_trace",
                description="Return the governed source trace for a Cygnus knowledge object.",
                parameters={
                    "type": "object",
                    "properties": {
                        "object_id": {"type": "string"},
                    },
                    "required": ["object_id"],
                },
                risk_level="R0",
            ),
            get_source_trace,
        ),
        (
            ToolDefinition(
                name="propose_knowledge_object",
                description="Create a Cygnus draft proposal without publishing it.",
                parameters={
                    "type": "object",
                    "properties": {
                        "object_type": {"type": "string"},
                        "title": {"type": "string"},
                        "summary": {"type": "string"},
                        "evidence_ids": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["object_type", "title", "summary", "evidence_ids"],
                },
                risk_level="R1",
            ),
            propose_knowledge_object,
        ),
        (
            ToolDefinition(
                name="request_review",
                description="Move a draft into the Cygnus review path.",
                parameters={
                    "type": "object",
                    "properties": {
                        "draft_id": {"type": "string"},
                    },
                    "required": ["draft_id"],
                },
                risk_level="R1",
            ),
            request_review,
        ),
        (
            ToolDefinition(
                name="validate_publish_policy",
                description="Check Cygnus publish policy before commit.",
                parameters={
                    "type": "object",
                    "properties": {
                        "draft_id": {"type": "string"},
                        "target_channel": {"type": "string"},
                    },
                    "required": ["draft_id", "target_channel"],
                },
                risk_level="R2",
            ),
            validate_publish_policy,
        ),
        (
            ToolDefinition(
                name="publish_knowledge_object",
                description="Request Cygnus publish execution through a governed boundary.",
                parameters={
                    "type": "object",
                    "properties": {
                        "draft_id": {"type": "string"},
                        "target_channel": {"type": "string"},
                    },
                    "required": ["draft_id", "target_channel"],
                },
                risk_level="R3",
            ),
            publish_knowledge_object,
        ),
        (
            ToolDefinition(
                name="list_drift_alerts",
                description="Read governance drift alerts through the Cygnus domain surface.",
                parameters={
                    "type": "object",
                    "properties": {
                        "filters": {"type": "object"},
                    },
                },
                risk_level="R0",
            ),
            list_drift_alerts,
        ),
    )



def _audience_context_from_payload(payload: dict[str, Any] | None) -> AudienceContext | None:
    if payload is None:
        return None

    visibility_value = payload.get("visibility")
    if visibility_value is None:
        return None

    normalized = dict(payload)
    if "plan_tier" in normalized and "plan" not in normalized:
        normalized["plan"] = normalized.pop("plan_tier")

    return AudienceContext(
        visibility=Visibility(visibility_value),
        brand=normalized.get("brand"),
        product_line=normalized.get("product_line"),
        plan=normalized.get("plan"),
        region=normalized.get("region"),
        language=normalized.get("language"),
        product_version=normalized.get("product_version"),
    )



def _allowed_channels_for(object_: KnowledgeObject) -> tuple[str, ...]:
    if isinstance(object_, AnswerCard):
        return object_.publish_targets
    if isinstance(object_, PolicyRule):
        return ("copilot", "review_console")
    if isinstance(object_, KnownIssuePage):
        return ("help_center", "copilot")
    if isinstance(object_, TroubleshootingFlow):
        return ("copilot",)
    if isinstance(object_, EscalationRoute):
        return ("copilot", "queue-sidebar")
    return ()
