from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast, final
import unittest
from unittest.mock import AsyncMock, patch
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.governance.audit import (
    GovernanceAuditEntry,
    GovernanceAuditPage,
    GovernanceAuditPhase,
    GovernanceAuditQuery,
    governance_audit_entry,
    governance_audit_phase,
    governance_audit_scope_clause,
    list_governance_audit_events,
)
from cygnus.governance.ledger import GovernanceEventType
from cygnus.runtime.database import get_db
from cygnus.runtime.database.models import (
    Employee,
    GovernanceLedgerEvent,
    WikiPage,
    WikiPageDraft,
)
from cygnus.runtime.routers.governance import audit as audit_router
from cygnus.runtime.services.auth_service import get_current_user

_NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
_DEPARTMENT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
_EVENT_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
_DRAFT_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
_PAGE_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
_ACTOR_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")


def _employee(
    *,
    role: str = "employee",
    global_role: str = "viewer",
    department_ids: tuple[uuid.UUID, ...] = (),
) -> Employee:
    return cast(
        Employee,
        cast(
            object,
            SimpleNamespace(
                id=_ACTOR_ID,
                name="Audit reader",
                role=role,
                global_role=global_role,
                department_ids=list(department_ids),
            ),
        ),
    )


def _event(
    event_type: GovernanceEventType = GovernanceEventType.PUBLISHED,
    *,
    payload: dict[str, object] | None = None,
) -> GovernanceLedgerEvent:
    return GovernanceLedgerEvent(
        id=_EVENT_ID,
        draft_id=_DRAFT_ID,
        sequence=4,
        event_type=event_type.value,
        from_state="approved",
        to_state="published",
        actor_id=_ACTOR_ID,
        idempotency_key="publish:command-1",
        reason="approved support publication",
        payload=payload
        or {
            "publication_id": "publication-1",
            "approval_ref": "approval-1",
            "command_id": "command-1",
            "request_fingerprint": "must-not-leak",
            "object_ref": "ko-billing-policy",
            "object_version": 2,
            "action_key": "publish",
            "target_channels": ["internal-copilot"],
            "initial_propagation_status": "pending",
            "result": {"must_not": "leak"},
        },
        occurred_at=_NOW,
        recorded_at=_NOW,
    )


def _draft(*, page_id: uuid.UUID | None = _PAGE_ID) -> WikiPageDraft:
    return WikiPageDraft(
        id=_DRAFT_ID,
        page_id=page_id,
        draft_kind="create",
        suggested_metadata={
            "slug": "billing-policy",
            "title": "Billing policy",
            "scope_type": "department",
            "scope_id": str(_DEPARTMENT_ID),
        },
        author_id=_ACTOR_ID,
        content_md="# Billing policy",
        revision_round=0,
        status="approved",
        source="web_ui",
    )


def _page() -> WikiPage:
    return WikiPage(
        id=_PAGE_ID,
        slug="billing-policy",
        title="Billing policy",
        status="mature",
        content_md="# Billing policy",
        summary="Governed billing policy",
        scope_type="department",
        scope_id=_DEPARTMENT_ID,
        knowledge_type_slugs=["policy_rule"],
        source_ids=[],
        version=2,
        orphaned=False,
    )


def _entry() -> GovernanceAuditEntry:
    return governance_audit_entry(
        event=_event(),
        draft=_draft(),
        page=_page(),
        actor=_employee(role="admin"),
    )


@final
class _ScalarResult:
    def __init__(self, value: int) -> None:
        self.value: int = value

    def scalar_one(self) -> int:
        return self.value


@final
class _RowsResult:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows: list[tuple[object, ...]] = rows

    def all(self) -> list[tuple[object, ...]]:
        return self.rows


