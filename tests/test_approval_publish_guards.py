"""Focused TOCTOU guard tests for CYG-143 approval + publish scope digests.

Covers the time-of-check / time-of-use contract: a durable publication may only
carry exactly what was reviewed (canonical approval digest) inside exactly the
scope that was previewed (publish scope digest), recomputed under the aggregate
lock at apply time. Edit, source, binding, freshness, object-version, and
action/target drift must reject atomically; an exact replay must stay a single
publication; legacy approvals without a canonical digest must never publish.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, cast
import unittest
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cygnus.domain import AudienceFilter, Visibility
from cygnus.domain.objects import governed_object_ref
from cygnus.governance.approval_guards import approval_digest, publish_scope_digest
from cygnus.governance.audience_bindings import (
    AudienceBindingCreate,
    create_audience_binding,
)
from cygnus.governance.ledger import GovernanceEventType, list_draft_events
from cygnus.publish import (
    DurablePublishCommand,
    DurablePublishConflict,
    DurablePublishDenied,
    apply_durable_publish,
)
from cygnus.publish.durable import durable_publish_command_for_signal
from cygnus.review.contributions import approve_wiki_draft, create_wiki_draft
from cygnus.runtime.database.models import (
    AuditLog,
    Employee,
    GovernanceAudienceBinding,
    GovernanceLedgerEvent,
    GovernancePropagation,
    GovernancePropagationDelivery,
    GovernancePublication,
    GovernanceSignal,
    Source,
    WikiPage,
    WikiPageDraft,
    WikiPageRevision,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _audience_filter() -> AudienceFilter:
    return AudienceFilter(visibility=Visibility.INTERNAL)


def _draft(**overrides: object) -> WikiPageDraft:
    payload = dict(
        id=uuid.uuid4(),
        draft_kind="edit",
        version=2,
        base_version=1,
        revision_round=1,
        source="web_ui",
        page_id=uuid.uuid4(),
        status="approved",
        content_md="# Refund policy\n\nUse verified evidence.",
        reviewed_by_id=uuid.uuid4(),
        reviewed_at=_now(),
        reviewer_note="evidence checked",
    )
    payload.update(overrides)
    return cast(WikiPageDraft, SimpleNamespace(**payload))


def _page(**overrides: object) -> WikiPage:
    payload = dict(
        id=uuid.uuid4(),
        slug="refund-policy",
        version=2,
        content_md="# Refund policy\n\nUse verified evidence.",
        source_ids=[uuid.uuid4()],
        status="evergreen",
    )
    payload.update(overrides)
    return cast(WikiPage, SimpleNamespace(**payload))


def _binding(**overrides: object) -> GovernanceAudienceBinding:
    payload = dict(
        binding_key="b" * 64,
        version=1,
        channel="agent-copilot",
        visibility="internal",
        brands=[],
        product_lines=["billing"],
        plans=[],
        regions=[],
        languages=["en"],
        product_versions=[],
    )
    payload.update(overrides)
    return cast(GovernanceAudienceBinding, SimpleNamespace(**payload))


class ApprovalDigestUnitTests(unittest.TestCase):
    def test_approval_digest_is_deterministic_over_exact_reviewed_truth(self) -> None:
        draft = _draft()
        page = _page()
        first = approval_digest(
            draft=draft,
            page=page,
            final_content=page.content_md,
            reviewer_id=draft.reviewed_by_id,
            reviewed_at=draft.reviewed_at,
            reviewer_note=draft.reviewer_note,
        )
        second = approval_digest(
            draft=draft,
            page=page,
            final_content=page.content_md,
            reviewer_id=draft.reviewed_by_id,
            reviewed_at=draft.reviewed_at,
            reviewer_note=draft.reviewer_note,
        )
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_approval_digest_changes_on_content_edit(self) -> None:
        draft = _draft()
        page = _page(content_md="# Refund policy\n\nUse verified evidence.")

        def digest_for(content: str) -> str:
            return approval_digest(
                draft=draft,
                page=page,
                final_content=content,
                reviewer_id=draft.reviewed_by_id,
                reviewed_at=draft.reviewed_at,
                reviewer_note=draft.reviewer_note,
            )

        self.assertNotEqual(
            digest_for("# Refund policy\n\nUse verified evidence."),
            digest_for(
                "# Refund policy\n\nUse verified evidence. Edited after approval."
            ),
        )

    def test_approval_digest_changes_on_page_revision_and_source_drift(self) -> None:
        draft = _draft()
        page = _page()
        baseline = approval_digest(
            draft=draft,
            page=page,
            final_content=page.content_md,
            reviewer_id=draft.reviewed_by_id,
            reviewed_at=draft.reviewed_at,
            reviewer_note=draft.reviewer_note,
        )
        version_bumped = approval_digest(
            draft=draft,
            page=_page(version=3),
            final_content=page.content_md,
            reviewer_id=draft.reviewed_by_id,
            reviewed_at=draft.reviewed_at,
            reviewer_note=draft.reviewer_note,
        )
        source_drifted = approval_digest(
            draft=draft,
            page=_page(source_ids=[uuid.uuid4()]),
            final_content=page.content_md,
            reviewer_id=draft.reviewed_by_id,
            reviewed_at=draft.reviewed_at,
            reviewer_note=draft.reviewer_note,
        )
        review_drifted = approval_digest(
            draft=draft,
            page=page,
            final_content=page.content_md,
            reviewer_id=uuid.uuid4(),
            reviewed_at=draft.reviewed_at,
            reviewer_note=draft.reviewer_note,
        )
        self.assertNotEqual(baseline, version_bumped)
        self.assertNotEqual(baseline, source_drifted)
        self.assertNotEqual(baseline, review_drifted)

    def test_scope_digest_covers_every_previewed_dimension(self) -> None:
        approval_ref = uuid.uuid4()
        canonical = "c" * 64
        source_id = uuid.uuid4()
        bindings = (
            _binding(binding_key="binding-a", channel="agent-copilot"),
            _binding(binding_key="binding-b", channel="internal-search"),
        )

        def scope(**overrides: object) -> str:
            payload: dict[str, Any] = dict(
                approval_ref=approval_ref,
                approval_digest_value=canonical,
                object_version=2,
                binding_rows=bindings,
                source_state=((source_id, "ready"),),
                signal_freshness="fresh",
                signal_id=_GUARD_SIGNAL_ID,
                signal_status="active",
                action_key="publish",
                target_channels=("agent-copilot", "internal-search"),
            )
            payload.update(overrides)
            return publish_scope_digest(**payload)

        baseline = scope()
        self.assertEqual(len(baseline), 64)
        self.assertEqual(scope(), baseline)
        self.assertNotEqual(scope(approval_ref=uuid.uuid4()), baseline)
        self.assertNotEqual(scope(approval_digest_value="d" * 64), baseline)
        self.assertNotEqual(scope(object_version=3), baseline)
        self.assertNotEqual(
            scope(
                binding_rows=(
                    _binding(binding_key="binding-a", version=2),
                    _binding(binding_key="binding-b", channel="internal-search"),
                )
            ),
            baseline,
        )
        self.assertNotEqual(scope(source_state=((source_id, "error"),)), baseline)
        self.assertNotEqual(scope(signal_freshness="stale"), baseline)
        self.assertNotEqual(scope(signal_id=uuid.uuid4()), baseline)
        self.assertNotEqual(scope(signal_status="resolved"), baseline)
        self.assertNotEqual(scope(action_key="republish"), baseline)
        self.assertNotEqual(scope(target_channels=("agent-copilot",)), baseline)

    def test_scope_digest_only_covers_requested_channel_bindings(self) -> None:
        approval_ref = uuid.uuid4()
        canonical = "c" * 64
        bindings = (
            _binding(binding_key="binding-a", channel="agent-copilot"),
            _binding(binding_key="binding-b", channel="internal-search"),
        )

        def scope(channels: tuple[str, ...]) -> str:
            return publish_scope_digest(
                approval_ref=approval_ref,
                approval_digest_value=canonical,
                object_version=2,
                binding_rows=bindings,
                source_state=(),
                signal_freshness="fresh",
                action_key="publish",
                target_channels=channels,
            )

        self.assertEqual(scope(("agent-copilot",)), scope(("agent-copilot",)))
        self.assertNotEqual(
            scope(("agent-copilot",)),
            scope(("agent-copilot", "internal-search")),
        )


_GUARD_DRAFT_ID = uuid.UUID("00000000-0000-4000-8000-000000000101")
_GUARD_APPROVAL_REF = uuid.UUID("00000000-0000-4000-8000-000000000102")
_GUARD_SIGNAL_ID = uuid.UUID("00000000-0000-4000-8000-000000000103")


class DurablePublishCommandGuardTests(unittest.TestCase):
    def _command(self, **overrides: object) -> DurablePublishCommand:
        payload: dict[str, Any] = dict(
            draft_id=_GUARD_DRAFT_ID,
            approval_ref=_GUARD_APPROVAL_REF,
            approval_digest="a" * 64,
            scope_digest="b" * 64,
            signal_id=_GUARD_SIGNAL_ID,
            signal_freshness="fresh",
            command_id="publish-command-1",
            action_key="publish",
            target_channels=("agent-copilot",),
            expected_version=3,
        )
        payload.update(overrides)
        return DurablePublishCommand(**payload)

    def test_guards_are_required_and_normalized(self) -> None:
        command = self._command(
            approval_digest="A" * 64,
            signal_freshness=" fresh ",
        )
        self.assertEqual(command.approval_digest, "a" * 64)
        self.assertEqual(command.signal_freshness, "fresh")

    def test_missing_or_invalid_guards_are_rejected(self) -> None:
        for label, overrides in (
            ("approval_digest", {"approval_digest": "short"}),
            ("scope_digest", {"scope_digest": "x" * 64}),
            ("signal_freshness", {"signal_freshness": "expired"}),
            ("expected_version", {"expected_version": 0}),
        ):
            with self.subTest(label=label):
                with self.assertRaises(ValueError):
                    _ = self._command(**overrides)

    def test_fingerprint_includes_all_guards(self) -> None:
        base = self._command()
        self.assertEqual(base.request_fingerprint, self._command().request_fingerprint)
        for label, overrides in (
            ("approval_digest", {"approval_digest": "e" * 64}),
            ("scope_digest", {"scope_digest": "f" * 64}),
            ("signal_id", {"signal_id": uuid.uuid4()}),
            ("signal_freshness", {"signal_freshness": "unknown"}),
            ("expected_version", {"expected_version": 4}),
        ):
            with self.subTest(label=label):
                self.assertNotEqual(
                    base.request_fingerprint,
                    self._command(**overrides).request_fingerprint,
                )


_INTEGRATION_DATABASE_URL = __import__("os").getenv(
    "CYGNUS_GOVERNANCE_TEST_DATABASE_URL"
)


@unittest.skipUnless(
    _INTEGRATION_DATABASE_URL,
    "CYGNUS_GOVERNANCE_TEST_DATABASE_URL is not configured",
)
class ApprovalPublishGuardPostgresTests(unittest.TestCase):
    def test_previewed_scope_publishes_once_and_drift_conflicts(self) -> None:
        asyncio.run(self._exercise_guarded_publish_and_drift())

    async def _exercise_guarded_publish_and_drift(self) -> None:
        if _INTEGRATION_DATABASE_URL is None:
            raise AssertionError("integration database URL unexpectedly absent")

        engine = create_async_engine(_INTEGRATION_DATABASE_URL)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        unique = uuid.uuid4().hex
        actor_id = uuid.uuid4()
        source_id = uuid.uuid4()
        other_source_id = uuid.uuid4()
        scope_id = uuid.uuid4()
        draft_id: uuid.UUID | None = None
        page_id: uuid.UUID | None = None
        signal_id: uuid.UUID | None = None
        publication_id: uuid.UUID | None = None
        source_updated_at = datetime.now(timezone.utc)

        def fresh_attestation() -> dict[str, object]:
            return {
                "freshness_state": "fresh",
                "freshness_actor_id": actor_id,
                "freshness_reason": "Attested fresh for guarded publish tests.",
                "freshness_attested_at": source_updated_at + timedelta(seconds=1),
                "freshness_expires_at": source_updated_at + timedelta(days=1),
            }

        try:
            async with sessions() as session:
                actor = Employee(
                    id=actor_id,
                    name="CYG-143 guard reviewer",
                    email=f"cyg143-guard-{unique}@example.test",
                    role="admin",
                    global_role="admin",
                    is_active=True,
                )
                source = Source(
                    id=source_id,
                    title="Guarded publish evidence",
                    full_text="Verified support evidence.",
                    source_type="url",
                    language="en",
                    url=f"https://example.test/evidence/{unique}",
                    status="ready",
                    created_at=source_updated_at,
                    updated_at=source_updated_at,
                    progress=100,
                    **fresh_attestation(),
                )
                other_source = Source(
                    id=other_source_id,
                    title="Guarded publish other evidence",
                    full_text="Different verified evidence.",
                    source_type="url",
                    language="en",
                    url=f"https://example.test/other/{unique}",
                    status="ready",
                    created_at=source_updated_at,
                    updated_at=source_updated_at,
                    progress=100,
                    **fresh_attestation(),
                )
                session.add_all((actor, source, other_source))
                await session.flush()
                draft = await create_wiki_draft(
                    session,
                    page_id=None,
                    author_id=actor.id,
                    content_md="# Guarded refund policy\n\nUse verified evidence.",
                    note="ready for governed review",
                    draft_kind="create",
                    source_metadata={"source_ids": [str(source.id)]},
                    suggested_metadata={
                        "slug": f"approval-guards-{unique}",
                        "title": "Guarded refund policy",
                        "page_type": "concept",
                        "knowledge_type_slugs": ["answer_card"],
                        "scope_type": "project",
                        "scope_id": str(scope_id),
                    },
                )
                page = await approve_wiki_draft(
                    session,
                    draft,
                    reviewer_id=actor.id,
                    reviewer_note="evidence and audience checked",
                )
                self.assertEqual(page.source_ids, [source.id])
                for channel, variant in (
                    ("agent-copilot", "guarded-internal"),
                    ("internal-search", "guarded-search"),
                ):
                    _ = await create_audience_binding(
                        session,
                        command=AudienceBindingCreate(
                            page_id=page.id,
                            object_ref=governed_object_ref(page.id),
                            variant_ref=variant,
                            channel=channel,
                            audience_filter=_audience_filter(),
                        ),
                        actor_id=actor.id,
                    )
                signal = GovernanceSignal(
                    signal_ref=f"approval-guards-signal-{unique}",
                    signal_type="human_rewrite",
                    object_ref=governed_object_ref(page.id),
                    title="Guarded refund policy",
                    object_type="answer_card",
                    page_id=page.id,
                    source_id=source.id,
                    audience_binding_ref=None,
                    audience_filter=_audience_filter().to_dict(),
                    affected_surfaces=["agent-copilot", "internal-search"],
                    trigger_signals=[],
                    evidence_source_type="support_document",
                    freshness="fresh",
                    summary="Verified evidence triggers guarded publication.",
                    reason="Evidence and audience verified.",
                    evidence_excerpt="Verified support evidence.",
                    status="active",
                    observed_at=datetime.now(timezone.utc),
                    resolved_at=None,
                    created_by_id=actor.id,
                    version=1,
                )
                session.add(signal)
                await session.flush()
                draft_id = draft.id
                page_id = page.id
                signal_id = signal.id
                await session.commit()

            async with sessions() as session:
                persisted_signal = await session.get(GovernanceSignal, signal_id)
                self.assertIsNotNone(persisted_signal)
                if persisted_signal is None:
                    raise AssertionError("signal fixture unexpectedly absent")
                envelope = await durable_publish_command_for_signal(
                    session,
                    signal=persisted_signal,
                )
                self.assertIsNotNone(envelope)
                if envelope is None:
                    raise AssertionError("guarded publish command unexpectedly absent")
                self.assertIn("approval_digest", envelope)
                self.assertIn("scope_digest", envelope)
                self.assertIn("signal_id", envelope)
                self.assertIn("signal_freshness", envelope)
                self.assertIn("expected_version", envelope)
                command = DurablePublishCommand(
                    draft_id=uuid.UUID(cast(str, envelope["draft_id"])),
                    approval_ref=uuid.UUID(cast(str, envelope["approval_ref"])),
                    approval_digest=cast(str, envelope["approval_digest"]),
                    scope_digest=cast(str, envelope["scope_digest"]),
                    signal_id=uuid.UUID(cast(str, envelope["signal_id"])),
                    signal_freshness=cast(str, envelope["signal_freshness"]),
                    command_id=cast(str, envelope["command_id"]),
                    action_key=cast(str, envelope["action_key"]),
                    target_channels=tuple(cast(list[str], envelope["target_channels"])),
                    expected_version=cast(int, envelope["expected_version"]),
                    reason=cast(str, envelope["reason"]),
                )
                result = await apply_durable_publish(
                    session,
                    command=command,
                    actor_id=actor_id,
                )
                self.assertTrue(result["persisted"])
                self.assertFalse(result["replayed"])
                self.assertEqual(result["approval_digest"], command.approval_digest)
                self.assertEqual(result["scope_digest"], command.scope_digest)
                publication_id = uuid.UUID(cast(str, result["publication_record_id"]))
                replay = await apply_durable_publish(
                    session,
                    command=command,
                    actor_id=actor_id,
                )
                self.assertTrue(replay["replayed"])
                self.assertEqual(
                    replay["publication_record_id"],
                    str(publication_id),
                )
                await session.commit()

            async with sessions() as session:
                loaded_draft = await session.get(WikiPageDraft, draft_id)
                loaded_page = await session.get(WikiPage, page_id)
                loaded_signal = await session.get(GovernanceSignal, signal_id)
                self.assertIsNotNone(loaded_draft)
                self.assertIsNotNone(loaded_page)
                self.assertIsNotNone(loaded_signal)
                if loaded_draft is None or loaded_page is None or loaded_signal is None:
                    raise AssertionError("guard fixtures unexpectedly absent")
                events = await list_draft_events(session, loaded_draft.id)
                approval = next(
                    event
                    for event in events
                    if event.event_type == GovernanceEventType.APPROVED.value
                )
                approval_digest_value = cast(str, approval.payload["approval_digest"])
                stored_scope = await _stored_scope(session, publication_id)
                # The caller always echoes the preview-time attestation; the
                # signal's current attestation may drift underneath it.
                preview_freshness = loaded_signal.freshness

                async def apply_with(
                    *,
                    scope_digest: str,
                    action_key: str,
                    target_channels: tuple[str, ...],
                    suffix: str,
                    signal_freshness: str | None = None,
                ) -> DurablePublishConflict | DurablePublishDenied | dict[str, object]:
                    attempt = DurablePublishCommand(
                        draft_id=loaded_draft.id,
                        approval_ref=approval.id,
                        approval_digest=approval_digest_value,
                        scope_digest=scope_digest,
                        signal_id=loaded_signal.id,
                        signal_freshness=(
                            signal_freshness
                            if signal_freshness is not None
                            else preview_freshness
                        ),
                        command_id=f"guard-drift-{suffix}-{unique}",
                        action_key=action_key,
                        target_channels=target_channels,
                        expected_version=loaded_page.version,
                        reason=f"exercise {suffix} drift",
                    )
                    try:
                        return await apply_durable_publish(
                            session,
                            command=attempt,
                            actor_id=actor_id,
                        )
                    except (DurablePublishDenied, DurablePublishConflict) as exc:
                        return exc

                def assert_conflict(outcome: object, *, fragment: str) -> None:
                    self.assertIsInstance(outcome, DurablePublishConflict)
                    self.assertIn(fragment, str(outcome))

                def assert_denied(outcome: object, *, fragment: str) -> None:
                    self.assertIsInstance(outcome, DurablePublishDenied)
                    self.assertIn(fragment, str(outcome))

                # Edit drift: content changed after approval/preview.
                original_content = loaded_page.content_md
                loaded_page.content_md = original_content + "\n# Edited after approval"
                await session.flush()
                assert_conflict(
                    await apply_with(
                        scope_digest=stored_scope,
                        action_key="publish",
                        target_channels=("agent-copilot", "internal-search"),
                        suffix="edit",
                    ),
                    fragment="approval content drift",
                )
                loaded_page.content_md = original_content
                await session.flush()

                # Source drift: linked source ids changed after approval.
                original_source_ids = list(loaded_page.source_ids or ())
                loaded_page.source_ids = [other_source_id]
                await session.flush()
                assert_conflict(
                    await apply_with(
                        scope_digest=stored_scope,
                        action_key="publish",
                        target_channels=("agent-copilot", "internal-search"),
                        suffix="source",
                    ),
                    fragment="approval content drift",
                )
                loaded_page.source_ids = original_source_ids
                await session.flush()

                # Binding drift: an active binding is held after preview.
                binding_rows = tuple(
                    (
                        await session.execute(
                            select(GovernanceAudienceBinding).where(
                                GovernanceAudienceBinding.page_id == loaded_page.id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                original_lifecycle = [row.lifecycle_state for row in binding_rows]
                binding_rows[0].lifecycle_state = "held"
                await session.flush()
                assert_conflict(
                    await apply_with(
                        scope_digest=stored_scope,
                        action_key="publish",
                        target_channels=("agent-copilot", "internal-search"),
                        suffix="binding",
                    ),
                    fragment="publish scope drift",
                )
                for row, lifecycle in zip(binding_rows, original_lifecycle):
                    row.lifecycle_state = lifecycle
                await session.flush()

                # Freshness drift: the signal attestation changed after preview.
                original_freshness = loaded_signal.freshness
                loaded_signal.freshness = "stale"
                await session.flush()
                assert_conflict(
                    await apply_with(
                        scope_digest=stored_scope,
                        action_key="publish",
                        target_channels=("agent-copilot", "internal-search"),
                        suffix="freshness",
                    ),
                    fragment="freshness attestation drift",
                )
                loaded_signal.freshness = original_freshness
                await session.flush()
                # Lifecycle drift: a preview is invalid after resolution or dismissal.
                for status in ("resolved", "dismissed"):
                    loaded_signal.status = status
                    await session.flush()
                    assert_conflict(
                        await apply_with(
                            scope_digest=stored_scope,
                            action_key="publish",
                            target_channels=("agent-copilot", "internal-search"),
                            suffix=f"signal-{status}",
                        ),
                        fragment="signal lifecycle drift",
                    )
                loaded_signal.status = "active"
                await session.flush()
                # Action drift: apply a different action than was previewed.
                assert_conflict(
                    await apply_with(
                        scope_digest=stored_scope,
                        action_key="republish",
                        target_channels=("agent-copilot", "internal-search"),
                        suffix="action",
                    ),
                    fragment="publish scope drift",
                )

                # Channel drift: apply a narrower channel set than previewed.
                assert_conflict(
                    await apply_with(
                        scope_digest=stored_scope,
                        action_key="publish",
                        target_channels=("agent-copilot",),
                        suffix="channels",
                    ),
                    fragment="publish scope drift",
                )

                # Object version drift: page version advanced after preview.
                loaded_page.version += 1
                await session.flush()
                assert_conflict(
                    await apply_with(
                        scope_digest=stored_scope,
                        action_key="publish",
                        target_channels=("agent-copilot", "internal-search"),
                        suffix="version",
                    ),
                    fragment="object version conflict",
                )
                loaded_page.version -= 1
                await session.flush()

                # Legacy approval without a canonical digest never publishes.
                original_payload = dict(approval.payload)
                approval.payload = {
                    key: value
                    for key, value in original_payload.items()
                    if key != "approval_digest"
                }
                await session.flush()
                assert_denied(
                    await apply_with(
                        scope_digest=stored_scope,
                        action_key="publish",
                        target_channels=("agent-copilot", "internal-search"),
                        suffix="legacy",
                    ),
                    fragment="no canonical approval digest",
                )
        finally:
            async with sessions() as cleanup:
                if publication_id is not None:
                    _ = await cleanup.execute(
                        delete(GovernancePropagationDelivery).where(
                            GovernancePropagationDelivery.publication_id
                            == publication_id
                        )
                    )
                    _ = await cleanup.execute(
                        delete(GovernancePropagation).where(
                            GovernancePropagation.publication_id == publication_id
                        )
                    )
                    _ = await cleanup.execute(
                        delete(GovernancePublication).where(
                            GovernancePublication.id == publication_id
                        )
                    )
                if page_id is not None:
                    _ = await cleanup.execute(
                        delete(GovernanceAudienceBinding).where(
                            GovernanceAudienceBinding.page_id == page_id
                        )
                    )
                if draft_id is not None:
                    _ = await cleanup.execute(
                        delete(GovernanceLedgerEvent).where(
                            GovernanceLedgerEvent.draft_id == draft_id
                        )
                    )
                    _ = await cleanup.execute(
                        delete(WikiPageRevision).where(
                            WikiPageRevision.draft_id == draft_id
                        )
                    )
                    _ = await cleanup.execute(
                        delete(WikiPageDraft).where(WikiPageDraft.id == draft_id)
                    )
                if page_id is not None:
                    _ = await cleanup.execute(
                        delete(WikiPageRevision).where(
                            WikiPageRevision.page_id == page_id
                        )
                    )
                    _ = await cleanup.execute(
                        delete(WikiPage).where(WikiPage.id == page_id)
                    )
                if signal_id is not None:
                    _ = await cleanup.execute(
                        delete(GovernanceSignal).where(GovernanceSignal.id == signal_id)
                    )
                _ = await cleanup.execute(
                    delete(Source).where(Source.id.in_((source_id, other_source_id)))
                )
                _ = await cleanup.execute(
                    delete(AuditLog).where(AuditLog.principal_id == actor_id)
                )
                _ = await cleanup.execute(
                    delete(Employee).where(Employee.id == actor_id)
                )
                await cleanup.commit()
            await engine.dispose()


async def _stored_scope(session: AsyncSession, publication_id: uuid.UUID) -> str:
    publication = (
        await session.execute(
            select(GovernancePublication).where(
                GovernancePublication.id == publication_id
            )
        )
    ).scalar_one_or_none()
    if publication is None:
        raise AssertionError("stored publication unexpectedly absent")
    return publication.scope_digest


if __name__ == "__main__":
    unittest.main()
