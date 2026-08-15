from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import cast

from cygnus.domain import LifecycleState
from cygnus.integrations.session_bridge import (
    GovernedQueryRequest,
    GovernedSessionBridge,
    PropagationDeliveryTruth,
)
from cygnus.publish import PropagationStatus
from cygnus.retrieval import SubstrateKnowledgeSnapshot

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
    EvalReport,
)
from .policy import evaluate_policy_expectation


_SUITE_NAME = "cygnus-production-domain-eval"
_EVAL_CHANNEL = "copilot"
_UNSUPPORTED_DISPOSITIONS = frozenset({"fallback", "escalate"})


@dataclass(frozen=True, slots=True)
class _BridgeObservation:
    disposition: str | None
    answer: Mapping[str, object] | None
    selected_object_ref: str | None
    object_refs: frozenset[str]
    trace_refs: frozenset[str]
    source_trace: Mapping[str, object] | None
    evidence_refs: frozenset[str]
    freshness: str | None
    direct_content_exposed: bool

    @classmethod
    def from_response(cls, response: Mapping[str, object]) -> _BridgeObservation:
        data = _as_mapping(response.get("data"))
        governance = _as_mapping(data.get("governance"))
        answer = _as_optional_mapping(data.get("answer"))
        alternatives = _mapping_items(data.get("alternatives"))
        source_trace = _as_optional_mapping(data.get("source_trace"))

        selected_object_ref = _string_value(answer, "object_id")
        object_refs = {
            ref
            for ref in (
                selected_object_ref,
                *(_string_value(item, "object_id") for item in alternatives),
            )
            if ref is not None
        }

        governance_context = _as_mapping(data.get("governance_context"))
        trace_refs = {
            ref
            for ref in (
                _optional_string(response.get("trace_ref")),
                _string_value(answer, "trace_ref"),
                _string_value(governance_context, "trace_ref"),
                *(_string_value(item, "trace_ref") for item in alternatives),
            )
            if ref is not None
        }

        evidence_refs = frozenset(
            evidence_id
            for item in _mapping_items(
                source_trace.get("evidence_refs") if source_trace is not None else None
            )
            if (evidence_id := _string_value(item, "evidence_id")) is not None
        )
        content = answer.get("content") if answer is not None else None
        direct_content_exposed = answer is not None and (
            content is not None
            or answer.get("direct_external_use") is True
            or answer.get("usage") == "direct"
        )

        return cls(
            disposition=_string_value(governance, "state"),
            answer=answer,
            selected_object_ref=selected_object_ref,
            object_refs=frozenset(object_refs),
            trace_refs=frozenset(trace_refs),
            source_trace=source_trace,
            evidence_refs=evidence_refs,
            freshness=_string_value(source_trace, "freshness"),
            direct_content_exposed=direct_content_exposed,
        )


def _evaluation_delivery_truth(
    case: EvalCase,
    *,
    channel: str,
) -> PropagationDeliveryTruth:
    """Build explicit signed-delivery fixtures for one evaluation scenario."""
    rows = (
        (
            object_.object_id,
            channel,
            PropagationStatus.SYNCED.value,
            tuple(
                {
                    "channel": channel,
                    "audience_filter": audience.to_dict(),
                }
                for audience in object_.supported_audiences
            ),
        )
        for object_ in case.objects
        if object_.lifecycle_state is LifecycleState.PUBLISHED
    )
    return PropagationDeliveryTruth.from_propagation_rows(rows)


