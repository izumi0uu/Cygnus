from __future__ import annotations

from dataclasses import dataclass, field

from cygnus.substrate.compilation_plan import CompilationProposal
from cygnus.substrate.pipeline_phases import PipelinePhase


@dataclass(slots=True, kw_only=True)
class ReviewPublishWorkflow:
    workflow_id: str
    current_phase: PipelinePhase = PipelinePhase.INGEST
    proposals: tuple[CompilationProposal, ...] = field(default_factory=tuple)
    review_notes: tuple[str, ...] = field(default_factory=tuple)
    publish_targets: tuple[str, ...] = field(default_factory=tuple)

    def advance(self, target: PipelinePhase) -> None:
        phases = list(PipelinePhase)
        current_idx = phases.index(self.current_phase)
        target_idx = phases.index(target)
        if target_idx < current_idx:
            raise ValueError("workflow phase cannot move backwards in the skeleton")
        self.current_phase = target

    def add_review_note(self, note: str) -> None:
        value = note.strip()
        if not value:
            raise ValueError("review note must not be blank")
        self.review_notes = (*self.review_notes, value)

    def to_dict(self) -> dict[str, object]:
        return {
            "workflow_id": self.workflow_id,
            "current_phase": self.current_phase.value,
            "proposals": [proposal.to_dict() for proposal in self.proposals],
            "review_notes": list(self.review_notes),
            "publish_targets": list(self.publish_targets),
        }
