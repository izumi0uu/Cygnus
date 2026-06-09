from __future__ import annotations

from enum import Enum


class PipelinePhase(str, Enum):
    INGEST = "ingest"
    NORMALIZE = "normalize"
    MAP_REDUCE = "map_reduce"
    PLAN = "plan"
    REVIEW = "review"
    PUBLISH = "publish"
    FEEDBACK = "feedback"