async def evaluate_case(case: EvalCase) -> EvalCaseResult:
    """Evaluate one deterministic corpus case against the governed session seam."""
    checks: list[EvalCheck] = []
    applicable = _applicable_retrieval_checks(case)

    try:
        snapshot = SubstrateKnowledgeSnapshot(
            objects=case.objects,
            evidence=case.evidence,
        )
        response = GovernedSessionBridge(snapshot).query_with_fixture_delivery(
            GovernedQueryRequest(
                request_ref=f"eval:{case.case_id}",
                query=case.query,
                audience_context=case.audience_context,
                channel=_EVAL_CHANNEL,
            ),
            delivery_truth=_evaluation_delivery_truth(case, channel=_EVAL_CHANNEL),
        )
        observation = _BridgeObservation.from_response(response)
    except Exception as exc:
        detail = _exception_detail(exc)
        checks.extend(
            EvalCheck(check_id=check_id, passed=False, detail=detail)
            for check_id in applicable
        )
    else:
        evaluators: tuple[tuple[str, Callable[[], EvalCheck]], ...] = (
            (
                CHECK_OBJECT_RETRIEVAL,
                lambda: _object_retrieval_check(case, observation),
            ),
            (
                CHECK_AUDIENCE_RESTRICTION,
                lambda: _audience_restriction_check(case, observation),
            ),
            (
                CHECK_TRACE_RESOLUTION,
                lambda: _trace_resolution_check(case, observation),
            ),
            (
                CHECK_CITATION_GROUNDING,
                lambda: _citation_grounding_check(case, observation),
            ),
            (
                CHECK_FRESHNESS_PREFERENCE,
                lambda: _freshness_preference_check(case, observation),
            ),
            (
                CHECK_UNSUPPORTED_ESCALATION,
                lambda: _unsupported_escalation_check(case, observation),
            ),
        )
        for check_id, evaluator in evaluators:
            if check_id not in applicable:
                continue
            try:
                checks.append(evaluator())
            except Exception as exc:
                checks.append(
                    EvalCheck(
                        check_id=check_id,
                        passed=False,
                        detail=_exception_detail(exc),
                    )
                )

    if case.expectation.policy is not None:
        policy_check_ids = (
            (CHECK_APPROVAL_REQUIRED, CHECK_PUBLISH_POLICY)
            if case.expectation.policy.expected_status == "approval_required"
            else (CHECK_PUBLISH_POLICY,)
        )
        try:
            policy_response = await evaluate_policy_expectation(case.expectation.policy)
            if CHECK_APPROVAL_REQUIRED in policy_check_ids:
                checks.append(_approval_required_check(policy_response))
            checks.append(_publish_policy_check(case, policy_response))
        except Exception as exc:
            detail = _exception_detail(exc)
            checks.extend(
                EvalCheck(check_id=check_id, passed=False, detail=detail)
                for check_id in policy_check_ids
            )

    if not checks:
        checks.append(
            EvalCheck(
                check_id=CHECK_OBJECT_RETRIEVAL,
                passed=False,
                detail="case defines no observable evaluation expectation",
            )
        )

    return EvalCaseResult(
        case_id=case.case_id, family=case.family, checks=tuple(checks)
    )


async def run_domain_eval(cases: Iterable[EvalCase] | None = None) -> EvalReport:
    """Run the reusable production-shaped corpus in stable case-ID order."""
    if cases is None:
        from .corpus import production_eval_cases

        source_cases: Iterable[EvalCase] = production_eval_cases()
    else:
        source_cases = cases
    ordered_cases = tuple(sorted(source_cases, key=lambda case: case.case_id))
    results: list[EvalCaseResult] = []
    for case in ordered_cases:
        try:
            results.append(await evaluate_case(case))
        except Exception as exc:
            results.append(
                EvalCaseResult(
                    case_id=case.case_id,
                    family=case.family,
                    checks=(
                        EvalCheck(
                            check_id=CHECK_OBJECT_RETRIEVAL,
                            passed=False,
                            detail=_exception_detail(exc),
                        ),
                    ),
                )
            )
    return EvalReport(suite_name=_SUITE_NAME, results=tuple(results))


