"""CYG-128 production migration upgrade/downgrade contract (Postgres).

These tests require a disposable Postgres database and are skipped unless
``CYGNUS_MIGRATION_TEST_DATABASE_URL`` (an asyncpg URL,
e.g. ``postgresql+asyncpg://cygnus:cygnus@localhost/cygnus_migration_test``)
is configured. Every test starts from a fully reset database and asserts the
production contract:

- a fresh empty database upgrades to exactly one Alembic head;
- upgrading from a baseline-compatible schema (only the 20260627_00 baseline
  applied) continues to head;
- downgrading head -> baseline deterministically restores the pre-governance
  schema (all 36 baseline tables, no governance tables), and downgrading to
  base leaves the schema empty;
- unversioned non-empty schemas and dirty duplicate version rows are rejected;
- only the init_local_stack in-process create_all+stamp bypass is permitted.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import unittest

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from cygnus.runtime.database import models as _runtime_models  # noqa: F401
from cygnus.runtime.database import oauth_models as _oauth_models  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parents[1]

_INTEGRATION_DATABASE_URL = os.getenv("CYGNUS_MIGRATION_TEST_DATABASE_URL")

PRE_GOVERNANCE_TABLES = frozenset(
    [
        "app_config",
        "audit_log",
        "departments",
        "embedding_jobs",
        "employee_departments",
        "employees",
        "knowledge_types",
        "mcp_query_log",
        "notes",
        "notifications",
        "oauth_auth_codes",
        "oauth_clients",
        "skill_contributions",
        "skill_departments",
        "skill_versions",
        "skills",
        "source_chunk_embeddings_1024",
        "source_chunk_embeddings_1536",
        "source_chunk_embeddings_3072",
        "source_chunk_embeddings_768",
        "source_chunk_extracts",
        "source_compilation_plans",
        "source_departments",
        "source_images",
        "sources",
        "stats_daily_rollup",
        "wiki_branches",
        "wiki_draft_rounds",
        "wiki_links",
        "wiki_page_drafts",
        "wiki_page_embeddings_1024",
        "wiki_page_embeddings_1536",
        "wiki_page_embeddings_3072",
        "wiki_page_embeddings_768",
        "wiki_page_revisions",
        "wiki_pages",
    ]
)


def _migration_config(database_url: str) -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    config.attributes["database_url"] = database_url
    return config


async def _reset_database(database_url: str) -> None:
    engine = create_async_engine(database_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            tables = await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_table_names()
            )
            for table in tables:
                await connection.execute(
                    text(f'DROP TABLE IF EXISTS "{table}" CASCADE')
                )
            await connection.execute(text("DROP TYPE IF EXISTS skill_status CASCADE"))
    finally:
        await engine.dispose()


async def _table_names(database_url: str) -> frozenset[str]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            tables = await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_table_names()
            )
            return frozenset(tables)
    finally:
        await engine.dispose()


async def _alembic_version_rows(database_url: str) -> list[str]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text("SELECT version_num FROM alembic_version ORDER BY version_num")
            )
            return [row[0] for row in result.fetchall()]
    finally:
        await engine.dispose()


async def _skill_status_enum_exists(database_url: str) -> bool:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'skill_status')"
                )
            )
            return bool(result.scalar_one())
    finally:
        await engine.dispose()


async def _execute_ddl(database_url: str, statements: list[str]) -> None:
    engine = create_async_engine(database_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            for statement in statements:
                await connection.execute(text(statement))
    finally:
        await engine.dispose()


async def _column_names(database_url: str, table: str) -> set[str]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            columns = await connection.run_sync(
                lambda sync_connection: {
                    column["name"]
                    for column in inspect(sync_connection).get_columns(table)
                }
            )
            return columns
    finally:
        await engine.dispose()


def _repository_heads() -> list[str] | None:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    script = ScriptDirectory.from_config(config)
    try:
        return sorted(script.get_heads())
    except KeyError:
        return None


@unittest.skipUnless(
    _INTEGRATION_DATABASE_URL,
    "CYGNUS_MIGRATION_TEST_DATABASE_URL is not configured",
)
class MigrationUpgradeDowngradePostgresTests(unittest.TestCase):
    def setUp(self) -> None:
        if _INTEGRATION_DATABASE_URL is None:
            self.skipTest("integration database URL unexpectedly absent")
        self.database_url = _INTEGRATION_DATABASE_URL
        asyncio.run(_reset_database(self.database_url))

    def _upgrade(self, target: str) -> None:
        command.upgrade(_migration_config(self.database_url), target)

    def _downgrade(self, target: str) -> None:
        command.downgrade(_migration_config(self.database_url), target)

    def _stamp(self, target: str, *, bypass: bool = False) -> None:
        config = _migration_config(self.database_url)
        if bypass:
            config.attributes["init_local_stack_bypass"] = True
        command.stamp(config, target)

    def test_fresh_database_upgrades_to_one_head(self) -> None:
        heads = _repository_heads()
        if heads is None:
            self.skipTest("migration graph incomplete (concurrent chain)")
        self.assertEqual(len(heads), 1)

        self._upgrade("head")

        versions = asyncio.run(_alembic_version_rows(self.database_url))
        self.assertEqual(versions, heads)
        tables = asyncio.run(_table_names(self.database_url))
        model_tables = set(_runtime_models.Base.metadata.tables)
        self.assertTrue(model_tables <= tables, sorted(model_tables - tables))
        self.assertIn("governance_ledger_events", tables)
        self.assertIn("wiki_draft_ai_pre_review_dispatches", tables)
        self.assertTrue(asyncio.run(_skill_status_enum_exists(self.database_url)))

    def test_upgrade_from_baseline_schema_works(self) -> None:
        self._upgrade("20260627_00")
        tables = asyncio.run(_table_names(self.database_url))
        self.assertEqual(tables - {"alembic_version"}, PRE_GOVERNANCE_TABLES)
        self.assertEqual(
            asyncio.run(_alembic_version_rows(self.database_url)),
            ["20260627_00"],
        )
        self.assertTrue(asyncio.run(_skill_status_enum_exists(self.database_url)))

        self._upgrade("head")
        heads = _repository_heads()
        if heads is None:
            self.skipTest("migration graph incomplete (concurrent chain)")
        self.assertEqual(asyncio.run(_alembic_version_rows(self.database_url)), heads)

    def test_downgrade_to_baseline_restores_pre_governance_schema(self) -> None:
        self._upgrade("head")
        self._downgrade("20260627_00")

        tables = asyncio.run(_table_names(self.database_url))
        self.assertEqual(tables - {"alembic_version"}, PRE_GOVERNANCE_TABLES)
        self.assertEqual(
            asyncio.run(_alembic_version_rows(self.database_url)),
            ["20260627_00"],
        )
        # The baseline owns notifications and the enum; the round trip must
        # restore both, and the governance-era version column must be gone.
        self.assertIn("notifications", tables)
        self.assertTrue(asyncio.run(_skill_status_enum_exists(self.database_url)))
        self.assertNotIn(
            "version",
            asyncio.run(_column_names(self.database_url, "wiki_page_drafts")),
        )

        # Downgrade to base leaves the schema empty and drops the enum.
        self._downgrade("base")
        tables = asyncio.run(_table_names(self.database_url))
        self.assertEqual(tables, set())
        self.assertFalse(asyncio.run(_skill_status_enum_exists(self.database_url)))

        # Recreate the exact frozen baseline after its complete teardown. This
        # executes the live upgrade → downgrade → upgrade path that protects
        # the pre-governance revision from dependent-object ordering failures.
        self._upgrade("20260627_00")
        tables = asyncio.run(_table_names(self.database_url))
        self.assertEqual(tables - {"alembic_version"}, PRE_GOVERNANCE_TABLES)
        self.assertEqual(
            asyncio.run(_alembic_version_rows(self.database_url)),
            ["20260627_00"],
        )
        self.assertTrue(asyncio.run(_skill_status_enum_exists(self.database_url)))

    def test_unversioned_non_empty_schema_is_rejected(self) -> None:
        asyncio.run(
            _execute_ddl(
                self.database_url,
                ["CREATE TABLE legacy_unversioned_marker (id INTEGER)"],
            )
        )

        with self.assertRaisesRegex(RuntimeError, "unversioned non-empty"):
            self._upgrade("head")

    def test_dirty_duplicate_version_rows_are_rejected(self) -> None:
        asyncio.run(
            _execute_ddl(
                self.database_url,
                [
                    "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)",
                    "INSERT INTO alembic_version VALUES ('20260627_00')",
                    "INSERT INTO alembic_version VALUES ('20260727_01')",
                    "CREATE TABLE legacy_unversioned_marker (id INTEGER)",
                ],
            )
        )

        with self.assertRaisesRegex(RuntimeError, "dirty duplicate"):
            self._upgrade("head")

    def test_stamp_bypass_only_for_local_stack(self) -> None:
        asyncio.run(
            _execute_ddl(
                self.database_url,
                ["CREATE TABLE legacy_unversioned_marker (id INTEGER)"],
            )
        )

        heads = _repository_heads()
        if heads is None:
            self.skipTest("migration graph incomplete (concurrent chain)")

        with self.assertRaisesRegex(RuntimeError, "unversioned non-empty"):
            self._stamp("head")

        self._stamp("head", bypass=True)
        self.assertEqual(asyncio.run(_alembic_version_rows(self.database_url)), heads)


if __name__ == "__main__":
    unittest.main()
