from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypedDict

from cygnus.domain import AudienceContext, Visibility
from cygnus.domain.audience import audience_context_allowed
from cygnus.domain.lifecycle import LifecycleState
from cygnus.evidence.records import FreshnessState
from cygnus.domain.objects import AnswerCard, KnowledgeObject
from cygnus.retrieval import (
    EvidenceIndex,
    KnowledgeObjectIndex,
    SubstrateKnowledgeSnapshot,
    slugify,
)
from cygnus.retrieval.contracts import KnowledgeObjectHit, SourceTrace
from cygnus.substrate.agent_protocol import ToolDefinition
from cygnus.substrate.tool_runtime import ToolRegistry


class _KnowledgeSearchArguments(TypedDict):
    query: str
    audience_context: dict[str, str | None]
    channel: str
    object_types: list[str] | None
    limit: int


class _KnowledgeReadArguments(TypedDict):
    object_id: str
    audience_context: dict[str, str | None]
    channel: str
    include_variants: bool
    include_trace: bool


class _EvidenceSearchArguments(TypedDict):
    query: str
    audience_context: dict[str, str | None]
    channel: str
    filters: dict[str, str] | None
    limit: int


class _SourceTraceArguments(TypedDict):
    object_id: str
    audience_context: dict[str, str | None]
    channel: str


