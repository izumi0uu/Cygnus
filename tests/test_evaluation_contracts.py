from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError

import cygnus.evaluation as evaluation
from cygnus.domain import AudienceContext, Visibility
from cygnus.evaluation.contracts import (
    EvalCase as ContractEvalCase,
    EvalReport as ContractEvalReport,
)
from cygnus.evaluation.corpus import production_eval_cases as corpus_function
from cygnus.evaluation.policy import (
    evaluate_policy_expectation as policy_function,
)
from cygnus.evaluation.runner import evaluate_case as case_function
from cygnus.evaluation.runner import run_domain_eval as runner_function


class EvaluationContractTests(unittest.TestCase):
    @staticmethod
    def _check(
        check_id: str = evaluation.CHECK_OBJECT_RETRIEVAL,
        *,
        passed: bool = True,
        detail: str = "observable evaluation detail",
    ) -> evaluation.EvalCheck:
        return evaluation.EvalCheck(
            check_id=check_id,
            passed=passed,
            detail=detail,
        )

    @classmethod
    def _result(
        cls,
        case_id: str,
        *,
        family: evaluation.EvalFamily = "plan_tier_refund",
        passed: bool = True,
    ) -> evaluation.EvalCaseResult:
        return evaluation.EvalCaseResult(
            case_id=case_id,
            family=family,
            checks=(cls._check(passed=passed),),
        )

    def test_contract_dataclasses_are_frozen(self) -> None:
        result = self._result("frozen-result")
        contracts_and_mutations = (
            (
                evaluation.PolicyExpectation(draft_status="approved"),
                "draft_status",
                "draft",
            ),
            (
                evaluation.EvalExpectation(disposition="answerable"),
                "disposition",
                "fallback",
            ),
            (
                evaluation.EvalCase(
                    case_id="frozen-case",
                    family="plan_tier_refund",
                    title="Frozen case",
                    query="What is the refund policy?",
                    audience_context=AudienceContext(
                        visibility=Visibility.EXTERNAL,
                    ),
                    objects=(),
                    evidence=(),
                    expectation=evaluation.EvalExpectation(
                        disposition="fallback",
                    ),
                ),
                "title",
                "Changed title",
            ),
            (self._check(), "detail", "changed detail"),
            (result, "case_id", "changed-result"),
            (
                evaluation.EvalReport(
                    suite_name="frozen-suite",
                    results=(result,),
                ),
                "suite_name",
                "changed-suite",
            ),
        )

        for contract, field_name, new_value in contracts_and_mutations:
            with self.subTest(contract=type(contract).__name__, field=field_name):
                with self.assertRaises(FrozenInstanceError):
                    setattr(contract, field_name, new_value)

    def test_report_to_dict_has_stable_shape_and_case_order(self) -> None:
        later = evaluation.EvalCaseResult(
            case_id="case-z",
            family="ticket_cluster_draft",
            checks=(
                self._check(
                    evaluation.CHECK_UNSUPPORTED_ESCALATION,
                    passed=False,
                    detail="direct answer was exposed",
                ),
            ),
        )
        earlier = evaluation.EvalCaseResult(
            case_id="case-a",
            family="plan_tier_refund",
            checks=(self._check(detail="required object was retrieved"),),
        )
        report = evaluation.EvalReport(
            suite_name="cygnus-production-domain",
            results=(later, earlier),
        )

        expected = {
            "suite_name": "cygnus-production-domain",
            "passed": False,
            "totals": {
                "cases": 2,
                "passed_cases": 1,
                "failed_cases": 1,
                "checks": 2,
                "failed_checks": 1,
            },
            "results": [
                {
                    "case_id": "case-a",
                    "family": "plan_tier_refund",
                    "passed": True,
                    "failed_check_ids": [],
                    "checks": [
                        {
                            "check_id": evaluation.CHECK_OBJECT_RETRIEVAL,
                            "passed": True,
                            "detail": "required object was retrieved",
                        }
                    ],
                },
                {
                    "case_id": "case-z",
                    "family": "ticket_cluster_draft",
                    "passed": False,
                    "failed_check_ids": [
                        evaluation.CHECK_UNSUPPORTED_ESCALATION,
                    ],
                    "checks": [
                        {
                            "check_id": evaluation.CHECK_UNSUPPORTED_ESCALATION,
                            "passed": False,
                            "detail": "direct answer was exposed",
                        }
                    ],
                },
            ],
        }

        first = report.to_dict()
        self.assertEqual(first, expected)
        self.assertEqual(report.to_dict(), expected)
        self.assertEqual(
            list(first),
            ["suite_name", "passed", "totals", "results"],
        )
        self.assertEqual(
            list(first["totals"]),
            ["cases", "passed_cases", "failed_cases", "checks", "failed_checks"],
        )
        self.assertEqual(
            list(first["results"][0]),
            ["case_id", "family", "passed", "failed_check_ids", "checks"],
        )
        self.assertEqual(
            list(first["results"][0]["checks"][0]),
            ["check_id", "passed", "detail"],
        )

    def test_duplicate_check_and_case_ids_are_rejected(self) -> None:
        check = self._check()
        with self.assertRaisesRegex(ValueError, "check IDs must be unique"):
            evaluation.EvalCaseResult(
                case_id="duplicate-checks",
                family="plan_tier_refund",
                checks=(check, check),
            )

        result = self._result("duplicate-case")
        with self.assertRaisesRegex(ValueError, "case IDs must be unique"):
            evaluation.EvalReport(
                suite_name="duplicate-cases",
                results=(result, result),
            )

    def test_results_and_reports_cannot_be_vacuously_passing(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one check"):
            evaluation.EvalCaseResult(
                case_id="empty-result",
                family="plan_tier_refund",
                checks=(),
            )

        with self.assertRaisesRegex(ValueError, "at least one case result"):
            evaluation.EvalReport(
                suite_name="empty-report",
                results=(),
            )

    def test_package_exposes_the_intentional_eager_api(self) -> None:
        self.assertEqual(
            evaluation.__all__,
            [
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
            ],
        )
        self.assertIs(evaluation.EvalCase, ContractEvalCase)
        self.assertIs(evaluation.EvalReport, ContractEvalReport)
        self.assertIs(evaluation.production_eval_cases, corpus_function)
        self.assertIs(evaluation.evaluate_policy_expectation, policy_function)
        self.assertIs(evaluation.evaluate_case, case_function)
        self.assertIs(evaluation.run_domain_eval, runner_function)


if __name__ == "__main__":
    unittest.main()
