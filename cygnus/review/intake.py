from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from cygnus.domain.audience import AudienceFilter, Visibility
from cygnus.domain.objects import KnowledgeObjectType
from cygnus.evidence.records import EvidenceSourceType, FreshnessState, SupportEvidence
from cygnus.review.home import ReviewHomeQuery, get_review_home_surface
from cygnus.review.drilldown import ReviewQueueDrilldownQuery, ReviewQueueDrilldownSurface, get_review_queue_drilldown
from cygnus.review.pressure import ReviewPressureSurface, build_review_pressure_surface
from cygnus.review.source_blindness import SourceBlindnessSurface, build_source_blindness_surface
from cygnus.review.briefing import ReviewRiskType
from cygnus.review.service import ProposalBundle, ReviewSignal
from cygnus.review.surface import ReviewCommandSurface
from cygnus.substrate.compilation_plan import CompilationProposal, EvidenceSufficiency, PlanAction, UrgencyLevel


class PressureSignalType(str, Enum):
    TICKET_CLUSTER = "ticket_cluster"
    HUMAN_REWRITE = "human_rewrite"
    SOURCE_FAILURE = "source_failure"


def _normalize(values: Iterable[str] | None, *, label: str) -> tuple[str, ...]:
    if values is None:
        return ()
    out: list[str] = []
    for raw in values:
        value = raw.strip()
        if not value:
            raise ValueError(f"{label} must not be blank")
        out.append(value)
    return tuple(out)


@dataclass(frozen=True, slots=True, kw_only=True)
class PressureIntakeRecord:
    signal_type: PressureSignalType
    signal_ref: str
    title: str
    summary: str
    source_ref: str
    source_type: EvidenceSourceType
    audience_filter: AudienceFilter
    object_type: KnowledgeObjectType
    affected_surfaces: tuple[str, ...]
    trigger_signals: tuple[str, ...] = field(default_factory=tuple)
    product_lines: tuple[str, ...] = field(default_factory=tuple)
    plans: tuple[str, ...] = field(default_factory=tuple)
    regions: tuple[str, ...] = field(default_factory=tuple)
    languages: tuple[str, ...] = field(default_factory=tuple)
    product_versions: tuple[str, ...] = field(default_factory=tuple)
    freshness_state: FreshnessState = FreshnessState.UNKNOWN
    queue_owner: str | None = None
    reason: str | None = None
    evidence_excerpt: str | None = None
    proposal_id: str | None = None

    def __post_init__(self) -> None:
        if not self.signal_ref.strip():
            raise ValueError("signal_ref must not be blank")
        if not self.title.strip():
            raise ValueError("title must not be blank")
        if not self.summary.strip():
            raise ValueError("summary must not be blank")
        if not self.source_ref.strip():
            raise ValueError("source_ref must not be blank")
        if not self.affected_surfaces:
            raise ValueError("affected_surfaces must not be empty")
        if self.queue_owner is not None and not self.queue_owner.strip():
            raise ValueError("queue_owner must not be blank when provided")
        object.__setattr__(self, "affected_surfaces", _normalize(self.affected_surfaces, label="affected surface"))
        object.__setattr__(self, "trigger_signals", _normalize(self.trigger_signals, label="trigger signal"))
        object.__setattr__(self, "product_lines", _normalize(self.product_lines, label="product line"))
        object.__setattr__(self, "plans", _normalize(self.plans, label="plan"))
        object.__setattr__(self, "regions", _normalize(self.regions, label="region"))
        object.__setattr__(self, "languages", _normalize(self.languages, label="language"))
        object.__setattr__(self, "product_versions", _normalize(self.product_versions, label="product version"))
        if self.reason is not None and not self.reason.strip():
            raise ValueError("reason must not be blank when provided")
        if self.evidence_excerpt is not None and not self.evidence_excerpt.strip():
            raise ValueError("evidence_excerpt must not be blank when provided")
        if self.proposal_id is not None and not self.proposal_id.strip():
            raise ValueError("proposal_id must not be blank when provided")


