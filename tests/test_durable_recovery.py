from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import cast
import uuid
from unittest.mock import AsyncMock

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects import postgresql

from cygnus.recovery import (
    DurableRecoveryNotFound,
    DurableRecoveryUnavailable,
    get_durable_downstream_reality_check,
    get_durable_governance_overview,
    get_durable_recovery_window,
)
from cygnus.runtime.database.models import Employee, GovernanceLedgerEvent, WikiPage
from cygnus.runtime.routers.governance.recovery import (
    downstream_reality_check,
    governance_overview,
    recovery_window,
)


class _Result:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object:
        return self.value

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[object]:
        return list(cast(tuple[object, ...], self.value))


class _RecoverySession:
    def __init__(
        self,
        *,
        publication: object | None,
        propagations: tuple[object, ...] = (),
        signals: tuple[object, ...] = (),
        page: object | None = None,
        actor: object | None = None,
        event: object | None = None,
    ) -> None:
        results = [_Result(publication)]
        if publication is not None:
            results.extend(
                (
                    _Result(propagations),
                    _Result(signals),
                    _Result(
                        tuple(
                            SimpleNamespace(
                                signal_id=signal.id,
                                owner_ref=signal.queue_owner,
                            )
                            for signal in signals
                        )
                    ),
                )
            )
        self.execute: AsyncMock = AsyncMock(side_effect=results)

        async def get(model: object, _key: object) -> object | None:
            if model is WikiPage:
                return page
            if model is Employee:
                return actor
            if model is GovernanceLedgerEvent:
                return event
            raise AssertionError(f"unexpected model lookup: {model}")

        self.get: AsyncMock = AsyncMock(side_effect=get)


def _publication(published_at: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        page_id=uuid.uuid4(),
        publish_event_id=uuid.uuid4(),
        published_by_id=uuid.uuid4(),
        command_id="durable-command-1",
        object_ref="ko-durable-recovery",
        action_key="publish",
        action_log=["approved evidence published to governed channels"],
        target_channels=["copilot", "help_center", "macro"],
        published_at=published_at,
    )


def _propagation(status: str, surface_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        surface_id=surface_id,
        status=status,
        reason=f"persisted {status} result",
        follow_up_commands=[f"follow_up_{surface_id}"],
        updated_by_id=None,
        last_event_id=uuid.uuid4(),
    )


def _signal(
    *,
    published_at: datetime,
    signal_ref: str,
    signal_type: str,
    observed_offset: int,
    status: str = "active",
    resolved_offset: int | None = None,
    triggers: tuple[str, ...] = (),
    surface: str = "copilot",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        signal_ref=signal_ref,
        signal_type=signal_type,
        object_ref="ko-durable-recovery",
        title=f"Persisted {signal_type} signal",
        object_type="answer_card",
        page_id=uuid.uuid4(),
        source_id=None,
        audience_binding_ref=None,
        audience_filter={
            "visibility": "external",
            "product_lines": ["billing"],
            "plans": ["enterprise"],
            "regions": ["eu"],
        },
        affected_surfaces=[surface],
        trigger_signals=list(triggers),
        freshness="fresh",
        summary=f"Persisted {signal_type} summary",
        reason=f"Persisted {signal_type} reason",
        evidence_excerpt=f"Persisted {signal_type} evidence",
        queue_owner="support-ops",
        status=status,
        observed_at=published_at + timedelta(minutes=observed_offset),
        resolved_at=(
            published_at + timedelta(minutes=resolved_offset)
            if resolved_offset is not None
            else None
        ),
    )


def _session(
    *,
    publication: SimpleNamespace,
    propagations: tuple[SimpleNamespace, ...],
    signals: tuple[SimpleNamespace, ...],
) -> AsyncSession:
    fake = _RecoverySession(
        publication=publication,
        propagations=propagations,
        signals=signals,
        page=SimpleNamespace(
            id=publication.page_id,
            title="Durable recovery answer",
            source_ids=[],
        ),
        actor=SimpleNamespace(name="Governance owner"),
        event=SimpleNamespace(reason="Persisted approval and publication reason"),
    )
    return cast(AsyncSession, cast(object, fake))


