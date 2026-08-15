from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import cast
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.domain.audience import AudienceFilter
from cygnus.governance.ledger import lock_governance_command
from cygnus.governance.signals import (
    GovernanceSignalStatus,
    governance_signal_to_pressure_record,
    resolve_governance_signal,
)
from cygnus.retrieval import slugify
from cygnus.review.contributions import (
    build_initial_draft_content,
    create_wiki_draft,
)
from cygnus.review.intake import (
    PressureSignalType,
    compile_pressure_proposal_bundles,
)
from cygnus.runtime.database.models import (
    GovernanceReviewAssignment,
    GovernanceSignal,
    GovernanceTicketDraftPromotion,
    WikiPageDraft,
)
from cygnus.substrate.compilation_plan import EvidenceSufficiency, PlanAction

TICKET_DRAFT_PROMOTION_REF_MAX_LENGTH = 220
TICKET_DRAFT_PROMOTION_REASON_MAX_LENGTH = 2_000
_MIN_TICKET_EVIDENCE_REFS = 2


class TicketDraftPromotionConflict(ValueError):
    """A promotion races durable state or reuses an idempotency key."""


@dataclass(frozen=True, slots=True, kw_only=True)
class TicketDraftPromotionCommand:
    command_id: str
    expected_assignment_version: int
    reason: str

    def __post_init__(self) -> None:
        command_id = self.command_id.strip()
        reason = self.reason.strip()
        if not command_id:
            raise ValueError("command_id must not be blank")
        if len(command_id) > TICKET_DRAFT_PROMOTION_REF_MAX_LENGTH:
            raise ValueError(
                f"command_id must not exceed {TICKET_DRAFT_PROMOTION_REF_MAX_LENGTH} characters"
            )
        if self.expected_assignment_version < 1:
            raise ValueError("expected_assignment_version must be at least 1")
        if not reason:
            raise ValueError("reason must not be blank")
        if len(reason) > TICKET_DRAFT_PROMOTION_REASON_MAX_LENGTH:
            raise ValueError(
                f"reason must not exceed {TICKET_DRAFT_PROMOTION_REASON_MAX_LENGTH} characters"
            )
        object.__setattr__(self, "command_id", command_id)
        object.__setattr__(self, "reason", reason)


@dataclass(frozen=True, slots=True, kw_only=True)
class TicketDraftPromotionResult:
    promotion: GovernanceTicketDraftPromotion
    draft: WikiPageDraft
    signal_ref: str
    replayed: bool = False

    def to_dict(self) -> dict[str, object]:
        suggested_metadata = cast(
            dict[str, object], self.draft.suggested_metadata or {}
        )
        source_metadata = cast(dict[str, object], self.draft.source_metadata or {})
        title = _required_metadata_value(suggested_metadata, "title")
        object_type = _required_metadata_value(source_metadata, "object_type")
        promotion_trace_ref = f"ticket-draft-promotion:{self.promotion.id}"
        return {
            "promotion": {
                "id": str(self.promotion.id),
                "signal_ref": self.signal_ref,
                "command_id": self.promotion.command_id,
                "draft_id": str(self.promotion.draft_id),
                "actor_id": str(self.promotion.actor_id),
                "expected_assignment_version": (
                    self.promotion.expected_assignment_version
                ),
                "trace_ref": promotion_trace_ref,
                "persisted": True,
                "created_at": self.promotion.created_at.isoformat(),
            },
            "draft": {
                "draft_id": str(self.draft.id),
                "draft_version": self.draft.version,
                "draft_kind": self.draft.draft_kind,
                "draft_status": self.draft.status,
                "object_type": object_type,
                "title": title,
            },
            "replayed": self.replayed,
            "review_state": "not_submitted",
            "publication_state": "not_published",
            "next_step": "update_draft_or_request_review",
        }


def _required_metadata_value(metadata: dict[str, object], key: str) -> str:
    value = metadata.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"promoted draft is missing {key} metadata")
    return value


