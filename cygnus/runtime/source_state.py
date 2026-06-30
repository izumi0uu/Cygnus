"""Source runtime execution-state transitions for Cygnus.

This module owns source execution-state presets that belong to runtime queue,
retry, and resume behavior. runtime queue, retry, and resume behavior stay
here as runtime truth. Routers remain HTTP adapters, while review owns
compilation-plan governance semantics.
"""

from __future__ import annotations

from typing import Optional


def mark_source_processing(
    source,
    *,
    progress: int,
    progress_message: Optional[str] = None,
) -> object:
    """Mark a source as actively processing with a runtime-owned message."""
    source.status = "processing"
    source.progress = progress
    if progress_message is not None:
        source.progress_message = progress_message
    return source


def attach_source_runtime_job(source, *, job_id: Optional[str]) -> object:
    """Attach a runtime job id without changing other source fields."""
    if job_id:
        source.job_id = job_id
    return source


def mark_source_requeued_after_department_change(
    source,
    *,
    job_id: Optional[str] = None,
) -> object:
    """Mark a source as re-queued after a scope-changing department edit."""
    mark_source_processing(
        source,
        progress=0,
        progress_message="Re-queued after department change...",
    )
    source.error_message = None
    return attach_source_runtime_job(source, job_id=job_id)


def mark_source_retry_queued(
    source,
    *,
    job_id: Optional[str] = None,
) -> object:
    """Mark a source as queued for an execution retry."""
    source.status = "pending"
    source.progress = 0
    source.progress_message = "Queued for retry..."
    source.error_message = None
    return attach_source_runtime_job(source, job_id=job_id)


def mark_source_post_extraction_resume(
    source,
    *,
    has_images: bool,
    job_id: Optional[str] = None,
    progress: int = 56,
) -> object:
    """Resume source execution after extraction approval or auto-continue."""
    mark_source_processing(
        source,
        progress=progress,
        progress_message=(
            "Captioning images before extraction..."
            if has_images
            else "Extraction queued..."
        ),
    )
    return attach_source_runtime_job(source, job_id=job_id)


def mark_source_plan_refine_queued(
    source,
    *,
    job_id: Optional[str] = None,
) -> object:
    """Attach refine-stage runtime job wiring after plan approval."""
    return attach_source_runtime_job(source, job_id=job_id)


def mark_source_awaiting_approval(
    source,
    *,
    token_count: int,
    threshold: int,
) -> object:
    """Mark a source as waiting for human approval after extraction."""
    source.status = "awaiting_approval"
    source.progress = 55
    source.progress_message = (
        f"Awaiting human approval: {token_count:,} tokens > {threshold:,} threshold"
    )
    return source


def mark_source_runtime_error(
    source,
    *,
    error_message: str,
    progress_message: Optional[str] = None,
) -> object:
    """Mark a source as failed in runtime execution."""
    source.status = "error"
    source.error_message = error_message
    source.progress = 0
    source.progress_message = progress_message or error_message
    return source


def mark_source_plan_ready_for_review(source) -> object:
    """Mark a source as paused on a ready-to-review compilation plan."""
    source.status = "plan_ready"
    source.progress = 80
    source.progress_message = "Compilation plan ready — awaiting review"
    source.auto_recover_count = 0
    return source


def mark_source_ready(
    source,
    *,
    progress_message: str = "Done",
) -> object:
    """Mark a source as fully complete and ready."""
    source.status = "ready"
    source.progress = 100
    source.progress_message = progress_message
    source.error_message = None
    source.auto_recover_count = 0
    return source
