"""Evidence normalization and record layer for Cygnus.

Ownership:
- source evidence normalization, freshness, and record contracts live here
- this package is not a runtime shell or governance workflow owner
"""

from cygnus.evidence.normalization import RawEvidenceInput, normalize_evidence, normalize_payload
from cygnus.evidence.records import EvidenceSourceType, FreshnessState, SupportEvidence

__all__ = [
    "EvidenceSourceType",
    "FreshnessState",
    "RawEvidenceInput",
    "SupportEvidence",
    "normalize_evidence",
    "normalize_payload",
]