def test_durable_recovery_uses_signal_snapshots_and_propagation_blockers() -> None:
    published_at = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
    publication = _publication(published_at)
    propagations = (
        _propagation("synced", "copilot"),
        _propagation("pending", "help_center"),
        _propagation("failed", "macro"),
        _propagation("manual_action_required", "external_bot"),
    )
    signals = (
        _signal(
            published_at=published_at,
            signal_ref="rewrite-before",
            signal_type="human_rewrite",
            observed_offset=-10,
            status="resolved",
            resolved_offset=5,
        ),
        _signal(
            published_at=published_at,
            signal_ref="incident-after",
            signal_type="incident_delta",
            observed_offset=5,
        ),
        _signal(
            published_at=published_at,
            signal_ref="pressure-conflict-after",
            signal_type="ticket_cluster",
            observed_offset=7,
            triggers=("audience_conflict",),
            surface="help_center",
        ),
        _signal(
            published_at=published_at,
            signal_ref="coverage-after",
            signal_type="source_failure",
            observed_offset=8,
            surface="macro",
        ),
    )

    surface = asyncio.run(
        get_durable_recovery_window(
            _session(
                publication=publication,
                propagations=propagations,
                signals=signals,
            ),
            command_id=publication.command_id,
        )
    ).to_dict()

    assert surface["command_ref"]["issued_by"] == "Governance owner"
    assert surface["rewrite_delta"]["before_value"] == 1
    assert surface["rewrite_delta"]["after_value"] == 0
    assert surface["drift_delta"]["after_value"] == 1
    assert surface["escalation_delta"]["after_value"] == 1
    assert surface["coverage_gap_delta"]["after_value"] == 1
    assert surface["publish_conflict_delta"]["after_value"] == 1
    assert surface["closure_judge"]["closeable"] is False
    residual_labels = {item["label"] for item in surface["residual_risks"]}
    assert "help_center propagation is pending" in residual_labels
    assert "macro propagation is failed" in residual_labels
    assert "external_bot propagation is manual_action_required" in residual_labels


def test_synced_propagation_and_zero_active_signals_can_close_without_fake_risk() -> (
    None
):
    published_at = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
    publication = _publication(published_at)

    surface = asyncio.run(
        get_durable_recovery_window(
            _session(
                publication=publication,
                propagations=(_propagation("synced", "copilot"),),
                signals=(),
            ),
            command_id=publication.command_id,
        )
    ).to_dict()

    assert surface["residual_risks"] == []
    assert surface["closure_judge"]["closeable"] is True
    assert surface["closure_judge"]["recommendation"] == "close_and_monitor"


def test_durable_downstream_feedback_uses_only_post_publication_supported_signals() -> (
    None
):
    published_at = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
    publication = _publication(published_at)
    feedback = _signal(
        published_at=published_at,
        signal_ref="rewrite-feedback",
        signal_type="human_rewrite",
        observed_offset=4,
        triggers=("feedback:human_rewrite",),
        surface="macro",
    )
    pre_publish = _signal(
        published_at=published_at,
        signal_ref="old-rewrite",
        signal_type="human_rewrite",
        observed_offset=-4,
    )

    surface = asyncio.run(
        get_durable_downstream_reality_check(
            _session(
                publication=publication,
                propagations=(_propagation("synced", "macro"),),
                signals=(pre_publish, feedback),
            ),
            command_id=publication.command_id,
        )
    ).to_dict()

    assert [item["signal_id"] for item in surface["feedback_feed"]] == [
        "rewrite-feedback"
    ]
    assert surface["feedback_feed"][0]["signal_type"] == "human_rewrite"
    assert surface["feedback_feed"][0]["audience_label"] == (
        "external · billing · enterprise · eu"
    )


def test_no_supported_post_publish_feedback_is_explicitly_unavailable() -> None:
    published_at = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
    publication = _publication(published_at)
    unsupported = _signal(
        published_at=published_at,
        signal_ref="release-delta-only",
        signal_type="release_delta",
        observed_offset=4,
    )

    try:
        asyncio.run(
            get_durable_downstream_reality_check(
                _session(
                    publication=publication,
                    propagations=(_propagation("synced", "copilot"),),
                    signals=(unsupported,),
                ),
                command_id=publication.command_id,
            )
        )
    except DurableRecoveryUnavailable as exc:
        assert "no persisted post-publication downstream feedback" in str(exc)
    else:
        raise AssertionError("unsupported feedback must remain unavailable")

    try:
        asyncio.run(
            downstream_reality_check(
                command_id=publication.command_id,
                current_user=cast(
                    Employee,
                    cast(object, SimpleNamespace(role="admin")),
                ),
                db=_session(
                    publication=publication,
                    propagations=(_propagation("synced", "copilot"),),
                    signals=(unsupported,),
                ),
            )
        )
    except HTTPException as exc:
        assert exc.status_code == 404
        assert "no persisted post-publication downstream feedback" in str(exc.detail)
    else:
        raise AssertionError("runtime unavailable feedback must return HTTP 404")


