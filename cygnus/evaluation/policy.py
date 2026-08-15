from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import cast, final

from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.domain import governed_object_ref
from cygnus.governance import GovernanceEventType
from cygnus.integrations.governed_publish_tools import GovernedPublishTools
from cygnus.runtime.database.models import (
    GovernanceAudienceBinding,
    GovernanceLedgerEvent,
    GovernancePublication,
    Source,
    WikiPage,
    WikiPageDraft,
)

from .contracts import PolicyExpectation


_ACTOR_ID = uuid.UUID("00000000-0000-4000-8000-000000000117")
_PAGE_ID = uuid.UUID("00000000-0000-4000-8000-000000000217")
_DRAFT_ID = uuid.UUID("00000000-0000-4000-8000-000000000317")
_SOURCE_ID = uuid.UUID("00000000-0000-4000-8000-000000000417")
_APPROVAL_ID = uuid.UUID("00000000-0000-4000-8000-000000000517")
_BINDING_ID = uuid.UUID("00000000-0000-4000-8000-000000000617")
_OBJECT_REF = governed_object_ref(_PAGE_ID)
_TARGET_CHANNEL = "internal-copilot"


@final
class _OfflineScalars:
    __slots__ = ("_rows",)

    def __init__(self, rows: tuple[object, ...]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return list(self._rows)


@final
class _OfflineResult:
    __slots__ = ("_rows",)

    def __init__(self, rows: tuple[object, ...] = ()) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return list(self._rows)

    def scalars(self) -> _OfflineScalars:
        return _OfflineScalars(self._rows)

    def scalar_one_or_none(self) -> object | None:
        if len(self._rows) > 1:
            raise AssertionError(
                "offline policy query unexpectedly returned multiple rows"
            )
        return self._rows[0] if self._rows else None


@final
class _OfflinePolicySession:
    """Small read-only AsyncSession adapter over production-shaped ORM rows."""

    __slots__ = ("_approval", "_binding", "_draft", "_page", "_source")

    def __init__(self, *, page: WikiPage, draft: WikiPageDraft) -> None:
        self._page = page
        self._draft = draft
        self._source = Source(
            id=_SOURCE_ID,
            status="ready",
            freshness_state="fresh",
            freshness_actor_id=_ACTOR_ID,
            freshness_reason="Offline policy fixture attests the source as fresh.",
            freshness_attested_at=datetime.now(timezone.utc),
            freshness_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        self._approval = GovernanceLedgerEvent(
            id=_APPROVAL_ID,
            draft_id=draft.id,
            sequence=1,
            event_type=GovernanceEventType.APPROVED.value,
            from_state="in_review",
            to_state="approved",
            actor_id=_ACTOR_ID,
            idempotency_key=f"domain-eval:approval:{draft.id}",
            payload={},
        )
        self._binding = GovernanceAudienceBinding(
            id=_BINDING_ID,
            page_id=page.id,
            object_ref=_OBJECT_REF,
            variant_ref="domain-eval-internal",
            channel=_TARGET_CHANNEL,
            visibility="internal",
            brands=[],
            product_lines=[],
            plans=[],
            regions=[],
            languages=[],
            product_versions=[],
            lifecycle_state="active",
            binding_key="domain-eval-policy-binding",
            created_by_id=_ACTOR_ID,
            version=1,
        )

    async def get(self, model: object, identifier: object) -> object | None:
        if model is WikiPageDraft:
            return self._draft if identifier == self._draft.id else None
        if model is WikiPage:
            return self._page if identifier == self._page.id else None
        raise AssertionError(f"unexpected offline policy lookup: {model}")

    async def execute(self, statement: object) -> _OfflineResult:
        descriptions = cast(
            list[dict[str, object]],
            getattr(statement, "column_descriptions", ()),
        )
        entities = {description.get("entity") for description in descriptions}
        if GovernanceLedgerEvent in entities:
            return _OfflineResult((self._approval,))
        if Source in entities:
            return _OfflineResult((self._source,))
        if GovernanceAudienceBinding in entities:
            return _OfflineResult((self._binding,))
        if GovernancePublication in entities:
            return _OfflineResult()
        raise AssertionError(f"unexpected offline policy query: {statement}")


def _policy_rows(expectation: PolicyExpectation) -> tuple[WikiPage, WikiPageDraft]:
    page = WikiPage(
        id=_PAGE_ID,
        slug="domain-eval-policy",
        title="Domain evaluation publish policy",
        status="mature",
        content_md="A deterministic governed publication candidate.",
        summary="Offline production-shaped publish-policy input.",
        scope_type="global",
        scope_id=None,
        knowledge_type_slugs=["answer_card"],
        source_ids=[_SOURCE_ID],
        version=expectation.page_version,
        orphaned=False,
    )
    draft = WikiPageDraft(
        id=_DRAFT_ID,
        page_id=page.id,
        draft_kind="edit",
        author_id=_ACTOR_ID,
        content_md=page.content_md,
        base_version=expectation.page_version,
        version=1,
        revision_round=0,
        ai_check_status="passed",
        status=expectation.draft_status,
        source="api_direct",
    )
    return page, draft


async def evaluate_policy_expectation(
    expectation: PolicyExpectation,
) -> dict[str, object]:
    """Exercise the durable publish-policy adapter without a database or provider."""

    page, draft = _policy_rows(expectation)
    session = _OfflinePolicySession(page=page, draft=draft)
    tools = GovernedPublishTools(
        cast(AsyncSession, cast(object, session)),
        actor_id=_ACTOR_ID,
        is_admin=expectation.is_admin,
        visible_object_ids=(_OBJECT_REF,),
    )
    result = await tools.validate_publish_policy(
        draft_id=str(draft.id),
        target_channel=_TARGET_CHANNEL,
        expected_version=expectation.expected_version,
    )
    return cast(dict[str, object], result)
