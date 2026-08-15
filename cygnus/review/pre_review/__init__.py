"""Governance draft pre-review annotations for Cygnus.

This package annotates wiki drafts before human review with permissive
regex/structural/semantic/LLM checks. Ownership lives under ``cygnus.review``
because these verdicts shape the review workflow, not the runtime service tree.

Public entry points:
    run_async_checks(draft_id, expected_round, expected_version) -> None
    stage_ai_pre_review(db, draft) -> None
    dispatch_pending_ai_pre_reviews() -> int
    sweep_ai_pre_review_dispatches() -> int

Lifecycle mutations insert a unique durable outbox intent in their own
transaction.  The request hook is only an accelerator; worker startup and
periodic recovery sweep committed intents.  ARQ receives a deterministic job
ID, and stale/disabled/failed delivery has a persisted terminal state.

The output JSON shape is documented in ``runner.py``.
"""

from cygnus.review.pre_review.runner import (  # noqa: F401
    CheckResult,
    AiReviewResults,
    run_sync_checks,
    run_async_checks,
    merge_results,
)
from cygnus.review.pre_review.dispatch import (  # noqa: F401
    AiPreReviewDispatchClaim,
    PendingAiPreReview,
    ai_pre_review_job_id,
    dispatch_pending_ai_pre_reviews,
    stage_ai_pre_review,
    sweep_ai_pre_review_dispatches,
)
