from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from cygnus.domain.objects import KnowledgeObjectType


class PlanAction(str, Enum):
    CREATE = "create"
    UPDATE = "update"


class UrgencyLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class EvidenceSufficiency(str, Enum):
    INSUFFICIENT = "insufficient"
    PARTIAL = "partial"
    SUFFICIENT = "sufficient"



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
class CompilationProposal:
    proposal_id: str
    object_type: KnowledgeObjectType
    action: PlanAction
    title: str
    summary: str
    evidence_ids: tuple[str, ...]
    urgency: UrgencyLevel
    evidence_sufficiency: EvidenceSufficiency
    review_owner: str
    why_now: str
    audience_notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.proposal_id.strip():
            raise ValueError("proposal_id must not be blank")
        if not self.title.strip():
            raise ValueError("title must not be blank")
        if not self.summary.strip():
            raise ValueError("summary must not be blank")
        if not self.review_owner.strip():
            raise ValueError("review_owner must not be blank")
        if not self.why_now.strip():
            raise ValueError("why_now must not be blank")
        object.__setattr__(self, "evidence_ids", _normalize(self.evidence_ids, label="evidence id"))
        object.__setattr__(self, "audience_notes", _normalize(self.audience_notes, label="audience note"))
        if not self.evidence_ids:
            raise ValueError("compilation proposal must reference at least one evidence id")

    def to_dict(self) -> dict[str, object]:
        return {
            "proposal_id": self.proposal_id,
            "object_type": self.object_type.value,
            "action": self.action.value,
            "title": self.title,
            "summary": self.summary,
            "evidence_ids": list(self.evidence_ids),
            "urgency": self.urgency.value,
            "evidence_sufficiency": self.evidence_sufficiency.value,
            "review_owner": self.review_owner,
            "why_now": self.why_now,
            "audience_notes": list(self.audience_notes),
        }
