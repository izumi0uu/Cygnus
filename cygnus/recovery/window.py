from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from cygnus.recovery.reality_check import GovernanceCommandRef, _normalize_strings


class RecoveryAssessment(str, Enum):
    RECOVERY_INCOMPLETE = "recovery_incomplete"
    RECOVERY_CONFIRMED = "recovery_confirmed"
    FALSE_RECOVERY = "false_recovery"
    DRIFT_REBOUND = "drift_rebound"


class RecoveryDecision(str, Enum):
    CONTINUE_WITH_LIGHTWEIGHT_FOLLOW_UP = "continue_with_lightweight_follow_up"
    CLOSE_AND_MONITOR = "close_and_monitor"
    REOPEN_DRIFT_ROUTE = "reopen_drift_route"


class MetricTrend(str, Enum):
    LOWER_IS_BETTER = "lower_is_better"
    HIGHER_IS_BETTER = "higher_is_better"


class TruthPlaneState(str, Enum):
    MISALIGNED = "misaligned"
    PARTIAL = "partial"
    ALIGNED = "aligned"
    SPLIT_BRAIN = "split_brain"


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoveryMetricSnapshot:
    metric_key: str
    label: str
    value: int
    trend: MetricTrend = MetricTrend.LOWER_IS_BETTER
    explanation: str = ""

    def __post_init__(self) -> None:
        if not self.metric_key.strip():
            raise ValueError("metric_key must not be blank")
        if not self.label.strip():
            raise ValueError("label must not be blank")
        if self.value < 0:
            raise ValueError("value must not be negative")
        if self.explanation and not self.explanation.strip():
            raise ValueError("explanation must not be blank when provided")

    def to_dict(self) -> dict[str, object]:
        return {
            "metric_key": self.metric_key,
            "label": self.label,
            "value": self.value,
            "trend": self.trend.value,
            "explanation": self.explanation,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoveryMetricDelta:
    metric_key: str
    label: str
    before_value: int
    after_value: int
    delta: int
    improved: bool
    status: str
    explanation: str

    def __post_init__(self) -> None:
        if not self.metric_key.strip():
            raise ValueError("metric_key must not be blank")
        if not self.label.strip():
            raise ValueError("label must not be blank")
        if self.before_value < 0 or self.after_value < 0:
            raise ValueError("metric values must not be negative")
        if self.status not in {"improved", "worsened", "flat"}:
            raise ValueError("status must be one of improved/worsened/flat")
        if self.explanation and not self.explanation.strip():
            raise ValueError("explanation must not be blank when provided")

    def to_dict(self) -> dict[str, object]:
        return {
            "metric_key": self.metric_key,
            "label": self.label,
            "before_value": self.before_value,
            "after_value": self.after_value,
            "delta": self.delta,
            "improved": self.improved,
            "status": self.status,
            "explanation": self.explanation,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class AlignmentPlaneChange:
    plane_key: str
    label: str
    before_state: TruthPlaneState
    after_state: TruthPlaneState
    before_score: float
    after_score: float
    residual_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.plane_key.strip():
            raise ValueError("plane_key must not be blank")
        if not self.label.strip():
            raise ValueError("label must not be blank")
        if not 0.0 <= self.before_score <= 1.0:
            raise ValueError("before_score must be between 0 and 1")
        if not 0.0 <= self.after_score <= 1.0:
            raise ValueError("after_score must be between 0 and 1")
        object.__setattr__(
            self,
            "residual_reasons",
            _normalize_strings(self.residual_reasons, label="residual reason"),
        )

    @property
    def improved(self) -> bool:
        return self.after_score > self.before_score

    def to_dict(self) -> dict[str, object]:
        return {
            "plane_key": self.plane_key,
            "label": self.label,
            "before_state": self.before_state.value,
            "after_state": self.after_state.value,
            "before_score": self.before_score,
            "after_score": self.after_score,
            "improved": self.improved,
            "residual_reasons": list(self.residual_reasons),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class BeforeAfterAlignmentView:
    before_score: float
    after_score: float
    plane_changes: tuple[AlignmentPlaneChange, ...]
    improved_truth_planes: tuple[str, ...]
    residual_truth_planes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not 0.0 <= self.before_score <= 1.0:
            raise ValueError("before_score must be between 0 and 1")
        if not 0.0 <= self.after_score <= 1.0:
            raise ValueError("after_score must be between 0 and 1")
        object.__setattr__(self, "plane_changes", tuple(self.plane_changes))
        if not self.plane_changes:
            raise ValueError("plane_changes must not be empty")
        object.__setattr__(
            self,
            "improved_truth_planes",
            _normalize_strings(self.improved_truth_planes, label="improved truth plane"),
        )
        object.__setattr__(
            self,
            "residual_truth_planes",
            _normalize_strings(self.residual_truth_planes, label="residual truth plane"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "before_score": self.before_score,
            "after_score": self.after_score,
            "delta": round(self.after_score - self.before_score, 3),
            "plane_changes": [item.to_dict() for item in self.plane_changes],
            "improved_truth_planes": list(self.improved_truth_planes),
            "residual_truth_planes": list(self.residual_truth_planes),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ResidualRisk:
    risk_id: str
    label: str
    severity: str
    truth_plane: str
    summary: str
    acceptable_residual: bool
    recommended_command: str
    owner: str | None = None
    blocking_surface: str | None = None
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.risk_id.strip():
            raise ValueError("risk_id must not be blank")
        if not self.label.strip():
            raise ValueError("label must not be blank")
        if not self.severity.strip():
            raise ValueError("severity must not be blank")
        if not self.truth_plane.strip():
            raise ValueError("truth_plane must not be blank")
        if not self.summary.strip():
            raise ValueError("summary must not be blank")
        if not self.recommended_command.strip():
            raise ValueError("recommended_command must not be blank")
        if self.owner is not None and not self.owner.strip():
            raise ValueError("owner must not be blank when provided")
        if self.blocking_surface is not None and not self.blocking_surface.strip():
            raise ValueError("blocking_surface must not be blank when provided")
        object.__setattr__(
            self,
            "evidence_refs",
            _normalize_strings(self.evidence_refs, label="evidence ref"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "risk_id": self.risk_id,
            "label": self.label,
            "severity": self.severity,
            "truth_plane": self.truth_plane,
            "summary": self.summary,
            "acceptable_residual": self.acceptable_residual,
            "recommended_command": self.recommended_command,
            "owner": self.owner,
            "blocking_surface": self.blocking_surface,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ClosureJudge:
    assessment: RecoveryAssessment
    recommendation: RecoveryDecision
    closeable: bool
    rationale: str
    improved_metrics: tuple[str, ...]
    residual_truth_planes: tuple[str, ...]
    next_commands: tuple[str, ...]
    monitor_targets: tuple[str, ...]
    closure_blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.rationale.strip():
            raise ValueError("rationale must not be blank")
        object.__setattr__(
            self,
            "improved_metrics",
            _normalize_strings(self.improved_metrics, label="improved metric"),
        )
        object.__setattr__(
            self,
            "residual_truth_planes",
            _normalize_strings(self.residual_truth_planes, label="residual truth plane"),
        )
        object.__setattr__(
            self,
            "next_commands",
            _normalize_strings(self.next_commands, label="next command"),
        )
        object.__setattr__(
            self,
            "monitor_targets",
            _normalize_strings(self.monitor_targets, label="monitor target"),
        )
        object.__setattr__(
            self,
            "closure_blockers",
            _normalize_strings(self.closure_blockers, label="closure blocker"),
        )
        if not self.next_commands:
            raise ValueError("next_commands must not be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "assessment": self.assessment.value,
            "recommendation": self.recommendation.value,
            "closeable": self.closeable,
            "rationale": self.rationale,
            "improved_metrics": list(self.improved_metrics),
            "residual_truth_planes": list(self.residual_truth_planes),
            "next_commands": list(self.next_commands),
            "monitor_targets": list(self.monitor_targets),
            "closure_blockers": list(self.closure_blockers),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoveryWindowSurface:
    surface_id: str
    headline: str
    summary: str
    command_ref: GovernanceCommandRef
    assessment: RecoveryAssessment
    before_after_alignment_view: BeforeAfterAlignmentView
    rewrite_delta: RecoveryMetricDelta
    drift_delta: RecoveryMetricDelta
    escalation_delta: RecoveryMetricDelta
    coverage_gap_delta: RecoveryMetricDelta
    publish_conflict_delta: RecoveryMetricDelta
    residual_risks: tuple[ResidualRisk, ...]
    closure_judge: ClosureJudge
    continue_commands: tuple[str, ...]
    monitor_targets: tuple[str, ...]
    supporting_links: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.surface_id.strip():
            raise ValueError("surface_id must not be blank")
        if not self.headline.strip():
            raise ValueError("headline must not be blank")
        if not self.summary.strip():
            raise ValueError("summary must not be blank")
        object.__setattr__(self, "residual_risks", tuple(self.residual_risks))
        if not self.residual_risks:
            raise ValueError("residual_risks must not be empty")
        object.__setattr__(
            self,
            "continue_commands",
            _normalize_strings(self.continue_commands, label="continue command"),
        )
        object.__setattr__(
            self,
            "monitor_targets",
            _normalize_strings(self.monitor_targets, label="monitor target"),
        )
        object.__setattr__(
            self,
            "supporting_links",
            _normalize_strings(self.supporting_links, label="supporting link"),
        )
        if not self.continue_commands:
            raise ValueError("continue_commands must not be empty")
        if not self.supporting_links:
            raise ValueError("supporting_links must not be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "surface_id": self.surface_id,
            "headline": self.headline,
            "summary": self.summary,
            "command_ref": self.command_ref.to_dict(),
            "assessment": self.assessment.value,
            "before_after_alignment_view": self.before_after_alignment_view.to_dict(),
            "rewrite_delta": self.rewrite_delta.to_dict(),
            "drift_delta": self.drift_delta.to_dict(),
            "escalation_delta": self.escalation_delta.to_dict(),
            "coverage_gap_delta": self.coverage_gap_delta.to_dict(),
            "publish_conflict_delta": self.publish_conflict_delta.to_dict(),
            "residual_risks": [item.to_dict() for item in self.residual_risks],
            "closure_judge": self.closure_judge.to_dict(),
            "continue_commands": list(self.continue_commands),
            "monitor_targets": list(self.monitor_targets),
            "supporting_links": list(self.supporting_links),
        }


def build_recovery_window_surface(
    *,
    command_ref: GovernanceCommandRef,
    before_metrics: Iterable[RecoveryMetricSnapshot],
    after_metrics: Iterable[RecoveryMetricSnapshot],
    alignment_planes: Iterable[AlignmentPlaneChange],
    residual_risks: Iterable[ResidualRisk],
) -> RecoveryWindowSurface:
    before_map = {item.metric_key: item for item in before_metrics}
    after_map = {item.metric_key: item for item in after_metrics}
    if set(before_map) != set(after_map):
        raise ValueError("before_metrics and after_metrics must contain the same metric keys")

    metric_deltas = {
        key: _build_metric_delta(before=before_map[key], after=after_map[key])
        for key in sorted(before_map)
    }
    planes = tuple(alignment_planes)
    if not planes:
        raise ValueError("alignment_planes must not be empty")
    residuals = tuple(residual_risks)
    if not residuals:
        raise ValueError("residual_risks must not be empty")

    alignment_view = BeforeAfterAlignmentView(
        before_score=round(sum(item.before_score for item in planes) / len(planes), 3),
        after_score=round(sum(item.after_score for item in planes) / len(planes), 3),
        plane_changes=planes,
        improved_truth_planes=_dedupe(item.plane_key for item in planes if item.improved),
        residual_truth_planes=_dedupe(
            item.plane_key for item in planes if item.residual_reasons or item.after_state is not TruthPlaneState.ALIGNED
        ),
    )
    assessment = _determine_assessment(metric_deltas=metric_deltas, residual_risks=residuals)
    closure_judge = _build_closure_judge(
        assessment=assessment,
        metric_deltas=metric_deltas,
        residual_risks=residuals,
        alignment_view=alignment_view,
    )
    return RecoveryWindowSurface(
        surface_id="recovery-window",
        headline="Recovery Window",
        summary=_build_summary(
            command_ref=command_ref,
            assessment=assessment,
            metric_deltas=metric_deltas,
            residual_risks=residuals,
        ),
        command_ref=command_ref,
        assessment=assessment,
        before_after_alignment_view=alignment_view,
        rewrite_delta=_required_metric(metric_deltas, "rewrite_count"),
        drift_delta=_required_metric(metric_deltas, "drift_count"),
        escalation_delta=_required_metric(metric_deltas, "escalation_count"),
        coverage_gap_delta=_required_metric(metric_deltas, "coverage_gap_count"),
        publish_conflict_delta=_required_metric(metric_deltas, "publish_conflict_count"),
        residual_risks=residuals,
        closure_judge=closure_judge,
        continue_commands=closure_judge.next_commands,
        monitor_targets=closure_judge.monitor_targets,
        supporting_links=(
            f"downstream_reality_check:{command_ref.command_id}",
            f"propagation_ledger:{command_ref.command_id}",
            f"command_center:{command_ref.command_id}",
        ),
    )


def _build_metric_delta(
    *,
    before: RecoveryMetricSnapshot,
    after: RecoveryMetricSnapshot,
) -> RecoveryMetricDelta:
    if before.label != after.label:
        raise ValueError(f"metric labels must match for {before.metric_key}")
    if before.trend is not after.trend:
        raise ValueError(f"metric trend must match for {before.metric_key}")

    delta = after.value - before.value
    if before.trend is MetricTrend.LOWER_IS_BETTER:
        improved = after.value < before.value
    else:
        improved = after.value > before.value
    status = "flat"
    if delta != 0:
        status = "improved" if improved else "worsened"
    explanation = after.explanation or before.explanation
    return RecoveryMetricDelta(
        metric_key=before.metric_key,
        label=before.label,
        before_value=before.value,
        after_value=after.value,
        delta=delta,
        improved=improved,
        status=status,
        explanation=explanation,
    )


def _required_metric(
    metric_deltas: dict[str, RecoveryMetricDelta],
    metric_key: str,
) -> RecoveryMetricDelta:
    try:
        return metric_deltas[metric_key]
    except KeyError as exc:
        raise ValueError(f"required metric missing: {metric_key}") from exc


def _determine_assessment(
    *,
    metric_deltas: dict[str, RecoveryMetricDelta],
    residual_risks: tuple[ResidualRisk, ...],
) -> RecoveryAssessment:
    drift_delta = _required_metric(metric_deltas, "drift_count")
    unacceptable_residuals = tuple(risk for risk in residual_risks if not risk.acceptable_residual)
    improved_count = sum(1 for item in metric_deltas.values() if item.improved)

    if drift_delta.after_value > drift_delta.before_value:
        return RecoveryAssessment.DRIFT_REBOUND
    if not unacceptable_residuals:
        return RecoveryAssessment.RECOVERY_CONFIRMED
    if improved_count >= 3:
        return RecoveryAssessment.FALSE_RECOVERY
    return RecoveryAssessment.RECOVERY_INCOMPLETE


def _build_closure_judge(
    *,
    assessment: RecoveryAssessment,
    metric_deltas: dict[str, RecoveryMetricDelta],
    residual_risks: tuple[ResidualRisk, ...],
    alignment_view: BeforeAfterAlignmentView,
) -> ClosureJudge:
    improved_metrics = _dedupe(
        item.label for item in metric_deltas.values() if item.improved
    )
    unacceptable_residuals = tuple(risk for risk in residual_risks if not risk.acceptable_residual)
    residual_truth_planes = _dedupe(risk.truth_plane for risk in unacceptable_residuals) or alignment_view.residual_truth_planes
    closure_blockers = _dedupe(risk.label for risk in unacceptable_residuals)

    if assessment is RecoveryAssessment.RECOVERY_CONFIRMED:
        return ClosureJudge(
            assessment=assessment,
            recommendation=RecoveryDecision.CLOSE_AND_MONITOR,
            closeable=True,
            rationale="Key recovery metrics improved and only monitor-level residuals remain.",
            improved_metrics=improved_metrics,
            residual_truth_planes=alignment_view.residual_truth_planes,
            next_commands=("close_and_monitor", "monitor_recent_cycle"),
            monitor_targets=(
                "rewrite_count",
                "drift_count",
                "escalation_count",
                "coverage_gap_count",
                "publish_conflict_count",
            ),
            closure_blockers=(),
        )
    if assessment is RecoveryAssessment.DRIFT_REBOUND:
        return ClosureJudge(
            assessment=assessment,
            recommendation=RecoveryDecision.REOPEN_DRIFT_ROUTE,
            closeable=False,
            rationale="Drift rebounded after the command, so the cycle must reopen before any closure decision.",
            improved_metrics=improved_metrics,
            residual_truth_planes=residual_truth_planes,
            next_commands=_dedupe(
                ("reopen_drift_route", *(risk.recommended_command for risk in residual_risks))
            ),
            monitor_targets=("drift_count", "publish_conflict_count"),
            closure_blockers=closure_blockers,
        )
    if assessment is RecoveryAssessment.FALSE_RECOVERY:
        rationale = (
            "Headline metrics improved, but audience and publish truth planes still show unresolved mismatch."
        )
    else:
        rationale = (
            "Recovery signals improved only partially, so the command should continue with a lightweight follow-up."
        )
    return ClosureJudge(
        assessment=assessment,
        recommendation=RecoveryDecision.CONTINUE_WITH_LIGHTWEIGHT_FOLLOW_UP,
        closeable=False,
        rationale=rationale,
        improved_metrics=improved_metrics,
        residual_truth_planes=residual_truth_planes,
        next_commands=_dedupe(risk.recommended_command for risk in unacceptable_residuals),
        monitor_targets=("rewrite_count", "escalation_count", "coverage_gap_count"),
        closure_blockers=closure_blockers,
    )


def _build_summary(
    *,
    command_ref: GovernanceCommandRef,
    assessment: RecoveryAssessment,
    metric_deltas: dict[str, RecoveryMetricDelta],
    residual_risks: tuple[ResidualRisk, ...],
) -> str:
    improved_count = sum(1 for item in metric_deltas.values() if item.improved)
    unacceptable_count = sum(1 for risk in residual_risks if not risk.acceptable_residual)
    if assessment is RecoveryAssessment.RECOVERY_CONFIRMED:
        status_clause = "the system is consistent enough to close and monitor"
    elif assessment is RecoveryAssessment.DRIFT_REBOUND:
        status_clause = "drift rebounded and the route must be reopened"
    elif assessment is RecoveryAssessment.FALSE_RECOVERY:
        status_clause = "headline improvements are real but the cycle is still not safe to close"
    else:
        status_clause = "the system is improving but still lacks full recovery proof"
    return (
        f"{command_ref.command_type} on {command_ref.object_title} improved {improved_count} key recovery metric(s); "
        f"{unacceptable_count} unacceptable residual risk(s) remain, so {status_clause}."
    )


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    normalized: list[str] = []
    for raw_value in values:
        value = raw_value.strip()
        if not value:
            raise ValueError("deduped value must not be blank")
        if value not in seen:
            seen.add(value)
            normalized.append(value)
    return tuple(normalized)
