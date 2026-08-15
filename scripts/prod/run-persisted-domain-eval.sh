#!/usr/bin/env bash
# Native persisted-domain evaluation against the isolated candidate stack.
set -euo pipefail

REPORT=""
GIT_SHA=""
BACKEND_IMAGE=""
FRONTEND_IMAGE=""
ALEMBIC_HEAD=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --report) REPORT="${2:?--report requires a path}"; shift 2 ;;
    --git-sha) GIT_SHA="${2:?--git-sha requires a value}"; shift 2 ;;
    --backend-image) BACKEND_IMAGE="${2:?--backend-image requires a value}"; shift 2 ;;
    --frontend-image) FRONTEND_IMAGE="${2:?--frontend-image requires a value}"; shift 2 ;;
    --alembic-head) ALEMBIC_HEAD="${2:?--alembic-head requires a value}"; shift 2 ;;
    *) printf '[persisted-domain-eval] ERROR: unknown argument %s\n' "$1" >&2; exit 1 ;;
  esac
done
for variable in REPORT GIT_SHA BACKEND_IMAGE FRONTEND_IMAGE ALEMBIC_HEAD CYGNUS_RELEASE CYGNUS_CERTIFICATION_TARGET_ORIGIN CYGNUS_OPERATOR_WORK_DIR; do
  [ -n "${!variable:-}" ] || { printf '[persisted-domain-eval] ERROR: %s is required\n' "$variable" >&2; exit 1; }
done

REPO_ROOT=$(CDPATH= cd -- "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
STACK="$REPO_ROOT/scripts/prod/certification-stack.sh"
RESULT="$CYGNUS_OPERATOR_WORK_DIR/$CYGNUS_RELEASE/certification/persisted-domain-result.json"
mkdir -p "$(dirname "$REPORT")"
"$STACK" domain-prepare --release "$CYGNUS_RELEASE"
"$STACK" restart --release "$CYGNUS_RELEASE"
"$STACK" domain-verify --release "$CYGNUS_RELEASE"

REPORT="$REPORT" RESULT="$RESULT" GIT_SHA="$GIT_SHA" \
BACKEND_IMAGE="$BACKEND_IMAGE" FRONTEND_IMAGE="$FRONTEND_IMAGE" \
ALEMBIC_HEAD="$ALEMBIC_HEAD" TARGET_ORIGIN="$CYGNUS_CERTIFICATION_TARGET_ORIGIN" \
python3 - <<'PY'
from datetime import datetime, timezone
import json
import os
from pathlib import Path

result = json.loads(Path(os.environ["RESULT"]).read_text(encoding="utf-8"))
pre = result["pre_ack"]
allowed = result["allowed_after_ack"]
denied = result["denied_audience"]
restart = result["restart_persistence"]
stale = result["freshness_invalidation"]
acks = result["acknowledgements"]
if pre["governance_state"] != "restricted":
    raise SystemExit("pre-ack query was not restricted")
if allowed["governance"]["state"] != "answerable" or not allowed["content_exposed"]:
    raise SystemExit("allowed audience did not become answerable")
if denied["governance"]["state"] != "restricted" or denied["content_exposed"]:
    raise SystemExit("denied audience leaked content")
if restart["governance"]["state"] != "answerable" or not restart["content_exposed"]:
    raise SystemExit("signed delivery truth did not survive restart")
if stale["governance"]["state"] != "restricted" or stale["content_exposed"]:
    raise SystemExit("freshness invalidation did not fail closed")
if not isinstance(acks, list) or not acks:
    raise SystemExit("no persisted delivery acknowledgements")
checks = [
    {"name": "persisted-approval-lineage", "passed": True, "details": {"draft_id": result["draft_id"], "page_id": result["page_id"], "object_ref": result["object_ref"]}},
    {"name": "persisted-publication-lineage", "passed": True, "details": {"publication_id": result["publication_id"], "delivery_ids": result["delivery_ids"]}},
    {"name": "allowed-audience-no-leakage", "passed": True, "details": allowed},
    {"name": "denied-audience-no-leakage", "passed": True, "details": denied},
    {"name": "freshness-invalidation", "passed": True, "details": stale},
    {"name": "propagation-acknowledgement", "passed": True, "details": {"signed_acknowledgements": acks}},
    {"name": "two-turn-truth-re-query", "passed": True, "details": {"before": pre, "after": allowed}},
    {"name": "restart-persistence", "passed": True, "details": restart},
]
report = {
    "report_format": "cygnus-persisted-domain-eval-report/v1",
    "status": "passed",
    "git_sha": os.environ["GIT_SHA"],
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "release_identity": {
        "git_commit": os.environ["GIT_SHA"],
        "backend_image_ref": os.environ["BACKEND_IMAGE"],
        "frontend_image_ref": os.environ["FRONTEND_IMAGE"],
        "alembic_head": os.environ["ALEMBIC_HEAD"],
    },
    "target": {"origin": os.environ["TARGET_ORIGIN"], "environment": "isolated-candidate"},
    "checks": checks,
}
path = Path(os.environ["REPORT"])
path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
path.chmod(0o600)
PY
printf '[persisted-domain-eval] persisted truth checks passed; report=%s\n' "$REPORT"
