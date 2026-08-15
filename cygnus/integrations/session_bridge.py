from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, final

from cygnus.domain import AudienceContext, AudienceFilter, Visibility
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
)
from cygnus.publish.propagation import PropagationStatus
from cygnus.retrieval import SubstrateKnowledgeSnapshot
from cygnus.retrieval.contracts import KnowledgeObjectHit, SourceTrace
from cygnus.substrate.agent_protocol import (
    SessionManifest,
    session_tool_manifest_result_envelope,
)
from cygnus.substrate.tool_runtime import session_tool_manifest

# The dispatcher owns the one cached canonical manifest. Every session-facing
# projection reads that same immutable instance; no REST, OpenAPI, MCP, or
# Nanobot surface re-builds tool fields independently.
_SESSION_MANIFEST: SessionManifest = session_tool_manifest()


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
    channel: str
    session_ref: str | None = None
    object_types: tuple[str, ...] = ()
    limit: int = 5
    previous_governance_context: PriorGovernanceContext | None = None

    def __post_init__(self) -> None:
        if not self.request_ref.strip():
            raise ValueError("request_ref must not be blank")
        if not self.query.strip():
            raise ValueError("query must not be blank")
        channel = self.channel.strip()
        if not channel:
            raise ValueError("channel must not be blank")
        if self.session_ref is not None and not self.session_ref.strip():
            raise ValueError("session_ref must not be blank when provided")
        if not 1 <= self.limit <= 10:
            raise ValueError("limit must be between 1 and 10")
        object.__setattr__(self, "channel", channel)
        object.__setattr__(self, "object_types", tuple(self.object_types))


@dataclass(frozen=True, slots=True, kw_only=True)
class PropagationDeliveryRecord:
    """One downstream propagation record for a publication surface."""

    surface_id: str
    status: str
    audiences: tuple[AudienceFilter, ...]

    def __post_init__(self) -> None:
        surface_id = self.surface_id.strip()
        if not surface_id:
            raise ValueError("propagation surface_id must not be blank")
        if self.status not in {state.value for state in PropagationStatus}:
            raise ValueError(
                f"propagation status must be one of {[s.value for s in PropagationStatus]}"
            )
        object.__setattr__(self, "surface_id", surface_id)
        object.__setattr__(self, "audiences", tuple(self.audiences))


@dataclass(frozen=True, slots=True)
class DeliveryVerdict:
    """Strict outcome of the channel/audience propagation delivery check."""

    delivered: bool
    code: str
    reason: str


@dataclass(frozen=True, slots=True)
class PropagationDeliveryTruth:
    """Pure view of synced propagation truth keyed by governed object ref.

    Answerability in a governed session requires an exact channel/audience
    match on a SYNCED propagation record; anything else (missing record,
    pending/failed status, or an audience the record does not cover) is a
    denial. There is no union across channels, statuses, or audiences.
    """

    _by_object: Mapping[str, tuple[PropagationDeliveryRecord, ...]]

    @classmethod
    def empty(cls) -> "PropagationDeliveryTruth":
        return cls(_by_object={})

    @classmethod
    def from_propagation_rows(
        cls,
        rows: Iterable[tuple[str, str, str, Iterable[object]]],
    ) -> "PropagationDeliveryTruth":
        """Build truth from (object_ref, surface_id, status, binding_refs) rows.

        ``binding_refs`` entries are publish binding dicts shaped like
        ``PublishBinding.to_dict()`` (audience_filter + channel).
        """
        by_object: dict[str, list[PropagationDeliveryRecord]] = {}
        for object_ref, surface_id, status, binding_refs in rows:
            audiences: list[AudienceFilter] = []
            for binding_payload in binding_refs:
                audience_payload = _audience_payload_from_binding(binding_payload)
                if audience_payload is not None:
                    audiences.append(audience_payload)
            by_object.setdefault(object_ref, []).append(
                PropagationDeliveryRecord(
                    surface_id=surface_id,
                    status=status,
                    audiences=tuple(audiences),
                )
            )
        return cls(
            _by_object={
                object_ref: tuple(records) for object_ref, records in by_object.items()
            }
        )

    def records_for(self, object_id: str) -> tuple[PropagationDeliveryRecord, ...]:
        return self._by_object.get(object_id, ())

    def delivery_verdict(
        self,
        object_id: str,
        channel: str,
        audience_context: AudienceContext,
    ) -> DeliveryVerdict:
        """Exact channel/audience synced-record check (no fallback)."""
        records = self.records_for(object_id)
        channel_records = tuple(
            record for record in records if record.surface_id == channel
        )
        if not channel_records:
            return DeliveryVerdict(
                delivered=False,
                code="channel_not_synced",
                reason=(
                    f"No propagation record exists for channel={channel} on "
                    f"object={object_id}."
                ),
            )
        for record in channel_records:
            if record.status != PropagationStatus.SYNCED.value:
                continue
            if any(audience.matches(audience_context) for audience in record.audiences):
                return DeliveryVerdict(
                    delivered=True,
                    code="delivered",
                    reason=(
                        f"Channel={channel} propagation is synced for the "
                        f"requested audience on object={object_id}."
                    ),
                )
        synced = any(
            record.status == PropagationStatus.SYNCED.value
            for record in channel_records
        )
        if not synced:
            statuses = sorted({record.status for record in channel_records})
            return DeliveryVerdict(
                delivered=False,
                code="propagation_pending",
                reason=(
                    f"Channel={channel} propagation is not synced for "
                    f"object={object_id} (statuses={statuses})."
                ),
            )
        return DeliveryVerdict(
            delivered=False,
            code="audience_not_delivered",
            reason=(
                f"Channel={channel} is synced for object={object_id} but does "
                f"not cover the requested audience."
            ),
        )


