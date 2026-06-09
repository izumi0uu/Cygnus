from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from cygnus.domain.audience import Visibility
from cygnus.review.briefing import OwnerState, ReviewRiskItem, ReviewRiskType
from cygnus.review.fixtures import sample_review_bundles
from cygnus.review.providers import build_review_command_surface
from cygnus.review.queries import build_review_command_brief
from cygnus.review.service import ProposalBundle, build_review_risk_item, rank_review_item
from cygnus.review.surface import ReviewCommandSurface


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewHomeQuery:
    visibility: Visibility | None = None
    owner_state: OwnerState | None = None
    risk_types: tuple[ReviewRiskType, ...] = field(default_factory=tuple)
    max_items: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "risk_types", tuple(self.risk_types))
        if self.max_items is not None and self.max_items <= 0:
            raise ValueError("max_items must be positive when provided")


DEFAULT_HOME_HEADLINE = "Today’s highest-leverage governance risks"
DEFAULT_HOME_NOTE = "Morning command brief before opening any draft detail."


def get_review_home_surface(
    query: ReviewHomeQuery | None = None,
    *,
    bundles: Iterable[ProposalBundle] | None = None,
) -> ReviewCommandSurface:
    query = query or ReviewHomeQuery()
    source_bundles = tuple(bundles) if bundles is not None else sample_review_bundles()
    items = tuple(sorted((build_review_risk_item(bundle) for bundle in source_bundles), key=rank_review_item))
    filtered_items = tuple(item for item in items if _matches_query(item=item, query=query))
    if query.max_items is not None:
        filtered_items = filtered_items[: query.max_items]
    if not filtered_items:
        raise ValueError("review home query returned no matching governance risks")

    brief = build_review_command_brief(
        brief_id="review-home:brief",
        headline=_headline_for_query(query),
        items=filtered_items,
        sort_items=False,
    )
    return build_review_command_surface(
        surface_id="review-home",
        briefing_note=_briefing_note_for_query(query),
        brief=brief,
    )


def _matches_query(*, item: ReviewRiskItem, query: ReviewHomeQuery) -> bool:
    if query.visibility is not None and not any(audience.visibility is query.visibility for audience in item.affected_audiences):
        return False
    if query.owner_state is not None and item.owner_state is not query.owner_state:
        return False
    if query.risk_types and item.risk_type not in query.risk_types:
        return False
    return True


def _headline_for_query(query: ReviewHomeQuery) -> str:
    if len(query.risk_types) == 1:
        risk_type = query.risk_types[0].value.replace("_", " ")
        return f"Focused governance brief: {risk_type}"
    if query.visibility is Visibility.EXTERNAL:
        return "External governance risks requiring command attention"
    if query.visibility is Visibility.INTERNAL:
        return "Internal governance risks requiring command attention"
    return DEFAULT_HOME_HEADLINE


def _briefing_note_for_query(query: ReviewHomeQuery) -> str:
    if query.owner_state is OwnerState.UNASSIGNED:
        return "Focused command brief for risks that still have an ownership gap."
    if query.visibility is Visibility.EXTERNAL:
        return "Focused command brief for external-answer governance risk."
    if query.visibility is Visibility.INTERNAL:
        return "Focused command brief for internal-support governance risk."
    return DEFAULT_HOME_NOTE
