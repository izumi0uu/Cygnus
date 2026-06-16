from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from cygnus.recovery.fixtures import (
    sample_reality_check_command_ref,
    sample_reality_check_feedback,
)
from cygnus.recovery.providers import build_downstream_reality_check
from cygnus.recovery.reality_check import (
    DownstreamFeedbackSignal,
    DownstreamRealityCheckSurface,
    GovernanceCommandRef,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class DownstreamRealityCheckQuery:
    command_id: str

    def __post_init__(self) -> None:
        if not self.command_id.strip():
            raise ValueError("command_id must not be blank")


def get_downstream_reality_check_surface(
    query: DownstreamRealityCheckQuery,
    *,
    command_refs: Iterable[GovernanceCommandRef] | None = None,
    feedback_feed: Iterable[DownstreamFeedbackSignal] | None = None,
) -> DownstreamRealityCheckSurface:
    refs = tuple(command_refs) if command_refs is not None else (sample_reality_check_command_ref(),)
    feed = tuple(feedback_feed) if feedback_feed is not None else sample_reality_check_feedback()
    for command_ref in refs:
        if command_ref.command_id != query.command_id:
            continue
        return build_downstream_reality_check(
            command_ref=command_ref,
            feedback_feed=feed,
        )
    raise ValueError(f"downstream reality check not found for command_id={query.command_id}")
