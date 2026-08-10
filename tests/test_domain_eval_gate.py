from __future__ import annotations

from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch


def _load_module():
    module_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "domain_eval_gate.py"
    )
    spec = importlib.util.spec_from_file_location("domain_eval_gate", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


domain_eval_gate = _load_module()


class _StubReport:
    def __init__(self, *, passed: bool, payload: dict[str, object]) -> None:
        self.passed = passed
        self.payload = payload

    def to_dict(self) -> dict[str, object]:
        return self.payload


class DomainEvalGateTests(unittest.TestCase):
    def _run_gate(
        self,
        report: _StubReport,
        argv: list[str] | None = None,
    ) -> tuple[int, str]:
        run_domain_eval = AsyncMock(return_value=report)
        output = io.StringIO()
        with (
            patch.object(
                domain_eval_gate.cygnus.evaluation.runner,
                "run_domain_eval",
                run_domain_eval,
            ),
            redirect_stdout(output),
        ):
            status = domain_eval_gate.main([] if argv is None else argv)

        run_domain_eval.assert_awaited_once_with()
        return status, output.getvalue()

    def test_default_output_is_stable_sorted_json(self) -> None:
        payload: dict[str, object] = {
            "suite_name": "production_domain",
            "passed": True,
            "results": [{"passed": True, "case_id": "case-1"}],
        }
        report = _StubReport(passed=True, payload=payload)

        status, output = self._run_gate(report)

        self.assertEqual(status, 0)
        self.assertEqual(
            output,
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )

    def test_failed_report_returns_failure_status(self) -> None:
        payload: dict[str, object] = {
            "suite_name": "production_domain",
            "passed": False,
            "results": [{"passed": False, "case_id": "case-1"}],
        }
        report = _StubReport(passed=False, payload=payload)

        status, output = self._run_gate(report)

        self.assertEqual(status, 1)
        self.assertEqual(json.loads(output), payload)

    def test_quiet_suppresses_output_without_changing_status(self) -> None:
        for passed, expected_status in ((True, 0), (False, 1)):
            with self.subTest(passed=passed):
                report = _StubReport(
                    passed=passed,
                    payload={"passed": passed, "suite_name": "production_domain"},
                )

                status, output = self._run_gate(report, ["--quiet"])

                self.assertEqual(status, expected_status)
                self.assertEqual(output, "")


if __name__ == "__main__":
    unittest.main()