def _applicable_retrieval_checks(case: EvalCase) -> tuple[str, ...]:
    expectation = case.expectation
    check_ids: list[str] = []
    if expectation.object_refs or expectation.disposition == "answerable":
        check_ids.append(CHECK_OBJECT_RETRIEVAL)
    if expectation.forbidden_object_refs:
        check_ids.append(CHECK_AUDIENCE_RESTRICTION)
    if expectation.trace_refs or expectation.disposition == "answerable":
        check_ids.append(CHECK_TRACE_RESOLUTION)
    if (
        expectation.evidence_refs
        or expectation.citation_refs
        or expectation.disposition == "answerable"
    ):
        check_ids.append(CHECK_CITATION_GROUNDING)
    if expectation.freshness is not None or expectation.disposition == "answerable":
        check_ids.append(CHECK_FRESHNESS_PREFERENCE)
    if expectation.disposition in _UNSUPPORTED_DISPOSITIONS:
        check_ids.append(CHECK_UNSUPPORTED_ESCALATION)
    return tuple(check_ids)


def _object_retrieval_check(
    case: EvalCase,
    observation: _BridgeObservation,
) -> EvalCheck:
    required = frozenset(case.expectation.object_refs)
    missing = sorted(required - observation.object_refs)
    selected_expected = not required or observation.selected_object_ref in required
    disposition_expected = (
        case.expectation.disposition != "answerable"
        or observation.disposition == "answerable"
    )
    passed = not missing and selected_expected and disposition_expected
    detail = (
        f"required={sorted(required)!r}; observed={sorted(observation.object_refs)!r}; "
        f"selected={observation.selected_object_ref!r}; disposition={observation.disposition!r}"
    )
    return EvalCheck(check_id=CHECK_OBJECT_RETRIEVAL, passed=passed, detail=detail)


def _audience_restriction_check(
    case: EvalCase,
    observation: _BridgeObservation,
) -> EvalCheck:
    forbidden = frozenset(case.expectation.forbidden_object_refs)
    exposed = sorted(forbidden & observation.object_refs)
    restricted = observation.disposition == case.expectation.disposition
    withheld = observation.answer is None
    passed = not exposed and restricted and withheld
    detail = (
        f"forbidden={sorted(forbidden)!r}; exposed={exposed!r}; "
        f"disposition={observation.disposition!r}; answer_withheld={withheld}"
    )
    return EvalCheck(check_id=CHECK_AUDIENCE_RESTRICTION, passed=passed, detail=detail)


def _trace_resolution_check(
    case: EvalCase,
    observation: _BridgeObservation,
) -> EvalCheck:
    required = frozenset(case.expectation.trace_refs)
    missing = sorted(required - observation.trace_refs)
    trace_object_ref = _string_value(observation.source_trace, "object_id")
    response_trace_ref = (
        f"trace:{trace_object_ref}" if trace_object_ref is not None else None
    )
    resolved = (
        observation.selected_object_ref is not None
        and trace_object_ref == observation.selected_object_ref
        and response_trace_ref in observation.trace_refs
    )
    passed = not missing and resolved
    detail = (
        f"required={sorted(required)!r}; observed={sorted(observation.trace_refs)!r}; "
        f"selected={observation.selected_object_ref!r}; trace_object={trace_object_ref!r}"
    )
    return EvalCheck(check_id=CHECK_TRACE_RESOLUTION, passed=passed, detail=detail)


def _citation_grounding_check(
    case: EvalCase,
    observation: _BridgeObservation,
) -> EvalCheck:
    required_evidence = frozenset(case.expectation.evidence_refs)
    missing_evidence = sorted(required_evidence - observation.evidence_refs)
    required_citations = frozenset(case.expectation.citation_refs)
    unresolved_citations = sorted(required_citations - observation.evidence_refs)
    citation_text = case.citation_text or ""
    missing_citations = sorted(
        ref for ref in required_citations if not _contains_ref(citation_text, ref)
    )
    has_grounding = observation.source_trace is not None and bool(
        observation.evidence_refs
    )
    passed = (
        not missing_evidence
        and not missing_citations
        and not unresolved_citations
        and has_grounding
    )
    detail = (
        f"required_evidence={sorted(required_evidence)!r}; "
        f"observed_evidence={sorted(observation.evidence_refs)!r}; "
        f"missing_citations={missing_citations!r}; "
        f"unresolved_citations={unresolved_citations!r}; grounded={has_grounding}"
    )
    return EvalCheck(check_id=CHECK_CITATION_GROUNDING, passed=passed, detail=detail)


