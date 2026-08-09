from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, final

from cygnus.domain import AudienceContext
from cygnus.domain.objects import (
    AnswerCard,
    EscalationRoute,
    KnowledgeObject,
    KnownIssuePage,
    PolicyRule,
    TroubleshootingFlow,
)
from cygnus.evidence.records import FreshnessState
from cygnus.integrations.nanobot_tools import (
    GovernedKnowledgeTools,
    allowed_channels_for,
    build_governed_tool_registry,
)
from cygnus.retrieval import SubstrateKnowledgeSnapshot
from cygnus.retrieval.contracts import KnowledgeObjectHit, SourceTrace


class GovernanceDisposition(str, Enum):
    ANSWERABLE = "answerable"
    RESTRICTED = "restricted"
    FALLBACK = "fallback"
    ESCALATE = "escalate"


class ContinuityDisposition(str, Enum):
    STARTED = "started"
    REVALIDATED = "revalidated"
    REFRESHED = "refreshed"
    INVALIDATED = "invalidated"


@dataclass(frozen=True, slots=True, kw_only=True)
class PriorGovernanceContext:
    governance_state: GovernanceDisposition
    audience_context: AudienceContext
    object_id: str | None = None
    object_version: int | None = None
    trace_ref: str | None = None
    freshness: FreshnessState | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class GovernedQueryRequest:
    request_ref: str
    query: str
    audience_context: AudienceContext
    session_ref: str | None = None
    object_types: tuple[str, ...] = ()
    limit: int = 5
    previous_governance_context: PriorGovernanceContext | None = None

    def __post_init__(self) -> None:
        if not self.request_ref.strip():
            raise ValueError("request_ref must not be blank")
        if not self.query.strip():
            raise ValueError("query must not be blank")
        if self.session_ref is not None and not self.session_ref.strip():
            raise ValueError("session_ref must not be blank when provided")
        if not 1 <= self.limit <= 10:
            raise ValueError("limit must be between 1 and 10")
        object.__setattr__(self, "object_types", tuple(self.object_types))


@final
class GovernedSessionBridge:
    """Cygnus-owned query handoff; Nanobot remains the session owner."""

    __slots__ = ("_tools",)
    _tools: GovernedKnowledgeTools

    def __init__(self, snapshot: SubstrateKnowledgeSnapshot) -> None:
        self._tools = GovernedKnowledgeTools(snapshot)

    def query(self, request: GovernedQueryRequest) -> dict[str, Any]:
        hits = self._tools.search_hits(
            query=request.query,
            audience_context=request.audience_context,
            object_types=list(request.object_types),
            limit=request.limit,
        )
        if not hits:
            return self._no_answer_response(request)

        selected = hits[0]
        object_ = self._tools.read_object(selected.object_id)
        trace = self._tools.read_trace(selected.object_id)
        if object_ is None or trace is None:
            raise RuntimeError(
                "governed retrieval returned an unresolved object reference"
            )

        disposition, codes, directives, expose_content = _governance_decision(
            selected,
            trace,
        )
        current_context = _governance_context(
            request.audience_context,
            disposition=disposition,
            object_id=selected.object_id,
            object_version=trace.version,
            trace_ref=selected.trace_ref,
            freshness=trace.freshness,
        )
        continuity = _evaluate_continuity(
            request.previous_governance_context,
            current_context,
            request.audience_context,
        )
        answer = _answer_projection(
            object_,
            selected,
            request.audience_context,
            expose_content=expose_content,
            disposition=disposition,
        )
        tool_trace = (
            _tool_trace("search_knowledge_objects"),
            _tool_trace("read_knowledge_object", result_ref=selected.object_id),
            _tool_trace("get_source_trace", result_ref=selected.trace_ref),
        )

        return _envelope(
            request,
            status=_status_for(disposition),
            summary=_summary_for(disposition, object_.title),
            disposition=disposition,
            codes=codes,
            directives=directives,
            answer=answer,
            source_trace=trace.to_dict(),
            alternatives=tuple(hit.to_dict() for hit in hits[1:]),
            continuity=continuity,
            current_context=current_context,
            tool_trace=tool_trace,
            trace_ref=selected.trace_ref,
        )

    def _no_answer_response(self, request: GovernedQueryRequest) -> dict[str, Any]:
        unpublished_hits = self._tools.search_hits(
            query=request.query,
            audience_context=request.audience_context,
            object_types=list(request.object_types),
            limit=request.limit,
            include_unpublished=True,
        )
        any_audience_hits = self._tools.search_hits(
            query=request.query,
            audience_context=None,
            object_types=list(request.object_types),
            limit=request.limit,
        )

        if unpublished_hits:
            disposition = GovernanceDisposition.RESTRICTED
            codes = ("pending_review",)
            directives = ("wait_for_review", "do_not_present_as_answered")
            summary = "A matching knowledge object exists but is not published."
        elif any_audience_hits:
            disposition = GovernanceDisposition.RESTRICTED
            codes = ("audience_restricted",)
            directives = ("do_not_expose_restricted_object", "offer_human_escalation")
            summary = (
                "Matching knowledge exists outside the requested audience boundary."
            )
        else:
            disposition = GovernanceDisposition.FALLBACK
            codes = ("no_governed_match", "fallback_suggested")
            directives = ("offer_human_escalation", "do_not_present_as_answered")
            summary = "No governed knowledge object can answer this query."

        current_context = _governance_context(
            request.audience_context,
            disposition=disposition,
        )
        continuity = _evaluate_continuity(
            request.previous_governance_context,
            current_context,
            request.audience_context,
        )
        return _envelope(
            request,
            status=_status_for(disposition),
            summary=summary,
            disposition=disposition,
            codes=codes,
            directives=directives,
            answer=None,
            source_trace=None,
            alternatives=(),
            continuity=continuity,
            current_context=current_context,
            tool_trace=(_tool_trace("search_knowledge_objects"),),
            trace_ref=None,
        )


