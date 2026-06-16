from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from cygnus.substrate.pipeline_phases import PipelinePhase

_PHASE_SEQUENCE: tuple[PipelinePhase, ...] = tuple(PipelinePhase)


def _phase_index(phase: PipelinePhase) -> int:
    return _PHASE_SEQUENCE.index(phase)


def _coerce_phase(value: PipelinePhase | str) -> PipelinePhase:
    if isinstance(value, PipelinePhase):
        return value
    return PipelinePhase(value)


def _normalize_completed_phases(
    values: Iterable[PipelinePhase | str],
) -> tuple[PipelinePhase, ...]:
    seen: set[PipelinePhase] = set()
    normalized: list[PipelinePhase] = []
    for raw in values:
        phase = _coerce_phase(raw)
        if phase in seen:
            raise ValueError("completed phases must not contain duplicates")
        seen.add(phase)
        normalized.append(phase)
    return tuple(sorted(normalized, key=_phase_index))


@dataclass(frozen=True, slots=True, kw_only=True)
class PipelineCheckpoint:
    workflow_id: str
    current_phase: PipelinePhase = PipelinePhase.INGEST
    completed_phases: tuple[PipelinePhase, ...] = ()
    is_complete: bool = False

    def __post_init__(self) -> None:
        if not self.workflow_id.strip():
            raise ValueError("workflow_id must not be blank")

        normalized = _normalize_completed_phases(self.completed_phases)
        object.__setattr__(self, "completed_phases", normalized)

        if self.is_complete:
            if self.current_phase is not PipelinePhase.FEEDBACK:
                raise ValueError("completed checkpoint must end at feedback phase")
            expected = _PHASE_SEQUENCE
        else:
            expected = _PHASE_SEQUENCE[: _phase_index(self.current_phase)]

        if normalized != expected:
            expected_values = ", ".join(phase.value for phase in expected) or "none"
            raise ValueError(
                "completed phases do not match pipeline truth for the current phase; "
                f"expected: {expected_values}"
            )

    @property
    def resume_phase(self) -> PipelinePhase | None:
        if self.is_complete:
            return None
        return self.current_phase

    @property
    def last_completed_phase(self) -> PipelinePhase | None:
        if not self.completed_phases:
            return None
        return self.completed_phases[-1]

    def advance_to(self, target: PipelinePhase | str) -> PipelineCheckpoint:
        if self.is_complete:
            raise ValueError("completed workflow cannot advance")

        target_phase = _coerce_phase(target)
        current_idx = _phase_index(self.current_phase)
        target_idx = _phase_index(target_phase)

        if target_idx <= current_idx:
            raise ValueError("workflow phase cannot move backwards in the skeleton")
        if target_idx != current_idx + 1:
            raise ValueError("workflow phase must advance one step at a time")

        return PipelineCheckpoint(
            workflow_id=self.workflow_id,
            current_phase=target_phase,
            completed_phases=(*self.completed_phases, self.current_phase),
        )

    def mark_current_phase_complete(self) -> PipelineCheckpoint:
        if self.is_complete:
            return self

        completed = (*self.completed_phases, self.current_phase)
        if self.current_phase is PipelinePhase.FEEDBACK:
            return PipelineCheckpoint(
                workflow_id=self.workflow_id,
                current_phase=self.current_phase,
                completed_phases=completed,
                is_complete=True,
            )

        next_phase = _PHASE_SEQUENCE[_phase_index(self.current_phase) + 1]
        return PipelineCheckpoint(
            workflow_id=self.workflow_id,
            current_phase=next_phase,
            completed_phases=completed,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "workflow_id": self.workflow_id,
            "current_phase": self.current_phase.value,
            "completed_phases": [phase.value for phase in self.completed_phases],
            "resume_phase": self.resume_phase.value if self.resume_phase else None,
            "is_complete": self.is_complete,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> PipelineCheckpoint:
        return cls(
            workflow_id=str(payload["workflow_id"]),
            current_phase=_coerce_phase(str(payload["current_phase"])),
            completed_phases=tuple(payload.get("completed_phases", ())),
            is_complete=bool(payload.get("is_complete", False)),
        )