def test_feedback_derived_signals_keep_exact_recovery_meaning() -> None:
    published_at = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
    publication = _publication(published_at)
    low_rating = _signal(
        published_at=published_at,
        signal_ref="feedback-route:low-rating",
        signal_type="low_rating",
        observed_offset=4,
        triggers=("low_rating",),
        surface="feedback",
    )
    stale_answer = _signal(
        published_at=published_at,
        signal_ref="feedback-route:stale-answer",
        signal_type="stale_answer",
        observed_offset=5,
        triggers=("stale_answer",),
        surface="review_queue",
    )

    recovery = asyncio.run(
        get_durable_recovery_window(
            _session(
                publication=publication,
                propagations=(_propagation("synced", "copilot"),),
                signals=(low_rating, stale_answer),
            ),
            command_id=publication.command_id,
        )
    ).to_dict()
    risks = {item["risk_id"]: item for item in recovery["residual_risks"]}

    assert recovery["escalation_delta"]["after_value"] == 1
    assert recovery["drift_delta"]["after_value"] == 1
    assert risks["signal:feedback-route:low-rating"]["recommended_command"] == (
        "open_feedback_review"
    )
    assert risks["signal:feedback-route:stale-answer"]["recommended_command"] == (
        "verify_freshness"
    )

    try:
        asyncio.run(
            get_durable_downstream_reality_check(
                _session(
                    publication=publication,
                    propagations=(_propagation("synced", "copilot"),),
                    signals=(low_rating, stale_answer),
                ),
                command_id=publication.command_id,
            )
        )
    except DurableRecoveryUnavailable as exc:
        assert "no persisted post-publication downstream feedback" in str(exc)
    else:
        raise AssertionError(
            "feedback-derived governance signals must not fabricate downstream feedback types"
        )


def test_unknown_command_is_not_resolved_from_sample_fixtures() -> None:
    fake = _RecoverySession(publication=None)
    session = cast(AsyncSession, cast(object, fake))

    try:
        asyncio.run(get_durable_recovery_window(session, command_id="missing-command"))
    except DurableRecoveryNotFound as exc:
        assert "missing-command" in str(exc)
    else:
        raise AssertionError("unknown durable command must not resolve")

    try:
        asyncio.run(
            recovery_window(
                command_id="missing-command",
                current_user=cast(
                    Employee,
                    cast(object, SimpleNamespace(role="admin")),
                ),
                db=cast(
                    AsyncSession,
                    cast(object, _RecoverySession(publication=None)),
                ),
            )
        )
    except HTTPException as exc:
        assert exc.status_code == 404
        assert "missing-command" in str(exc.detail)
    else:
        raise AssertionError("runtime unknown command must return HTTP 404")


def test_durable_overview_is_scoped_and_uses_persisted_recovery_windows() -> None:
    published_at = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
    publication = _publication(published_at)
    fake = _RecoverySession(
        publication=(publication,),
        propagations=(_propagation("pending", "help_center"),),
        signals=(),
        page=SimpleNamespace(
            id=publication.page_id,
            title="Durable recovery answer",
            source_ids=[],
        ),
        actor=SimpleNamespace(name="Governance owner"),
        event=SimpleNamespace(reason="Persisted publication reason"),
    )
    session = cast(AsyncSession, cast(object, fake))

    payload = asyncio.run(
        get_durable_governance_overview(
            session,
            page_scope_clause=WikiPage.id.is_(None),
        )
    ).to_dict()

    statement = fake.execute.await_args_list[0].args[0]
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "JOIN wiki_pages" in sql
    assert "wiki_pages.id IS NULL" in sql
    assert len(payload["open_loops"]) == 1
    assert payload["open_loops"][0]["command_id"] == publication.command_id
    assert payload["open_loops"][0]["pending_propagation_count"] == 1


def test_recovery_overview_route_marks_durable_truth_not_rehearsal() -> None:
    published_at = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
    publication = _publication(published_at)
    fake = _RecoverySession(
        publication=(publication,),
        propagations=(_propagation("synced", "copilot"),),
        signals=(),
        page=SimpleNamespace(
            id=publication.page_id,
            title="Durable recovery answer",
            source_ids=[],
        ),
        actor=SimpleNamespace(name="Governance owner"),
        event=SimpleNamespace(reason="Persisted publication reason"),
    )

    payload = asyncio.run(
        governance_overview(
            current_user=cast(
                Employee,
                cast(object, SimpleNamespace(role="admin")),
            ),
            db=cast(AsyncSession, cast(object, fake)),
        )
    )

    assert payload["persisted"] is True
    assert payload["rehearsal"] is False
    assert len(payload["open_loops"]) == 1


def test_recovery_overview_without_visible_publications_is_unavailable() -> None:
    fake = _RecoverySession(publication=())
    try:
        asyncio.run(
            get_durable_governance_overview(
                cast(AsyncSession, cast(object, fake)),
            )
        )
    except DurableRecoveryUnavailable as exc:
        assert "no persisted recovery windows" in str(exc)
    else:
        raise AssertionError("empty durable recovery scope must remain unavailable")
