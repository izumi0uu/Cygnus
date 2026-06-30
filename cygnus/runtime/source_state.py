"""Source runtime execution-state transitions for Cygnus.

This module owns source execution-state presets that belong to runtime queue,
retry, and resume behavior. runtime queue, retry, and resume behavior stay
here as runtime truth. Routers remain HTTP adapters, while review owns
compilation-plan governance semantics.
"""

from __future__ import annotations

from typing import Optional


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
    source.status = "processing"
    source.progress = 0
    source.progress_message = "Re-queued after department change..."
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
    source.status = "processing"
    source.progress = progress
    source.progress_message = (
        "Captioning images before extraction..."
        if has_images
        else "Extraction queued..."
    )
    return attach_source_runtime_job(source, job_id=job_id)


def mark_source_plan_refine_queued(
    source,
    *,
    job_id: Optional[str] = None,
) -> object:
    """Attach refine-stage runtime job wiring after plan approval."""
    return attach_source_runtime_job(source, job_id=job_id)
