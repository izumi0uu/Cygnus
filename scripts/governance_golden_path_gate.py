from __future__ import annotations

import argparse
import json

from cygnus.workflows import assert_governance_golden_path_complete


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify Cygnus's post-cutover governance golden path remains complete."
    )
    parser.add_argument("--quiet", action="store_true", help="Only return exit status.")
    args = parser.parse_args()

    payload = assert_governance_golden_path_complete()
    if not args.quiet:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
