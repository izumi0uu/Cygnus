"""Object/evidence retrieval and source-trace query layer for Cygnus.

Ownership:
- knowledge-object search, evidence lookup, and source-trace resolution live here
- page/source embedding persistence backing semantic retrieval lives here
- this package serves retrieval truth, not runtime entry wiring
"""

from cygnus.retrieval.contracts import (
    EvidenceHit,
    KnowledgeObjectHit,
    SourceTrace,
    excerpt_ref_for,
    freshness_rollup,
    slugify,
)
from cygnus.retrieval.evidence_index import EvidenceIndex
from cygnus.retrieval.object_index import KnowledgeObjectIndex
from cygnus.retrieval.sample_data import sample_knowledge_objects, sample_support_evidence
from cygnus.retrieval.semantic_search import search_pages_semantic
from cygnus.retrieval.source_chunks import (
    VerbatimChunk,
    build_verbatim_chunks,
    index_verbatim_source,
    search_source_chunks_semantic,
)
from cygnus.retrieval.source_trace import SourceTraceResolver, collect_evidence_links
from cygnus.retrieval.substrate_provider import (
    SubstrateKnowledgeSnapshot,
    build_substrate_snapshot,
    load_substrate_snapshot,
    resolve_object_type,
    source_to_support_evidence,
    wiki_page_to_knowledge_object,
)

__all__ = [
    "EvidenceHit",
    "EvidenceIndex",
    "KnowledgeObjectHit",
    "KnowledgeObjectIndex",
    "SourceTrace",
    "SourceTraceResolver",
    "SubstrateKnowledgeSnapshot",
    "build_substrate_snapshot",
    "collect_evidence_links",
    "excerpt_ref_for",
    "freshness_rollup",
    "sample_knowledge_objects",
    "sample_support_evidence",
    "slugify",
    "search_pages_semantic",
    "search_source_chunks_semantic",
    "VerbatimChunk",
    "build_verbatim_chunks",
    "index_verbatim_source",
    "load_substrate_snapshot",
    "resolve_object_type",
    "source_to_support_evidence",
    "wiki_page_to_knowledge_object",
]
