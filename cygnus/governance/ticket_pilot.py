from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import cast
import uuid

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.governance.ledger import GovernanceEventType
from cygnus.governance.ticket_draft_promotions import validate_eligible_ticket_cluster
from cygnus.governance.ticket_import import validate_ticket_source_ref
from cygnus.review.surface import ObservationState, SurfaceObservation
from cygnus.runtime.database.models import (
    GovernanceLedgerEvent,
    GovernancePublication,
    GovernanceSignal,
    GovernanceTicketDraftPromotion,
    WikiPageDraft,
)


_TICKET_EVIDENCE_MARKER = "#ticket="
_TICKET_IMPORT_TRIGGER = "ticket_import:"
_REVIEW_SUBMISSION_EVENTS = frozenset(
    {
        GovernanceEventType.REVIEW_REQUESTED.value,
        GovernanceEventType.REVIEW_RESUBMITTED.value,
    }
)
_REVIEW_DECISION_EVENTS = frozenset(
    {
        GovernanceEventType.CHANGES_REQUESTED.value,
        GovernanceEventType.APPROVED.value,
        GovernanceEventType.REJECTED.value,
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class TicketPilotFunnelQuery:
    """Exact immutable ticket-export scope for the pilot read surface."""

    source_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "source_ref", validate_ticket_source_ref(self.source_ref)
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class TicketPilotFunnelItem:
    """One source-scoped projection assembled from existing durable owners."""

    source_ref: str
    import_digest: str
    signal_ref: str
    ticket_cluster_ref: str
    object_type: str
    signal_status: str
    signal_observed_at: datetime
    signal_created_at: datetime
    evidence_ref_count: int
    promotion_id: uuid.UUID | None
    promotion_created_at: datetime | None
    draft_id: uuid.UUID | None
    draft_status: str | None
    review_submitted_at: datetime | None
    review_decision_at: datetime | None
    review_decision: str | None
    publication_id: uuid.UUID | None
    published_at: datetime | None
    signal_to_draft_seconds: float | None
    draft_to_review_seconds: float | None
    signal_to_publish_seconds: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "source_ref": self.source_ref,
            "import_digest": self.import_digest,
            "signal_ref": self.signal_ref,
            "ticket_cluster_ref": self.ticket_cluster_ref,
            "object_type": self.object_type,
            "signal_status": self.signal_status,
            "signal_observed_at": _datetime_value(self.signal_observed_at),
            "signal_created_at": _datetime_value(self.signal_created_at),
            "evidence_ref_count": self.evidence_ref_count,
            "promotion": {
                "id": _uuid_value(self.promotion_id),
                "created_at": _datetime_value(self.promotion_created_at),
            },
            "draft": {
                "id": _uuid_value(self.draft_id),
                "status": self.draft_status,
            },
            "review": {
                "submitted_at": _datetime_value(self.review_submitted_at),
                "decision_at": _datetime_value(self.review_decision_at),
                "decision": self.review_decision,
            },
            "publication": {
                "id": _uuid_value(self.publication_id),
                "published_at": _datetime_value(self.published_at),
            },
            "durations_seconds": {
                "signal_to_draft": self.signal_to_draft_seconds,
                "draft_to_review": self.draft_to_review_seconds,
                "signal_to_publish": self.signal_to_publish_seconds,
            },
            "persisted": True,
            "rehearsal": False,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class TicketPilotFunnelReport:
    """Read-only pilot instrumentation; never represents business impact."""

    source_ref: str
    items: tuple[TicketPilotFunnelItem, ...]
    matched_signal_count: int
    excluded_signal_count: int
    import_digests: tuple[str, ...]
    observation: SurfaceObservation

    def to_dict(self) -> dict[str, object]:
        return {
            "source_ref": self.source_ref,
            "import_digests": list(self.import_digests),
            "matched_signal_count": self.matched_signal_count,
            "excluded_signal_count": self.excluded_signal_count,
            "summary": _summary(self.items),
            "items": [item.to_dict() for item in self.items],
            "observation": self.observation.to_dict(),
            "metric_boundary": {
                "kind": "durable_pilot_instrumentation",
                "business_impact_proven": False,
            },
            "persisted": True,
            "rehearsal": False,
        }


def _datetime_value(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _uuid_value(value: uuid.UUID | None) -> str | None:
    return str(value) if value is not None else None


def _duration_seconds(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    seconds = (end - start).total_seconds()
    if seconds < 0:
        return None
    return round(seconds, 3)


def _duration_summary(
    items: Sequence[TicketPilotFunnelItem],
    attribute: str,
) -> dict[str, object]:
    values = [
        value
        for item in items
        if (value := cast(float | None, getattr(item, attribute))) is not None
    ]
    if not values:
        return {
            "observed_count": 0,
            "average": None,
            "minimum": None,
            "maximum": None,
        }
    return {
        "observed_count": len(values),
        "average": round(sum(values) / len(values), 3),
        "minimum": min(values),
        "maximum": max(values),
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def _summary(items: Sequence[TicketPilotFunnelItem]) -> dict[str, object]:
    eligible = len(items)
    promoted = sum(item.promotion_id is not None for item in items)
    submitted = sum(item.review_submitted_at is not None for item in items)
    decided = sum(item.review_decision_at is not None for item in items)
    approved = sum(item.review_decision == "approved" for item in items)
    rejected = sum(item.review_decision == "rejected" for item in items)
    needs_revision = sum(item.review_decision == "needs_revision" for item in items)
    published = sum(item.publication_id is not None for item in items)
    terminal_decisions = approved + rejected
    return {
        "eligible_signal_count": eligible,
        "promoted_draft_count": promoted,
        "review_submitted_draft_count": submitted,
        "review_decided_draft_count": decided,
        "approved_draft_count": approved,
        "rejected_draft_count": rejected,
        "needs_revision_draft_count": needs_revision,
        "published_draft_count": published,
        "rates": {
            "signal_to_draft": _ratio(promoted, eligible),
            "draft_to_review": _ratio(submitted, promoted),
            "terminal_review_acceptance": _ratio(approved, terminal_decisions),
            "draft_to_publish": _ratio(published, promoted),
        },
        "durations_seconds": {
            "signal_to_draft": _duration_summary(items, "signal_to_draft_seconds"),
            "draft_to_review": _duration_summary(items, "draft_to_review_seconds"),
            "signal_to_publish": _duration_summary(items, "signal_to_publish_seconds"),
        },
    }


def _source_ref_from_evidence(signal: GovernanceSignal) -> str | None:
    evidence_refs = cast(Sequence[object], signal.evidence_refs or [])
    if not evidence_refs:
        return None
    source_refs: list[str] = []
    for raw_ref in evidence_refs:
        if not isinstance(raw_ref, dict):
            return None
        payload = cast(Mapping[str, object], raw_ref)
        source_ref = payload.get("source_ref")
        if not isinstance(source_ref, str):
            return None
        source, marker, ticket_id = source_ref.rpartition(_TICKET_EVIDENCE_MARKER)
        if not marker or not source or not ticket_id:
            return None
        source_refs.append(source)
    if len(set(source_refs)) != 1:
        return None
    return source_refs[0]


def _import_digest_from_signal(signal: GovernanceSignal) -> str | None:
    triggers = cast(Sequence[object], signal.trigger_signals or [])
    digests = [
        trigger.removeprefix(_TICKET_IMPORT_TRIGGER)
        for trigger in triggers
        if isinstance(trigger, str) and trigger.startswith(_TICKET_IMPORT_TRIGGER)
    ]
    if len(digests) != 1 or not digests[0]:
        return None
    return digests[0]


def _validated_import_signal(
    signal: GovernanceSignal,
    *,
    source_ref: str,
) -> str | None:
    if _source_ref_from_evidence(signal) != source_ref:
        return None
    import_digest = _import_digest_from_signal(signal)
    if import_digest is None:
        return None
    try:
        _ = validate_eligible_ticket_cluster(signal)
    except (KeyError, TypeError, ValueError):
        return None
    return import_digest


def _ticket_signal_statement(source_ref: str):
    """Build a SQL-first source filter over structured JSON evidence refs."""
    evidence = (
        func.jsonb_array_elements(GovernanceSignal.evidence_refs)
        .table_valued("value")
        .alias("ticket_evidence")
    )
    evidence_source_ref = evidence.c.value.op("->>")("source_ref")
    return (
        select(GovernanceSignal)
        .where(
            GovernanceSignal.signal_type == "ticket_cluster",
            GovernanceSignal.evidence_source_type == "resolved_ticket",
            exists(
                select(1)
                .select_from(evidence)
                .where(
                    func.starts_with(
                        evidence_source_ref,
                        f"{source_ref}{_TICKET_EVIDENCE_MARKER}",
                    )
                )
            ),
        )
        .order_by(GovernanceSignal.created_at, GovernanceSignal.signal_ref)
    )


def _review_times(
    events: Sequence[GovernanceLedgerEvent],
) -> tuple[datetime | None, datetime | None]:
    submissions = [
        event.occurred_at
        for event in events
        if event.event_type in _REVIEW_SUBMISSION_EVENTS
    ]
    decisions = [
        event.occurred_at
        for event in events
        if event.event_type in _REVIEW_DECISION_EVENTS
    ]
    return (
        min(submissions) if submissions else None,
        max(decisions) if decisions else None,
    )


def _build_item(
    signal: GovernanceSignal,
    *,
    source_ref: str,
    import_digest: str,
    promotion: GovernanceTicketDraftPromotion | None,
    draft: WikiPageDraft | None,
    events: Sequence[GovernanceLedgerEvent],
    publication: GovernancePublication | None,
) -> TicketPilotFunnelItem:
    if promotion is not None and draft is None:
        raise RuntimeError(
            f"ticket draft promotion {promotion.id} references a missing draft"
        )
    submitted_at, decision_at = _review_times(events)
    decision = (
        draft.status
        if draft is not None
        and draft.status in {"approved", "rejected", "needs_revision"}
        else None
    )
    promotion_created_at = promotion.created_at if promotion is not None else None
    draft_id = draft.id if draft is not None else None
    draft_status = draft.status if draft is not None else None
    published_at = publication.published_at if publication is not None else None
    return TicketPilotFunnelItem(
        source_ref=source_ref,
        import_digest=import_digest,
        signal_ref=signal.signal_ref,
        ticket_cluster_ref=signal.object_ref,
        object_type=signal.object_type,
        signal_status=signal.status,
        signal_observed_at=signal.observed_at,
        signal_created_at=signal.created_at,
        evidence_ref_count=len(signal.evidence_refs or []),
        promotion_id=promotion.id if promotion is not None else None,
        promotion_created_at=promotion_created_at,
        draft_id=draft_id,
        draft_status=draft_status,
        review_submitted_at=submitted_at,
        review_decision_at=decision_at,
        review_decision=decision,
        publication_id=publication.id if publication is not None else None,
        published_at=published_at,
        signal_to_draft_seconds=_duration_seconds(
            signal.created_at,
            promotion_created_at,
        ),
        draft_to_review_seconds=_duration_seconds(
            promotion_created_at,
            submitted_at,
        ),
        signal_to_publish_seconds=_duration_seconds(
            signal.created_at,
            published_at,
        ),
    )


def _build_report(
    query: TicketPilotFunnelQuery,
    *,
    signals: Sequence[GovernanceSignal],
    promotions: Mapping[uuid.UUID, GovernanceTicketDraftPromotion],
    drafts: Mapping[uuid.UUID, WikiPageDraft],
    events: Mapping[uuid.UUID, Sequence[GovernanceLedgerEvent]],
    publications: Mapping[uuid.UUID, GovernancePublication],
) -> TicketPilotFunnelReport:
    items: list[TicketPilotFunnelItem] = []
    excluded = 0
    import_digests: set[str] = set()
    for signal in signals:
        import_digest = _validated_import_signal(signal, source_ref=query.source_ref)
        if import_digest is None:
            excluded += 1
            continue
        import_digests.add(import_digest)
        promotion = promotions.get(signal.id)
        draft = drafts.get(promotion.draft_id) if promotion is not None else None
        publication = (
            publications.get(promotion.draft_id) if promotion is not None else None
        )
        items.append(
            _build_item(
                signal,
                source_ref=query.source_ref,
                import_digest=import_digest,
                promotion=promotion,
                draft=draft,
                events=events.get(promotion.draft_id, ()) if promotion else (),
                publication=publication,
            )
        )

    if excluded:
        observation = SurfaceObservation(
            state=ObservationState.PARTIAL,
            observed_count=len(items),
            reason="durable_ticket_to_knowledge_pilot_funnel_partial_source_integrity",
            covered_signals=("ticket_cluster_signal",),
            missing_signals=("ticket_source_evidence_integrity",),
        )
    else:
        observation = SurfaceObservation(
            state=ObservationState.READY,
            observed_count=len(items),
            reason="durable_ticket_to_knowledge_pilot_funnel",
            covered_signals=(
                "ticket_cluster_signal",
                "ticket_draft_promotion",
                "draft_review_ledger",
                "publication_record",
            ),
        )
    return TicketPilotFunnelReport(
        source_ref=query.source_ref,
        items=tuple(items),
        matched_signal_count=len(signals),
        excluded_signal_count=excluded,
        import_digests=tuple(sorted(import_digests)),
        observation=observation,
    )


async def get_ticket_pilot_funnel(
    session: AsyncSession,
    *,
    query: TicketPilotFunnelQuery,
) -> TicketPilotFunnelReport:
    """Project one immutable ticket export from durable governance truth."""
    signals_result = await session.execute(_ticket_signal_statement(query.source_ref))
    signals = tuple(signals_result.scalars().all())
    signal_ids = tuple(signal.id for signal in signals)
    if not signal_ids:
        return _build_report(
            query,
            signals=(),
            promotions={},
            drafts={},
            events={},
            publications={},
        )

    promotions_result = await session.execute(
        select(GovernanceTicketDraftPromotion)
        .where(GovernanceTicketDraftPromotion.signal_id.in_(signal_ids))
        .order_by(GovernanceTicketDraftPromotion.created_at)
    )
    promotion_rows = tuple(promotions_result.scalars().all())
    promotions = {promotion.signal_id: promotion for promotion in promotion_rows}
    draft_ids = tuple(promotion.draft_id for promotion in promotion_rows)
    if not draft_ids:
        return _build_report(
            query,
            signals=signals,
            promotions=promotions,
            drafts={},
            events={},
            publications={},
        )

    drafts_result = await session.execute(
        select(WikiPageDraft).where(WikiPageDraft.id.in_(draft_ids))
    )
    drafts = {draft.id: draft for draft in drafts_result.scalars().all()}

    events_result = await session.execute(
        select(GovernanceLedgerEvent)
        .where(
            GovernanceLedgerEvent.draft_id.in_(draft_ids),
            GovernanceLedgerEvent.event_type.in_(
                tuple(_REVIEW_SUBMISSION_EVENTS | _REVIEW_DECISION_EVENTS)
            ),
        )
        .order_by(
            GovernanceLedgerEvent.draft_id,
            GovernanceLedgerEvent.sequence,
        )
    )
    events: dict[uuid.UUID, list[GovernanceLedgerEvent]] = defaultdict(list)
    for event in events_result.scalars().all():
        events[event.draft_id].append(event)

    publications_result = await session.execute(
        select(GovernancePublication)
        .where(GovernancePublication.draft_id.in_(draft_ids))
        .order_by(
            GovernancePublication.draft_id,
            GovernancePublication.published_at,
            GovernancePublication.id,
        )
    )
    publications: dict[uuid.UUID, GovernancePublication] = {}
    for publication in publications_result.scalars().all():
        _ = publications.setdefault(publication.draft_id, publication)

    return _build_report(
        query,
        signals=signals,
        promotions=promotions,
        drafts=drafts,
        events=events,
        publications=publications,
    )
