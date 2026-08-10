from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from sqlalchemy import and_, or_, select
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.governance.review_assignments import load_review_assignments
from cygnus.review.intake import PressureSignalType, is_feedback_derived_signal_type
from cygnus.publish.durable import list_publication_propagations
from cygnus.recovery.overview import GovernanceOverviewSurface
from cygnus.recovery.providers import (
    build_downstream_reality_check,
    build_governance_overview,
    build_recovery_window,
)
from cygnus.recovery.reality_check import (
    DownstreamFeedbackSignal,
    DownstreamRealityCheckSurface,
    FeedbackSignalType,
    GovernanceCommandRef,
)
from cygnus.recovery.window import (
    AlignmentPlaneChange,
    RecoveryMetricSnapshot,
    RecoveryWindowSurface,
    ResidualRisk,
    TruthPlaneState,
)
from cygnus.runtime.database.models import (
    Employee,
    GovernanceLedgerEvent,
    GovernancePropagation,
    GovernancePublication,
    GovernanceSignal,
    WikiPage,
)


class DurableRecoveryNotFound(LookupError):
    """The requested durable publication command does not exist."""


class DurableRecoveryUnavailable(LookupError):
    """Durable command truth exists, but the requested observation does not."""


@dataclass(frozen=True, slots=True)
class _DurableRecoveryContext:
    publication: GovernancePublication
    page: WikiPage | None
    actor: Employee | None
    publish_event: GovernanceLedgerEvent | None
    propagations: tuple[GovernancePropagation, ...]
    signals: tuple[GovernanceSignal, ...]
    owner_ref_by_signal_id: dict[object, str | None]


_METRIC_DEFINITIONS = (
    ("rewrite_count", "Rewrite Delta"),
    ("drift_count", "Drift Delta"),
    ("escalation_count", "Escalation / Pressure Delta"),
    ("coverage_gap_count", "Coverage Gap Delta"),
    ("publish_conflict_count", "Audience Conflict Delta"),
)

_CONFLICT_TRIGGERS = {
    "audience_conflict",
    "audience_overlap_conflict",
    "publish_conflict",
    "variant_conflict",
}
_COVERAGE_TRIGGERS = {"coverage_gap", "unsupported_answer"}
_DRIFT_TRIGGERS = {"drift", "release_drift", "incident_drift", "stale_answer"}
_ESCALATION_TRIGGERS = {
    "escalated",
    "escalation",
    "escalation_after_suggestion",
    "ticket_pressure",
}
_REWRITE_TRIGGERS = {"human_rewrite", "rewrite"}


async def get_durable_recovery_window(
    session: AsyncSession,
    *,
    command_id: str,
    page_scope_clause: ColumnElement[bool] | None = None,
) -> RecoveryWindowSurface:
    """Compile before/after recovery truth for one persisted publish command."""
    context = await _load_context_by_command(
        session,
        command_id=command_id,
        page_scope_clause=page_scope_clause,
    )
    return _build_recovery_window(context)


async def get_durable_downstream_reality_check(
    session: AsyncSession,
    *,
    command_id: str,
    page_scope_clause: ColumnElement[bool] | None = None,
) -> DownstreamRealityCheckSurface:
    """Compile post-publication downstream feedback without rehearsal fallbacks."""
    context = await _load_context_by_command(
        session,
        command_id=command_id,
        page_scope_clause=page_scope_clause,
    )
    command_ref = _command_ref(context)
    feedback = tuple(
        item
        for signal in context.signals
        if signal.status in {"active", "resolved"}
        and signal.observed_at > context.publication.published_at
        for item in (
            _feedback_signal(
                signal,
                command_ref=command_ref,
                owner_ref=context.owner_ref_by_signal_id.get(signal.id),
            ),
        )
        if item is not None
    )
    if not feedback:
        raise DurableRecoveryUnavailable(
            f"no persisted post-publication downstream feedback is available for command_id={command_id.strip()}"
        )
    return build_downstream_reality_check(
        command_ref=command_ref,
        feedback_feed=feedback,
    )