async def promote_ticket_cluster_to_draft(
    session: AsyncSession,
    *,
    signal_ref: str,
    command: TicketDraftPromotionCommand,
    actor_id: uuid.UUID,
) -> TicketDraftPromotionResult | None:
    """Materialize one eligible durable ticket cluster into one draft."""
    normalized_ref = signal_ref.strip()
    if not normalized_ref:
        raise ValueError("signal_ref must not be blank")

    await lock_governance_command(
        session,
        f"ticket-draft-promotion-command:{command.command_id}",
    )
    await lock_governance_command(session, f"governance-signal:{normalized_ref}")

    row = cast(
        tuple[GovernanceSignal, GovernanceReviewAssignment] | None,
        (
            await session.execute(
                select(GovernanceSignal, GovernanceReviewAssignment)
                .join(
                    GovernanceReviewAssignment,
                    GovernanceReviewAssignment.signal_id == GovernanceSignal.id,
                )
                .where(GovernanceSignal.signal_ref == normalized_ref)
                .with_for_update()
            )
        ).one_or_none(),
    )
    if row is None:
        return None
    signal, assignment = row
    fingerprint = _command_fingerprint(
        normalized_ref,
        command,
        actor_id=actor_id,
    )

    existing_command = (
        await session.execute(
            select(GovernanceTicketDraftPromotion).where(
                GovernanceTicketDraftPromotion.command_id == command.command_id
            )
        )
    ).scalar_one_or_none()
    if existing_command is not None:
        if (
            existing_command.signal_id != signal.id
            or existing_command.request_fingerprint != fingerprint
        ):
            raise TicketDraftPromotionConflict(
                f"command_id={command.command_id} is already bound to another ticket draft promotion"
            )
        draft = await session.get(WikiPageDraft, existing_command.draft_id)
        if draft is None:
            raise RuntimeError(
                "ticket draft promotion references a missing durable draft"
            )
        return TicketDraftPromotionResult(
            promotion=existing_command,
            draft=draft,
            signal_ref=signal.signal_ref,
            replayed=True,
        )

    existing_signal = (
        await session.execute(
            select(GovernanceTicketDraftPromotion).where(
                GovernanceTicketDraftPromotion.signal_id == signal.id
            )
        )
    ).scalar_one_or_none()
    if existing_signal is not None:
        raise TicketDraftPromotionConflict(
            f"signal_ref={normalized_ref} already created draft_id={existing_signal.draft_id}"
        )
    if signal.status != GovernanceSignalStatus.ACTIVE.value:
        raise TicketDraftPromotionConflict(
            f"signal_ref={normalized_ref} cannot create a draft from status={signal.status}"
        )
    if assignment.version != command.expected_assignment_version:
        raise TicketDraftPromotionConflict(
            f"expected_assignment_version={command.expected_assignment_version} does not match current version={assignment.version}"
        )

    audience_filter = validate_eligible_ticket_cluster(signal)
    evidence_refs = [dict(item) for item in signal.evidence_refs or []]
    source_signal_version = signal.version
    created_at = datetime.now(timezone.utc)
    source_ids = [str(signal.source_id)] if signal.source_id is not None else []
    source_metadata: dict[str, object] = {
        "origin": "ticket_cluster_promotion",
        "object_type": signal.object_type,
        "audience_context": _audience_context(audience_filter),
        "audience_filter": audience_filter.to_dict(),
        "evidence_refs": evidence_refs,
        "source_ids": source_ids,
        "ticket_cluster_ref": signal.object_ref,
        "governance_signal_ref": signal.signal_ref,
        "review_assignment_ref": f"review-assignment:{assignment.id}",
        "audience_variants": [],
    }
    draft = await create_wiki_draft(
        session,
        page_id=None,
        author_id=actor_id,
        content_md=build_initial_draft_content(signal.title, signal.summary),
        note=command.reason,
        source="web_ui",
        source_metadata=source_metadata,
        base_version=None,
        draft_kind="create",
        suggested_metadata={
            "slug": slugify(signal.title),
            "title": signal.title,
            "page_type": "concept",
            "knowledge_type_slugs": [signal.object_type],
            "scope_type": "global",
            "scope_id": None,
        },
        submit_for_review=False,
    )
    promotion = GovernanceTicketDraftPromotion(
        signal_id=signal.id,
        id=uuid.uuid4(),
        draft_id=draft.id,
        command_id=command.command_id,
        request_fingerprint=fingerprint,
        source_signal_version=source_signal_version,
        expected_assignment_version=command.expected_assignment_version,
        actor_id=actor_id,
        reason=command.reason,
        created_at=created_at,
    )
    session.add(promotion)
    await session.flush()
    resolved = await resolve_governance_signal(
        session,
        normalized_ref,
        resolved_at=created_at,
    )
    if resolved is None:
        raise RuntimeError("ticket draft promotion lost its governance signal")
    return TicketDraftPromotionResult(
        promotion=promotion,
        draft=draft,
        signal_ref=signal.signal_ref,
    )


def validate_eligible_ticket_cluster(signal: GovernanceSignal) -> AudienceFilter:
    if signal.signal_type != PressureSignalType.TICKET_CLUSTER.value:
        raise ValueError("only ticket_cluster signals can create ticket drafts")
    if signal.page_id is not None:
        raise ValueError("ticket cluster updates cannot create a new draft")
    triggers = tuple(signal.trigger_signals or ())
    if "ticket_cluster" not in triggers or not any(
        item.startswith("ticket_import:") for item in triggers
    ):
        raise ValueError("ticket cluster is not backed by a resolved-ticket import")
    if signal.evidence_source_type != "resolved_ticket":
        raise ValueError("ticket cluster must use resolved_ticket evidence")
    if len(signal.evidence_refs or ()) < _MIN_TICKET_EVIDENCE_REFS:
        raise ValueError(
            "ticket cluster must include at least two structured evidence refs"
        )

    record = governance_signal_to_pressure_record(signal)
    proposal = compile_pressure_proposal_bundles((record,))[0].proposal
    if proposal.action is not PlanAction.CREATE:
        raise ValueError("ticket cluster proposal must be a create action")
    if proposal.evidence_sufficiency is not EvidenceSufficiency.SUFFICIENT:
        raise ValueError("ticket cluster evidence is not sufficient to create a draft")
    return record.audience_filter


def _audience_context(audience_filter: AudienceFilter) -> dict[str, str | None]:
    return {
        "visibility": audience_filter.visibility.value,
        "brand": _single_dimension(audience_filter.brands, label="brands"),
        "product_line": _single_dimension(
            audience_filter.product_lines, label="product_lines"
        ),
        "plan_tier": _single_dimension(audience_filter.plans, label="plans"),
        "region": _single_dimension(audience_filter.regions, label="regions"),
        "language": _single_dimension(audience_filter.languages, label="languages"),
        "product_version": _single_dimension(
            audience_filter.product_versions, label="product_versions"
        ),
    }


def _single_dimension(values: tuple[str, ...], *, label: str) -> str | None:
    if len(values) > 1:
        raise ValueError(
            f"ticket cluster audience {label} must contain at most one value"
        )
    return values[0] if values else None


def _command_fingerprint(
    signal_ref: str,
    command: TicketDraftPromotionCommand,
    *,
    actor_id: uuid.UUID,
) -> str:
    payload = {
        "signal_ref": signal_ref,
        "expected_assignment_version": command.expected_assignment_version,
        "reason": command.reason,
        "actor_id": str(actor_id),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
