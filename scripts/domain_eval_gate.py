#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
import json

import cygnus.evaluation.runner


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Cygnus's deterministic production domain evaluation gate."
    )
    parser.add_argument("--quiet", action="store_true", help="Only return exit status.")
    args = parser.parse_args(argv)

    report = asyncio.run(cygnus.evaluation.runner.run_domain_eval())
    if not args.quiet:
        print(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        )
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
