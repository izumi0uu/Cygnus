"""Canonical approval and publish-scope digest guards for governed publication.

CYG-143: a durable publication may only carry exactly what was reviewed (the
canonical approval digest persisted on the APPROVED ledger event) inside
exactly the scope that was previewed (the publish scope digest signed into the
durable command). Both digests are recomputed under the draft aggregate lock
at apply time; any edit, source, binding, freshness, object-version, or
action/target drift rejects atomically as a conflict instead of publishing
stale truth. There is no optional legacy bypass: commands without guards, and
approvals without a persisted canonical digest, never qualify for publication.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import TypedDict

from cygnus.runtime.database.models import (
    GovernanceAudienceBinding,
    WikiPage,
    WikiPageDraft,
)


def _canonical_sha256(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _reviewed_at_iso(reviewed_at: datetime | None) -> str | None:
    if reviewed_at is None:
        return None
    return reviewed_at.astimezone(timezone.utc).isoformat()


def approval_digest(
    *,
    draft: WikiPageDraft,
    page: WikiPage,
    final_content: str,
    reviewer_id: uuid.UUID | None,
    reviewed_at: datetime | None,
    reviewer_note: str | None,
) -> str:
    """Canonical digest over the exact reviewed draft/page revision, content, source, and review metadata.

    Approve time persists this value on the APPROVED ledger event. Apply time
    recomputes it from persisted truth under the aggregate lock; any change to
    the draft, page revision, content, linked sources, or review metadata after
    approval changes the digest and publication rejects as drift.
    """
    payload: dict[str, object] = {
        "draft_id": str(draft.id),
        "draft_kind": draft.draft_kind,
        "draft_version": draft.version,
        "base_version": draft.base_version,
        "revision_round": draft.revision_round,
        "source": draft.source,
        "page_id": str(page.id),
        "page_version": page.version,
        "page_slug": page.slug,
        "content_sha256": hashlib.sha256(final_content.encode("utf-8")).hexdigest(),
        "source_ids": sorted(str(source_id) for source_id in (page.source_ids or ())),
        "reviewer_id": str(reviewer_id),
        "reviewed_at": _reviewed_at_iso(reviewed_at),
        "reviewer_note": reviewer_note,
    }
    return _canonical_sha256(payload)


class _BindingScopePayload(TypedDict):
    binding_key: str
    version: int
    channel: str
    visibility: str
    brands: list[str]
    product_lines: list[str]
    plans: list[str]
    regions: list[str]
    languages: list[str]
    product_versions: list[str]


def _binding_scope_payload(row: GovernanceAudienceBinding) -> _BindingScopePayload:
    return {
        "binding_key": row.binding_key,
        "version": row.version,
        "channel": row.channel,
        "visibility": row.visibility,
        "brands": sorted(row.brands or ()),
        "product_lines": sorted(row.product_lines or ()),
        "plans": sorted(row.plans or ()),
        "regions": sorted(row.regions or ()),
        "languages": sorted(row.languages or ()),
        "product_versions": sorted(row.product_versions or ()),
    }


def publish_scope_digest(
    *,
    approval_ref: uuid.UUID,
    approval_digest_value: str,
    object_version: int,
    binding_rows: Iterable[GovernanceAudienceBinding],
    source_state: Iterable[tuple[uuid.UUID, str]],
    signal_freshness: str,
    action_key: str,
    target_channels: Iterable[str],
    signal_id: uuid.UUID | None = None,
    signal_status: str = "active",
) -> str:
    """Canonical digest over the full publish scope that must be previewed before apply.

    Covers the approval (ref + canonical digest), the exact object version, the
    binding versions/audiences/channels for the requested channels, the source
    and signal freshness attestations, and the action + targets. Preview signs
    it into the durable command; apply recomputes it under lock and conflicts
    on any drift.
    """
    normalized_action = action_key.strip()
    normalized_freshness = signal_freshness.strip()
    if not normalized_action:
        raise ValueError("action_key must not be blank")
    if not normalized_freshness:
        raise ValueError("signal_freshness must not be blank")
    normalized_signal_status = signal_status.strip()
    if not normalized_signal_status:
        raise ValueError("signal_status must not be blank")
    normalized_channels: list[str] = []
    for raw_channel in target_channels:
        channel = raw_channel.strip()
        if not channel:
            raise ValueError("target channel must not be blank")
        if channel not in normalized_channels:
            normalized_channels.append(channel)
    if not normalized_channels:
        raise ValueError("target_channels must not be empty")
    channel_set = set(normalized_channels)

    bindings = sorted(
        (
            _binding_scope_payload(row)
            for row in binding_rows
            if row.channel in channel_set
        ),
        key=lambda item: item["binding_key"],
    )
    sources = sorted(
        (
            {"source_id": str(source_id), "status": status}
            for source_id, status in source_state
        ),
        key=lambda item: item["source_id"],
    )
    payload: dict[str, object] = {
        "approval_ref": str(approval_ref),
        "approval_digest": approval_digest_value,
        "object_version": object_version,
        "bindings": bindings,
        "sources": sources,
        "signal_freshness": normalized_freshness,
        "signal_id": str(signal_id) if signal_id is not None else None,
        "signal_status": normalized_signal_status,
        "action_key": normalized_action,
        "target_channels": sorted(normalized_channels),
    }
    return _canonical_sha256(payload)
