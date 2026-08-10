"""Deterministic domain-evaluation contracts and execution surface."""

from .contracts import (
    CHECK_APPROVAL_REQUIRED,
    CHECK_AUDIENCE_RESTRICTION,
    CHECK_CITATION_GROUNDING,
    CHECK_FRESHNESS_PREFERENCE,
    CHECK_OBJECT_RETRIEVAL,
    CHECK_PUBLISH_POLICY,
    CHECK_TRACE_RESOLUTION,
    CHECK_UNSUPPORTED_ESCALATION,
    EvalCase,
    EvalCaseResult,
    EvalCheck,
    EvalDisposition,
    EvalExpectation,
    EvalFamily,
    EvalReport,
    PolicyExpectation,
    PolicyStatus,
)
from .corpus import production_eval_cases
from .policy import evaluate_policy_expectation
from .runner import evaluate_case, run_domain_eval

__all__ = [
    "CHECK_APPROVAL_REQUIRED",
    "CHECK_AUDIENCE_RESTRICTION",
    "CHECK_CITATION_GROUNDING",
    "CHECK_FRESHNESS_PREFERENCE",
    "CHECK_OBJECT_RETRIEVAL",
    "CHECK_PUBLISH_POLICY",
    "CHECK_TRACE_RESOLUTION",
    "CHECK_UNSUPPORTED_ESCALATION",
    "EvalCase",
    "EvalCaseResult",
    "EvalCheck",
    "EvalDisposition",
    "EvalExpectation",
    "EvalFamily",
    "EvalReport",
    "PolicyExpectation",
    "PolicyStatus",
    "evaluate_case",
    "evaluate_policy_expectation",
    "production_eval_cases",
    "run_domain_eval",
]