async def get_durable_recovery_proof(
    session: AsyncSession,
    *,
    object_ref: str | None = None,
    action_key: str | None = None,
    page_scope_clause: ColumnElement[bool] | None = None,
) -> dict[str, object]:
    """Resolve the latest durable object/action recovery window for the legacy proof route."""
    normalized_object_ref = object_ref.strip() if object_ref is not None else None
    normalized_action_key = action_key.strip() if action_key is not None else None
    if not normalized_object_ref and not normalized_action_key:
        raise DurableRecoveryUnavailable(
            "durable recovery proof requires object_ref or action_key"
        )

    statement = select(GovernancePublication).join(
        WikiPage,
        WikiPage.id == GovernancePublication.page_id,
    )
    if normalized_object_ref:
        statement = statement.where(
            GovernancePublication.object_ref == normalized_object_ref
        )
    if normalized_action_key:
        statement = statement.where(
            GovernancePublication.action_key == normalized_action_key
        )
    if page_scope_clause is not None:
        statement = statement.where(page_scope_clause)
    publication = (
        await session.execute(
            statement.order_by(
                GovernancePublication.published_at.desc(),
                GovernancePublication.id.desc(),
            ).limit(1)
        )
    ).scalar_one_or_none()
    if publication is None:
        filters = []
        if normalized_object_ref:
            filters.append(f"object_ref={normalized_object_ref}")
        if normalized_action_key:
            filters.append(f"action_key={normalized_action_key}")
        raise DurableRecoveryNotFound(
            f"durable publication was not found for {', '.join(filters)}"
        )

    context = await _load_context_for_publication(session, publication=publication)
    window = _build_recovery_window(context)
    return {
        "surface_id": "recovery-proof",
        "persisted": True,
        "rehearsal": False,
        "command_id": publication.command_id,
        "object_ref": publication.object_ref,
        "recovery_window": window.to_dict(),
    }


