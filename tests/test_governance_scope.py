from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import cast
import unittest
from unittest.mock import patch
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.elements import ColumnElement

from cygnus.retrieval import (
    SubstrateKnowledgeSnapshot,
    sample_knowledge_objects,
    sample_support_evidence,
)
from cygnus.runtime.database.models import Employee, Source, WikiPage, WikiPageDraft
from cygnus.runtime.routers.governance.knowledge_graph import (
    knowledge_graph,
    traceability,
)
from cygnus.runtime.services.permission_engine import (
    build_document_scope_clause,
    build_wiki_draft_scope_clause,
    build_wiki_scope_clause,
    can_access_document,
)


DEPARTMENT_ID = UUID("11111111-1111-1111-1111-111111111111")
OTHER_DEPARTMENT_ID = UUID("22222222-2222-2222-2222-222222222222")


def scoped_employee(
    *,
    role: str = "employee",
    global_role: str = "viewer",
    department_ids: tuple[UUID, ...] = (),
) -> Employee:
    return cast(
        Employee,
        cast(
            object,
            SimpleNamespace(
                role=role,
                global_role=global_role,
                department_ids=list(department_ids),
            ),
        ),
    )


def compile_clause(
    table: type[Source] | type[WikiPage] | type[WikiPageDraft],
    clause: ColumnElement[bool] | None,
) -> str:
    if clause is None:
        raise AssertionError("expected a restrictive SQL clause")
    return str(
        select(table.id)
        .where(clause)
        .compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


class GovernanceScopeTests(unittest.TestCase):
    def test_admin_and_all_roles_have_unrestricted_sql_scope(self) -> None:
        admin = scoped_employee(role="admin")
        manager = scoped_employee(global_role="knowledge_manager")

        for user in (admin, manager):
            with self.subTest(user=user.role, global_role=user.global_role):
                self.assertIsNone(build_wiki_scope_clause(user))
                self.assertIsNone(build_document_scope_clause(user))

    def test_own_department_scope_keeps_global_and_matching_resources(self) -> None:
        user = scoped_employee(department_ids=(DEPARTMENT_ID,))
        wiki_sql = compile_clause(WikiPage, build_wiki_scope_clause(user))
        source_sql = compile_clause(Source, build_document_scope_clause(user))

        self.assertIn("wiki_pages.scope_type = 'global'", wiki_sql)
        self.assertIn(str(DEPARTMENT_ID), wiki_sql)
        self.assertIn("NOT (EXISTS", source_sql)
        self.assertIn(str(DEPARTMENT_ID), source_sql)

    def test_own_department_user_without_departments_sees_only_global_rows(
        self,
    ) -> None:
        user = scoped_employee()
        wiki_sql = compile_clause(WikiPage, build_wiki_scope_clause(user))
        source_sql = compile_clause(Source, build_document_scope_clause(user))

        self.assertIn("wiki_pages.scope_type = 'global'", wiki_sql)
        self.assertIn("wiki_pages.id IS NULL", wiki_sql)
        self.assertIn("NOT (EXISTS", source_sql)
        self.assertNotIn("source_departments.department_id IN", source_sql)

    def test_malformed_department_scope_is_not_reclassified_as_global(self) -> None:
        user = scoped_employee(department_ids=(OTHER_DEPARTMENT_ID,))
        source_sql = compile_clause(Source, build_document_scope_clause(user))

        self.assertIn("sources.scope_type = 'global'", source_sql)
        self.assertIn("sources.scope_id IS NULL", source_sql)
        self.assertIn("source_departments.department_id = sources.scope_id", source_sql)

        class _Result:
            def __init__(self, department_ids: tuple[UUID, ...]) -> None:
                self._department_ids = department_ids

            def all(self) -> list[tuple[UUID]]:
                return [(department_id,) for department_id in self._department_ids]

        class _Session:
            def __init__(self, department_ids: tuple[UUID, ...]) -> None:
                self._department_ids = department_ids

            async def execute(self, _statement):
                return _Result(self._department_ids)

        async def can_read(
            *,
            scope_type: str,
            scope_id: UUID | None,
            links: tuple[UUID, ...],
        ) -> bool:
            source = SimpleNamespace(
                id=UUID("33333333-3333-3333-3333-333333333333"),
                scope_type=scope_type,
                scope_id=scope_id,
            )
            with patch(
                "cygnus.runtime.services.permission_engine._get_user_permissions",
                return_value={"doc:read:own_dept"},
            ):
                return await can_access_document(
                    cast(AsyncSession, cast(object, _Session(links))),
                    user,
                    cast(Source, cast(object, source)),
                )

        malformed_unlinked = asyncio.run(
            can_read(scope_type="department", scope_id=DEPARTMENT_ID, links=())
        )
        malformed_mismatched = asyncio.run(
            can_read(
                scope_type="department",
                scope_id=DEPARTMENT_ID,
                links=(OTHER_DEPARTMENT_ID,),
            )
        )
        valid_multidepartment = asyncio.run(
            can_read(
                scope_type="department",
                scope_id=DEPARTMENT_ID,
                links=(DEPARTMENT_ID, OTHER_DEPARTMENT_ID),
            )
        )
        valid_global = asyncio.run(
            can_read(scope_type="global", scope_id=None, links=())
        )

        self.assertFalse(malformed_unlinked)
        self.assertFalse(malformed_mismatched)
        self.assertTrue(valid_multidepartment)
        self.assertTrue(valid_global)

    def test_user_without_permissions_gets_always_false_scope(self) -> None:
        user = scoped_employee(global_role="viewer")
        with patch(
            "cygnus.runtime.services.permission_engine._get_user_permissions",
            return_value=set(),
        ):
            wiki_sql = compile_clause(WikiPage, build_wiki_scope_clause(user))
            source_sql = compile_clause(Source, build_document_scope_clause(user))
        self.assertIn("wiki_pages.id IS NULL", wiki_sql)
        self.assertIn("sources.id IS NULL", source_sql)

    def test_staged_draft_scope_filters_before_projection(self) -> None:
        user = scoped_employee(department_ids=(DEPARTMENT_ID,))
        clause = build_wiki_draft_scope_clause(user, action="read")
        self.assertIsNotNone(clause)
        if clause is None:
            raise AssertionError("own-department reader must receive a draft scope")
        sql = str(
            select(WikiPageDraft.id)
            .where(clause)
            .compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertIn("wiki_page_drafts.suggested_metadata", sql)
        self.assertIn("wiki_pages.scope_type = 'global'", sql)
        self.assertIn(str(DEPARTMENT_ID), sql)

    def test_graph_keeps_object_and_evidence_planes_separate(self) -> None:
        snapshot = SubstrateKnowledgeSnapshot(
            objects=sample_knowledge_objects(),
            evidence=sample_support_evidence(),
        )
        payload = asyncio.run(knowledge_graph(snapshot=snapshot))
        nodes = cast(list[dict[str, str]], payload["nodes"])
        edges = cast(list[dict[str, str]], payload["edges"])
        kinds = {node["kind"] for node in nodes}
        self.assertTrue({"object", "evidence", "audience"}.issubset(kinds))
        self.assertTrue(any(edge["kind"] == "cites" for edge in edges))
        self.assertTrue(any(edge["kind"] == "serves" for edge in edges))

    def test_hidden_and_absent_traceability_are_indistinguishable_after_scoping(
        self,
    ) -> None:
        empty_snapshot = SubstrateKnowledgeSnapshot(objects=(), evidence=())
        details: list[str] = []
        for object_id in ("does-not-exist", "scope-hidden-object"):
            with self.subTest(object_id=object_id):
                with self.assertRaises(HTTPException) as raised:
                    _ = asyncio.run(
                        traceability(object_id=object_id, snapshot=empty_snapshot)
                    )
                self.assertEqual(raised.exception.status_code, 404)
                details.append(str(raised.exception.detail).replace(object_id, "<ref>"))
        self.assertEqual(details[0], details[1])
