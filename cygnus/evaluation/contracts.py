from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from cygnus.domain import AudienceContext
from cygnus.evidence.records import FreshnessState, SupportEvidence
from cygnus.domain.objects import KnowledgeObject


EvalFamily = Literal[
    "plan_tier_refund",
    "product_version_known_issue",
    "region_feature_availability",
    "freshness_conflict",
    "ticket_cluster_draft",
]
EvalDisposition = Literal["answerable", "restricted", "fallback", "escalate"]
PolicyStatus = Literal[
    "success", "approval_required", "conflict", "denied", "not_found"
]

CHECK_OBJECT_RETRIEVAL = "object_retrieval"
CHECK_AUDIENCE_RESTRICTION = "audience_restriction"
CHECK_TRACE_RESOLUTION = "trace_resolution"
CHECK_CITATION_GROUNDING = "citation_grounding"
CHECK_FRESHNESS_PREFERENCE = "freshness_preference"
CHECK_UNSUPPORTED_ESCALATION = "unsupported_escalation"
CHECK_APPROVAL_REQUIRED = "approval_required"
CHECK_PUBLISH_POLICY = "publish_policy"
_EVAL_FAMILIES: frozenset[str] = frozenset(
    {
        "plan_tier_refund",
        "product_version_known_issue",
        "region_feature_availability",
        "freshness_conflict",
        "ticket_cluster_draft",
    }
)


def _normalize_refs(values: tuple[str, ...], *, label: str) -> tuple[str, ...]:
    normalized = tuple(value.strip() for value in values)
    if any(not value for value in normalized):
        raise ValueError(f"{label} must not contain blank values")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{label} must be unique")
    return normalized


@dataclass(frozen=True, slots=True, kw_only=True)
class PolicyExpectation:
    """Input and expected result for an existing publish-policy adapter probe."""

    draft_status: str
    page_version: int = 1
    expected_version: int | None = None
    is_admin: bool = False
    expected_status: PolicyStatus = "approval_required"
    expected_error: str | None = None

    def __post_init__(self) -> None:
        if not self.draft_status.strip():
            raise ValueError("draft_status must not be blank")
        if self.page_version < 1:
            raise ValueError("page_version must be positive")
        if self.expected_version is not None and self.expected_version < 1:
            raise ValueError("expected_version must be positive when provided")
        if self.expected_error is not None and not self.expected_error.strip():
            raise ValueError("expected_error must not be blank when provided")


@dataclass(frozen=True, slots=True, kw_only=True)
class EvalExpectation:
    disposition: EvalDisposition
    object_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    trace_refs: tuple[str, ...] = ()
    citation_refs: tuple[str, ...] = ()
    forbidden_object_refs: tuple[str, ...] = ()
    freshness: FreshnessState | None = None
    policy: PolicyExpectation | None = None

    def __post_init__(self) -> None:
        normalized = (
            _normalize_refs(self.object_refs, label="object_refs"),
            _normalize_refs(self.evidence_refs, label="evidence_refs"),
            _normalize_refs(self.trace_refs, label="trace_refs"),
            _normalize_refs(self.citation_refs, label="citation_refs"),
            _normalize_refs(
                self.forbidden_object_refs,
                label="forbidden_object_refs",
            ),
        )
        object.__setattr__(self, "object_refs", normalized[0])
        object.__setattr__(self, "evidence_refs", normalized[1])
        object.__setattr__(self, "trace_refs", normalized[2])
        object.__setattr__(self, "citation_refs", normalized[3])
        object.__setattr__(self, "forbidden_object_refs", normalized[4])
        overlap = set(self.object_refs) & set(self.forbidden_object_refs)
        if overlap:
            joined = ", ".join(sorted(overlap))
            raise ValueError(f"expected and forbidden object refs overlap: {joined}")


@dataclass(frozen=True, slots=True, kw_only=True)
class EvalCase:
    case_id: str
    family: EvalFamily
    title: str
    query: str
    audience_context: AudienceContext
    objects: tuple[KnowledgeObject, ...]
    evidence: tuple[SupportEvidence, ...]
    expectation: EvalExpectation
    citation_text: str | None = None

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("case_id must not be blank")
        if not self.title.strip():
            raise ValueError("title must not be blank")
        if not self.query.strip():
            raise ValueError("query must not be blank")
        if self.family not in _EVAL_FAMILIES:
            raise ValueError(f"unsupported evaluation family: {self.family}")
        object_ids = tuple(item.object_id for item in self.objects)
        if len(set(object_ids)) != len(object_ids):
            raise ValueError("case objects must have unique object_id values")
        evidence_ids = tuple(item.evidence_id for item in self.evidence)
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("case evidence must have unique evidence_id values")
        object.__setattr__(self, "objects", tuple(self.objects))
        object.__setattr__(self, "evidence", tuple(self.evidence))
        if self.citation_text is not None and not self.citation_text.strip():
            raise ValueError("citation_text must not be blank when provided")


@dataclass(frozen=True, slots=True, kw_only=True)
class EvalCheck:
    check_id: str
    passed: bool
    detail: str

    def __post_init__(self) -> None:
        if not self.check_id.strip():
            raise ValueError("check_id must not be blank")
        if not self.detail.strip():
            raise ValueError("detail must not be blank")

    def to_dict(self) -> dict[str, object]:
        return {
            "check_id": self.check_id,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class EvalCaseResult:
    case_id: str
    family: EvalFamily
    checks: tuple[EvalCheck, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("case_id must not be blank")
        if not self.checks:
            raise ValueError("case result must contain at least one check")
        check_ids = tuple(check.check_id for check in self.checks)
        if len(set(check_ids)) != len(check_ids):
            raise ValueError("case result check IDs must be unique")
        object.__setattr__(self, "checks", tuple(self.checks))

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failed_check_ids(self) -> tuple[str, ...]:
        return tuple(check.check_id for check in self.checks if not check.passed)

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "family": self.family,
            "passed": self.passed,
            "failed_check_ids": list(self.failed_check_ids),
            "checks": [check.to_dict() for check in self.checks],
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class EvalReport:
    suite_name: str
    results: tuple[EvalCaseResult, ...]

    def __post_init__(self) -> None:
        if not self.suite_name.strip():
            raise ValueError("suite_name must not be blank")
        if not self.results:
            raise ValueError("eval report must contain at least one case result")
        case_ids = tuple(result.case_id for result in self.results)
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("eval report case IDs must be unique")
        object.__setattr__(self, "results", tuple(self.results))

    @property
    def total_cases(self) -> int:
        return len(self.results)

    @property
    def passed_cases(self) -> int:
        return sum(result.passed for result in self.results)

    @property
    def failed_cases(self) -> int:
        return self.total_cases - self.passed_cases

    @property
    def total_checks(self) -> int:
        return sum(len(result.checks) for result in self.results)

    @property
    def failed_checks(self) -> int:
        return sum(len(result.failed_check_ids) for result in self.results)

    @property
    def passed(self) -> bool:
        return self.failed_cases == 0 and self.failed_checks == 0

    def to_dict(self) -> dict[str, object]:
        ordered = tuple(sorted(self.results, key=lambda result: result.case_id))
        return {
            "suite_name": self.suite_name,
            "passed": self.passed,
            "totals": {
                "cases": self.total_cases,
                "passed_cases": self.passed_cases,
                "failed_cases": self.failed_cases,
                "checks": self.total_checks,
                "failed_checks": self.failed_checks,
            },
            "results": [result.to_dict() for result in ordered],
        }
