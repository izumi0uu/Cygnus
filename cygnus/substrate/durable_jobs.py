from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from cygnus.substrate.pipeline_checkpoint import PipelineCheckpoint


class QueueStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    FAILED = "failed"
    RESUMED = "resumed"
    COMPLETED = "completed"


_ALLOWED_STATUS_TRANSITIONS: dict[QueueStatus, set[QueueStatus]] = {
    QueueStatus.PENDING: {QueueStatus.ACTIVE},
    QueueStatus.ACTIVE: {QueueStatus.FAILED, QueueStatus.COMPLETED},
    QueueStatus.FAILED: {QueueStatus.RESUMED},
    QueueStatus.RESUMED: {QueueStatus.ACTIVE},
    QueueStatus.COMPLETED: set(),
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


@dataclass(frozen=True, slots=True, kw_only=True)
class DurableWorkflowJob:
    job_id: str
    workflow_id: str
    workflow_name: str
    queue_name: str
    checkpoint: PipelineCheckpoint
    workflow_payload: dict[str, Any]
    queue_status: QueueStatus = QueueStatus.PENDING
    attempt_count: int = 0
    created_at: datetime = _utc_now()
    updated_at: datetime = _utc_now()
    last_error: str | None = None

    def __post_init__(self) -> None:
        if not self.job_id.strip():
            raise ValueError("job_id must not be blank")
        if not self.workflow_id.strip():
            raise ValueError("workflow_id must not be blank")
        if not self.workflow_name.strip():
            raise ValueError("workflow_name must not be blank")
        if not self.queue_name.strip():
            raise ValueError("queue_name must not be blank")
        if self.checkpoint.workflow_id != self.workflow_id:
            raise ValueError("checkpoint workflow_id must match job workflow_id")
        if self.attempt_count < 0:
            raise ValueError("attempt_count must not be negative")
        if self.last_error is not None and not self.last_error.strip():
            raise ValueError("last_error must not be blank when provided")

    @classmethod
    def from_workflow(
        cls,
        *,
        workflow_name: str,
        workflow: Any,
        queue_name: str = "governance",
        job_id: str | None = None,
    ) -> DurableWorkflowJob:
        checkpoint = getattr(workflow, "phase_checkpoint")
        payload = workflow.to_dict()
        return cls(
            job_id=job_id or f"job-{uuid.uuid4().hex}",
            workflow_id=str(workflow.workflow_id),
            workflow_name=workflow_name,
            queue_name=queue_name,
            checkpoint=checkpoint,
            workflow_payload=payload,
        )

    @property
    def resume_phase(self) -> str | None:
        phase = self.checkpoint.resume_phase
        return None if phase is None else phase.value

    def transition_to(self, target: QueueStatus, *, error: str | None = None) -> DurableWorkflowJob:
        if target not in _ALLOWED_STATUS_TRANSITIONS[self.queue_status]:
            allowed = ", ".join(item.value for item in sorted(_ALLOWED_STATUS_TRANSITIONS[self.queue_status], key=lambda value: value.value)) or "none"
            raise ValueError(
                f"invalid queue transition: {self.queue_status.value} -> {target.value}; "
                f"allowed targets: {allowed}"
            )

        attempt_count = self.attempt_count + 1 if target is QueueStatus.ACTIVE else self.attempt_count
        last_error = None
        if target is QueueStatus.FAILED:
            if error is None or not error.strip():
                raise ValueError("failed queue transition requires a non-blank error")
            last_error = error.strip()

        return DurableWorkflowJob(
            job_id=self.job_id,
            workflow_id=self.workflow_id,
            workflow_name=self.workflow_name,
            queue_name=self.queue_name,
            checkpoint=self.checkpoint,
            workflow_payload=dict(self.workflow_payload),
            queue_status=target,
            attempt_count=attempt_count,
            created_at=self.created_at,
            updated_at=_utc_now(),
            last_error=last_error,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "queue_name": self.queue_name,
            "queue_status": self.queue_status.value,
            "attempt_count": self.attempt_count,
            "checkpoint": self.checkpoint.to_dict(),
            "workflow_payload": self.workflow_payload,
            "resume_phase": self.resume_phase,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DurableWorkflowJob:
        return cls(
            job_id=str(payload["job_id"]),
            workflow_id=str(payload["workflow_id"]),
            workflow_name=str(payload["workflow_name"]),
            queue_name=str(payload["queue_name"]),
            queue_status=QueueStatus(str(payload["queue_status"])),
            attempt_count=int(payload.get("attempt_count", 0)),
            checkpoint=PipelineCheckpoint.from_dict(dict(payload["checkpoint"])),
            workflow_payload=dict(payload.get("workflow_payload", {})),
            created_at=_parse_timestamp(str(payload["created_at"])),
            updated_at=_parse_timestamp(str(payload["updated_at"])),
            last_error=payload.get("last_error"),
        )


class FileDurableJobStore:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def enqueue(self, job: DurableWorkflowJob) -> DurableWorkflowJob:
        return self.save(job)

    def load(self, job_id: str) -> DurableWorkflowJob:
        path = self._path_for(job_id)
        payload = json.loads(path.read_text(encoding="utf-8"))
        return DurableWorkflowJob.from_dict(payload)

    def save(self, job: DurableWorkflowJob) -> DurableWorkflowJob:
        path = self._path_for(job.job_id)
        path.write_text(json.dumps(job.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        return job

    def activate(self, job_id: str) -> DurableWorkflowJob:
        job = self.load(job_id).transition_to(QueueStatus.ACTIVE)
        return self.save(job)

    def fail(self, job_id: str, *, error: str) -> DurableWorkflowJob:
        job = self.load(job_id).transition_to(QueueStatus.FAILED, error=error)
        return self.save(job)

    def resume(self, job_id: str) -> DurableWorkflowJob:
        job = self.load(job_id).transition_to(QueueStatus.RESUMED)
        return self.save(job)

    def complete(self, job_id: str) -> DurableWorkflowJob:
        job = self.load(job_id).transition_to(QueueStatus.COMPLETED)
        return self.save(job)

    def _path_for(self, job_id: str) -> Path:
        if not job_id.strip():
            raise ValueError("job_id must not be blank")
        return self.root_dir / f"{job_id}.json"