@dataclass(frozen=True, slots=True, kw_only=True)
class PressureIntakeBundle:
    proposal: CompilationProposal
    signal: ReviewSignal
    evidence: tuple[SupportEvidence, ...]
    intake_record: PressureIntakeRecord

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", tuple(self.evidence))

    def as_proposal_bundle(self) -> ProposalBundle:
        return ProposalBundle(
            proposal=self.proposal,
            signal=self.signal,
            evidence=self.evidence,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class PressureIntakeSurfaces:
    bundles: tuple[ProposalBundle, ...]
    review_home: ReviewCommandSurface
    pressure_surface: ReviewPressureSurface | None = None
    source_blindness_surface: SourceBlindnessSurface | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "bundles": [bundle.proposal.to_dict() for bundle in self.bundles],
            "review_home": self.review_home.to_dict(),
            "pressure_surface": self.pressure_surface.to_dict() if self.pressure_surface is not None else None,
            "source_blindness_surface": self.source_blindness_surface.to_dict() if self.source_blindness_surface is not None else None,
        }


def compile_pressure_intake(record: PressureIntakeRecord) -> PressureIntakeBundle:
    proposal = _proposal_for_record(record)
    evidence = (_evidence_for_record(record),)
    signal = _signal_for_record(record, proposal=proposal)
    return PressureIntakeBundle(
        proposal=proposal,
        signal=signal,
        evidence=evidence,
        intake_record=record,
    )


def compile_pressure_intake_bundle(records: Iterable[PressureIntakeRecord]) -> tuple[PressureIntakeBundle, ...]:
    return tuple(compile_pressure_intake(record) for record in records)


def compile_pressure_proposal_bundles(records: Iterable[PressureIntakeRecord]) -> tuple[ProposalBundle, ...]:
    return tuple(bundle.as_proposal_bundle() for bundle in compile_pressure_intake_bundle(records))


def build_pressure_intake_surfaces(
    records: Iterable[PressureIntakeRecord],
    *,
    review_query: ReviewHomeQuery | None = None,
) -> PressureIntakeSurfaces:
    bundles = compile_pressure_proposal_bundles(records)
    if not bundles:
        raise ValueError("pressure intake requires at least one record")

    review_home = get_review_home_surface(review_query, bundles=bundles)
    pressure_bundles = tuple(bundle for bundle in bundles if bundle.signal.risk_type is ReviewRiskType.TICKET_PRESSURE)
    source_bundles = tuple(bundle for bundle in bundles if bundle.signal.risk_type is ReviewRiskType.SOURCE_BLINDNESS)

    return PressureIntakeSurfaces(
        bundles=bundles,
        review_home=review_home,
        pressure_surface=build_review_pressure_surface(pressure_bundles) if pressure_bundles else None,
        source_blindness_surface=build_source_blindness_surface(source_bundles) if source_bundles else None,
    )


def get_pressure_intake_review_brief_surface(
    *,
    records: Iterable[PressureIntakeRecord] | None = None,
    review_query: ReviewHomeQuery | None = None,
) -> ReviewCommandSurface:
    source_records = tuple(records) if records is not None else sample_pressure_intake_records()
    return build_pressure_intake_surfaces(source_records, review_query=review_query).review_home


def get_pressure_intake_review_queue_drilldown(
    selected_object_ref: str,
    *,
    records: Iterable[PressureIntakeRecord] | None = None,
    review_query: ReviewHomeQuery | None = None,
) -> ReviewQueueDrilldownSurface:
    source_records = tuple(records) if records is not None else sample_pressure_intake_records()
    bundles = compile_pressure_proposal_bundles(source_records)
    return get_review_queue_drilldown(
        ReviewQueueDrilldownQuery(selected_object_ref=selected_object_ref, home_query=review_query),
        bundles=bundles,
    )