def _freshness_preference_check(
    case: EvalCase,
    observation: _BridgeObservation,
) -> EvalCheck:
    expected_freshness = case.expectation.freshness
    expected_freshness_value = (
        expected_freshness.value if expected_freshness is not None else "fresh"
    )
    disposition_matches = observation.disposition == case.expectation.disposition
    freshness_matches = observation.freshness == expected_freshness_value
    unsafe_answerable = (
        observation.freshness in {"stale", "unknown"}
        and observation.disposition == "answerable"
    )
    passed = freshness_matches and disposition_matches and not unsafe_answerable
    detail = (
        f"expected_freshness={expected_freshness_value!r}; "
        f"actual_freshness={observation.freshness!r}; "
        f"expected_disposition={case.expectation.disposition!r}; "
        f"actual_disposition={observation.disposition!r}; "
        f"unsafe_answerable={unsafe_answerable}"
    )
    return EvalCheck(check_id=CHECK_FRESHNESS_PREFERENCE, passed=passed, detail=detail)


def _unsupported_escalation_check(
    case: EvalCase,
    observation: _BridgeObservation,
) -> EvalCheck:
    disposition_matches = observation.disposition == case.expectation.disposition
    passed = disposition_matches and not observation.direct_content_exposed
    detail = (
        f"expected_disposition={case.expectation.disposition!r}; "
        f"actual_disposition={observation.disposition!r}; "
        f"direct_content_exposed={observation.direct_content_exposed}"
    )
    return EvalCheck(
        check_id=CHECK_UNSUPPORTED_ESCALATION,
        passed=passed,
        detail=detail,
    )


def _approval_required_check(response: Mapping[str, object]) -> EvalCheck:
    status = _optional_string(response.get("status"))
    errors = _string_items(response.get("errors"))
    allowed = _as_mapping(response.get("data")).get("allowed")
    passed = (
        status == "approval_required"
        and "approval_required" in errors
        and allowed is False
    )
    detail = (
        f"status={status!r}; errors={list(errors)!r}; "
        f"allowed={allowed!r}; blocked={passed}"
    )
    return EvalCheck(check_id=CHECK_APPROVAL_REQUIRED, passed=passed, detail=detail)


def _publish_policy_check(
    case: EvalCase,
    response: Mapping[str, object],
) -> EvalCheck:
    expectation = case.expectation.policy
    assert expectation is not None
    status = _optional_string(response.get("status"))
    errors = _string_items(response.get("errors"))
    error_matches = (
        not errors
        if expectation.expected_error is None
        else expectation.expected_error in errors
    )
    passed = status == expectation.expected_status and error_matches
    detail = (
        f"expected_status={expectation.expected_status!r}; actual_status={status!r}; "
        f"expected_error={expectation.expected_error!r}; errors={list(errors)!r}"
    )
    return EvalCheck(check_id=CHECK_PUBLISH_POLICY, passed=passed, detail=detail)


def _as_mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return cast(Mapping[str, object], value)


def _as_optional_mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    return cast(Mapping[str, object], value)


def _mapping_items(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    items = cast(list[object] | tuple[object, ...], value)
    return tuple(
        cast(Mapping[str, object], item) for item in items if isinstance(item, Mapping)
    )


def _string_items(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    items = cast(list[object] | tuple[object, ...], value)
    return tuple(item for item in items if isinstance(item, str))


def _string_value(
    mapping: Mapping[str, object] | None,
    key: str,
) -> str | None:
    if mapping is None:
        return None
    return _optional_string(mapping.get(key))


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _contains_ref(text: str, ref: str) -> bool:
    ref_chars = r"A-Za-z0-9_.:/#-"
    return (
        re.search(
            rf"(?<![{ref_chars}]){re.escape(ref)}(?![{ref_chars}])",
            text,
        )
        is not None
    )


def _exception_detail(exc: Exception) -> str:
    message = str(exc).strip()
    suffix = f": {message}" if message else ""
    return f"evaluator exception {type(exc).__name__}{suffix}"
