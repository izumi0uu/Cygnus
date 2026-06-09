from __future__ import annotations

from typing import Iterable

from cygnus.domain.audience import AudienceFilter
from cygnus.review.briefing import OwnerState, ReviewCommandBrief, ReviewRiskItem
from cygnus.review.queries import build_review_command_brief
from cygnus.review.service import ProposalBundle, build_review_risk_item, rank_review_item
from cygnus.review.surface import PriorityStackCard, ReviewCommandSurface, SituationFrame
from cygnus.substrate.compilation_plan import UrgencyLevel


def build_review_command_surface(
    *,
    surface_id: str,
    briefing_note: str,
    brief: ReviewCommandBrief,
) -> ReviewCommandSurface:
    cards = tuple(_card_from_item(item) for item in brief.priority_items)
    situation_frame = _build_situation_frame(briefing_note=briefing_note, items=brief.priority_items)
    return ReviewCommandSurface(
        surface_id=surface_id,
        headline=brief.headline,
        situation_frame=situation_frame,
        priority_stack=cards,
        available_commands=_available_commands(cards),
        command_brief=brief,
    )


def build_review_command_surface_from_bundles(
    *,
    surface_id: str,
    headline: str,
    briefing_note: str,
    bundles: Iterable[ProposalBundle],
) -> ReviewCommandSurface:
    items = tuple(sorted((build_review_risk_item(bundle) for bundle in bundles), key=rank_review_item))
    brief = build_review_command_brief(
        brief_id=f"{surface_id}:brief",
        headline=headline,
        items=items,
        sort_items=False,
    )
    return build_review_command_surface(
        surface_id=surface_id,
        briefing_note=briefing_note,
        brief=brief,
    )


def _build_situation_frame(
    *,
    briefing_note: str,
    items: tuple[ReviewRiskItem, ...],
) -> SituationFrame:
    urgent_items = sum(1 for item in items if item.urgency is UrgencyLevel.URGENT)
    owner_gaps = sum(1 for item in items if item.owner_state is OwnerState.UNASSIGNED)
    affected_surfaces = _dedupe_strings(
        surface
        for item in items
        for surface in item.why_now.affected_surfaces
    )
    summary = (
        f"{len(items)} governance risk(s) are currently stacked; "
        f"{urgent_items} urgent item(s) and {owner_gaps} owner gap(s) need command attention."
    )
    return SituationFrame(
        briefing_note=briefing_note,
        summary=summary,
        primary_tension=items[0].why_now.summary,
        urgent_items=urgent_items,
        owner_gaps=owner_gaps,
        affected_surfaces=tuple(affected_surfaces),
        recommended_commands=_dedupe_strings(
            command
            for item in items[:3]
            for command in item.recommended_actions
        ),
    )


def _card_from_item(item: ReviewRiskItem) -> PriorityStackCard:
    return PriorityStackCard(
        risk_id=item.risk_id,
        title=item.title,
        risk_type=item.risk_type,
        urgency=item.urgency,
        object_type=item.object_type,
        object_ref=item.object_ref,
        why_now_summary=item.why_now.summary,
        audience_labels=tuple(_audience_label(audience) for audience in item.affected_audiences),
        affected_audiences=item.affected_audiences,
        affected_surfaces=item.why_now.affected_surfaces,
        owner_state=item.owner_state,
        queue_owner=item.queue_owner,
        command_actions=item.recommended_actions,
        primary_command=_primary_command(item),
    )


def _primary_command(item: ReviewRiskItem) -> str:
    preferred = (
        "mark_urgent",
        "restrict_publish",
        "refresh_sources",
        "assign_owner",
        "request_more_evidence",
        "open_review",
    )
    for candidate in preferred:
        if candidate in item.recommended_actions:
            return candidate
    return item.recommended_actions[0]


def _available_commands(cards: tuple[PriorityStackCard, ...]) -> tuple[str, ...]:
    return tuple(
        _dedupe_strings(
            command
            for card in cards
            for command in card.command_actions
        )
    )


def _audience_label(audience: AudienceFilter) -> str:
    parts = [audience.visibility.value]
    for values in (
        audience.brands,
        audience.product_lines,
        audience.plans,
        audience.regions,
        audience.languages,
        audience.product_versions,
    ):
        if values:
            parts.append("/".join(values))
    if len(parts) == 1:
        parts.append("global")
    return " · ".join(parts)


def _dedupe_strings(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        if raw not in seen:
            seen.add(raw)
            out.append(raw)
    return tuple(out)
