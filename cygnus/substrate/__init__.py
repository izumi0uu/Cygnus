"""Cygnus-owned substrate contracts.

Ownership:
- provider-neutral tool/agent protocol
- pipeline phase/checkpoint primitives
- source outline extraction and page-slice primitives
- source image extraction primitives
- source text extraction and content-type primitives
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
from cygnus.substrate.source_images import (
    ImageInfo,
    SourceImageStorage,
    extract_images,
    extract_images_from_docx,
    extract_images_from_pdf,
    inline_image_markers,
)
from cygnus.substrate.source_text import (
    _extract_text_from_file,
    _extract_text_from_url,
    _guess_content_type,
)

__all__ = [
    "CompilationProposal",
    "DurableWorkflowJob",
    "EvidenceSufficiency",
    "FileDurableJobStore",
    "ImageInfo",
    "PlanAction",
    "PipelineCheckpoint",
    "PipelinePhase",
    "QueueStatus",
    "SourceImageStorage",
    "UrgencyLevel",
    "PAGE_JOIN_SEPARATOR",
    "_extract_text_from_file",
    "_extract_text_from_url",
    "_guess_content_type",
    "assemble_full_text",
    "build_outline",
    "flatten_outline",
    "flatten_outline_with_depth",
    "extract_images",
    "extract_images_from_docx",
    "extract_images_from_pdf",
    "inline_image_markers",
    "parse_page_range",
    "slice_by_outline_node",
    "slice_pages_by_range",
]