def delivered_truth_for_objects(
    objects: Iterable[KnowledgeObject],
) -> PropagationDeliveryTruth:
    """Fixture/eval truth: every published object is delivered on its allowed
    channels for its supported audiences.

    Never used for live REST handoffs — the runtime router builds truth from
    the durable propagation table.
    """
    from cygnus.domain.lifecycle import LifecycleState

    by_object: dict[str, tuple[PropagationDeliveryRecord, ...]] = {}
    for object_ in objects:
        if object_.lifecycle_state is not LifecycleState.PUBLISHED:
            continue
        audiences = tuple(object_.supported_audiences)
        records = tuple(
            PropagationDeliveryRecord(
                surface_id=channel,
                status=PropagationStatus.SYNCED.value,
                audiences=audiences,
            )
            for channel in allowed_channels_for(object_)
        )
        if records:
            by_object[object_.object_id] = records
    return PropagationDeliveryTruth(_by_object=by_object)


def _audience_payload_from_binding(payload: object) -> AudienceFilter | None:
    """Decode one publish binding dict into the audience it delivered to."""
    if not isinstance(payload, dict):
        return None
    audience_payload = payload.get("audience_filter")
    if not isinstance(audience_payload, dict):
        return None
    visibility = audience_payload.get("visibility")
    if not isinstance(visibility, str):
        return None

    def _dimension(name: str) -> tuple[str, ...]:
        value = audience_payload.get(name, [])
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value
        ):
            return ()
        return tuple(value)

    try:
        return AudienceFilter(
            visibility=Visibility(visibility),
            brands=_dimension("brands"),
            product_lines=_dimension("product_lines"),
            plans=_dimension("plans"),
            regions=_dimension("regions"),
            languages=_dimension("languages"),
            product_versions=_dimension("product_versions"),
        )
    except ValueError:
        return None


