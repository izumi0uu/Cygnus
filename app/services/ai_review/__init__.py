"""
AI pre-review — permissive layer that annotates wiki drafts before human review.

Public entry points:
    run_async_checks(draft_id)   -> None  (L1 + L2 + L3 + L4; called from arq worker)

`run_sync_checks` is retained for ad-hoc tools / manual replays but is no
longer called from the submit path — see contribution_service._enqueue_ai_review.

The output JSON shape is documented in `runner.py`.
"""

from app.services.ai_review.runner import (  # noqa: F401
    CheckResult,
    AiReviewResults,
    run_sync_checks,
    run_async_checks,
    merge_results,
)
