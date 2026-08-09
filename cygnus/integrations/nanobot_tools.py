from __future__ import annotations

from typing import Any

from cygnus.domain import AudienceContext, Visibility
from cygnus.domain.objects import (
    AnswerCard,
    EscalationRoute,
    KnowledgeObject,
    KnownIssuePage,
    PolicyRule,
    TroubleshootingFlow,
)
from cygnus.retrieval import (
    EvidenceIndex,
    KnowledgeObjectIndex,
    SubstrateKnowledgeSnapshot,
    slugify,
)
from cygnus.retrieval.contracts import KnowledgeObjectHit, SourceTrace
from cygnus.substrate.agent_protocol import ToolDefinition
from cygnus.substrate.tool_runtime import ToolRegistry


class GovernedKnowledgeTools:
    """Request-scoped implementation of Cygnus' governed retrieval tools."""

    __slots__ = ("_evidence_index", "_object_index")

    def __init__(self, snapshot: SubstrateKnowledgeSnapshot) -> None:
        self._object_index = KnowledgeObjectIndex(snapshot.objects, snapshot.evidence)
        self._evidence_index = EvidenceIndex(snapshot.evidence)

    def search_hits(
        self,
        *,
        query: str,
        audience_context: AudienceContext | None = None,
        object_types: list[str] | None = None,
        limit: int = 10,
        include_unpublished: bool = False,
    ) -> tuple[KnowledgeObjectHit, ...]:
        return self._object_index.search(
            query=query,
            audience_context=audience_context,
            object_types=object_types,
            limit=limit,
            include_unpublished=include_unpublished,
        )

    def read_object(self, id_or_slug: str) -> KnowledgeObject | None:
        return self._object_index.read(id_or_slug)

    def read_trace(self, object_id: str) -> SourceTrace | None:
        return self._object_index.trace_resolver.get_trace(object_id)

    def search_knowledge_objects(
        self,
        *,
        query: str,
        audience_context: dict[str, Any] | None = None,
        object_types: list[str] | None = None,
        limit: int = 10,
        include_unpublished: bool = False,
    ) -> dict[str, Any]:
        runtime_context = audience_context_from_payload(audience_context)
        results = self.search_hits(
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
        self,
        *,
        id_or_slug: str,
        include_variants: bool = True,
        include_trace: bool = True,
    ) -> dict[str, Any]:
        object_ = self.read_object(id_or_slug)
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
                "allowed_channels": list(allowed_channels_for(object_)),
            }
        )

        trace_ref = None
        if include_trace:
            trace = self._object_index.trace_resolver.build_trace_for_object(object_)
            payload["source_trace_summary"] = trace.summary()
            trace_ref = f"trace:{object_.object_id}"

        return {
            "status": "success",
            "summary": f"Knowledge object loaded: {object_.title}",
            "data": payload,
            "trace_ref": trace_ref,
            "warnings": [],
            "errors": [],
        }

    def search_support_evidence(
        self,
        *,
        query: str,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        results = self._evidence_index.search(query=query, filters=filters, limit=limit)
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

    def get_source_trace(self, *, object_id: str) -> dict[str, Any]:
        trace = self.read_trace(object_id)
        if trace is None:
            return {
                "status": "not_found",
                "summary": f"Source trace not found: {object_id}",
                "data": {"object_id": object_id},
                "warnings": [],
                "errors": ["trace_unavailable"],
            }

        return {
            "status": "success",
            "summary": f"Source trace loaded for {object_id}",
            "data": trace.to_dict(),
            "trace_ref": f"trace:{object_id}",
            "warnings": list(trace.blind_spots),
            "errors": [],
        }


def build_governed_tool_registry(snapshot: SubstrateKnowledgeSnapshot) -> ToolRegistry:
    """Build the truthful R0 tool surface for one permission-filtered request."""
    tools = GovernedKnowledgeTools(snapshot)
    registry = ToolRegistry()
    for definition, handler in tool_bindings(tools):
        registry.register(definition, handler)
    return registry


def tool_bindings(
    tools: GovernedKnowledgeTools,
) -> tuple[tuple[ToolDefinition, Any], ...]:
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
            tools.search_knowledge_objects,
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
            tools.read_knowledge_object,
        ),
        (
            ToolDefinition(
                name="search_support_evidence",
                description="Search support evidence without collapsing it to object truth.",
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
            tools.search_support_evidence,
        ),
        (
            ToolDefinition(
                name="get_source_trace",
                description="Return the governed source trace for a Cygnus knowledge object.",
                parameters={
                    "type": "object",
                    "properties": {"object_id": {"type": "string"}},
                    "required": ["object_id"],
                },
                risk_level="R0",
            ),
            tools.get_source_trace,
        ),
    )


def audience_context_from_payload(
    payload: dict[str, Any] | None,
) -> AudienceContext | None:
    if payload is None:
        return None

    visibility_value = payload.get("visibility")
    if visibility_value is None:
        return None

    return AudienceContext(
        visibility=Visibility(visibility_value),
        brand=payload.get("brand"),
        product_line=payload.get("product_line"),
        plan=payload.get("plan", payload.get("plan_tier")),
        region=payload.get("region"),
        language=payload.get("language"),
        product_version=payload.get("product_version"),
    )


def allowed_channels_for(object_: KnowledgeObject) -> tuple[str, ...]:
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