@final
class GovernedSessionBridge:
    """Cygnus-owned query handoff; Nanobot remains the session owner."""

    __slots__ = ("_snapshot", "_tools")
    _snapshot: SubstrateKnowledgeSnapshot
    _tools: GovernedKnowledgeTools

    def __init__(self, snapshot: SubstrateKnowledgeSnapshot) -> None:
        self._snapshot = snapshot
        self._tools = GovernedKnowledgeTools(snapshot)

    def query(self, request: GovernedQueryRequest) -> dict[str, Any]:
        """Resolve one runtime query only from its canonical snapshot truth."""
        return self._query(request, fixture_delivery_truth=None)

    def query_with_fixture_delivery(
        self,
        request: GovernedQueryRequest,
        *,
        delivery_truth: PropagationDeliveryTruth,
    ) -> dict[str, Any]:
        """Evaluation/test-only adapter for synthetic delivery fixtures.

        Runtime routers must call :meth:`query`, whose delivery predicate is
        database-backed and request-scoped. This isolated seam keeps legacy
        scenario fixtures out of the production path.
        """
        return self._query(request, fixture_delivery_truth=delivery_truth)

    def _query(
        self,
        request: GovernedQueryRequest,
        *,
        fixture_delivery_truth: PropagationDeliveryTruth | None,
    ) -> dict[str, Any]:
        hits = self._tools.search_hits(
            query=request.query,
            audience_context=request.audience_context,
            object_types=list(request.object_types),
            channel=request.channel,
            limit=request.limit,
        )
        if not hits:
            return self._no_answer_response(request)

        selected = hits[0]
        object_ = self._tools.read_object(selected.object_id)
        trace = self._tools.read_trace(
            selected.object_id,
            audience_context=request.audience_context,
            channel=request.channel,
        )
        if object_ is None or trace is None:
            raise RuntimeError(
                "governed retrieval returned an unresolved object reference"
            )

        verdict = (
            fixture_delivery_truth.delivery_verdict(
                selected.object_id,
                request.channel,
                request.audience_context,
            )
            if fixture_delivery_truth is not None
            else self._snapshot_delivery_verdict(selected.object_id, request)
        )
        disposition, codes, directives, expose_content = _governance_decision(
            selected,
            trace,
            verdict,
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
            allowed_channels=(request.channel,) if verdict.delivered else (),
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

    def _snapshot_delivery_verdict(
        self,
        object_id: str,
        request: GovernedQueryRequest,
    ) -> DeliveryVerdict:
        try:
            delivered = self._snapshot.delivery_verdict(
                object_id,
                channel=request.channel,
                audience_context=request.audience_context,
            )
        except Exception:
            delivered = False
        if delivered:
            return DeliveryVerdict(
                delivered=True,
                code="delivered",
                reason="Current signed delivery receipt covers this channel and audience.",
            )
        return DeliveryVerdict(
            delivered=False,
            code="propagation_pending",
            reason="Current signed delivery receipt is unavailable for this channel and audience.",
        )

    def _no_answer_response(
        self,
        request: GovernedQueryRequest,
    ) -> dict[str, Any]:
        unpublished_hits = self._tools.search_hits(
            query=request.query,
            audience_context=request.audience_context,
            object_types=list(request.object_types),
            channel=request.channel,
            limit=request.limit,
            include_unpublished=True,
        )
        any_audience_hits = self._tools.search_hits(
            query=request.query,
            object_types=list(request.object_types),
            channel=request.channel,
            limit=request.limit,
            match_audience=False,
        )

        if unpublished_hits:
            disposition = GovernanceDisposition.RESTRICTED
            codes: tuple[str, ...] = ("pending_review",)
            directives = ("wait_for_review", "do_not_present_as_answered")
            summary = "A matching knowledge object exists but is not published."
            answer: dict[str, object] | None = None
        elif any_audience_hits:
            disposition = GovernanceDisposition.RESTRICTED
            codes = ("audience_restricted",)
            directives = ("do_not_expose_restricted_object", "offer_human_escalation")
            summary = (
                "Matching knowledge exists outside the requested audience boundary."
            )
            # Object-level denial: the matched object does not cover the
            # requested audience, so no restricted metadata or trace may be
            # projected — even when propagation truth exists for the object.
            # Delivery coupling applies only to audience-matched objects
            # selected in the main query path, which remains fail-closed here.
            answer = None
        else:
            disposition = GovernanceDisposition.FALLBACK
            codes = ("no_governed_match", "fallback_suggested")
            directives = ("offer_human_escalation", "do_not_present_as_answered")
            summary = "No governed knowledge object can answer this query."
            answer = None

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
            answer=answer,
            source_trace=None,
            alternatives=(),
            continuity=continuity,
            current_context=current_context,
            tool_trace=(_tool_trace("search_knowledge_objects"),),
            trace_ref=None,
        )