async def get_durable_governance_overview(
    session: AsyncSession,
    *,
    page_scope_clause: ColumnElement[bool] | None = None,
) -> GovernanceOverviewSurface:
    """Compile the overview from the latest persisted publication per visible object."""
    statement = select(GovernancePublication).join(
        WikiPage,
        WikiPage.id == GovernancePublication.page_id,
    )
    if page_scope_clause is not None:
        statement = statement.where(page_scope_clause)
    publications = tuple(
        (
            await session.execute(
                statement.order_by(
                    GovernancePublication.published_at.desc(),
                    GovernancePublication.id.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    latest_by_object: dict[str, GovernancePublication] = {}
    for publication in publications:
        if publication.object_ref not in latest_by_object:
            latest_by_object[publication.object_ref] = publication
    latest_publications = tuple(latest_by_object.values())
    windows: list[RecoveryWindowSurface] = []
    for publication in latest_publications:
        try:
            context = await _load_context_for_publication(
                session,
                publication=publication,
            )
        except DurableRecoveryUnavailable:
            continue
        windows.append(_build_recovery_window(context))
    if not windows:
        raise DurableRecoveryUnavailable(
            "no persisted recovery windows are available in this scope"
        )
    return build_governance_overview(
        command_refs=(window.command_ref for window in windows),
        recovery_windows=windows,
        residual_risks=(risk for window in windows for risk in window.residual_risks),
    )


async def _load_context_by_command(
    session: AsyncSession,
    *,
    command_id: str,
    page_scope_clause: ColumnElement[bool] | None = None,
) -> _DurableRecoveryContext:
    normalized = command_id.strip()
    if not normalized:
        raise ValueError("command_id must not be blank")
    statement = (
        select(GovernancePublication)
        .join(WikiPage, WikiPage.id == GovernancePublication.page_id)
        .where(GovernancePublication.command_id == normalized)
    )
    if page_scope_clause is not None:
        statement = statement.where(page_scope_clause)
    publication = (await session.execute(statement)).scalar_one_or_none()
    if publication is None:
        raise DurableRecoveryNotFound(
            f"durable publication command_id={normalized} was not found"
        )
    return await _load_context_for_publication(session, publication=publication)


async def _load_context_for_publication(
    session: AsyncSession,
    *,
    publication: GovernancePublication,
) -> _DurableRecoveryContext:
    page = await session.get(WikiPage, publication.page_id)
    actor = (
        await session.get(Employee, publication.published_by_id)
        if publication.published_by_id is not None
        else None
    )
    publish_event = await session.get(
        GovernanceLedgerEvent, publication.publish_event_id
    )
    propagations = await list_publication_propagations(session, publication.id)
    if not propagations:
        raise DurableRecoveryUnavailable(
            f"no persisted propagation rows are available for command_id={publication.command_id}"
        )

    signal_scope = [
        GovernanceSignal.object_ref == publication.object_ref,
        GovernanceSignal.page_id == publication.page_id,
    ]
    source_ids = tuple(dict.fromkeys(page.source_ids or ())) if page is not None else ()
    if source_ids:
        signal_scope.append(
            and_(
                GovernanceSignal.page_id.is_(None),
                GovernanceSignal.source_id.in_(source_ids),
            )
        )
    signals = tuple(
        (
            await session.execute(
                select(GovernanceSignal)
                .where(or_(*signal_scope))
                .order_by(GovernanceSignal.observed_at, GovernanceSignal.id)
            )
        )
        .scalars()
        .all()
    )
    assignments = await load_review_assignments(
        session,
        tuple(signal.id for signal in signals),
    )
    return _DurableRecoveryContext(
        publication=publication,
        page=page,
        actor=actor,
        publish_event=publish_event,
        propagations=propagations,
        signals=signals,
        owner_ref_by_signal_id={
            signal_id: assignment.owner_ref
            for signal_id, assignment in assignments.items()
        },
    )


def _build_recovery_window(
    context: _DurableRecoveryContext,
) -> RecoveryWindowSurface:
    before_signals = tuple(
        signal
        for signal in context.signals
        if _active_at(signal, context.publication.published_at)
    )
    after_signals = tuple(signal for signal in context.signals if _active_now(signal))
    return build_recovery_window(
        command_ref=_command_ref(context),
        before_metrics=_metric_snapshots(before_signals, phase="publication time"),
        after_metrics=_metric_snapshots(after_signals, phase="current durable state"),
        alignment_planes=_alignment_planes(
            before_signals=before_signals,
            after_signals=after_signals,
            propagations=context.propagations,
        ),
        residual_risks=_residual_risks(
            command_id=context.publication.command_id,
            signals=after_signals,
            propagations=context.propagations,
            owner_ref_by_signal_id=context.owner_ref_by_signal_id,
        ),
    )


def _command_ref(context: _DurableRecoveryContext) -> GovernanceCommandRef:
    actor_name = context.actor.name.strip() if context.actor is not None else ""
    actor_ref = actor_name or "unavailable"
    event_reason = (
        context.publish_event.reason.strip()
        if context.publish_event is not None and context.publish_event.reason
        else None
    )
    action_reason = next(
        (
            item.strip()
            for item in reversed(context.publication.action_log)
            if item.strip()
        ),
        None,
    )
    rationale = (
        event_reason
        or action_reason
        or f"durable {context.publication.action_key} publication"
    )
    affected_surfaces = _dedupe(
        propagation.surface_id for propagation in context.propagations
    )
    return GovernanceCommandRef(
        command_id=context.publication.command_id,
        command_type=context.publication.action_key,
        object_id=context.publication.object_ref,
        object_title=(
            context.page.title.strip()
            if context.page is not None and context.page.title.strip()
            else context.publication.object_ref
        ),
        issued_by=actor_ref,
        issued_at=_isoformat(context.publication.published_at),
        rationale=rationale,
        affected_surfaces=affected_surfaces,
    )


def _metric_snapshots(
    signals: Iterable[GovernanceSignal],
    *,
    phase: str,
) -> tuple[RecoveryMetricSnapshot, ...]:
    counts = _metric_counts(signals)
    return tuple(
        RecoveryMetricSnapshot(
            metric_key=metric_key,
            label=label,
            value=counts[metric_key],
            explanation=f"Persisted active governance signals at {phase}.",
        )
        for metric_key, label in _METRIC_DEFINITIONS
    )


def _metric_keys(signal: GovernanceSignal) -> tuple[str, ...]:
    triggers = _trigger_tokens(signal.trigger_signals)
    keys: list[str] = []
    if signal.signal_type == "human_rewrite" or triggers & _REWRITE_TRIGGERS:
        keys.append("rewrite_count")
    if (
        signal.signal_type
        in {
            "release_delta",
            "incident_delta",
            PressureSignalType.STALE_ANSWER.value,
        }
        or triggers & _DRIFT_TRIGGERS
    ):
        keys.append("drift_count")
    if (
        signal.signal_type in {"ticket_cluster", PressureSignalType.LOW_RATING.value}
        or triggers & _ESCALATION_TRIGGERS
    ):
        keys.append("escalation_count")
    if signal.signal_type == "source_failure" or triggers & _COVERAGE_TRIGGERS:
        keys.append("coverage_gap_count")
    if triggers & _CONFLICT_TRIGGERS:
        keys.append("publish_conflict_count")
    return tuple(dict.fromkeys(keys))


def _alignment_planes(
    *,
    before_signals: tuple[GovernanceSignal, ...],
    after_signals: tuple[GovernanceSignal, ...],
    propagations: tuple[GovernancePropagation, ...],
) -> tuple[AlignmentPlaneChange, ...]:
    before_counts = _metric_counts(before_signals)
    after_counts = _metric_counts(after_signals)
    object_metric_keys = {"rewrite_count", "drift_count", "escalation_count"}
    before_object_signals = tuple(
        signal
        for signal in before_signals
        if object_metric_keys.intersection(_metric_keys(signal))
    )
    after_object_signals = tuple(
        signal
        for signal in after_signals
        if object_metric_keys.intersection(_metric_keys(signal))
    )
    unresolved = tuple(item for item in propagations if item.status != "synced")
    synced_count = len(propagations) - len(unresolved)
    before_publish_count = len(propagations) + before_counts["publish_conflict_count"]
    after_publish_count = len(unresolved) + after_counts["publish_conflict_count"]

    return (
        _count_plane(
            key="object_truth",
            label="Object Truth",
            before_count=len(before_object_signals),
            after_count=len(after_object_signals),
            residual_reasons=(signal.title for signal in after_object_signals),
        ),
        _count_plane(
            key="audience_truth",
            label="Audience Truth",
            before_count=before_counts["publish_conflict_count"],
            after_count=after_counts["publish_conflict_count"],
            residual_reasons=(
                signal.title
                for signal in after_signals
                if "publish_conflict_count" in _metric_keys(signal)
            ),
        ),
        AlignmentPlaneChange(
            plane_key="publish_truth",
            label="Publish Truth",
            before_state=_truth_state(before_publish_count),
            after_state=_truth_state(
                after_publish_count,
                split_brain=bool(unresolved and synced_count),
            ),
            before_score=_count_score(before_publish_count),
            after_score=_count_score(after_publish_count),
            residual_reasons=_dedupe(
                f"{item.surface_id}: {item.status} ({item.reason})"
                for item in unresolved
            ),
        ),
        _count_plane(
            key="coverage_truth",
            label="Coverage Truth",
            before_count=before_counts["coverage_gap_count"],
            after_count=after_counts["coverage_gap_count"],
            residual_reasons=(
                signal.title
                for signal in after_signals
                if "coverage_gap_count" in _metric_keys(signal)
            ),
        ),
    )


def _count_plane(
    *,
    key: str,
    label: str,
    before_count: int,
    after_count: int,
    residual_reasons: Iterable[str],
) -> AlignmentPlaneChange:
    return AlignmentPlaneChange(
        plane_key=key,
        label=label,
        before_state=_truth_state(before_count),
        after_state=_truth_state(after_count),
        before_score=_count_score(before_count),
        after_score=_count_score(after_count),
        residual_reasons=_dedupe(residual_reasons),
    )


def _residual_risks(
    *,
    command_id: str,
    signals: tuple[GovernanceSignal, ...],
    propagations: tuple[GovernancePropagation, ...],
    owner_ref_by_signal_id: dict[object, str | None],
) -> tuple[ResidualRisk, ...]:
    signal_risks = tuple(
        ResidualRisk(
            command_id=command_id,
            risk_id=f"signal:{signal.signal_ref}",
            label=signal.title,
            severity=_signal_severity(signal),
            truth_plane=_signal_truth_plane(signal),
            summary=signal.summary,
            acceptable_residual=False,
            recommended_command=_signal_follow_up(signal),
            owner=owner_ref_by_signal_id.get(signal.id),
            blocking_surface=(
                signal.affected_surfaces[0] if signal.affected_surfaces else None
            ),
            evidence_refs=_signal_evidence_refs(signal),
        )
        for signal in signals
    )
    propagation_risks = tuple(
        ResidualRisk(
            command_id=command_id,
            risk_id=f"propagation:{propagation.id}",
            label=f"{propagation.surface_id} propagation is {propagation.status}",
            severity=(
                "critical"
                if propagation.status in {"failed", "manual_action_required"}
                else "elevated"
            ),
            truth_plane="publish_truth",
            summary=propagation.reason,
            acceptable_residual=False,
            recommended_command=(
                propagation.follow_up_commands[0]
                if propagation.follow_up_commands
                else f"confirm_propagation:{propagation.surface_id}"
            ),
            owner=(
                f"employee:{propagation.updated_by_id}"
                if propagation.updated_by_id is not None
                else None
            ),
            blocking_surface=propagation.surface_id,
            evidence_refs=(
                f"propagation:{propagation.id}",
                f"event:{propagation.last_event_id}",
            ),
        )
        for propagation in propagations
        if propagation.status != "synced"
    )
    return (*signal_risks, *propagation_risks)


def _feedback_signal(
    signal: GovernanceSignal,
    *,
    command_ref: GovernanceCommandRef,
    owner_ref: str | None,
) -> DownstreamFeedbackSignal | None:
    signal_type = _feedback_type(signal)
    if signal_type is None or not signal.affected_surfaces:
        return None
    return DownstreamFeedbackSignal(
        signal_id=signal.signal_ref,
        surface_id=signal.affected_surfaces[0],
        signal_type=signal_type,
        command_ref=command_ref,
        audience_label=_audience_label(signal),
        session_ref=f"signal:{signal.signal_ref}",
        summary=signal.summary,
        changed_behavior=signal.reason,
        event_at=_isoformat(signal.observed_at),
        queue_owner=owner_ref,
        source_refs=_signal_evidence_refs(signal),
        follow_up_actions=(_feedback_follow_up(signal_type),),
    )


def _feedback_type(signal: GovernanceSignal) -> FeedbackSignalType | None:
    if is_feedback_derived_signal_type(signal.signal_type):
        return None
    triggers = _trigger_tokens(signal.trigger_signals)
    mappings = (
        ({"answer_accepted", "copilot_accepted"}, FeedbackSignalType.COPILOT_ACCEPTED),
        ({"human_rewrite", "rewrite"}, FeedbackSignalType.HUMAN_REWRITE),
        (
            {"low_rating", "reject_after_suggestion", "unsupported_answer"},
            FeedbackSignalType.REJECT_AFTER_SUGGESTION,
        ),
        (
            {"escalated", "escalation_after_suggestion"},
            FeedbackSignalType.ESCALATION_AFTER_SUGGESTION,
        ),
        (
            {"stale_answer", "unresolved_conversation"},
            FeedbackSignalType.UNRESOLVED_CONVERSATION,
        ),
    )
    for candidates, feedback_type in mappings:
        if triggers & candidates:
            return feedback_type
    if signal.signal_type == "human_rewrite":
        return FeedbackSignalType.HUMAN_REWRITE
    return None


def _feedback_follow_up(signal_type: FeedbackSignalType) -> str:
    return {
        FeedbackSignalType.COPILOT_ACCEPTED: "monitor_recent_cycle",
        FeedbackSignalType.HUMAN_REWRITE: "route_rewrite_to_review",
        FeedbackSignalType.REJECT_AFTER_SUGGESTION: "inspect_rejected_suggestions",
        FeedbackSignalType.ESCALATION_AFTER_SUGGESTION: "inspect_escalation_pressure",
        FeedbackSignalType.UNRESOLVED_CONVERSATION: "inspect_unresolved_sessions",
    }[signal_type]


def _signal_truth_plane(signal: GovernanceSignal) -> str:
    metric_keys = set(_metric_keys(signal))
    if "publish_conflict_count" in metric_keys:
        return "audience_truth"
    if "coverage_gap_count" in metric_keys:
        return "coverage_truth"
    return "object_truth"


def _signal_follow_up(signal: GovernanceSignal) -> str:
    if is_feedback_derived_signal_type(signal.signal_type):
        return {
            PressureSignalType.LOW_RATING.value: "open_feedback_review",
            PressureSignalType.STALE_ANSWER.value: "verify_freshness",
        }[signal.signal_type]
    if "publish_conflict_count" in _metric_keys(signal):
        return "open_audience_conflict_review"
    return {
        "human_rewrite": "route_rewrite_to_review",
        "ticket_cluster": "inspect_ticket_cluster",
        "source_failure": "repair_source",
        "release_delta": "reopen_release_drift",
        "incident_delta": "reopen_incident_drift",
    }[signal.signal_type]


def _signal_severity(signal: GovernanceSignal) -> str:
    if signal.signal_type in {
        "source_failure",
        "incident_delta",
    } or "publish_conflict_count" in _metric_keys(signal):
        return "critical"
    return "elevated"


def _signal_evidence_refs(signal: GovernanceSignal) -> tuple[str, ...]:
    refs: list[str] = [f"signal:{signal.signal_ref}"]
    if signal.page_id is not None:
        refs.append(f"page:{signal.page_id}")
    if signal.source_id is not None:
        refs.append(f"source:{signal.source_id}")
    return tuple(refs)


def _audience_label(signal: GovernanceSignal) -> str:
    payload = signal.audience_filter
    if payload:
        labels: list[str] = []
        visibility = payload.get("visibility")
        if isinstance(visibility, str) and visibility.strip():
            labels.append(visibility.strip())
        for dimension in (
            "brands",
            "product_lines",
            "plans",
            "regions",
            "languages",
            "product_versions",
        ):
            values = payload.get(dimension)
            if isinstance(values, list):
                labels.extend(
                    value.strip()
                    for value in values
                    if isinstance(value, str) and value.strip()
                )
        if labels:
            return " · ".join(_dedupe(labels))
    if signal.audience_binding_ref:
        return f"binding:{signal.audience_binding_ref}"
    return "audience:unavailable"


def _active_at(signal: GovernanceSignal, instant: datetime) -> bool:
    if signal.status == "dismissed" or signal.observed_at > instant:
        return False
    return signal.resolved_at is None or signal.resolved_at > instant


def _active_now(signal: GovernanceSignal) -> bool:
    return signal.status == "active" and signal.resolved_at is None


def _metric_counts(signals: Iterable[GovernanceSignal]) -> dict[str, int]:
    counts = {key: 0 for key, _label in _METRIC_DEFINITIONS}
    for signal in signals:
        for key in _metric_keys(signal):
            counts[key] += 1
    return counts


def _trigger_tokens(values: Iterable[str]) -> set[str]:
    tokens: set[str] = set()
    for raw_value in values:
        normalized = raw_value.strip().lower().replace("-", "_").replace(" ", "_")
        if not normalized:
            continue
        tokens.add(normalized)
        tokens.add(normalized.rsplit(":", 1)[-1])
    return tokens


def _truth_state(count: int, *, split_brain: bool = False) -> TruthPlaneState:
    if count == 0:
        return TruthPlaneState.ALIGNED
    if split_brain:
        return TruthPlaneState.SPLIT_BRAIN
    if count == 1:
        return TruthPlaneState.PARTIAL
    return TruthPlaneState.MISALIGNED


def _count_score(count: int) -> float:
    return round(1.0 / (1.0 + count), 3)


def _isoformat(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return tuple(result)
