"""Compilation-plan review lifecycle governance for source ingest plans.

This module owns the review-state machine for source compilation plans. The
runtime sources router remains the app-shell adapter, while review owns approve / reject / regenerate / auto-approve semantics for governed source plans.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.runtime.database.models import Employee, Source, SourceCompilationPlan
from cygnus.runtime.services.audit_service import log_audit


class SourcePlanInvalidTransition(Exception):
    """Raised when a source compilation plan cannot take the requested transition."""


async def approve_source_compilation_plan(
    db: AsyncSession,
    plan: SourceCompilationPlan,
    source: Optional[Source],
    reviewer: Employee,
    reviewer_note: Optional[str] = None,
) -> SourceCompilationPlan:
    """Promote a pending_review plan into approved state."""
    if plan.status == "regenerating":
        raise SourcePlanInvalidTransition(
            "Plan is being regenerated. Wait for it to finish before approving.",
        )
    if plan.status != "pending_review":
        raise SourcePlanInvalidTransition(
            f"Plan is not pending review (status={plan.status})",
        )

    plan.status = "approved"
    plan.reviewed_by = reviewer.id
    plan.review_note = reviewer_note
    plan.reviewed_at = datetime.now(timezone.utc)
    if source is not None:
        source.status = "processing"
        source.progress = 78
        source.progress_message = "Plan approved — compiling wiki pages..."

    await log_audit(
        db,
        reviewer,
        "approve",
        "compilation_plan",
        str(plan.id),
        reason=reviewer_note or None,
    )
    return plan


async def reject_source_compilation_plan(
    db: AsyncSession,
    plan: SourceCompilationPlan,
    source: Optional[Source],
    reviewer: Employee,
    reviewer_note: str,
) -> SourceCompilationPlan:
    """Reject a pending_review plan and return the source to error state."""
    if plan.status == "regenerating":
        raise SourcePlanInvalidTransition(
            "Plan is being regenerated. Wait for it to finish before rejecting.",
        )
    if plan.status != "pending_review":
        raise SourcePlanInvalidTransition(
            f"Plan is not pending review (status={plan.status})",
        )

    plan.status = "rejected"
    plan.reviewed_by = reviewer.id
    plan.review_note = reviewer_note
    plan.reviewed_at = datetime.now(timezone.utc)
    if source is not None:
        source.status = "error"
        source.error_message = f"Compilation plan rejected: {reviewer_note}"

    await log_audit(
        db,
        reviewer,
        "reject",
        "compilation_plan",
        str(plan.id),
        reason=reviewer_note,
    )
    return plan


async def request_source_plan_regeneration(
    db: AsyncSession,
    plan: SourceCompilationPlan,
    reviewer: Employee,
    reviewer_note: str,
) -> SourceCompilationPlan:
    """Move a plan into regenerating so the background job can rebuild it."""
    if plan.status not in ("pending_review", "rejected"):
        raise SourcePlanInvalidTransition(
            f"Plan cannot be regenerated (status={plan.status})",
        )

    plan.status = "regenerating"
    plan.review_note = reviewer_note[:1000]
    await log_audit(
        db,
        reviewer,
        "regenerate",
        "compilation_plan",
        str(plan.id),
        reason=reviewer_note[:200],
    )
    return plan


def auto_approve_source_compilation_plan(
    plan: SourceCompilationPlan,
    source: Optional[Source],
    *,
    review_note: str = "Auto-approved",
) -> SourceCompilationPlan:
    """System approval path used by auto-approve pipelines."""
    if plan.status != "pending_review":
        return plan

    plan.status = "approved"
    plan.review_note = review_note
    plan.reviewed_at = datetime.now(timezone.utc)
    if source is not None:
        source.status = "processing"
        source.progress_message = "Plan approved — compiling wiki pages..."
    return plan


def restore_source_plan_pending_review(
    plan: SourceCompilationPlan,
    *,
    plan_json: dict,
) -> SourceCompilationPlan:
    """Restore a regenerated plan back to pending_review with fresh content."""
    plan.plan_json = plan_json
    plan.status = "pending_review"
    plan.reviewed_by = None
    plan.review_note = None
    plan.reviewed_at = None
    return plan


def fail_source_plan_regeneration(
    plan: SourceCompilationPlan,
    *,
    reason: str,
) -> SourceCompilationPlan:
    """Recover a failed regeneration attempt back to pending_review."""
    if plan.status == "regenerating":
        plan.status = "pending_review"
        plan.review_note = f"Regeneration failed: {reason[:200]}"
    return plan
