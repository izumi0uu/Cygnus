from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from cygnus.substrate.pipeline_checkpoint import PipelineCheckpoint
from cygnus.substrate.pipeline_phases import PipelinePhase


class GoldenPathStage(str, Enum):
    INGEST = "ingest"
    COMPILE = "compile"
    REVIEW = "review"
    PUBLISH = "publish"
    RECOVERY = "recovery"


_GOLDEN_PATH_SEQUENCE: tuple[GoldenPathStage, ...] = tuple(GoldenPathStage)
_STAGE_ENTRY_PHASE: dict[GoldenPathStage, PipelinePhase] = {
    GoldenPathStage.INGEST: PipelinePhase.INGEST,
    GoldenPathStage.COMPILE: PipelinePhase.NORMALIZE,
    GoldenPathStage.REVIEW: PipelinePhase.REVIEW,
    GoldenPathStage.PUBLISH: PipelinePhase.PUBLISH,
    GoldenPathStage.RECOVERY: PipelinePhase.FEEDBACK,
}


def _stage_index(stage: GoldenPathStage) -> int:
    return _GOLDEN_PATH_SEQUENCE.index(stage)


@dataclass(frozen=True, slots=True, kw_only=True)
class GoldenPathCheckpoint:
    workflow_id: str
    current_stage: GoldenPathStage = GoldenPathStage.INGEST
    completed_stages: tuple[GoldenPathStage, ...] = ()
    is_complete: bool = False

    def __post_init__(self) -> None:
        if not self.workflow_id.strip():
            raise ValueError("workflow_id must not be blank")

        seen: set[GoldenPathStage] = set()
        normalized: list[GoldenPathStage] = []
        for stage in self.completed_stages:
            if stage in seen:
                raise ValueError("completed stages must not contain duplicates")
            seen.add(stage)
            normalized.append(stage)
        normalized = sorted(normalized, key=_stage_index)
        object.__setattr__(self, "completed_stages", tuple(normalized))

        if self.is_complete:
            expected = _GOLDEN_PATH_SEQUENCE
            if self.current_stage is not GoldenPathStage.RECOVERY:
                raise ValueError("completed golden path must end at recovery")
        else:
            expected = _GOLDEN_PATH_SEQUENCE[: _stage_index(self.current_stage)]

        if tuple(normalized) != expected:
            expected_values = ", ".join(stage.value for stage in expected) or "none"
            raise ValueError(
                "completed stages do not match golden-path truth; "
                f"expected: {expected_values}"
            )

    @property
    def resume_stage(self) -> GoldenPathStage | None:
        if self.is_complete:
            return None
        return self.current_stage

    def advance_to(self, target: GoldenPathStage) -> GoldenPathCheckpoint:
        if self.is_complete:
            raise ValueError("completed golden path cannot advance")
        current_idx = _stage_index(self.current_stage)
        target_idx = _stage_index(target)
        if target_idx <= current_idx:
            raise ValueError("golden path stage cannot move backwards")
        if target_idx != current_idx + 1:
            raise ValueError("golden path stage must advance one step at a time")
        return GoldenPathCheckpoint(
            workflow_id=self.workflow_id,
            current_stage=target,
            completed_stages=(*self.completed_stages, self.current_stage),
        )

    def mark_current_stage_complete(self) -> GoldenPathCheckpoint:
        if self.is_complete:
            return self
        completed = (*self.completed_stages, self.current_stage)
        if self.current_stage is GoldenPathStage.RECOVERY:
            return GoldenPathCheckpoint(
                workflow_id=self.workflow_id,
                current_stage=self.current_stage,
                completed_stages=completed,
                is_complete=True,
            )
        next_stage = _GOLDEN_PATH_SEQUENCE[_stage_index(self.current_stage) + 1]
        return GoldenPathCheckpoint(
            workflow_id=self.workflow_id,
            current_stage=next_stage,
            completed_stages=completed,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "workflow_id": self.workflow_id,
            "current_stage": self.current_stage.value,
            "completed_stages": [stage.value for stage in self.completed_stages],
            "resume_stage": self.resume_stage.value if self.resume_stage else None,
            "is_complete": self.is_complete,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> GoldenPathCheckpoint:
        return cls(
            workflow_id=str(payload["workflow_id"]),
            current_stage=GoldenPathStage(str(payload["current_stage"])),
            completed_stages=tuple(
                GoldenPathStage(str(stage))
                for stage in payload.get("completed_stages", ())
            ),
            is_complete=bool(payload.get("is_complete", False)),
        )


@dataclass(slots=True, kw_only=True)
class GovernanceGoldenPathWorkflow:
    workflow_id: str
    stage_checkpoint: GoldenPathCheckpoint | None = None
    phase_checkpoint: PipelineCheckpoint | None = None
    ingress_ref: str | None = None
    compile_ref: str | None = None
    review_ref: str | None = None
    publish_ref: str | None = None
    recovery_ref: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.workflow_id.strip():
            raise ValueError("workflow_id must not be blank")
        if self.stage_checkpoint is None:
            self.stage_checkpoint = GoldenPathCheckpoint(workflow_id=self.workflow_id)
        elif self.stage_checkpoint.workflow_id != self.workflow_id:
            raise ValueError("stage checkpoint must match workflow_id")
        if self.phase_checkpoint is None:
            self.phase_checkpoint = PipelineCheckpoint(workflow_id=self.workflow_id)
        elif self.phase_checkpoint.workflow_id != self.workflow_id:
            raise ValueError("phase checkpoint must match workflow_id")

    @property
    def current_stage(self) -> GoldenPathStage:
        return self.stage_checkpoint.current_stage

    @property
    def current_phase(self) -> PipelinePhase:
        return self.phase_checkpoint.current_phase

    @property
    def is_complete(self) -> bool:
        return self.stage_checkpoint.is_complete and self.phase_checkpoint.is_complete

    def advance_to(self, target: GoldenPathStage) -> None:
        self.stage_checkpoint = self.stage_checkpoint.advance_to(target)
        target_phase = _STAGE_ENTRY_PHASE[target]
        while (
            not self.phase_checkpoint.is_complete
            and self.phase_checkpoint.current_phase is not target_phase
        ):
            self.phase_checkpoint = self.phase_checkpoint.mark_current_phase_complete()

    def mark_current_stage_complete(self) -> None:
        self.stage_checkpoint = self.stage_checkpoint.mark_current_stage_complete()
        if self.stage_checkpoint.is_complete:
            while not self.phase_checkpoint.is_complete:
                self.phase_checkpoint = self.phase_checkpoint.mark_current_phase_complete()
            return

        target_phase = _STAGE_ENTRY_PHASE[self.stage_checkpoint.current_stage]
        while (
            not self.phase_checkpoint.is_complete
            and self.phase_checkpoint.current_phase is not target_phase
        ):
            self.phase_checkpoint = self.phase_checkpoint.mark_current_phase_complete()

    def add_note(self, note: str) -> None:
        value = note.strip()
        if not value:
            raise ValueError("note must not be blank")
        self.notes = (*self.notes, value)

    def to_dict(self) -> dict[str, object]:
        return {
            "workflow_id": self.workflow_id,
            "workflow_name": "governance_golden_path",
            "stage_checkpoint": self.stage_checkpoint.to_dict(),
            "phase_checkpoint": self.phase_checkpoint.to_dict(),
            "current_stage": self.current_stage.value,
            "current_phase": self.current_phase.value,
            "is_complete": self.is_complete,
            "ingress_ref": self.ingress_ref,
            "compile_ref": self.compile_ref,
            "review_ref": self.review_ref,
            "publish_ref": self.publish_ref,
            "recovery_ref": self.recovery_ref,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> GovernanceGoldenPathWorkflow:
        stage_payload = payload.get("stage_checkpoint")
        if stage_payload is None:
            stage_checkpoint = GoldenPathCheckpoint.from_dict(payload)
        else:
            stage_checkpoint = GoldenPathCheckpoint.from_dict(dict(stage_payload))

        phase_payload = payload.get("phase_checkpoint")
        if phase_payload is None:
            phase_checkpoint = PipelineCheckpoint.from_dict(payload)
        else:
            phase_checkpoint = PipelineCheckpoint.from_dict(dict(phase_payload))

        return cls(
            workflow_id=str(payload["workflow_id"]),
            stage_checkpoint=stage_checkpoint,
            phase_checkpoint=phase_checkpoint,
            ingress_ref=payload.get("ingress_ref"),
            compile_ref=payload.get("compile_ref"),
            review_ref=payload.get("review_ref"),
            publish_ref=payload.get("publish_ref"),
            recovery_ref=payload.get("recovery_ref"),
            notes=tuple(str(note) for note in payload.get("notes", ())),
        )

    @classmethod
    def sample(cls) -> GovernanceGoldenPathWorkflow:
        workflow = cls(
            workflow_id="golden-path-1",
            ingress_ref="source:billing-export-guide",
            compile_ref="plan:billing-export-answer",
            review_ref="review:refund-enterprise-rewrite",
            publish_ref="publish:ko-billing-refund-policy",
            recovery_ref="recovery:cmd-publish-1",
        )
        workflow.add_note("Product-level golden path for post-cutover governance verification.")
        return workflow


def build_governance_golden_path() -> GovernanceGoldenPathWorkflow:
    workflow = GovernanceGoldenPathWorkflow.sample()
    workflow.mark_current_stage_complete()  # ingest
    workflow.mark_current_stage_complete()  # compile
    workflow.mark_current_stage_complete()  # review
    workflow.mark_current_stage_complete()  # publish
    workflow.mark_current_stage_complete()  # recovery
    return workflow


def assert_governance_golden_path_complete() -> dict[str, object]:
    workflow = build_governance_golden_path()
    if not workflow.is_complete:
        raise ValueError("governance golden path is not complete")
    return workflow.to_dict()
