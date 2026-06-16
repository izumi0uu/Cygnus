from __future__ import annotations

from dataclasses import dataclass, field

from cygnus.substrate.compilation_plan import CompilationProposal
from cygnus.substrate.pipeline_checkpoint import PipelineCheckpoint
from cygnus.substrate.pipeline_phases import PipelinePhase


@dataclass(slots=True, kw_only=True)
class ReviewPublishWorkflow:
    workflow_id: str
    phase_checkpoint: PipelineCheckpoint | None = None
    proposals: tuple[CompilationProposal, ...] = field(default_factory=tuple)
    review_notes: tuple[str, ...] = field(default_factory=tuple)
    publish_targets: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.workflow_id.strip():
            raise ValueError("workflow_id must not be blank")
        if self.phase_checkpoint is None:
            self.phase_checkpoint = PipelineCheckpoint(workflow_id=self.workflow_id)
        elif self.phase_checkpoint.workflow_id != self.workflow_id:
            raise ValueError("phase checkpoint must match workflow_id")

    @property
    def current_phase(self) -> PipelinePhase:
        return self.phase_checkpoint.current_phase

    @property
    def completed_phases(self) -> tuple[PipelinePhase, ...]:
        return self.phase_checkpoint.completed_phases

    @property
    def resume_phase(self) -> PipelinePhase | None:
        return self.phase_checkpoint.resume_phase

    @property
    def is_complete(self) -> bool:
        return self.phase_checkpoint.is_complete

    def advance(self, target: PipelinePhase) -> None:
        self.phase_checkpoint = self.phase_checkpoint.advance_to(target)

    def complete_current_phase(self) -> None:
        self.phase_checkpoint = self.phase_checkpoint.mark_current_phase_complete()

    def add_review_note(self, note: str) -> None:
        value = note.strip()
        if not value:
            raise ValueError("review note must not be blank")
        self.review_notes = (*self.review_notes, value)

    def to_dict(self) -> dict[str, object]:
        return {
            "workflow_id": self.workflow_id,
            "phase_checkpoint": self.phase_checkpoint.to_dict(),
            "current_phase": self.current_phase.value,
            "completed_phases": [phase.value for phase in self.completed_phases],
            "resume_phase": self.resume_phase.value if self.resume_phase else None,
            "is_complete": self.is_complete,
            "proposals": [proposal.to_dict() for proposal in self.proposals],
            "review_notes": list(self.review_notes),
            "publish_targets": list(self.publish_targets),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> ReviewPublishWorkflow:
        checkpoint_payload = payload.get("phase_checkpoint")
        if checkpoint_payload is None:
            checkpoint = PipelineCheckpoint.from_dict(payload)
        else:
            checkpoint = PipelineCheckpoint.from_dict(dict(checkpoint_payload))

        return cls(
            workflow_id=str(payload["workflow_id"]),
            phase_checkpoint=checkpoint,
            proposals=tuple(
                CompilationProposal.from_dict(dict(item))
                for item in payload.get("proposals", ())
            ),
            review_notes=tuple(str(item) for item in payload.get("review_notes", ())),
            publish_targets=tuple(str(item) for item in payload.get("publish_targets", ())),
        )