def session_bridge_capabilities(
    _snapshot: SubstrateKnowledgeSnapshot,
    *,
    actor: object | None = None,
) -> dict[str, object]:
    """Nanobot-facing session contract, derived only from the canonical manifest.

    ``actor`` is an optional permission view (e.g. an authenticated employee or
    a :class:`SessionActorScope`); availability per tool is projected truthfully
    from it. With no actor, every governed tool is reported denied.
    """
    capabilities = _SESSION_MANIFEST.capabilities(actor)
    return {
        **capabilities,
        "owners": {
            "session_continuity": "nanobot",
            "knowledge_truth": "cygnus",
            "approval_truth": "cygnus",
        },
        "query_handoff": {
            "endpoint": "/api/session-bridge/query",
            "audience_context_required": True,
            "channel_required": True,
            "answerability_requires_synced_propagation": True,
            "revalidates_every_query": True,
            "session_memory_is_truth": False,
        },
        "not_exposed": [],
    }


def session_bridge_openapi_projection() -> dict[str, object]:
    """OpenAPI session-contract projection, derived from the canonical manifest."""
    return _SESSION_MANIFEST.openapi_projection()


_SOURCE_BLINDNESS_TRACE_SPOTS = frozenset(
    {
        "object_has_no_evidence",
        "object_has_no_readable_evidence",
        "object_identity_mismatch",
        "source_evidence_incomplete",
    }
)
_DELIVERY_TRACE_BLIND_SPOTS = frozenset(
    {"signed_delivery_not_current", "publication_delivery_trace_mismatch"}
)


def _governance_decision(
    hit: KnowledgeObjectHit,
    trace: SourceTrace,
    delivery_verdict: DeliveryVerdict,
) -> tuple[GovernanceDisposition, tuple[str, ...], tuple[str, ...], bool]:
    severe_blind_spots = tuple(
        blind_spot
        for blind_spot in trace.blind_spots
        if blind_spot in _SOURCE_BLINDNESS_TRACE_SPOTS
        or blind_spot.startswith("missing_evidence:")
    )
    if severe_blind_spots:
        return (
            GovernanceDisposition.ESCALATE,
            ("source_blindness", *severe_blind_spots, "escalate_required"),
            ("withhold_answer_content", "escalate_to_human"),
            False,
        )

    delivery_codes = tuple(
        blind_spot
        for blind_spot in trace.blind_spots
        if blind_spot in _DELIVERY_TRACE_BLIND_SPOTS
    )
    if not delivery_verdict.delivered:
        delivery_codes = (*delivery_codes, delivery_verdict.code)
    if delivery_codes:
        # Answerability is coupled to an exact channel/audience synced receipt
        # and its matching publication trace. Neither may authorize content
        # independently, and both failures retain the restricted status.
        return (
            GovernanceDisposition.RESTRICTED,
            tuple(
                dict.fromkeys(
                    (
                        *delivery_codes,
                        "not_delivered_to_channel",
                        "propagation_pending",
                        "do_not_present_as_answered",
                    )
                )
            ),
            (
                "withhold_answer_content",
                "do_not_present_as_answered",
                "offer_human_escalation",
                "check_propagation_status",
            ),
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
            (
                "withhold_answer_content",
                "show_governance_warning",
                "require_human_check_before_external_use",
            ),
            False,
        )
    if trace.freshness is FreshnessState.UNKNOWN:
        codes.extend(("freshness_unknown", "fallback_suggested"))
        return (
            GovernanceDisposition.RESTRICTED,
            tuple(codes),
            (
                "withhold_answer_content",
                "show_governance_warning",
                "require_human_check_before_external_use",
            ),
            False,
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
    allowed_channels: tuple[str, ...],
) -> dict[str, object]:
    content = _object_content(object_, audience_context) if expose_content else None
    return {
        **hit.to_dict(),
        "content": content,
        "allowed_channels": list(allowed_channels),
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
        "risk_level": _SESSION_MANIFEST.tool(name).risk_class,
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
    payload = session_tool_manifest_result_envelope(
        status=status,
        summary=summary,
        data={
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
        trace_ref=trace_ref,
        warnings=list(codes),
        errors=[],
    )
    payload["trace_ref"] = trace_ref
    return payload