def sample_pressure_intake_records() -> tuple[PressureIntakeRecord, ...]:
    return (
        PressureIntakeRecord(
            signal_type=PressureSignalType.TICKET_CLUSTER,
            signal_ref="billing-verification-w25",
            title="Billing verification cluster should become a governed troubleshooting flow",
            summary="Repeated escalations show a reusable support flow is missing.",
            source_ref="cluster/billing-verification-w25",
            source_type=EvidenceSourceType.RESOLVED_TICKET,
            audience_filter=AudienceFilter(
                visibility=Visibility.INTERNAL,
                product_lines=("billing",),
            ),
            object_type=KnowledgeObjectType.TROUBLESHOOTING_FLOW,
            affected_surfaces=("copilot", "queue-sidebar"),
            trigger_signals=("ticket_pressure", "rewrite_cluster"),
            product_lines=("billing",),
            evidence_excerpt="Agents repeatedly reconstruct the same verification steps from memory.",
        ),
        PressureIntakeRecord(
            signal_type=PressureSignalType.HUMAN_REWRITE,
            signal_ref="refund-enterprise-rewrite",
            title="Refund rewrite pressure should become a governed policy correction",
            summary="Frontline rewrites show enterprise exceptions are leaking into the wrong answer path.",
            source_ref="rewrite/refund-enterprise-rewrite",
            source_type=EvidenceSourceType.CHAT_TRANSCRIPT,
            audience_filter=AudienceFilter(
                visibility=Visibility.EXTERNAL,
                product_lines=("billing",),
                plans=("free",),
                regions=("us",),
            ),
            object_type=KnowledgeObjectType.POLICY_RULE,
            affected_surfaces=("copilot", "macro"),
            trigger_signals=("rewrite_cluster", "audience_boundary_conflict"),
            product_lines=("billing",),
            plans=("free",),
            regions=("us",),
            evidence_excerpt="Agents keep removing enterprise-only refund clauses before sending replies.",
            queue_owner="support-ops",
        ),
        PressureIntakeRecord(
            signal_type=PressureSignalType.SOURCE_FAILURE,
            signal_ref="incident-sync-eu-billing",
            title="Incident source failure should become a known-issue governance blind spot",
            summary="Source loss is weakening confidence in current EU billing workaround guidance.",
            source_ref="incident/sev2-eu-billing",
            source_type=EvidenceSourceType.INCIDENT_UPDATE,
            audience_filter=AudienceFilter(
                visibility=Visibility.EXTERNAL,
                product_lines=("billing",),
                plans=("enterprise",),
                regions=("eu",),
            ),
            object_type=KnowledgeObjectType.KNOWN_ISSUE_PAGE,
            affected_surfaces=("help_center", "copilot"),
            trigger_signals=("source_sync_failed", "active_incident"),
            product_lines=("billing",),
            plans=("enterprise",),
            regions=("eu",),
            freshness_state=FreshnessState.STALE,
            evidence_excerpt="Incident feed is degraded while the workaround continues to be customer-facing.",
        ),
        # Governance signal on an EXISTING published object — bridges the
        # publish write-path (which keys on object_ref) to traceability (which
        # resolves the same ko-* id). Human-rewrite pressure on the already-
        # published refund policy => REPUBLISH / restrict_publish presets, so
        # APPLY on ko-billing-refund-policy runs and the traceability drawer's
        # post-apply what-if projection can trigger on matching ids.
        PressureIntakeRecord(
            signal_type=PressureSignalType.HUMAN_REWRITE,
            signal_ref="refund-policy-rewrite",
            proposal_id="ko-billing-refund-policy",
            title="Refund policy is accumulating frontline rewrites that cross the plan boundary",
            summary="Published refund policy needs a governed republish before enterprise exceptions leak further.",
            source_ref="rewrite/refund-policy-rewrite",
            source_type=EvidenceSourceType.CHAT_TRANSCRIPT,
            audience_filter=AudienceFilter(
                visibility=Visibility.INTERNAL,
                product_lines=("billing",),
            ),
            object_type=KnowledgeObjectType.POLICY_RULE,
            affected_surfaces=("copilot", "macro"),
            trigger_signals=("rewrite_cluster", "audience_boundary_conflict"),
            product_lines=("billing",),
            evidence_excerpt="Agents keep softening enterprise-only refund clauses before sending replies.",
            queue_owner="support-ops",
        ),
    )


def _proposal_for_record(record: PressureIntakeRecord) -> CompilationProposal:
    proposal_id = record.proposal_id or record.signal_ref
    audience_note = _audience_note(record.audience_filter, record)
    return CompilationProposal(
        proposal_id=proposal_id,
        object_type=record.object_type,
        action=PlanAction.CREATE,
        title=record.title,
        summary=record.summary,
        evidence_ids=(f"ev:{record.signal_type.value}:{record.signal_ref}",),
        urgency=_urgency_for_signal(record.signal_type, record.trigger_signals),
        evidence_sufficiency=_evidence_sufficiency_for_signal(record.signal_type, record.evidence_excerpt),
        review_owner=record.queue_owner or "support-ops",
        why_now=record.reason or _why_now_for_signal(record),
        audience_notes=(audience_note,) if audience_note else (),
    )