class GovernedKnowledgeTools:
    """Request-scoped implementation of the closed governed retrieval surface.

    Public methods require a strict audience and target channel, then recheck
    the current immutable object, publication, audience, delivery receipt, and
    audience-scoped freshness before projecting any answer-bearing content.
    Internal session-bridge helpers remain separate so it can produce its own
    restricted diagnostics without creating a public MCP escape hatch.
    """

    __slots__ = ("_evidence_index", "_object_index", "_objects_by_id", "_snapshot")

    def __init__(self, snapshot: SubstrateKnowledgeSnapshot) -> None:
        objects = tuple(snapshot.objects)
        self._snapshot = snapshot
        self._object_index = KnowledgeObjectIndex(
            objects,
            snapshot.evidence,
            persisted_truth_by_object=snapshot.persisted_truth_by_object,
            delivery_records_by_object=snapshot.delivery_records_by_object,
        )
        self._evidence_index = EvidenceIndex(snapshot.evidence)
        self._objects_by_id = {object_.object_id: object_ for object_ in objects}

    def search_hits(
        self,
        *,
        query: str,
        audience_context: AudienceContext | None = None,
        object_types: list[str] | None = None,
        channel: str | None = None,
        limit: int = 10,
        include_unpublished: bool = False,
        match_audience: bool = True,
    ) -> tuple[KnowledgeObjectHit, ...]:
        """Internal session bridge search; not a public MCP parameter surface."""
        return self._object_index.search(
            query=query,
            audience_context=audience_context,
            object_types=object_types,
            limit=limit,
            include_unpublished=include_unpublished,
            channel=channel,
            match_audience=match_audience,
        )

    def read_object(self, object_id: str) -> KnowledgeObject | None:
        """Resolve only an exact immutable object ID; never resolve a slug."""
        return (
            self._objects_by_id.get(object_id) if isinstance(object_id, str) else None
        )

    def read_trace(
        self,
        object_id: str,
        *,
        audience_context: AudienceContext,
        channel: str,
    ) -> SourceTrace | None:
        """Return an audience-filtered trace for an exact current object."""
        object_ = self._published_object_for_context(object_id, audience_context)
        if object_ is None:
            return None
        return self._object_index.trace_resolver.build_trace_for_object(
            object_,
            audience_context=audience_context,
            channel=channel,
        )

    def search_knowledge_objects(
        self,
        *,
        query: str,
        audience_context: dict[str, Any],
        channel: str,
        object_types: list[str] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        try:
            normalized_query = _required_text(query, label="query", max_length=4_000)
            runtime_context = _required_audience_context(audience_context)
            normalized_channel = _required_text(
                channel, label="channel", max_length=120
            )
            normalized_object_types = _normalize_object_types(object_types)
            normalized_limit = _normalize_limit(limit)
        except ValueError as exc:
            return _invalid_arguments(str(exc))

        hits = self.search_hits(
            query=normalized_query,
            audience_context=runtime_context,
            object_types=normalized_object_types,
            channel=normalized_channel,
            limit=normalized_limit,
        )
        eligible_hits = [
            hit
            for hit in hits
            if hit.freshness is FreshnessState.FRESH
            and self._is_answer_deliverable(
                hit.object_id,
                audience_context=runtime_context,
                channel=normalized_channel,
            )
        ]
        if hits and not eligible_hits:
            return _restricted_read()
        return {
            "status": "success",
            "summary": f"{len(eligible_hits)} matching knowledge objects found",
            "data": {
                "query": normalized_query,
                "audience_context": _audience_context_payload(runtime_context),
                "channel": normalized_channel,
                "object_types": normalized_object_types or [],
                "limit": normalized_limit,
                "results": [item.to_dict() for item in eligible_hits],
            },
            "warnings": [],
            "errors": [],
        }

    def read_knowledge_object(
        self,
        *,
        object_id: str,
        audience_context: dict[str, Any],
        channel: str,
        include_variants: bool = True,
        include_trace: bool = True,
    ) -> dict[str, Any]:
        try:
            normalized_object_id = _required_text(
                object_id, label="object_id", max_length=320
            )
            runtime_context = _required_audience_context(audience_context)
            normalized_channel = _required_text(
                channel, label="channel", max_length=120
            )
            _require_bool(include_variants, label="include_variants")
            _require_bool(include_trace, label="include_trace")
        except ValueError as exc:
            return _invalid_arguments(str(exc))
        object_ = self._published_object_for_context(
            normalized_object_id, runtime_context
        )
        if object_ is None:
            return _unavailable_object(normalized_object_id, label="Knowledge object")
        if not self._delivery_is_current(
            object_.object_id,
            audience_context=runtime_context,
            channel=normalized_channel,
        ):
            return _restricted_read()
        trace = self.read_trace(
            object_.object_id,
            audience_context=runtime_context,
            channel=normalized_channel,
        )
        if trace is None:
            return _unavailable_object(normalized_object_id, label="Knowledge object")
        if trace.freshness is not FreshnessState.FRESH:
            return _restricted_read()

        payload = object_.to_dict()
        if isinstance(object_, AnswerCard):
            payload["audience_variants"] = (
                [
                    variant.to_dict()
                    for variant in object_.audience_variants
                    if variant.audience_filter.matches(runtime_context)
                ]
                if include_variants
                else []
            )
        payload.update(
            {
                "slug": slugify(object_.title),
                "version": trace.version,
            }
        )
        if include_trace:
            payload["source_trace_summary"] = trace.summary()

        return {
            "status": "success",
            "summary": f"Knowledge object loaded: {object_.title}",
            "data": payload,
            "trace_ref": f"trace:{object_.object_id}",
            "warnings": [],
            "errors": [],
        }

    def search_support_evidence(
        self,
        *,
        query: str,
        audience_context: dict[str, Any],
        channel: str,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        try:
            normalized_query = _required_text(query, label="query", max_length=4_000)
            runtime_context = _required_audience_context(audience_context)
            normalized_channel = _required_text(
                channel, label="channel", max_length=120
            )
            normalized_filters = _normalize_evidence_filters(filters)
            normalized_limit = _normalize_limit(limit)
        except ValueError as exc:
            return _invalid_arguments(str(exc))
        hits = self._evidence_index.search(
            query=normalized_query,
            audience_context=runtime_context,
            filters=normalized_filters,
            limit=normalized_limit,
        )
        eligible_hits = [
            hit
            for hit in hits
            if hit.freshness is FreshnessState.FRESH
            and self._evidence_is_deliverable(
                hit.evidence_id,
                audience_context=runtime_context,
                channel=normalized_channel,
            )
        ]
        if hits and not eligible_hits:
            return _restricted_read()
        return {
            "status": "success",
            "summary": f"{len(eligible_hits)} matching evidence records found",
            "data": {
                "query": normalized_query,
                "audience_context": _audience_context_payload(runtime_context),
                "channel": normalized_channel,
                "filters": normalized_filters or {},
                "limit": normalized_limit,
                "results": [item.to_dict() for item in eligible_hits],
            },
            "warnings": [],
            "errors": [],
        }

    def get_source_trace(
        self,
        *,
        object_id: str,
        audience_context: dict[str, Any],
        channel: str,
    ) -> dict[str, Any]:
        try:
            normalized_object_id = _required_text(
                object_id, label="object_id", max_length=320
            )
            runtime_context = _required_audience_context(audience_context)
            normalized_channel = _required_text(
                channel, label="channel", max_length=120
            )
        except ValueError as exc:
            return _invalid_arguments(str(exc))
        object_ = self._published_object_for_context(
            normalized_object_id, runtime_context
        )
        if object_ is None:
            return _unavailable_object(normalized_object_id, label="Source trace")
        if not self._delivery_is_current(
            object_.object_id,
            audience_context=runtime_context,
            channel=normalized_channel,
        ):
            return _restricted_read()
        trace = self.read_trace(
            object_.object_id,
            audience_context=runtime_context,
            channel=normalized_channel,
        )
        if trace is None:
            return _unavailable_object(normalized_object_id, label="Source trace")
        if trace.freshness is not FreshnessState.FRESH:
            return _restricted_read()
        return {
            "status": "success",
            "summary": "Source trace loaded.",
            "data": trace.to_dict(),
            "trace_ref": f"trace:{normalized_object_id}",
            "warnings": list(trace.blind_spots),
            "errors": [],
        }

    def _published_object_for_context(
        self,
        object_id: str,
        audience_context: AudienceContext,
    ) -> KnowledgeObject | None:
        object_ = self.read_object(object_id)
        if object_ is None or object_.lifecycle_state is not LifecycleState.PUBLISHED:
            return None
        if not audience_context_allowed(audience_context, object_.supported_audiences):
            return None
        return object_

    def _delivery_is_current(
        self,
        object_id: str,
        *,
        audience_context: AudienceContext,
        channel: str,
    ) -> bool:
        try:
            return self._snapshot.delivery_verdict(
                object_id,
                channel=channel,
                audience_context=audience_context,
            )
        except Exception:
            # Missing truth, stale projection, and invalid delivery state are
            # indistinguishable to the caller and never authorize content.
            return False

    def _is_answer_deliverable(
        self,
        object_id: str,
        *,
        audience_context: AudienceContext,
        channel: str,
    ) -> bool:
        object_ = self._published_object_for_context(object_id, audience_context)
        if object_ is None or not self._delivery_is_current(
            object_id,
            audience_context=audience_context,
            channel=channel,
        ):
            return False
        trace = self.read_trace(
            object_id,
            audience_context=audience_context,
            channel=channel,
        )
        return trace is not None and trace.freshness is FreshnessState.FRESH

    def _evidence_is_deliverable(
        self,
        evidence_id: str,
        *,
        audience_context: AudienceContext,
        channel: str,
    ) -> bool:
        try:
            if not self._snapshot.evidence_delivery_verdict(
                evidence_id,
                channel=channel,
                audience_context=audience_context,
            ):
                return False
        except Exception:
            # A missing or malformed binding must not inherit an object-level
            # delivery acknowledgement.
            return False
        for object_ in self._objects_by_id.values():
            linked_evidence_ids = set(object_.evidence_ids)
            if isinstance(object_, AnswerCard):
                linked_evidence_ids.update(
                    evidence_id
                    for variant in object_.audience_variants
                    if variant.audience_filter.matches(audience_context)
                    for evidence_id in variant.evidence_ids
                )
            if evidence_id not in linked_evidence_ids:
                continue
            if self._is_answer_deliverable(
                object_.object_id,
                audience_context=audience_context,
                channel=channel,
            ):
                return True
        return False


def _invalid_arguments(summary: str) -> dict[str, Any]:
    return {
        "status": "invalid",
        "summary": summary,
        "data": {},
        "warnings": [],
        "errors": ["invalid_arguments"],
    }


def _required_text(value: object, *, label: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} must not be blank")
    if len(normalized) > max_length:
        raise ValueError(f"{label} must be at most {max_length} characters")
    return normalized


def _require_bool(value: object, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean")
    return value


def _normalize_limit(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 50:
        raise ValueError("limit must be an integer between 1 and 50")
    return value


def _normalize_object_types(value: object) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > 10:
        raise ValueError("object_types must contain at most 10 strings")
    return [
        _required_text(item, label="object_types item", max_length=64) for item in value
    ]


def _unavailable_object(object_id: object, *, label: str) -> dict[str, Any]:
    return {
        "status": "not_found",
        "summary": f"{label} is unavailable.",
        "data": {"object_id": object_id},
        "warnings": [],
        "errors": ["not_found"],
    }


def _restricted_read() -> dict[str, Any]:
    """Fail closed without distinguishing delivery, freshness, or binding state."""
    return {
        "status": "restricted",
        "summary": "Governed content is not currently available for the requested audience and channel.",
        "data": {},
        "warnings": [],
        "errors": ["not_currently_deliverable"],
    }


def build_governed_tool_registry(snapshot: SubstrateKnowledgeSnapshot) -> ToolRegistry:
    """Build the truthful R0 tool surface for one permission-filtered request."""
    tools = GovernedKnowledgeTools(snapshot)
    registry = ToolRegistry()
    for definition, handler in tool_bindings(tools):
        registry.register(definition, handler)
    return registry


def knowledge_tool_definitions() -> tuple[ToolDefinition, ...]:
    """Return the stable governed retrieval contract without binding request state."""
    return _KNOWLEDGE_TOOL_DEFINITIONS


def tool_bindings(
    tools: GovernedKnowledgeTools,
) -> tuple[tuple[ToolDefinition, Any], ...]:
    return tuple(
        zip(
            knowledge_tool_definitions(),
            (
                tools.search_knowledge_objects,
                tools.read_knowledge_object,
                tools.search_support_evidence,
                tools.get_source_trace,
            ),
            strict=True,
        )
    )


_AUDIENCE_CONTEXT_KEYS = frozenset(
    {
        "visibility",
        "brand",
        "product_line",
        "plan_tier",
        "region",
        "language",
        "product_version",
    }
)
_EVIDENCE_FILTER_KEYS = frozenset(
    {"source_type", "product_line", "plan", "region", "language", "product_version"}
)
_EVIDENCE_SOURCE_TYPES = frozenset(
    {
        "help_center",
        "internal_sop",
        "resolved_ticket",
        "release_note",
        "incident_update",
        "chat_transcript",
        "consumption_feedback",
    }
)


def audience_context_from_payload(
    payload: Mapping[str, Any] | None,
) -> AudienceContext | None:
    """Parse the one canonical audience payload shape without aliases."""
    if payload is None:
        return None
    if not isinstance(payload, Mapping):
        raise ValueError("audience_context must be an object")
    unknown = sorted(set(payload) - _AUDIENCE_CONTEXT_KEYS)
    if unknown:
        raise ValueError(
            f"audience_context contains unsupported fields: {', '.join(unknown)}"
        )
    visibility_value = payload.get("visibility")
    if visibility_value is None:
        return None
    if not isinstance(visibility_value, str) or visibility_value not in {
        item.value for item in Visibility
    }:
        raise ValueError("audience_context.visibility is invalid")

    def dimension(name: str) -> str | None:
        value = payload.get(name)
        if value is None:
            return None
        return _required_text(
            value,
            label=f"audience_context.{name}",
            max_length=200,
        )

    return AudienceContext(
        visibility=Visibility(visibility_value),
        brand=dimension("brand"),
        product_line=dimension("product_line"),
        plan=dimension("plan_tier"),
        region=dimension("region"),
        language=dimension("language"),
        product_version=dimension("product_version"),
    )


def _required_audience_context(payload: Mapping[str, Any] | None) -> AudienceContext:
    context = audience_context_from_payload(payload)
    if context is None:
        raise ValueError("audience_context.visibility is required")
    return context


def _audience_context_payload(context: AudienceContext) -> dict[str, str | None]:
    return {
        "visibility": context.visibility.value,
        "brand": context.brand,
        "product_line": context.product_line,
        "plan_tier": context.plan,
        "region": context.region,
        "language": context.language,
        "product_version": context.product_version,
    }


def _normalize_evidence_filters(
    filters: Mapping[str, Any] | None,
) -> dict[str, str] | None:
    if filters is None:
        return None
    if not isinstance(filters, Mapping):
        raise ValueError("filters must be an object")
    unknown = sorted(set(filters) - _EVIDENCE_FILTER_KEYS)
    if unknown:
        raise ValueError(f"filters contain unsupported fields: {', '.join(unknown)}")
    normalized: dict[str, str] = {}
    for name, value in filters.items():
        if value is None:
            continue
        normalized_value = _required_text(
            value,
            label=f"filters.{name}",
            max_length=200,
        )
        if name == "source_type" and normalized_value not in _EVIDENCE_SOURCE_TYPES:
            raise ValueError("filters.source_type is invalid")
        normalized[name] = normalized_value
    return normalized


def _required_audience_payload(value: object) -> dict[str, str | None]:
    if value is None:
        context = _required_audience_context(None)
    elif isinstance(value, Mapping):
        context = _required_audience_context(value)
    else:
        raise ValueError("audience_context must be an object")
    return _audience_context_payload(context)


def _normalized_evidence_filters(value: object | None) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("filters must be an object")
    return _normalize_evidence_filters(value)


def normalize_knowledge_search_arguments(
    *,
    query: object,
    audience_context: object,
    channel: object,
    object_types: object | None = None,
    limit: object = 10,
) -> _KnowledgeSearchArguments:
    """Validate raw MCP search arguments into the typed adapter contract."""
    return _KnowledgeSearchArguments(
        query=_required_text(query, label="query", max_length=4_000),
        audience_context=_required_audience_payload(audience_context),
        channel=_required_text(channel, label="channel", max_length=120),
        object_types=_normalize_object_types(object_types),
        limit=_normalize_limit(limit),
    )


def normalize_knowledge_read_arguments(
    *,
    object_id: object,
    audience_context: object,
    channel: object,
    include_variants: object = True,
    include_trace: object = True,
) -> _KnowledgeReadArguments:
    """Validate raw MCP read arguments into the typed adapter contract."""
    return _KnowledgeReadArguments(
        object_id=_required_text(object_id, label="object_id", max_length=320),
        audience_context=_required_audience_payload(audience_context),
        channel=_required_text(channel, label="channel", max_length=120),
        include_variants=_require_bool(include_variants, label="include_variants"),
        include_trace=_require_bool(include_trace, label="include_trace"),
    )


def normalize_evidence_search_arguments(
    *,
    query: object,
    audience_context: object,
    channel: object,
    filters: object | None = None,
    limit: object = 10,
) -> _EvidenceSearchArguments:
    """Validate raw MCP evidence arguments into the typed adapter contract."""
    return _EvidenceSearchArguments(
        query=_required_text(query, label="query", max_length=4_000),
        audience_context=_required_audience_payload(audience_context),
        channel=_required_text(channel, label="channel", max_length=120),
        filters=_normalized_evidence_filters(filters),
        limit=_normalize_limit(limit),
    )


def normalize_source_trace_arguments(
    *,
    object_id: object,
    audience_context: object,
    channel: object,
) -> _SourceTraceArguments:
    """Validate raw MCP trace arguments into the typed adapter contract."""
    return _SourceTraceArguments(
        object_id=_required_text(object_id, label="object_id", max_length=320),
        audience_context=_required_audience_payload(audience_context),
        channel=_required_text(channel, label="channel", max_length=120),
    )


def allowed_channels_for(object_: KnowledgeObject) -> tuple[str, ...]:
    """Return only channels explicitly carried by the object fixture."""
    return object_.publish_targets if isinstance(object_, AnswerCard) else ()


_AUDIENCE_CONTEXT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "minProperties": 1,
    "properties": {
        "visibility": {"type": "string", "enum": ["internal", "external"]},
        "brand": {"type": "string", "minLength": 1, "maxLength": 200},
        "product_line": {"type": "string", "minLength": 1, "maxLength": 200},
        "plan_tier": {"type": "string", "minLength": 1, "maxLength": 200},
        "region": {"type": "string", "minLength": 1, "maxLength": 200},
        "language": {"type": "string", "minLength": 1, "maxLength": 200},
        "product_version": {"type": "string", "minLength": 1, "maxLength": 200},
    },
    "required": ["visibility"],
}
_EVIDENCE_FILTER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "source_type": {"type": "string", "enum": sorted(_EVIDENCE_SOURCE_TYPES)},
        "product_line": {"type": "string", "minLength": 1, "maxLength": 200},
        "plan": {"type": "string", "minLength": 1, "maxLength": 200},
        "region": {"type": "string", "minLength": 1, "maxLength": 200},
        "language": {"type": "string", "minLength": 1, "maxLength": 200},
        "product_version": {"type": "string", "minLength": 1, "maxLength": 200},
    },
}


_KNOWLEDGE_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="search_knowledge_objects",
        description="Search only current delivered Cygnus knowledge for one required audience and channel.",
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 4_000},
                "audience_context": _AUDIENCE_CONTEXT_SCHEMA,
                "channel": {"type": "string", "minLength": 1, "maxLength": 120},
                "object_types": {
                    "type": "array",
                    "maxItems": 10,
                    "items": {"type": "string", "minLength": 1, "maxLength": 64},
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "required": ["query", "audience_context", "channel"],
        },
        risk_level="R0",
    ),
    ToolDefinition(
        name="read_knowledge_object",
        description="Read one current delivered Cygnus object by immutable ID, audience, and channel.",
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "object_id": {"type": "string", "minLength": 1, "maxLength": 320},
                "audience_context": _AUDIENCE_CONTEXT_SCHEMA,
                "channel": {"type": "string", "minLength": 1, "maxLength": 120},
                "include_variants": {"type": "boolean"},
                "include_trace": {"type": "boolean"},
            },
            "required": ["object_id", "audience_context", "channel"],
        },
        risk_level="R0",
    ),
    ToolDefinition(
        name="search_support_evidence",
        description="Search evidence backed by current delivered knowledge for one audience and channel.",
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 4_000},
                "audience_context": _AUDIENCE_CONTEXT_SCHEMA,
                "channel": {"type": "string", "minLength": 1, "maxLength": 120},
                "filters": _EVIDENCE_FILTER_SCHEMA,
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "required": ["query", "audience_context", "channel"],
        },
        risk_level="R0",
    ),
    ToolDefinition(
        name="get_source_trace",
        description="Return a source trace only for current delivered Cygnus truth.",
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "object_id": {"type": "string", "minLength": 1, "maxLength": 320},
                "audience_context": _AUDIENCE_CONTEXT_SCHEMA,
                "channel": {"type": "string", "minLength": 1, "maxLength": 120},
            },
            "required": ["object_id", "audience_context", "channel"],
        },
        risk_level="R0",
    ),
)
