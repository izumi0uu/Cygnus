#!/usr/bin/env python3
"""Render deployment-approved Prometheus alert rules (CYG-142)."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
ALERT_RULES_MODULE = REPO_ROOT / "cygnus" / "observability" / "alert_rules.py"
DEFAULT_TEMPLATE = REPO_ROOT / "config" / "observability" / "alert_rules.yml"


def _load_alert_rules_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_cygnus_deploy_alert_rules", ALERT_RULES_MODULE
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the alert-rule renderer")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_alert_rules: Any = _load_alert_rules_module()
AlertThresholdInputError = _alert_rules.AlertThresholdInputError
load_alert_threshold_inputs = _alert_rules.load_alert_threshold_inputs
write_rendered_alert_rules = _alert_rules.write_rendered_alert_rules


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--thresholds",
        type=Path,
        required=True,
        help="Approved external alert-threshold JSON document.",
    )
    parser.add_argument(
        "--approval-ref",
        required=True,
        help="Expected external approval reference.",
    )
    parser.add_argument(
        "--thresholds-ref",
        required=True,
        help="Expected external alert-threshold document reference.",
    )
    parser.add_argument(
        "--thresholds-sha256",
        required=True,
        help="Expected sha256:<64 hex> hash of --thresholds.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    try:
        inputs = load_alert_threshold_inputs(
            args.thresholds,
            expected_approval_ref=args.approval_ref,
            expected_thresholds_ref=args.thresholds_ref,
            expected_thresholds_sha256=args.thresholds_sha256,
        )
        write_rendered_alert_rules(
            args.output,
            template_path=args.template,
            inputs=inputs,
        )
    except AlertThresholdInputError as exc:
        if not args.quiet:
            print(f"[render-alert-rules] BLOCKED: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        if not args.quiet:
            print(f"[render-alert-rules] BLOCKED: {exc}", file=sys.stderr)
        return 2

    if not args.quiet:
        print(
            json.dumps(
                {
                    "status": "rendered",
                    "output": str(args.output),
                    "approval_ref": inputs.approval_ref,
                    "thresholds_ref": inputs.thresholds_ref,
                    "thresholds_sha256": inputs.thresholds_sha256,
                },
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
