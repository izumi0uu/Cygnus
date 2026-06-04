from __future__ import annotations

from enum import Enum


class LifecycleState(str, Enum):
    """Unified lifecycle for support knowledge objects."""

    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


_ALLOWED_TRANSITIONS: dict[LifecycleState, set[LifecycleState]] = {
    LifecycleState.DRAFT: {LifecycleState.IN_REVIEW, LifecycleState.ARCHIVED},
    LifecycleState.IN_REVIEW: {
        LifecycleState.DRAFT,
        LifecycleState.APPROVED,
        LifecycleState.ARCHIVED,
    },
    LifecycleState.APPROVED: {
        LifecycleState.IN_REVIEW,
        LifecycleState.PUBLISHED,
        LifecycleState.ARCHIVED,
    },
    LifecycleState.PUBLISHED: {
        LifecycleState.SUPERSEDED,
        LifecycleState.ARCHIVED,
    },
    LifecycleState.SUPERSEDED: {LifecycleState.ARCHIVED},
    LifecycleState.ARCHIVED: set(),
}


def allowed_transitions(state: LifecycleState) -> tuple[LifecycleState, ...]:
    return tuple(sorted(_ALLOWED_TRANSITIONS[state], key=lambda item: item.value))


def can_transition(current: LifecycleState, target: LifecycleState) -> bool:
    return target in _ALLOWED_TRANSITIONS[current]


def assert_transition(current: LifecycleState, target: LifecycleState) -> None:
    if can_transition(current, target):
        return

    allowed = ", ".join(state.value for state in allowed_transitions(current)) or "none"
    raise ValueError(
        f"invalid lifecycle transition: {current.value} -> {target.value}; "
        f"allowed targets: {allowed}"
    )


def transition(current: LifecycleState, target: LifecycleState) -> LifecycleState:
    assert_transition(current, target)
    return target