def _signal_for_record(record: PressureIntakeRecord, *, proposal: CompilationProposal) -> ReviewSignal:
    risk_type = _risk_type_for_signal(record.signal_type)
    recommended_actions = _recommended_actions_for_signal(record.signal_type, record.queue_owner)
    return ReviewSignal(
        proposal_id=proposal.proposal_id,
        risk_type=risk_type,
        affected_audiences=(record.audience_filter,),
        affected_surfaces=record.affected_surfaces,
        trigger_signals=record.trigger_signals,
        queue_owner=record.queue_owner,
        recommended_actions=recommended_actions,
        title_override=record.title,
    )


def _evidence_for_record(record: PressureIntakeRecord) -> SupportEvidence:
    return SupportEvidence(
        evidence_id=f"ev:{record.signal_type.value}:{record.signal_ref}",
        source_type=record.source_type,
        source_ref=record.source_ref,
        title=record.title,
        content=record.evidence_excerpt or record.summary,
        audience_filter=record.audience_filter,
        product_lines=record.product_lines,
        plans=record.plans,
        regions=record.regions,
        languages=record.languages,
        product_versions=record.product_versions,
        freshness_state=record.freshness_state,
    )


def _risk_type_for_signal(signal_type: PressureSignalType) -> ReviewRiskType:
    return {
        PressureSignalType.TICKET_CLUSTER: ReviewRiskType.TICKET_PRESSURE,
        PressureSignalType.HUMAN_REWRITE: ReviewRiskType.TICKET_PRESSURE,
        PressureSignalType.SOURCE_FAILURE: ReviewRiskType.SOURCE_BLINDNESS,
    }[signal_type]


def _urgency_for_signal(signal_type: PressureSignalType, trigger_signals: tuple[str, ...]) -> UrgencyLevel:
    if signal_type is PressureSignalType.SOURCE_FAILURE:
        return UrgencyLevel.URGENT
    if "urgent" in trigger_signals or "hot" in trigger_signals:
        return UrgencyLevel.HIGH
    return UrgencyLevel.MEDIUM


def _evidence_sufficiency_for_signal(signal_type: PressureSignalType, evidence_excerpt: str) -> EvidenceSufficiency:
    if signal_type is PressureSignalType.SOURCE_FAILURE:
        return EvidenceSufficiency.PARTIAL
    if evidence_excerpt and evidence_excerpt.strip():
        return EvidenceSufficiency.SUFFICIENT
    return EvidenceSufficiency.PARTIAL


def _recommended_actions_for_signal(signal_type: PressureSignalType, queue_owner: str | None) -> tuple[str, ...]:
    if signal_type is PressureSignalType.SOURCE_FAILURE:
        return ("open_review", "restrict_publish", "assign_owner")
    if queue_owner:
        return ("open_review", "assign_owner", "request_more_evidence")
    return ("open_review", "assign_owner")


def _why_now_for_signal(record: PressureIntakeRecord) -> str:
    if record.signal_type is PressureSignalType.TICKET_CLUSTER:
        return "Recurring ticket pressure is ready to enter review."
    if record.signal_type is PressureSignalType.HUMAN_REWRITE:
        return "Human rewrite pressure is indicating a reusable knowledge gap."
    return "Source failure is weakening confidence in support propagation."


def _audience_note(audience_filter: AudienceFilter, record: PressureIntakeRecord) -> str | None:
    if audience_filter.visibility is Visibility.INTERNAL:
        scope = "internal"
    else:
        scope = "external"
    segments = [scope]
    for values in (audience_filter.product_lines, audience_filter.plans, audience_filter.regions, audience_filter.languages, audience_filter.product_versions):
        if values:
            segments.append("/".join(values))
    if record.affected_surfaces:
        segments.append(",".join(record.affected_surfaces))
    return " | ".join(segments) if segments else None
