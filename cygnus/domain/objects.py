from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

from cygnus.domain.audience import AudienceFilter
from cygnus.domain.lifecycle import LifecycleState, transition


class KnowledgeObjectType(str, Enum):
    ANSWER_CARD = "answer_card"
    TROUBLESHOOTING_FLOW = "troubleshooting_flow"
    POLICY_RULE = "policy_rule"
    KNOWN_ISSUE_PAGE = "known_issue_page"
    ESCALATION_ROUTE = "escalation_route"


def _normalize_strings(values: Iterable[str] | None, *, label: str) -> tuple[str, ...]:
    if values is None:
        return ()

    normalized: list[str] = []
    for raw_value in values:
        value = raw_value.strip()
        if not value:
            raise ValueError(f"{label} values must not be empty")
        normalized.append(value)
    return tuple(normalized)


@dataclass(frozen=True, slots=True, kw_only=True)
class AudienceVariant:
    """Audience-specific override layer attached to a knowledge object."""

    audience_filter: AudienceFilter
    content: str
    label: str | None = None
    caveats: tuple[str, ...] = field(default_factory=tuple)
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.content.strip():
            raise ValueError("audience variant content must not be blank")
        if self.label is not None and not self.label.strip():
            raise ValueError("audience variant label must not be blank when provided")
        object.__setattr__(
            self, "caveats", _normalize_strings(self.caveats, label="caveat")
        )
        object.__setattr__(
            self, "evidence_ids", _normalize_strings(self.evidence_ids, label="evidence")
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "content": self.content,
            "audience_filter": self.audience_filter.to_dict(),
            "caveats": list(self.caveats),
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(slots=True, kw_only=True)
class KnowledgeObject:
    """Base contract for support-native knowledge objects."""

    object_id: str
    title: str
    summary: str
    lifecycle_state: LifecycleState = LifecycleState.DRAFT
    supported_audiences: tuple[AudienceFilter, ...] = field(default_factory=tuple)
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    tags: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.object_id.strip():
            raise ValueError("object_id must not be blank")
        if not self.title.strip():
            raise ValueError("title must not be blank")
        if not self.summary.strip():
            raise ValueError("summary must not be blank")
        self.supported_audiences = tuple(self.supported_audiences)
        self.evidence_ids = _normalize_strings(self.evidence_ids, label="evidence")
        self.tags = _normalize_strings(self.tags, label="tag")

    @property
    def object_type(self) -> KnowledgeObjectType:
        raise NotImplementedError

    def transition_to(self, target: LifecycleState) -> None:
        self.lifecycle_state = transition(self.lifecycle_state, target)

    def to_dict(self) -> dict[str, object]:
        return {
            "object_id": self.object_id,
            "object_type": self.object_type.value,
            "title": self.title,
            "summary": self.summary,
            "lifecycle_state": self.lifecycle_state.value,
            "supported_audiences": [
                audience.to_dict() for audience in self.supported_audiences
            ],
            "evidence_ids": list(self.evidence_ids),
            "tags": list(self.tags),
        }


@dataclass(slots=True, kw_only=True)
class AnswerCard(KnowledgeObject):
    question: str
    canonical_answer: str
    constraints: tuple[str, ...] = field(default_factory=tuple)
    audience_variants: tuple[AudienceVariant, ...] = field(default_factory=tuple)
    publish_targets: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        KnowledgeObject.__post_init__(self)
        if not self.question.strip():
            raise ValueError("question must not be blank")
        if not self.canonical_answer.strip():
            raise ValueError("canonical_answer must not be blank")
        self.constraints = _normalize_strings(self.constraints, label="constraint")
        self.audience_variants = tuple(self.audience_variants)
        self.publish_targets = _normalize_strings(
            self.publish_targets, label="publish target"
        )

    @property
    def object_type(self) -> KnowledgeObjectType:
        return KnowledgeObjectType.ANSWER_CARD

    def to_dict(self) -> dict[str, object]:
        payload = KnowledgeObject.to_dict(self)
        payload.update(
            {
                "question": self.question,
                "canonical_answer": self.canonical_answer,
                "constraints": list(self.constraints),
                "audience_variants": [
                    variant.to_dict() for variant in self.audience_variants
                ],
                "publish_targets": list(self.publish_targets),
            }
        )
        return payload


@dataclass(slots=True, kw_only=True)
class TroubleshootingFlow(KnowledgeObject):
    problem_statement: str
    prerequisites: tuple[str, ...] = field(default_factory=tuple)
    steps: tuple[str, ...] = field(default_factory=tuple)
    branching_conditions: tuple[str, ...] = field(default_factory=tuple)
    stop_conditions: tuple[str, ...] = field(default_factory=tuple)
    escalation_route_id: str | None = None

    def __post_init__(self) -> None:
        KnowledgeObject.__post_init__(self)
        if not self.problem_statement.strip():
            raise ValueError("problem_statement must not be blank")
        self.prerequisites = _normalize_strings(
            self.prerequisites, label="prerequisite"
        )
        self.steps = _normalize_strings(self.steps, label="step")
        self.branching_conditions = _normalize_strings(
            self.branching_conditions, label="branching condition"
        )
        self.stop_conditions = _normalize_strings(
            self.stop_conditions, label="stop condition"
        )
        if not self.steps:
            raise ValueError("troubleshooting flow must contain at least one step")
        if self.escalation_route_id is not None and not self.escalation_route_id.strip():
            raise ValueError("escalation_route_id must not be blank when provided")

    @property
    def object_type(self) -> KnowledgeObjectType:
        return KnowledgeObjectType.TROUBLESHOOTING_FLOW

    def to_dict(self) -> dict[str, object]:
        payload = KnowledgeObject.to_dict(self)
        payload.update(
            {
                "problem_statement": self.problem_statement,
                "prerequisites": list(self.prerequisites),
                "steps": list(self.steps),
                "branching_conditions": list(self.branching_conditions),
                "stop_conditions": list(self.stop_conditions),
                "escalation_route_id": self.escalation_route_id,
            }
        )
        return payload


@dataclass(slots=True, kw_only=True)
class PolicyRule(KnowledgeObject):
    rule_domain: str
    rule_statement: str
    effective_conditions: tuple[str, ...] = field(default_factory=tuple)
    exceptions: tuple[str, ...] = field(default_factory=tuple)
    authority_source: str | None = None
    human_override_notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        KnowledgeObject.__post_init__(self)
        if not self.rule_domain.strip():
            raise ValueError("rule_domain must not be blank")
        if not self.rule_statement.strip():
            raise ValueError("rule_statement must not be blank")
        self.effective_conditions = _normalize_strings(
            self.effective_conditions, label="effective condition"
        )
        self.exceptions = _normalize_strings(self.exceptions, label="exception")
        self.human_override_notes = _normalize_strings(
            self.human_override_notes, label="override note"
        )
        if self.authority_source is not None and not self.authority_source.strip():
            raise ValueError("authority_source must not be blank when provided")

    @property
    def object_type(self) -> KnowledgeObjectType:
        return KnowledgeObjectType.POLICY_RULE

    def to_dict(self) -> dict[str, object]:
        payload = KnowledgeObject.to_dict(self)
        payload.update(
            {
                "rule_domain": self.rule_domain,
                "rule_statement": self.rule_statement,
                "effective_conditions": list(self.effective_conditions),
                "exceptions": list(self.exceptions),
                "authority_source": self.authority_source,
                "human_override_notes": list(self.human_override_notes),
            }
        )
        return payload


@dataclass(slots=True, kw_only=True)
class KnownIssuePage(KnowledgeObject):
    issue_summary: str
    workaround: str
    issue_status: str
    affected_products: tuple[str, ...] = field(default_factory=tuple)
    affected_versions: tuple[str, ...] = field(default_factory=tuple)
    expected_next_update: str | None = None

    def __post_init__(self) -> None:
        KnowledgeObject.__post_init__(self)
        if not self.issue_summary.strip():
            raise ValueError("issue_summary must not be blank")
        if not self.workaround.strip():
            raise ValueError("workaround must not be blank")
        if not self.issue_status.strip():
            raise ValueError("issue_status must not be blank")
        self.affected_products = _normalize_strings(
            self.affected_products, label="affected product"
        )
        self.affected_versions = _normalize_strings(
            self.affected_versions, label="affected version"
        )
        if self.expected_next_update is not None and not self.expected_next_update.strip():
            raise ValueError("expected_next_update must not be blank when provided")

    @property
    def object_type(self) -> KnowledgeObjectType:
        return KnowledgeObjectType.KNOWN_ISSUE_PAGE

    def to_dict(self) -> dict[str, object]:
        payload = KnowledgeObject.to_dict(self)
        payload.update(
            {
                "issue_summary": self.issue_summary,
                "workaround": self.workaround,
                "issue_status": self.issue_status,
                "affected_products": list(self.affected_products),
                "affected_versions": list(self.affected_versions),
                "expected_next_update": self.expected_next_update,
            }
        )
        return payload


@dataclass(slots=True, kw_only=True)
class EscalationRoute(KnowledgeObject):
    trigger_conditions: tuple[str, ...]
    destination_team: str
    required_context: tuple[str, ...] = field(default_factory=tuple)
    blocked_domains: tuple[str, ...] = field(default_factory=tuple)
    severity_hint: str | None = None

    def __post_init__(self) -> None:
        KnowledgeObject.__post_init__(self)
        self.trigger_conditions = _normalize_strings(
            self.trigger_conditions, label="trigger condition"
        )
        self.required_context = _normalize_strings(
            self.required_context, label="required context"
        )
        self.blocked_domains = _normalize_strings(
            self.blocked_domains, label="blocked domain"
        )
        if not self.trigger_conditions:
            raise ValueError("escalation route must define at least one trigger condition")
        if not self.destination_team.strip():
            raise ValueError("destination_team must not be blank")
        if self.severity_hint is not None and not self.severity_hint.strip():
            raise ValueError("severity_hint must not be blank when provided")

    @property
    def object_type(self) -> KnowledgeObjectType:
        return KnowledgeObjectType.ESCALATION_ROUTE

    def to_dict(self) -> dict[str, Any]:
        payload = KnowledgeObject.to_dict(self)
        payload.update(
            {
                "trigger_conditions": list(self.trigger_conditions),
                "destination_team": self.destination_team,
                "required_context": list(self.required_context),
                "blocked_domains": list(self.blocked_domains),
                "severity_hint": self.severity_hint,
            }
        )
        return payload
