"""Evidence normalization and record layer for Cygnus.

Ownership:
- source evidence normalization, freshness, and record contracts live here
- this package is not a runtime shell or governance workflow owner
"""

from cygnus.evidence.freshness import (
    FreshnessGateResult,
    freshness_gate,
    resolve_source_freshness,
    rollup_freshness,
    source_freshness_attestation,
    validate_freshness_attestation,
)
from cygnus.evidence.normalization import (
    RawEvidenceInput,
    normalize_evidence,
    normalize_payload,
)
from cygnus.evidence.records import EvidenceSourceType, FreshnessState, SupportEvidence

__all__ = [
    "EvidenceSourceType",
    "FreshnessGateResult",
    "FreshnessState",
    "RawEvidenceInput",
    "SupportEvidence",
    "freshness_gate",
    "normalize_evidence",
    "normalize_payload",
    "resolve_source_freshness",
    "rollup_freshness",
    "source_freshness_attestation",
    "validate_freshness_attestation",
]
