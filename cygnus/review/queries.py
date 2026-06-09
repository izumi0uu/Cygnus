from __future__ import annotations

from cygnus.review.briefing import ReviewCommandBrief, ReviewRiskItem, ReviewRiskType
from cygnus.substrate.compilation_plan import UrgencyLevel



def build_review_command_brief(
    *,
    brief_id: str,
    headline: str,
    items: tuple[ReviewRiskItem, ...],
    sort_items: bool = True,
) -> ReviewCommandBrief:
    ordered = tuple(sorted(items, key=_priority_sort_key)) if sort_items else tuple(items)
    return ReviewCommandBrief(
        brief_id=brief_id,
        headline=headline,
        priority_items=ordered,
        summary_counts=summarize_review_items(ordered),
    )



def _priority_sort_key(item: ReviewRiskItem) -> tuple[int, int, str]:
    urgency_rank = {
        UrgencyLevel.URGENT: 0,
        UrgencyLevel.HIGH: 1,
        UrgencyLevel.MEDIUM: 2,
        UrgencyLevel.LOW: 3,
    }[item.urgency]
    risk_rank = {
        ReviewRiskType.SOURCE_BLINDNESS: 0,
        ReviewRiskType.DRIFT: 1,
        ReviewRiskType.AUDIENCE_MISMATCH: 2,
        ReviewRiskType.TICKET_PRESSURE: 3,
        ReviewRiskType.POLICY_CONFLICT: 4,
        ReviewRiskType.OWNER_GAP: 5,
    }[item.risk_type]
    return (urgency_rank, risk_rank, item.title.lower())



def summarize_review_items(items: tuple[ReviewRiskItem, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.risk_type.value] = counts.get(item.risk_type.value, 0) + 1
    return counts