def session_bridge_capabilities(
    snapshot: SubstrateKnowledgeSnapshot,
) -> dict[str, object]:
    registry = build_governed_tool_registry(snapshot)
    return {
        "contract_version": "2026-08-08",
        "owners": {
            "session_continuity": "nanobot",
            "knowledge_truth": "cygnus",
            "approval_truth": "cygnus",
        },
        "query_handoff": {
            "endpoint": "/api/session-bridge/query",
            "audience_context_required": True,
            "revalidates_every_query": True,
            "session_memory_is_truth": False,
        },
        "governed_tools": [
            {
                "name": definition.name,
                "description": definition.description,
                "risk_level": definition.risk_level,
                "parameters": definition.parameters,
                "availability": "ready",
            }
            for definition in registry.list_definitions()
        ],
        "not_exposed": [
            {
                "name": name,
                "availability": "not_exposed",
                "reason": "durable_governance_command_adapter_required",
            }
            for name in (
                "propose_knowledge_object",
                "update_draft_object",
                "request_review",
                "read_review_feedback",
                "validate_publish_policy",
                "publish_knowledge_object",
                "list_drift_alerts",
                "record_feedback_signal",
            )
        ],
    }


def _governance_decision(
    hit: KnowledgeObjectHit,
    trace: SourceTrace,
) -> tuple[GovernanceDisposition, tuple[str, ...], tuple[str, ...], bool]:
    severe_blind_spots = tuple(
        blind_spot
        for blind_spot in trace.blind_spots
        if blind_spot == "object_has_no_evidence"
        or blind_spot.startswith("missing_evidence:")
    )
    if severe_blind_spots:
        return (
            GovernanceDisposition.ESCALATE,
            ("source_blindness", *severe_blind_spots, "escalate_required"),
            ("withhold_answer_content", "escalate_to_human"),
            False,
        )

    codes: list[str] = []
    if hit.audience_match == "partial":
        codes.append("partial_audience_match")

    if trace.freshness is FreshnessState.STALE:
        codes.extend(("stale_evidence", "fallback_suggested"))
        return (
            GovernanceDisposition.RESTRICTED,
            tuple(codes),
            ("show_governance_warning", "require_human_check_before_external_use"),
            True,
        )
    if trace.freshness is FreshnessState.UNKNOWN:
        codes.extend(("freshness_unknown", "fallback_suggested"))
        return (
            GovernanceDisposition.RESTRICTED,
            tuple(codes),
            ("show_governance_warning", "require_human_check_before_external_use"),
            True,
        )

    return (
        GovernanceDisposition.ANSWERABLE,
        tuple(codes),
        ("answer_from_governed_object",),
        True,
    )


def _answer_projection(
    object_: KnowledgeObject,
    hit: KnowledgeObjectHit,
    audience_context: AudienceContext,
    *,
    expose_content: bool,
    disposition: GovernanceDisposition,
) -> dict[str, object]:
    content = _object_content(object_, audience_context) if expose_content else None
    return {
        **hit.to_dict(),
        "content": content,
        "allowed_channels": list(allowed_channels_for(object_)),
        "usage": (
            "direct"
            if disposition is GovernanceDisposition.ANSWERABLE
            else "internal_reference_only"
            if expose_content
            else "withheld"
        ),
        "direct_external_use": disposition is GovernanceDisposition.ANSWERABLE,
    }


