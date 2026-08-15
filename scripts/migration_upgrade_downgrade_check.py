"""Production migration upgrade/downgrade check (CYG-128).

Verifies the governed database contract against a disposable Postgres
database:

1. a fresh empty database upgrades to exactly one Alembic head;
2. the resulting schema contains every runtime model table;
3. downgrade head -> pre-governance baseline (20260627_00) deterministically
   restores the frozen pre-governance schema (36 tables + skill_status enum,
   no governance tables) — proving the downgrade is safe and explicit;
4. downgrade to base leaves the schema empty and drops the enum;
5. upgrade head -> head round-trip leaves the database at the head.

The database is left at the head revision on success.

Usage:
    python -m scripts.migration_upgrade_downgrade_check \
        --database-url postgresql+asyncpg://cygnus:cygnus@localhost/cygnus_check

The target database is DESTROYED (all public tables dropped) before running;
it must be a disposable database.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from cygnus.runtime.database import models as _runtime_models  # noqa: F401
from cygnus.runtime.database import oauth_models as _oauth_models  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_REVISION = "20260627_00"

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


class MigrationCheckError(RuntimeError):
    """Raised when a migration check step fails."""


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
                    "SELECT EXISTS (SELECT 1 FROM pg_type "
                    "WHERE typname = 'skill_status')"
                )
            )
            return bool(result.scalar_one())
    finally:
        await engine.dispose()


def _repository_heads() -> tuple[str, ...]:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    script = ScriptDirectory.from_config(config)
    heads = tuple(sorted(script.get_heads()))
    if not heads:
        raise MigrationCheckError("migration graph exposes no head")
    if len(heads) != 1:
        raise MigrationCheckError(f"migration graph exposes multiple heads: {heads}")
    return heads


def run_check(database_url: str) -> None:
    heads = _repository_heads()
    asyncio.run(_reset_database(database_url))
    config = _migration_config(database_url)

    # 1. Fresh empty database upgrades to exactly one head.
    command.upgrade(config, "head")
    versions = asyncio.run(_alembic_version_rows(database_url))
    if versions != list(heads):
        raise MigrationCheckError(
            f"after fresh upgrade, alembic_version is {versions}, expected {heads}"
        )

    # 2. The head schema contains every runtime model table.
    tables = asyncio.run(_table_names(database_url))
    model_tables = set(_runtime_models.Base.metadata.tables)
    missing_model_tables = model_tables - set(tables)
    if missing_model_tables:
        raise MigrationCheckError(
            f"head schema is missing model tables: {sorted(missing_model_tables)}"
        )

    # 3. Downgrade head -> baseline restores the frozen pre-governance schema.
    command.downgrade(config, BASELINE_REVISION)
    tables = asyncio.run(_table_names(database_url))
    if tables - {"alembic_version"} != PRE_GOVERNANCE_TABLES:
        unexpected = sorted((tables - {"alembic_version"}) - PRE_GOVERNANCE_TABLES)
        missing = sorted(PRE_GOVERNANCE_TABLES - (tables - {"alembic_version"}))
        raise MigrationCheckError(
            f"downgrade to baseline left unexpected tables {unexpected} "
            f"and is missing {missing}"
        )
    if asyncio.run(_alembic_version_rows(database_url)) != [BASELINE_REVISION]:
        raise MigrationCheckError(
            f"downgrade to baseline did not land on {BASELINE_REVISION}"
        )
    if not asyncio.run(_skill_status_enum_exists(database_url)):
        raise MigrationCheckError("baseline downgrade dropped the skill_status enum")

    # 4. Downgrade to base leaves the schema empty and drops the enum.
    command.downgrade(config, "base")
    if asyncio.run(_table_names(database_url)):
        raise MigrationCheckError("downgrade to base left application tables behind")
    if asyncio.run(_skill_status_enum_exists(database_url)):
        raise MigrationCheckError("downgrade to base left the skill_status enum behind")

    # 5. Upgrade back to head (leave the database in the useful governed state).
    command.upgrade(config, "head")
    versions = asyncio.run(_alembic_version_rows(database_url))
    if versions != list(heads):
        raise MigrationCheckError(
            f"final upgrade left alembic_version at {versions}, expected {heads}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify the governed production migration contract: fresh upgrade to "
            "one head, baseline-compatible round trip, and deterministic "
            "downgrade to baseline and base."
        )
    )
    parser.add_argument(
        "--database-url",
        required=True,
        help=(
            "Disposable asyncpg Postgres URL to check against "
            "(postgresql+asyncpg://...). Its contents are destroyed."
        ),
    )
    parser.add_argument("--quiet", action="store_true", help="Only return exit status.")
    args = parser.parse_args()

    try:
        run_check(args.database_url)
    except Exception as exc:  # noqa: BLE001
        if not args.quiet:
            print(f"FAIL: {exc}")
        return 1
    if not args.quiet:
        print("PASS: fresh upgrade, baseline round trip, and downgrade all verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
