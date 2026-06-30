"""Cygnus-owned substrate contracts.

Ownership:
- provider-neutral tool/agent protocol
- pipeline phase/checkpoint primitives
- source outline extraction and page-slice primitives
- durable workflow primitives
- not a second app shell or API entry layer
- not a LangGraph runtime host; substrate contracts remain framework-neutral
"""

from cygnus.substrate.compilation_plan import CompilationProposal, EvidenceSufficiency, PlanAction, UrgencyLevel
from cygnus.substrate.durable_jobs import DurableWorkflowJob, FileDurableJobStore, QueueStatus
from cygnus.substrate.pipeline_checkpoint import PipelineCheckpoint
from cygnus.substrate.pipeline_phases import PipelinePhase
from cygnus.substrate.source_outline import (
    PAGE_JOIN_SEPARATOR,
    assemble_full_text,
    build_outline,
    flatten_outline,
    flatten_outline_with_depth,
    parse_page_range,
    slice_by_outline_node,
    slice_pages_by_range,
)

__all__ = [
    "CompilationProposal",
    "DurableWorkflowJob",
    "EvidenceSufficiency",
    "FileDurableJobStore",
    "PlanAction",
    "PipelineCheckpoint",
    "PipelinePhase",
    "QueueStatus",
    "UrgencyLevel",
    "PAGE_JOIN_SEPARATOR",
    "assemble_full_text",
    "build_outline",
    "flatten_outline",
    "flatten_outline_with_depth",
    "parse_page_range",
    "slice_by_outline_node",
    "slice_pages_by_range",
]
