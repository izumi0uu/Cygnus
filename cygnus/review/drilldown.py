from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from cygnus.review.detail import ReviewItemQuery, get_review_item_detail
from cygnus.review.home import ReviewHomeQuery, get_review_home_surface
from cygnus.review.service import ProposalBundle
from cygnus.review.surface import PriorityStackCard, ReviewCommandSurface


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewQueueDrilldownQuery:
    selected_object_ref: str
    home_query: ReviewHomeQuery | None = None

    def __post_init__(self) -> None:
        if not self.selected_object_ref.strip():
            raise ValueError("selected_object_ref must not be blank")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewQueueDrilldownSurface:
    surface_id: str
    queue_surface: ReviewCommandSurface
    selected_card: PriorityStackCard
    selected_detail: object
    selected_position: int
    total_items: int
    previous_object_ref: str | None = None
    next_object_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.surface_id.strip():
            raise ValueError("surface_id must not be blank")
        if self.selected_position < 0:
            raise ValueError("selected_position must not be negative")
        if self.total_items <= 0:
            raise ValueError("total_items must be positive")
        if self.selected_position >= self.total_items:
            raise ValueError("selected_position must be within total_items")
        if self.previous_object_ref is not None and not self.previous_object_ref.strip():
            raise ValueError("previous_object_ref must not be blank when provided")
        if self.next_object_ref is not None and not self.next_object_ref.strip():
            raise ValueError("next_object_ref must not be blank when provided")

    def to_dict(self) -> dict[str, object]:
        return {
            "surface_id": self.surface_id,
            "queue_surface": self.queue_surface.to_dict(),
            "selected_card": self.selected_card.to_dict(),
            "selected_detail": self.selected_detail.to_dict(),
            "selected_position": self.selected_position,
            "total_items": self.total_items,
            "previous_object_ref": self.previous_object_ref,
            "next_object_ref": self.next_object_ref,
        }


def get_review_queue_drilldown(
    query: ReviewQueueDrilldownQuery,
    *,
    bundles: Iterable[ProposalBundle] | None = None,
) -> ReviewQueueDrilldownSurface:
    queue_surface = get_review_home_surface(query.home_query, bundles=bundles)
    selected_index = _find_selected_index(queue_surface=queue_surface, object_ref=query.selected_object_ref)
    selected_card = queue_surface.priority_stack[selected_index]
    selected_detail = get_review_item_detail(
        ReviewItemQuery(object_ref=query.selected_object_ref),
        bundles=bundles,
    )
    previous_object_ref = None if selected_index == 0 else queue_surface.priority_stack[selected_index - 1].object_ref
    next_object_ref = None if selected_index == len(queue_surface.priority_stack) - 1 else queue_surface.priority_stack[selected_index + 1].object_ref
    return ReviewQueueDrilldownSurface(
        surface_id="review-queue-drilldown",
        queue_surface=queue_surface,
        selected_card=selected_card,
        selected_detail=selected_detail,
        selected_position=selected_index,
        total_items=len(queue_surface.priority_stack),
        previous_object_ref=previous_object_ref,
        next_object_ref=next_object_ref,
    )


def _find_selected_index(*, queue_surface: ReviewCommandSurface, object_ref: str) -> int:
    for index, card in enumerate(queue_surface.priority_stack):
        if card.object_ref == object_ref:
            return index
    raise ValueError(f"selected object_ref={object_ref} is not present in the current review queue")