@final
class GovernanceAuditContractTests(unittest.TestCase):
    def test_every_ledger_event_maps_to_one_governance_phase(self) -> None:
        mapped = {
            event_type: governance_audit_phase(event_type.value)
            for event_type in GovernanceEventType
        }

        self.assertEqual(set(mapped), set(GovernanceEventType))
        self.assertIs(
            mapped[GovernanceEventType.PROPAGATION_UPDATED],
            GovernanceAuditPhase.RECOVERY,
        )
        self.assertIs(
            mapped[GovernanceEventType.APPROVED],
            GovernanceAuditPhase.APPROVAL,
        )

    def test_projection_whitelists_trace_fields_and_excludes_internal_payload(
        self,
    ) -> None:
        payload = _entry().to_dict()
        details = cast(dict[str, object], payload["details"])
        resource = cast(dict[str, object], payload["resource"])

        self.assertEqual(payload["trace_ref"], f"governance-event:{_EVENT_ID}")
        self.assertEqual(payload["phase"], "publish")
        self.assertEqual(resource["scope_id"], str(_DEPARTMENT_ID))
        self.assertEqual(details["publication_id"], "publication-1")
        self.assertNotIn("request_fingerprint", details)
        self.assertNotIn("result", details)
        self.assertTrue(payload["persisted"])
        self.assertFalse(payload["rehearsal"])

    def test_approval_event_uses_ledger_event_as_approval_reference(self) -> None:
        event = _event(
            GovernanceEventType.APPROVED,
            payload={"page_id": str(_PAGE_ID), "page_version": 2},
        )
        event.from_state = "in_review"
        event.to_state = "approved"
        payload = governance_audit_entry(
            event=event,
            draft=_draft(),
            page=_page(),
            actor=_employee(role="admin"),
        ).to_dict()
        details = cast(dict[str, object], payload["details"])

        self.assertEqual(payload["phase"], "approval")
        self.assertEqual(details["approval_ref"], str(_EVENT_ID))

    def test_draft_update_projection_exposes_rebase_integrity_trace(self) -> None:
        event = _event(
            GovernanceEventType.DRAFT_UPDATED,
            payload={
                "action": "branch_rebase",
                "previous_draft_version": 1,
                "draft_version": 2,
                "base_version": 3,
                "revision_round": 0,
                "content_sha256": "content-digest",
                "branch_id": "branch-1",
                "page_id": str(_PAGE_ID),
                "base_page_version": 3,
                "unrelated": "must-not-leak",
            },
        )
        event.from_state = "in_review"
        event.to_state = "in_review"
        payload = governance_audit_entry(
            event=event,
            draft=_draft(),
            page=_page(),
            actor=_employee(role="admin"),
        ).to_dict()
        details = cast(dict[str, object], payload["details"])

        self.assertEqual(payload["phase"], "review")
        self.assertEqual(details["action"], "branch_rebase")
        self.assertEqual(details["draft_version"], 2)
        self.assertEqual(details["content_sha256"], "content-digest")
        self.assertEqual(details["base_page_version"], 3)
        self.assertNotIn("unrelated", details)

    def test_ready_observation_stays_explicit_when_scoped_result_is_empty(self) -> None:
        payload = GovernanceAuditPage(items=(), total=0, page=1, page_size=50).to_dict()
        observation = cast(dict[str, object], payload["observation"])

        self.assertEqual(payload["items"], [])
        self.assertEqual(observation["state"], "ready")
        self.assertEqual(observation["observed_count"], 0)
        self.assertEqual(observation["reason"], "durable_governance_ledger")
        self.assertEqual(observation["missing_signals"], [])

    def test_own_department_scope_is_enforced_for_pages_and_create_drafts(self) -> None:
        clause = governance_audit_scope_clause(
            _employee(department_ids=(_DEPARTMENT_ID,))
        )
        self.assertIsNotNone(clause)
        if clause is None:
            raise AssertionError("own-department reader must receive an audit scope")
        sql = str(
            select(GovernanceLedgerEvent.id)
            .where(clause)
            .compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )

        self.assertIn("EXISTS", sql)
        self.assertIn("wiki_pages.scope_type = 'global'", sql)
        self.assertIn("suggested_metadata ->> 'scope_type'", sql)
        self.assertIn(str(_DEPARTMENT_ID), sql)

    def test_admin_is_unrestricted_and_missing_wiki_permission_is_always_false(
        self,
    ) -> None:
        self.assertIsNone(governance_audit_scope_clause(_employee(role="admin")))

        with patch(
            "cygnus.runtime.services.permission_engine._get_user_permissions",
            return_value=set(),
        ):
            clause = governance_audit_scope_clause(_employee())
        self.assertIsNotNone(clause)
        if clause is None:
            raise AssertionError("reader without Wiki permission must be denied")
        sql = str(
            select(GovernanceLedgerEvent.id)
            .where(clause)
            .compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertIn("governance_ledger_events.id IS NULL", sql)

    def test_list_returns_deterministic_scoped_page(self) -> None:
        fake_session = AsyncMock()
        fake_session.execute.side_effect = [
            _ScalarResult(1),
            _RowsResult([(_event(), _draft(), _page(), _employee(role="admin"))]),
        ]

        result = asyncio.run(
            list_governance_audit_events(
                cast(AsyncSession, cast(object, fake_session)),
                current_user=_employee(department_ids=(_DEPARTMENT_ID,)),
                query=GovernanceAuditQuery(
                    phase=GovernanceAuditPhase.PUBLISH,
                    page=1,
                    page_size=10,
                    page_id=_PAGE_ID,
                ),
            )
        )

        self.assertEqual(result.total, 1)
        self.assertEqual(result.items[0].event_id, _EVENT_ID)
        statement = fake_session.execute.call_args_list[1].args[0]
        sql = str(statement.compile(dialect=postgresql.dialect()))
        self.assertIn("ORDER BY governance_ledger_events.recorded_at DESC", sql)
        self.assertIn("governance_ledger_events.id DESC", sql)


@final
class GovernanceAuditApiTests(unittest.TestCase):
    def api_client(self, *, authenticated: bool) -> TestClient:
        app = FastAPI()
        app.include_router(audit_router.router)
        if authenticated:
            user = _employee(role="admin")
            app.dependency_overrides[get_current_user] = lambda: user
            app.dependency_overrides[get_db] = lambda: AsyncMock()
        client = TestClient(app)
        self.addCleanup(client.close)
        self.addCleanup(app.dependency_overrides.clear)
        return client

    def test_audit_routes_require_authentication(self) -> None:
        client = self.api_client(authenticated=False)
        self.assertEqual(client.get("/api/governance/audit").status_code, 401)
        self.assertEqual(
            client.get(f"/api/governance/audit/{_EVENT_ID}").status_code,
            401,
        )

    def test_list_route_rejects_oversized_pages(self) -> None:
        client = self.api_client(authenticated=True)
        response = client.get("/api/governance/audit?page_size=101")

        self.assertEqual(response.status_code, 422)

    def test_list_route_serializes_durable_contract_and_filters(self) -> None:
        client = self.api_client(authenticated=True)
        page = GovernanceAuditPage(items=(_entry(),), total=1, page=1, page_size=10)
        with patch.object(
            audit_router,
            "list_governance_audit_events",
            AsyncMock(return_value=page),
        ) as list_events:
            response = client.get("/api/governance/audit?phase=publish&page_size=10")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["items"][0]["event_id"], str(_EVENT_ID))
        self.assertTrue(payload["persisted"])
        self.assertFalse(payload["rehearsal"])
        await_args = list_events.await_args
        if await_args is None:
            raise AssertionError("audit list service was not awaited")
        query = cast(GovernanceAuditQuery, await_args.kwargs["query"])
        self.assertIs(query.phase, GovernanceAuditPhase.PUBLISH)
        self.assertEqual(query.page_size, 10)

    def test_detail_route_returns_stable_trace_contract(self) -> None:
        client = self.api_client(authenticated=True)
        with patch.object(
            audit_router,
            "get_governance_audit_event",
            AsyncMock(return_value=_entry()),
        ):
            response = client.get(f"/api/governance/audit/{_EVENT_ID}")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["trace_ref"], f"governance-event:{_EVENT_ID}")
        self.assertTrue(payload["persisted"])
        self.assertFalse(payload["rehearsal"])

    def test_detail_route_hides_absent_and_out_of_scope_events(self) -> None:
        client = self.api_client(authenticated=True)
        with patch.object(
            audit_router,
            "get_governance_audit_event",
            AsyncMock(return_value=None),
        ):
            response = client.get(f"/api/governance/audit/{_EVENT_ID}")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "governance audit event not found")


if __name__ == "__main__":
    unittest.main()
