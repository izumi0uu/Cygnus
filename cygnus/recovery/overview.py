from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from cygnus.recovery.reality_check import GovernanceCommandRef, _normalize_strings
from cygnus.recovery.window import RecoveryAssessment, RecoveryWindowSurface, ResidualRisk


@dataclass(frozen=True, slots=True, kw_only=True)
class OpenLoopComparisonRow:
    command_id: str
    command_type: str
    object_title: str
    assessment: RecoveryAssessment
    closeable: bool
    residual_risk_count: int
    unacceptable_residual_count: int
    pending_propagation_count: int
    pending_propagation_summary: str
    recovery_proof_summary: str
    top_next_command: str
    open_loop_label: str

    def __post_init__(self) -> None:
        if not self.command_id.strip():
            raise ValueError("command_id must not be blank")
        if not self.command_type.strip():
            raise ValueError("command_type must not be blank")
        if not self.object_title.strip():
            raise ValueError("object_title must not be blank")
        if not self.pending_propagation_summary.strip():
            raise ValueError("pending_propagation_summary must not be blank")
        if not self.recovery_proof_summary.strip():
            raise ValueError("recovery_proof_summary must not be blank")
        if not self.top_next_command.strip():
            raise ValueError("top_next_command must not be blank")
        if not self.open_loop_label.strip():
            raise ValueError("open_loop_label must not be blank")
        if (
            self.residual_risk_count < 0
            or self.unacceptable_residual_count < 0
            or self.pending_propagation_count < 0
        ):
            raise ValueError("risk counts must not be negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "command_id": self.command_id,
            "command_type": self.command_type,
            "object_title": self.object_title,
            "assessment": self.assessment.value,
            "closeable": self.closeable,
            "residual_risk_count": self.residual_risk_count,
            "unacceptable_residual_count": self.unacceptable_residual_count,
            "pending_propagation_count": self.pending_propagation_count,
            "pending_propagation_summary": self.pending_propagation_summary,
            "recovery_proof_summary": self.recovery_proof_summary,
            "top_next_command": self.top_next_command,
            "open_loop_label": self.open_loop_label,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class OpenLoopRank:
    command_id: str
    label: str
    rank: int
    leverage_score: float
    residual_risk_count: int
    unacceptable_residual_count: int
    pending_propagation_count: int
    recovery_status: str

    def __post_init__(self) -> None:
        if not self.command_id.strip():
            raise ValueError("command_id must not be blank")
        if not self.label.strip():
            raise ValueError("label must not be blank")
        if self.rank < 0:
            raise ValueError("rank must not be negative")
        if not 0.0 <= self.leverage_score <= 100.0:
            raise ValueError("leverage_score must be between 0 and 100")
        if (
            self.residual_risk_count < 0
            or self.unacceptable_residual_count < 0
            or self.pending_propagation_count < 0
        ):
            raise ValueError("risk counts must not be negative")
        if not self.recovery_status.strip():
            raise ValueError("recovery_status must not be blank")

    def to_dict(self) -> dict[str, object]:
        return {
            "command_id": self.command_id,
            "label": self.label,
            "rank": self.rank,
            "leverage_score": self.leverage_score,
            "residual_risk_count": self.residual_risk_count,
            "unacceptable_residual_count": self.unacceptable_residual_count,
            "pending_propagation_count": self.pending_propagation_count,
            "recovery_status": self.recovery_status,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class GovernanceOverviewSurface:
    surface_id: str
    headline: str
    summary: str
    open_loops: tuple[OpenLoopComparisonRow, ...]
    open_loop_ranks: tuple[OpenLoopRank, ...]
    highest_leverage_command: str
    next_command_ribbon: tuple[str, ...]
    command_horizon: tuple[str, ...]
    governance_notes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.surface_id.strip():
            raise ValueError("surface_id must not be blank")
        if not self.headline.strip():
            raise ValueError("headline must not be blank")
        if not self.summary.strip():
            raise ValueError("summary must not be blank")
        object.__setattr__(self, "open_loops", tuple(self.open_loops))
        object.__setattr__(self, "open_loop_ranks", tuple(self.open_loop_ranks))
        object.__setattr__(self, "highest_leverage_command", self.highest_leverage_command.strip())
        object.__setattr__(
            self,
            "next_command_ribbon",
            _normalize_strings(self.next_command_ribbon, label="next command ribbon"),
        )
        object.__setattr__(
            self,
            "command_horizon",
            _normalize_strings(self.command_horizon, label="command horizon item"),
        )
        object.__setattr__(
            self,
            "governance_notes",
            _normalize_strings(self.governance_notes, label="governance note"),
        )
        if not self.open_loops:
            raise ValueError("open_loops must not be empty")
        if not self.open_loop_ranks:
            raise ValueError("open_loop_ranks must not be empty")
        if not self.highest_leverage_command:
            raise ValueError("highest_leverage_command must not be blank")

    def to_dict(self) -> dict[str, object]:
        return {
            "surface_id": self.surface_id,
            "headline": self.headline,
            "summary": self.summary,
            "open_loops": [item.to_dict() for item in self.open_loops],
            "open_loop_ranks": [item.to_dict() for item in self.open_loop_ranks],
            "highest_leverage_command": self.highest_leverage_command,
            "next_command_ribbon": list(self.next_command_ribbon),
            "command_horizon": list(self.command_horizon),
            "governance_notes": list(self.governance_notes),
        }


def build_governance_overview_surface(
    *,
    command_refs: Iterable[GovernanceCommandRef],
    recovery_windows: Iterable[RecoveryWindowSurface],
    residual_risks: Iterable[ResidualRisk],
) -> GovernanceOverviewSurface:
    refs = tuple(command_refs)
    windows = tuple(recovery_windows)
    risks = tuple(residual_risks)
    if not windows:
        raise ValueError("recovery_windows must not be empty")
    if not refs:
        raise ValueError("command_refs must not be empty")

    window_map = {window.command_ref.command_id: window for window in windows}
    missing_windows = [ref.command_id for ref in refs if ref.command_id not in window_map]
    if missing_windows:
        raise ValueError(
            "recovery_windows are missing command ids: " + ", ".join(sorted(missing_windows))
        )

    risk_map = _group_risks_by_command(risks)
    comparison_rows: list[tuple[OpenLoopComparisonRow, float]] = []
    for ref in refs:
        window = window_map[ref.command_id]
        per_window_risks = risk_map.get(ref.command_id, ())
        unacceptable = tuple(
            sorted(
                (risk for risk in per_window_risks if not risk.acceptable_residual),
                key=_risk_sort_key,
            )
        )
        pending_propagation_count = _pending_propagation_count(
            window=window,
            residual_risks=per_window_risks,
        )
        leverage = _calculate_leverage(
            window=window,
            risk_count=len(per_window_risks),
            unacceptable_count=len(unacceptable),
            pending_propagation_count=pending_propagation_count,
        )
        top_next_command = _top_next_command(
            window=window,
            residual_risks=per_window_risks,
        )
        comparison_rows.append(
            (
                OpenLoopComparisonRow(
                    command_id=ref.command_id,
                    command_type=ref.command_type,
                    object_title=ref.object_title,
                    assessment=window.assessment,
                    closeable=window.closure_judge.closeable,
                    residual_risk_count=len(per_window_risks),
                    unacceptable_residual_count=len(unacceptable),
                    pending_propagation_count=pending_propagation_count,
                    pending_propagation_summary=_pending_propagation_summary(
                        window=window,
                        pending_propagation_count=pending_propagation_count,
                    ),
                    recovery_proof_summary=_recovery_proof_summary(window),
                    top_next_command=top_next_command,
                    open_loop_label=f"open loop · {ref.object_title}",
                ),
                leverage,
            ),
        )

    sorted_rows = tuple(
        sorted(
            comparison_rows,
            key=lambda item: (
                -item[1],
                -item[0].unacceptable_residual_count,
                -item[0].pending_propagation_count,
                item[0].command_id,
            ),
        )
    )
    rank_rows: list[OpenLoopRank] = []
    for index, (row, leverage) in enumerate(sorted_rows, start=1):
        rank_rows.append(
            OpenLoopRank(
                command_id=row.command_id,
                label=f"{index}. {row.object_title}",
                rank=index,
                leverage_score=leverage,
                residual_risk_count=row.residual_risk_count,
                unacceptable_residual_count=row.unacceptable_residual_count,
                pending_propagation_count=row.pending_propagation_count,
                recovery_status=row.assessment.value,
            )
        )

    sorted_loop_rows = tuple(row for row, _ in sorted_rows)
    sorted_ranks = tuple(rank_rows)
    highest_leverage = sorted_loop_rows[0].command_id
    pending_loop_count = sum(1 for row in sorted_loop_rows if row.pending_propagation_count > 0)
    unacceptable_loop_count = sum(
        1 for row in sorted_loop_rows if row.unacceptable_residual_count > 0
    )
    return GovernanceOverviewSurface(
        surface_id="governance-overview",
        headline="Governance overview",
        summary=(
            f"{len(sorted_loop_rows)} open loop(s) remain visible to command; "
            f"{unacceptable_loop_count} loop(s) still carry unacceptable residuals and "
            f"{pending_loop_count} loop(s) still show pending propagation."
        ),
        open_loops=sorted_loop_rows,
        open_loop_ranks=sorted_ranks,
        highest_leverage_command=highest_leverage,
        next_command_ribbon=_next_command_ribbon(sorted_loop_rows),
        command_horizon=(
            f"{len(sorted_loop_rows)} unfinished governance loop(s) remain in play.",
            f"{pending_loop_count} loop(s) still need propagation follow-through before recovery can be trusted.",
            f"Route {sorted_loop_rows[0].top_next_command} first to move the highest-leverage loop.",
        ),
        governance_notes=(
            "Do not send the user back to raw data panes to reconstruct the situation.",
            "Propagation is not recovery; keep both states visible while ranking the next move.",
        ),
    )


def _group_risks_by_command(
    residual_risks: tuple[ResidualRisk, ...],
) -> dict[str, tuple[ResidualRisk, ...]]:
    grouped: dict[str, list[ResidualRisk]] = {}
    for risk in residual_risks:
        grouped.setdefault(risk.command_id, []).append(risk)
    return {
        command_id: tuple(sorted(items, key=_risk_sort_key))
        for command_id, items in grouped.items()
    }


def _calculate_leverage(
    *,
    window: RecoveryWindowSurface,
    risk_count: int,
    unacceptable_count: int,
    pending_propagation_count: int,
) -> float:
    assessment_weight = {
        RecoveryAssessment.DRIFT_REBOUND: 34.0,
        RecoveryAssessment.FALSE_RECOVERY: 25.0,
        RecoveryAssessment.RECOVERY_INCOMPLETE: 18.0,
        RecoveryAssessment.RECOVERY_CONFIRMED: 8.0,
    }[window.assessment]
    alignment_penalty = (1.0 - window.before_after_alignment_view.after_score) * 18.0
    closeable_penalty = 10.0 if window.closure_judge.closeable else 0.0
    score = (
        assessment_weight
        + (unacceptable_count * 10.0)
        + (pending_propagation_count * 6.0)
        + (risk_count * 2.0)
        + alignment_penalty
        - closeable_penalty
    )
    return round(max(0.0, min(100.0, score)), 1)


def _pending_propagation_count(
    *,
    window: RecoveryWindowSurface,
    residual_risks: tuple[ResidualRisk, ...],
) -> int:
    publish_truth_residuals = sum(
        1 for risk in residual_risks if risk.truth_plane == "publish_truth"
    )
    return max(window.publish_conflict_delta.after_value, publish_truth_residuals)


def _pending_propagation_summary(
    *,
    window: RecoveryWindowSurface,
    pending_propagation_count: int,
) -> str:
    if pending_propagation_count <= 0:
        return "No pending propagation remains; downstream surfaces are aligned with the latest command."
    if pending_propagation_count == 1:
        return "1 propagation blocker still keeps at least one downstream surface behind the latest command."
    return (
        f"{pending_propagation_count} propagation blockers still keep downstream surfaces behind "
        "the latest command."
    )


def _recovery_proof_summary(window: RecoveryWindowSurface) -> str:
    improved_metrics = len(window.closure_judge.improved_metrics)
    residual_planes = len(window.closure_judge.residual_truth_planes)
    return (
        f"{improved_metrics} recovery metric(s) improved, but {residual_planes} truth plane(s) "
        f"still prevent closure ({window.assessment.value})."
    )


def _next_command_ribbon(open_loops: tuple[OpenLoopComparisonRow, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    ribbon: list[str] = []
    for row in open_loops:
        if row.top_next_command in seen:
            continue
        seen.add(row.top_next_command)
        ribbon.append(row.top_next_command)
    return tuple(ribbon[:4])


def _top_next_command(
    *,
    window: RecoveryWindowSurface,
    residual_risks: tuple[ResidualRisk, ...],
) -> str:
    if window.closure_judge.closeable:
        return "close_and_monitor"
    sorted_risks = tuple(sorted(residual_risks, key=_risk_sort_key))
    unacceptable = tuple(risk for risk in sorted_risks if not risk.acceptable_residual)
    if unacceptable:
        return unacceptable[0].recommended_command
    if sorted_risks:
        return sorted_risks[0].recommended_command
    return window.continue_commands[0]


def _risk_sort_key(risk: ResidualRisk) -> tuple[int, int, str]:
    severity_weight = {
        "critical": 4,
        "elevated": 3,
        "emerging": 2,
        "watch": 1,
    }.get(risk.severity, 0)
    return (
        0 if not risk.acceptable_residual else 1,
        -severity_weight,
        risk.risk_id,
    )
