from __future__ import annotations

import copy
import unittest
from dataclasses import replace
from unittest.mock import AsyncMock, patch

from cygnus.domain import (
    AnswerCard,
    AudienceContext,
    AudienceFilter,
    LifecycleState,
    Visibility,
)
from cygnus.evaluation.contracts import (
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
    PolicyExpectation,
)
from cygnus.evaluation.runner import evaluate_case, run_domain_eval
from cygnus.evidence import EvidenceSourceType, FreshnessState, SupportEvidence
from cygnus.integrations.session_bridge import (
    GovernedQueryRequest,
    GovernedSessionBridge,
)
from cygnus.retrieval import SubstrateKnowledgeSnapshot


_AUDIENCE_FILTER = AudienceFilter(
    visibility=Visibility.EXTERNAL,
    product_lines=("billing",),
    plans=("free",),
    languages=("en",),
)
_AUDIENCE_CONTEXT = AudienceContext(
    visibility=Visibility.EXTERNAL,
    product_line="billing",
    plan="free",
    language="en",
)


def _evidence(
    *,
    freshness: FreshnessState = FreshnessState.FRESH,
) -> SupportEvidence:
    return SupportEvidence(
        evidence_id="ev-refund-window",
        source_type=EvidenceSourceType.HELP_CENTER,
        source_ref="help-center/refund-window",
        title="Free-plan refund window",
        content="A first paid upgrade may be refunded within fourteen days.",
        audience_filter=_AUDIENCE_FILTER,
        product_lines=("billing",),
        plans=("free",),
        languages=("en",),
        freshness_state=freshness,
        updated_at="2026-08-01T09:00:00Z",
    )


def _answer(*, evidence_ids: tuple[str, ...] = ("ev-refund-window",)) -> AnswerCard:
    return AnswerCard(
        object_id="ko-refund-window",
        title="Free-plan refund window",
        summary="Answers refund-window questions for a first paid upgrade.",
        lifecycle_state=LifecycleState.PUBLISHED,
        supported_audiences=(_AUDIENCE_FILTER,),
        evidence_ids=evidence_ids,
        tags=("billing", "refund"),
        question="Can a free-plan customer refund a first paid upgrade?",
        canonical_answer="Request the refund within fourteen days.",
        publish_targets=("help_center", "copilot"),
    )


def _supported_case(
    *,
    case_id: str = "plan-tier-refund-supported",
    freshness: FreshnessState = FreshnessState.FRESH,
    disposition: EvalDisposition = "answerable",
    policy: PolicyExpectation | None = None,
) -> EvalCase:
    evidence = _evidence(freshness=freshness)
    answer = _answer()
    return EvalCase(
        case_id=case_id,
        family="plan_tier_refund",
        title="Supported free-plan refund answer",
        query="free plan first paid upgrade refund window",
        audience_context=_AUDIENCE_CONTEXT,
        objects=(answer,),
        evidence=(evidence,),
        expectation=EvalExpectation(
            disposition=disposition,
            object_refs=(answer.object_id,),
            evidence_refs=(evidence.evidence_id,),
            trace_refs=(f"trace:{answer.object_id}",),
            citation_refs=(evidence.evidence_id,),
            freshness=freshness,
            policy=policy,
        ),
        citation_text=f"Refund guidance [{evidence.evidence_id}]",
    )


def _unsupported_case() -> EvalCase:
    return EvalCase(
        case_id="product-version-unsupported",
        family="product_version_known_issue",
        title="Unsupported product-version question",
        query="legacy product version undocumented failure",
        audience_context=_AUDIENCE_CONTEXT,
        objects=(),
        evidence=(),
        expectation=EvalExpectation(disposition="fallback"),
    )


def _bridge_payload(case: EvalCase) -> dict[str, object]:
    return GovernedSessionBridge(
        SubstrateKnowledgeSnapshot(objects=case.objects, evidence=case.evidence)
    ).query(
        GovernedQueryRequest(
            request_ref=f"test:{case.case_id}",
            query=case.query,
            audience_context=case.audience_context,
        )
    )


def _check(result: EvalCaseResult, check_id: str) -> EvalCheck:
    return next(check for check in result.checks if check.check_id == check_id)


class EvaluationRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_supported_case_passes_observable_retrieval_checks(self) -> None:
        result = await evaluate_case(_supported_case())

        self.assertTrue(result.passed, result.to_dict())
        self.assertEqual(
            tuple(check.check_id for check in result.checks),
            (
                CHECK_OBJECT_RETRIEVAL,
                CHECK_TRACE_RESOLUTION,
                CHECK_CITATION_GROUNDING,
                CHECK_FRESHNESS_PREFERENCE,
            ),
        )

    async def test_plausible_but_wrong_expected_object_fails_retrieval(self) -> None:
        case = _supported_case()
        plausible_other = AnswerCard(
            object_id="ko-refund-enterprise-exception",
            title="Enterprise refund exception",
            summary="A plausible but inapplicable refund policy object.",
            lifecycle_state=LifecycleState.PUBLISHED,
            supported_audiences=(_AUDIENCE_FILTER,),
            question="How are enterprise exceptions handled?",
            canonical_answer="Escalate enterprise exceptions.",
        )
        wrong_expectation = replace(
            case.expectation,
            object_refs=(plausible_other.object_id,),
        )
        wrong_case = replace(
            case,
            objects=(*case.objects, plausible_other),
            expectation=wrong_expectation,
        )

        result = await evaluate_case(wrong_case)

        self.assertFalse(_check(result, CHECK_OBJECT_RETRIEVAL).passed)

    async def test_restricted_case_requires_expected_object_to_be_selected(
        self,
    ) -> None:
        case = _supported_case(
            freshness=FreshnessState.STALE,
            disposition="restricted",
        )
        payload = copy.deepcopy(_bridge_payload(case))
        payload["data"]["answer"]["object_id"] = "ko-plausible-stale-alternative"
        payload["data"]["alternatives"].append(
            {
                "object_id": case.expectation.object_refs[0],
                "trace_ref": case.expectation.trace_refs[0],
            }
        )

        with patch.object(GovernedSessionBridge, "query", return_value=payload):
            result = await evaluate_case(case)

        self.assertFalse(_check(result, CHECK_OBJECT_RETRIEVAL).passed)

    async def test_missing_resolved_trace_fails_trace_and_grounding(self) -> None:
        case = _supported_case()
        payload = copy.deepcopy(_bridge_payload(case))
        payload["trace_ref"] = None
        data = payload["data"]
        self.assertIsInstance(data, dict)
        data["source_trace"] = None
        data["governance_context"]["trace_ref"] = None
        data["answer"]["trace_ref"] = None

        with patch.object(GovernedSessionBridge, "query", return_value=payload):
            result = await evaluate_case(case)

        self.assertFalse(_check(result, CHECK_TRACE_RESOLUTION).passed)
        self.assertFalse(_check(result, CHECK_CITATION_GROUNDING).passed)

    async def test_missing_required_evidence_fails_citation_grounding(self) -> None:
        case = _supported_case()
        payload = copy.deepcopy(_bridge_payload(case))
        source_trace = payload["data"]["source_trace"]
        self.assertIsInstance(source_trace, dict)
        source_trace["evidence_refs"] = []

        with patch.object(GovernedSessionBridge, "query", return_value=payload):
            result = await evaluate_case(case)

        self.assertFalse(_check(result, CHECK_CITATION_GROUNDING).passed)

    async def test_citation_must_resolve_to_observed_trace_evidence(self) -> None:
        base_case = _supported_case()
        case = replace(
            base_case,
            expectation=replace(base_case.expectation, evidence_refs=()),
        )
        payload = copy.deepcopy(_bridge_payload(case))
        source_trace = payload["data"]["source_trace"]
        self.assertIsInstance(source_trace, dict)
        source_trace["evidence_refs"][0]["evidence_id"] = "ev-different-source"

        with patch.object(GovernedSessionBridge, "query", return_value=payload):
            result = await evaluate_case(case)

        citation_check = _check(result, CHECK_CITATION_GROUNDING)
        self.assertFalse(citation_check.passed)
        self.assertIn(
            "unresolved_citations=['ev-refund-window']", citation_check.detail
        )

    async def test_missing_explicit_citation_ref_fails_grounding(self) -> None:
        case = replace(
            _supported_case(),
            citation_text="Refund guidance [ev-refund-window-superseded].",
        )

        result = await evaluate_case(case)

        self.assertFalse(_check(result, CHECK_CITATION_GROUNDING).passed)

    async def test_stale_response_presented_as_answerable_fails_freshness(self) -> None:
        case = _supported_case(
            freshness=FreshnessState.STALE,
            disposition="restricted",
        )
        payload = copy.deepcopy(_bridge_payload(case))
        payload["status"] = "success"
        payload["data"]["governance"]["state"] = "answerable"
        payload["data"]["answer"]["direct_external_use"] = True
        payload["data"]["answer"]["usage"] = "direct"

        with patch.object(GovernedSessionBridge, "query", return_value=payload):
            result = await evaluate_case(case)

        freshness_check = _check(result, CHECK_FRESHNESS_PREFERENCE)
        self.assertFalse(freshness_check.passed)
        self.assertIn("unsafe_answerable=True", freshness_check.detail)

    async def test_forbidden_audience_object_is_withheld(self) -> None:
        internal_only = AudienceFilter(
            visibility=Visibility.INTERNAL,
            product_lines=("billing",),
            plans=("enterprise",),
        )
        restricted_answer = AnswerCard(
            object_id="ko-enterprise-refund-internal",
            title="Enterprise refund approval",
            summary="Internal-only enterprise refund approval guidance.",
            lifecycle_state=LifecycleState.PUBLISHED,
            supported_audiences=(internal_only,),
            question="Who approves enterprise refund exceptions?",
            canonical_answer="Billing Ops approves enterprise exceptions.",
        )
        case = EvalCase(
            case_id="plan-tier-refund-restricted",
            family="plan_tier_refund",
            title="Enterprise refund guidance is audience restricted",
            query="enterprise refund approval",
            audience_context=AudienceContext(
                visibility=Visibility.EXTERNAL,
                product_line="billing",
                plan="enterprise",
            ),
            objects=(restricted_answer,),
            evidence=(),
            expectation=EvalExpectation(
                disposition="restricted",
                forbidden_object_refs=(restricted_answer.object_id,),
            ),
        )

        result = await evaluate_case(case)

        self.assertTrue(_check(result, CHECK_AUDIENCE_RESTRICTION).passed)

    async def test_unsupported_response_with_direct_answer_fails_escalation(
        self,
    ) -> None:
        unsupported = _unsupported_case()
        exposed_payload = _bridge_payload(_supported_case())

        with patch.object(
            GovernedSessionBridge,
            "query",
            return_value=exposed_payload,
        ):
            result = await evaluate_case(unsupported)

        unsupported_check = _check(result, CHECK_UNSUPPORTED_ESCALATION)
        self.assertFalse(unsupported_check.passed)
        self.assertIn("direct_content_exposed=True", unsupported_check.detail)

    async def test_true_unsupported_response_passes_without_content(self) -> None:
        result = await evaluate_case(_unsupported_case())

        self.assertTrue(_check(result, CHECK_UNSUPPORTED_ESCALATION).passed)

    async def test_approval_policy_emits_distinct_block_and_adapter_checks(
        self,
    ) -> None:
        expectation = PolicyExpectation(
            draft_status="pending",
            is_admin=False,
            expected_status="approval_required",
            expected_error="approval_required",
        )
        unsupported = _unsupported_case()
        case = replace(
            unsupported,
            expectation=replace(unsupported.expectation, policy=expectation),
        )
        policy_result = {
            "status": "approval_required",
            "data": {"allowed": False},
            "errors": ["approval_required"],
        }
        evaluator = AsyncMock(return_value=policy_result)

        with patch(
            "cygnus.evaluation.runner.evaluate_policy_expectation",
            evaluator,
        ):
            result = await evaluate_case(case)

        self.assertTrue(_check(result, CHECK_APPROVAL_REQUIRED).passed)
        self.assertTrue(_check(result, CHECK_PUBLISH_POLICY).passed)
        evaluator.assert_awaited_once_with(expectation)

    async def test_approval_check_rejects_allowed_policy_candidate(self) -> None:
        expectation = PolicyExpectation(
            draft_status="pending",
            is_admin=False,
            expected_status="approval_required",
            expected_error="approval_required",
        )
        unsupported = _unsupported_case()
        case = replace(
            unsupported,
            expectation=replace(unsupported.expectation, policy=expectation),
        )
        evaluator = AsyncMock(
            return_value={
                "status": "approval_required",
                "data": {"allowed": True},
                "errors": ["approval_required"],
            }
        )

        with patch(
            "cygnus.evaluation.runner.evaluate_policy_expectation",
            evaluator,
        ):
            result = await evaluate_case(case)

        self.assertFalse(_check(result, CHECK_APPROVAL_REQUIRED).passed)
        self.assertTrue(_check(result, CHECK_PUBLISH_POLICY).passed)

    async def test_wrong_delegated_policy_status_fails_publish_policy(self) -> None:
        expectation = PolicyExpectation(
            draft_status="approved",
            is_admin=True,
            expected_status="success",
        )
        unsupported = _unsupported_case()
        case = replace(
            unsupported,
            expectation=replace(unsupported.expectation, policy=expectation),
        )
        evaluator = AsyncMock(
            return_value={"status": "conflict", "errors": ["stale_version"]}
        )

        with patch(
            "cygnus.evaluation.runner.evaluate_policy_expectation",
            evaluator,
        ):
            result = await evaluate_case(case)

        self.assertFalse(_check(result, CHECK_PUBLISH_POLICY).passed)

    async def test_evaluator_exception_becomes_failed_checks(self) -> None:
        with patch.object(
            GovernedSessionBridge,
            "query",
            side_effect=RuntimeError("broken evaluator"),
        ):
            result = await evaluate_case(_supported_case())

        self.assertFalse(result.passed)
        self.assertEqual(
            result.failed_check_ids,
            (
                CHECK_OBJECT_RETRIEVAL,
                CHECK_TRACE_RESOLUTION,
                CHECK_CITATION_GROUNDING,
                CHECK_FRESHNESS_PREFERENCE,
            ),
        )
        self.assertTrue(all("RuntimeError" in check.detail for check in result.checks))

    async def test_report_order_is_stable_by_case_id(self) -> None:
        later = _supported_case(case_id="z-supported")
        earlier = _supported_case(case_id="a-supported")

        report = await run_domain_eval((later, earlier))

        self.assertEqual(report.suite_name, "cygnus-production-domain-eval")
        self.assertEqual(
            tuple(result.case_id for result in report.results),
            ("a-supported", "z-supported"),
        )
        self.assertEqual(
            [item["case_id"] for item in report.to_dict()["results"]],
            ["a-supported", "z-supported"],
        )
