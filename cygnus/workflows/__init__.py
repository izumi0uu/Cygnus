"""Workflow composition layer for Cygnus.

Ownership:
- long-lived governance workflow composition belongs here
- this package is not a generic session runtime shell
- governance workflows stay explicit and bounded; they do not justify reintroducing a LangGraph mainline
"""

from cygnus.workflows.golden_path import (
    GovernanceGoldenPathWorkflow,
    GoldenPathCheckpoint,
    GoldenPathStage,
    assert_governance_golden_path_complete,
    build_governance_golden_path,
)
from cygnus.workflows.review_publish import ReviewPublishWorkflow

__all__ = [
    "GovernanceGoldenPathWorkflow",
    "GoldenPathCheckpoint",
    "GoldenPathStage",
    "ReviewPublishWorkflow",
    "assert_governance_golden_path_complete",
    "build_governance_golden_path",
]