def _object_content(
    object_: KnowledgeObject,
    audience_context: AudienceContext,
) -> dict[str, object]:
    if isinstance(object_, AnswerCard):
        variant = next(
            (
                candidate
                for candidate in object_.audience_variants
                if candidate.audience_filter.matches(audience_context)
            ),
            None,
        )
        return {
            "answer": variant.content
            if variant is not None
            else object_.canonical_answer,
            "variant_label": variant.label if variant is not None else None,
            "caveats": list(variant.caveats) if variant is not None else [],
            "constraints": list(object_.constraints),
        }
    if isinstance(object_, TroubleshootingFlow):
        return {
            "problem_statement": object_.problem_statement,
            "prerequisites": list(object_.prerequisites),
            "steps": list(object_.steps),
            "stop_conditions": list(object_.stop_conditions),
            "escalation_route_id": object_.escalation_route_id,
        }
    if isinstance(object_, PolicyRule):
        return {
            "rule_statement": object_.rule_statement,
            "effective_conditions": list(object_.effective_conditions),
            "exceptions": list(object_.exceptions),
            "human_override_notes": list(object_.human_override_notes),
        }
    if isinstance(object_, KnownIssuePage):
        return {
            "issue_summary": object_.issue_summary,
            "workaround": object_.workaround,
            "issue_status": object_.issue_status,
            "expected_next_update": object_.expected_next_update,
        }
    if isinstance(object_, EscalationRoute):
        return {
            "trigger_conditions": list(object_.trigger_conditions),
            "destination_team": object_.destination_team,
            "required_context": list(object_.required_context),
            "severity_hint": object_.severity_hint,
        }
    return {"summary": object_.summary}


def _governance_context(
    audience_context: AudienceContext,
    *,
    disposition: GovernanceDisposition,
    object_id: str | None = None,
    object_version: int | None = None,
    trace_ref: str | None = None,
    freshness: FreshnessState | None = None,
) -> dict[str, object]:
    return {
        "governance_state": disposition.value,
        "audience_context": _audience_payload(audience_context),
        "object_id": object_id,
        "object_version": object_version,
        "trace_ref": trace_ref,
        "freshness": freshness.value if freshness is not None else None,
    }


def _evaluate_continuity(
    previous: PriorGovernanceContext | None,
    current: dict[str, object],
    audience_context: AudienceContext,
) -> dict[str, object]:
    reasons: list[str] = []
    if previous is None:
        disposition = ContinuityDisposition.STARTED
        reasons.append("no_prior_governance_context")
    elif previous.audience_context != audience_context:
        disposition = ContinuityDisposition.INVALIDATED
        reasons.append("audience_context_changed")
    else:
        comparisons = (
            ("object_changed", previous.object_id, current["object_id"]),
            (
                "object_version_changed",
                previous.object_version,
                current["object_version"],
            ),
            ("trace_changed", previous.trace_ref, current["trace_ref"]),
            (
                "freshness_changed",
                previous.freshness.value if previous.freshness is not None else None,
                current["freshness"],
            ),
            (
                "governance_state_changed",
                previous.governance_state.value,
                current["governance_state"],
            ),
        )
        reasons.extend(reason for reason, old, new in comparisons if old != new)
        if reasons:
            disposition = ContinuityDisposition.REFRESHED
        else:
            disposition = ContinuityDisposition.REVALIDATED
            reasons.append("governed_truth_rechecked")

    return {
        "state": disposition.value,
        "revalidated": True,
        "session_memory_used_as_truth": False,
        "reasons": reasons,
        "governance_context": current,
    }


def _audience_payload(context: AudienceContext) -> dict[str, str | None]:
    return {
        "visibility": context.visibility.value,
        "brand": context.brand,
        "product_line": context.product_line,
        "plan_tier": context.plan,
        "region": context.region,
        "language": context.language,
        "product_version": context.product_version,
    }


def _tool_trace(name: str, *, result_ref: str | None = None) -> dict[str, object]:
    return {
        "name": name,
        "risk_level": "R0",
        "owner": "cygnus",
        "result_ref": result_ref,
    }


def _status_for(disposition: GovernanceDisposition) -> str:
    if disposition is GovernanceDisposition.ANSWERABLE:
        return "success"
    if disposition is GovernanceDisposition.FALLBACK:
        return "not_found"
    return "denied"


def _summary_for(disposition: GovernanceDisposition, title: str) -> str:
    if disposition is GovernanceDisposition.ANSWERABLE:
        return f"Governed answer ready from {title}."
    if disposition is GovernanceDisposition.RESTRICTED:
        return f"Governed knowledge found in {title}, but direct use is restricted."
    return (
        f"Governed knowledge found in {title}, but source evidence requires escalation."
    )


def _envelope(
    request: GovernedQueryRequest,
    *,
    status: str,
    summary: str,
    disposition: GovernanceDisposition,
    codes: tuple[str, ...],
    directives: tuple[str, ...],
    answer: dict[str, object] | None,
    source_trace: dict[str, object] | None,
    alternatives: tuple[dict[str, object], ...],
    continuity: dict[str, object],
    current_context: dict[str, object],
    tool_trace: tuple[dict[str, object], ...],
    trace_ref: str | None,
) -> dict[str, Any]:
    return {
        "status": status,
        "summary": summary,
        "data": {
            "request_ref": request.request_ref,
            "session_ref": request.session_ref,
            "query": request.query,
            "audience_context": _audience_payload(request.audience_context),
            "governance": {
                "state": disposition.value,
                "codes": list(codes),
                "directives": list(directives),
            },
            "answer": answer,
            "source_trace": source_trace,
            "alternatives": list(alternatives),
            "continuity": continuity,
            "governance_context": current_context,
            "tool_trace": list(tool_trace),
        },
        "trace_ref": trace_ref,
        "warnings": list(codes),
        "errors": [],
    }
