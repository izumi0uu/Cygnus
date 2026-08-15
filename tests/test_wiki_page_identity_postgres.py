"""Postgres integration tests for CYG-130: canonical WikiPage identity.

Exercises the canonical insert-or-lock-and-version-update write path
(``wiki_service.write_page``), the DB-enforced nullable-global identity, and
the migration's dirty-duplicate diagnostic. These tests require a migrated
Postgres (``alembic upgrade head`` including 20260812_06) and are skipped
unless ``CYGNUS_WIKI_IDENTITY_TEST_DATABASE_URL`` is set.
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import os
from typing import cast
import unittest
import uuid

from sqlalchemy import delete, select, text as sa_text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cygnus.runtime.database.models import WikiPage, WikiPageRevision
from cygnus.runtime.services import wiki_service


_INTEGRATION_DATABASE_URL = os.getenv("CYGNUS_WIKI_IDENTITY_TEST_DATABASE_URL")


def _load_identity_migration():
    """Import the digit-prefixed migration module via importlib."""
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20260812_06_canonical_wiki_page_identity.py"
    )
    spec = importlib.util.spec_from_file_location("identity_migration_probe", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(
    _INTEGRATION_DATABASE_URL,
    "CYGNUS_WIKI_IDENTITY_TEST_DATABASE_URL is not configured",
)
class WikiPageIdentityPostgresTests(unittest.TestCase):
    def test_concurrent_divergent_writes_serialize(self) -> None:
        asyncio.run(self._concurrent_divergent_writes())

    def test_exact_retry_is_noop(self) -> None:
        asyncio.run(self._exact_retry_is_noop())

    def test_global_nullable_scope_identity_enforced(self) -> None:
        asyncio.run(self._global_nullable_scope_identity_enforced())

    def test_same_slug_different_scopes_coexist(self) -> None:
        asyncio.run(self._same_slug_different_scopes_coexist())

    def test_expected_version_conflict_raises(self) -> None:
        asyncio.run(self._expected_version_conflict_raises())

    def test_migration_duplicate_diagnostic(self) -> None:
        asyncio.run(self._migration_duplicate_diagnostic())

    async def _concurrent_divergent_writes(self) -> None:
        if _INTEGRATION_DATABASE_URL is None:
            raise AssertionError("integration database URL unexpectedly absent")
        engine = create_async_engine(_INTEGRATION_DATABASE_URL)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        unique = uuid.uuid4().hex
        slug = f"identity-race-{unique}"

        async def _writer(content: str) -> int:
            async with sessions() as session:
                outcome = await wiki_service.write_page(
                    session,
                    slug=slug,
                    title="Race page",
                    content_md=content,
                    summary="race",
                    knowledge_type_slugs=["concept"],
                    source_ids=[],
                    scope_type="global",
                    scope_id=None,
                )
                await session.commit()
                self.assertIsNotNone(outcome.page)
                assert outcome.page is not None
                return outcome.page.version

        try:
            versions = await asyncio.gather(
                _writer("# writer A"), _writer("# writer B")
            )
            self.assertEqual(sorted(versions), [1, 2])

            async with sessions() as session:
                page = await wiki_service.get_page_by_slug(session, slug)
                self.assertIsNotNone(page)
                page = cast(WikiPage, page)
                # One writer inserted (v1), the other locked and applied on top
                # (v2) — the final content is whichever writer serialized last.
                self.assertEqual(page.version, 2)
                self.assertIn(page.content_md, ("# writer A", "# writer B"))
                revisions = (
                    (
                        await session.execute(
                            select(WikiPageRevision)
                            .where(WikiPageRevision.page_id == page.id)
                            .order_by(WikiPageRevision.version)
                        )
                    )
                    .scalars()
                    .all()
                )
                self.assertEqual([r.version for r in revisions], [1, 2])
                self.assertEqual(
                    {r.content_md for r in revisions}, {"# writer A", "# writer B"}
                )
                rows = (
                    (
                        await session.execute(
                            select(WikiPage).where(WikiPage.slug == slug)
                        )
                    )
                    .scalars()
                    .all()
                )
                self.assertEqual(len(rows), 1, "concurrent writers created a duplicate")
        finally:
            await self._cleanup(engine, sessions, slug)

    async def _exact_retry_is_noop(self) -> None:
        if _INTEGRATION_DATABASE_URL is None:
            raise AssertionError("integration database URL unexpectedly absent")
        engine = create_async_engine(_INTEGRATION_DATABASE_URL)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        unique = uuid.uuid4().hex
        slug = f"identity-noop-{unique}"
        try:
            async with sessions() as session:
                first = await wiki_service.write_page(
                    session,
                    slug=slug,
                    title="No-op page",
                    content_md="# v1",
                    summary="s",
                    knowledge_type_slugs=[],
                    source_ids=[],
                    scope_type="global",
                    scope_id=None,
                )
                self.assertTrue(first.inserted)
                self.assertTrue(first.applied)
                await session.commit()
                assert first.page is not None
                self.assertEqual(first.page.version, 1)

                retry = await wiki_service.write_page(
                    session,
                    slug=slug,
                    title="No-op page",
                    content_md="# v1",
                    summary="s",
                    knowledge_type_slugs=[],
                    source_ids=[],
                    scope_type="global",
                    scope_id=None,
                )
                self.assertFalse(retry.inserted)
                self.assertFalse(retry.applied)
                assert retry.page is not None
                self.assertEqual(retry.page.version, 1)
                await session.commit()

                page = await wiki_service.get_page_by_slug(session, slug)
                self.assertIsNotNone(page)
                page = cast(WikiPage, page)
                self.assertEqual(page.version, 1)
                revisions = (
                    (
                        await session.execute(
                            select(WikiPageRevision).where(
                                WikiPageRevision.page_id == page.id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                self.assertEqual(len(revisions), 1)
                self.assertEqual(revisions[0].version, 1)
        finally:
            await self._cleanup(engine, sessions, slug)

    async def _global_nullable_scope_identity_enforced(self) -> None:
        if _INTEGRATION_DATABASE_URL is None:
            raise AssertionError("integration database URL unexpectedly absent")
        engine = create_async_engine(_INTEGRATION_DATABASE_URL)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        unique = uuid.uuid4().hex
        slug = f"identity-global-{unique}"
        try:
            async with sessions() as session:
                outcome = await wiki_service.write_page(
                    session,
                    slug=slug,
                    title="Global page",
                    content_md="# g",
                    summary="",
                    knowledge_type_slugs=[],
                    source_ids=[],
                    scope_type="global",
                    scope_id=None,
                )
                await session.commit()
                self.assertTrue(outcome.inserted)

            # A raw duplicate INSERT with the same identity (scope_id IS NULL)
            # must be rejected by the partial unique index covering the
            # nullable global scope.
            async with sessions() as session:
                with self.assertRaises(IntegrityError):
                    await session.execute(
                        pg_insert(WikiPage).values(
                            slug=slug,
                            title="Dup",
                            status="seed",
                            content_md="# dup",
                            summary="",
                            knowledge_type_slugs=[],
                            source_ids=[],
                            scope_type="global",
                            scope_id=None,
                            language="en",
                            normalized_path=wiki_service.normalize_page_path(slug),
                            version=1,
                        )
                    )
                    await session.commit()
                await session.rollback()

            # Service-level: a divergent second write on the same identity
            # updates the row — it never creates a duplicate.
            async with sessions() as session:
                second = await wiki_service.write_page(
                    session,
                    slug=slug,
                    title="Global page",
                    content_md="# g2",
                    summary="",
                    knowledge_type_slugs=[],
                    source_ids=[],
                    scope_type="global",
                    scope_id=None,
                )
                self.assertFalse(second.inserted)
                self.assertTrue(second.applied)
                await session.commit()
                rows = (
                    (
                        await session.execute(
                            select(WikiPage).where(WikiPage.slug == slug)
                        )
                    )
                    .scalars()
                    .all()
                )
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].version, 2)
        finally:
            await self._cleanup(engine, sessions, slug)

    async def _same_slug_different_scopes_coexist(self) -> None:
        if _INTEGRATION_DATABASE_URL is None:
            raise AssertionError("integration database URL unexpectedly absent")
        engine = create_async_engine(_INTEGRATION_DATABASE_URL)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        unique = uuid.uuid4().hex
        slug = f"identity-scopes-{unique}"
        project_id = uuid.uuid4()
        try:
            async with sessions() as session:
                global_outcome = await wiki_service.write_page(
                    session,
                    slug=slug,
                    title="Global",
                    content_md="# g",
                    summary="",
                    knowledge_type_slugs=[],
                    source_ids=[],
                    scope_type="global",
                    scope_id=None,
                )
                project_outcome = await wiki_service.write_page(
                    session,
                    slug=slug,
                    title="Project",
                    content_md="# p",
                    summary="",
                    knowledge_type_slugs=[],
                    source_ids=[],
                    scope_type="project",
                    scope_id=project_id,
                )
                await session.commit()
                self.assertTrue(global_outcome.inserted)
                self.assertTrue(project_outcome.inserted)

                global_page = await wiki_service.get_page_by_slug(
                    session, slug, scope_type="global", scope_id=None
                )
                project_page = await wiki_service.get_page_by_slug(
                    session, slug, scope_type="project", scope_id=project_id
                )
                self.assertIsNotNone(global_page)
                self.assertIsNotNone(project_page)
                assert global_page is not None
                assert project_page is not None
                self.assertNotEqual(global_page.id, project_page.id)
        finally:
            await self._cleanup(engine, sessions, slug)

    async def _expected_version_conflict_raises(self) -> None:
        if _INTEGRATION_DATABASE_URL is None:
            raise AssertionError("integration database URL unexpectedly absent")
        engine = create_async_engine(_INTEGRATION_DATABASE_URL)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        unique = uuid.uuid4().hex
        slug = f"identity-version-{unique}"
        try:
            async with sessions() as session:
                await wiki_service.write_page(
                    session,
                    slug=slug,
                    title="V",
                    content_md="# 1",
                    summary="",
                    knowledge_type_slugs=[],
                    source_ids=[],
                    scope_type="global",
                    scope_id=None,
                )
                await session.commit()

            async with sessions() as session:
                await wiki_service.write_page(
                    session,
                    slug=slug,
                    title="V",
                    content_md="# 2",
                    summary="",
                    knowledge_type_slugs=[],
                    source_ids=[],
                    scope_type="global",
                    scope_id=None,
                    expected_version=1,
                )
                await session.commit()

            # A write carrying a stale expected_version must fail loudly
            # instead of clobbering the committed version.
            async with sessions() as session:
                with self.assertRaises(wiki_service.PageWriteConflict):
                    await wiki_service.write_page(
                        session,
                        slug=slug,
                        title="V",
                        content_md="# 3",
                        summary="",
                        knowledge_type_slugs=[],
                        source_ids=[],
                        scope_type="global",
                        scope_id=None,
                        expected_version=1,
                    )
                await session.rollback()
        finally:
            await self._cleanup(engine, sessions, slug)

    async def _migration_duplicate_diagnostic(self) -> None:
        if _INTEGRATION_DATABASE_URL is None:
            raise AssertionError("integration database URL unexpectedly absent")
        module = _load_identity_migration()
        engine = create_async_engine(_INTEGRATION_DATABASE_URL)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with sessions() as session:
                await session.execute(
                    sa_text(
                        "CREATE TEMP TABLE wiki_pages_identity_probe ("
                        "  scope_type varchar(20) NOT NULL,"
                        "  scope_id uuid,"
                        "  language varchar(10) NOT NULL,"
                        "  normalized_path varchar(300) NOT NULL"
                        ") ON COMMIT DROP"
                    )
                )
                project_id = uuid.uuid4()
                rows = [
                    ("global", None, "en", "dup"),  # dirty duplicate (NULL scope_id)
                    ("global", None, "en", "dup"),
                    ("global", None, "en", "dup"),  # triple group
                    ("project", project_id, "en", "dup"),  # dirty duplicate (scoped)
                    ("project", project_id, "en", "dup"),
                    ("project", project_id, "en", "ok"),  # clean singleton
                ]
                for scope_type, scope_id, language, path in rows:
                    await session.execute(
                        sa_text(
                            "INSERT INTO wiki_pages_identity_probe "
                            "(scope_type, scope_id, language, normalized_path) "
                            "VALUES (:st, :sid, :lang, :path)"
                        ),
                        {
                            "st": scope_type,
                            "sid": scope_id,
                            "lang": language,
                            "path": path,
                        },
                    )
                groups = cast(
                    list[tuple[str, str, str, str, int]],
                    (await session.connection()).run_sync(
                        lambda conn: module._duplicate_identity_groups(
                            conn, "wiki_pages_identity_probe"
                        )
                    ),
                )
                by_key = {(st, sid, lang, path): n for st, sid, lang, path, n in groups}
                self.assertEqual(by_key.get(("global", "<global>", "en", "dup")), 3)
                self.assertEqual(
                    by_key.get(("project", str(project_id), "en", "dup")), 2
                )
                self.assertNotIn(("project", str(project_id), "en", "ok"), by_key)

                diagnostic = module._duplicate_diagnostic(groups)
                self.assertIn("migration blocked", diagnostic)
                self.assertIn("normalized_path='dup'", diagnostic)
                self.assertIn("scope_id='<global>'", diagnostic)
                self.assertIn("are NOT created", diagnostic)
                await session.rollback()
        finally:
            await engine.dispose()

    async def _cleanup(self, engine, sessions, slug: str) -> None:
        try:
            async with sessions() as session:
                page_ids = (
                    (
                        await session.execute(
                            select(WikiPage.id).where(WikiPage.slug == slug)
                        )
                    )
                    .scalars()
                    .all()
                )
                if page_ids:
                    await session.execute(
                        delete(WikiPageRevision).where(
                            WikiPageRevision.page_id.in_(tuple(page_ids))
                        )
                    )
                    await session.execute(
                        delete(WikiPage).where(WikiPage.id.in_(tuple(page_ids)))
                    )
                await session.commit()
        finally:
            await engine.dispose()


if __name__ == "__main__":
    _ = unittest.main()
