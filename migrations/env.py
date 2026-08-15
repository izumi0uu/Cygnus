from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import cast

from alembic import context
from sqlalchemy import inspect, text
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from cygnus.runtime.config import get_settings
from cygnus.runtime.database import models as _runtime_models  # noqa: F401
from cygnus.runtime.database import oauth_models as _oauth_models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

runtime_database_url = (
    config.attributes.get("database_url") or get_settings().database_url
)
config.set_main_option(
    "sqlalchemy.url",
    str(runtime_database_url).replace("%", "%%"),
)
target_metadata = _runtime_models.Base.metadata
_oauth_model_registration = _oauth_models.OAuthClient

# Narrow, opt-in bypass marker. Only the local-stack bootstrap
# (cygnus.runtime.bootstrap.init_local_stack) sets this, and only for its
# in-process `Base.metadata.create_all` + `alembic stamp head` flow on a fresh
# database. Every other migration or stamp run must start from a governed
# (versioned) schema; an unversioned non-empty schema is refused.
INIT_LOCAL_STACK_BYPASS_ATTRIBUTE = "init_local_stack_bypass"

# Postgres alembic_version table name; excluded from the "has application
# tables?" determination.
ALEMBIC_VERSION_TABLE = "alembic_version"


class MigrationSchemaError(RuntimeError):
    """Raised when a migration run targets a schema whose version state cannot
    be trusted (unversioned non-empty, or dirty/duplicate version rows)."""


def _guard_schema_state(connection: Connection) -> None:
    """Reject migration runs that could hide drift on an ungoverned schema.

    Applies to both ``upgrade``/``downgrade`` and ``stamp``, because every
    online Alembic command executes this env module. Offline (``--sql``) mode
    cannot inspect a database and is intentionally not guarded.

    The guard is read-only. Its introspection queries autobegin an implicit
    transaction; if that were left open, Alembic would treat the connection as
    externally transactioned and never commit the migrations. The transaction
    is therefore ended before returning, unless the caller had already opened
    one (e.g. the local-stack bootstrap's ``begin()`` context) — in that case
    the caller owns commit/rollback and the guard must not touch it.
    """
    was_in_transaction = connection.in_transaction()
    try:
        inspector = inspect(connection)
        table_names = set(inspector.get_table_names())
        has_version_table = ALEMBIC_VERSION_TABLE in table_names
        app_tables = table_names - {ALEMBIC_VERSION_TABLE}

        if has_version_table:
            version_row_count = int(
                connection.execute(
                    text(f"SELECT COUNT(*) FROM {ALEMBIC_VERSION_TABLE}")
                ).scalar_one()
            )
            if version_row_count > 1:
                raise MigrationSchemaError(
                    f"schema contains {version_row_count} rows in "
                    f"{ALEMBIC_VERSION_TABLE}; refusing to run migrations on a "
                    "schema with dirty duplicate version entries. Reconcile the "
                    "version table before migrating."
                )
            if version_row_count == 0 and app_tables:
                raise MigrationSchemaError(
                    "schema contains application tables but "
                    f"{ALEMBIC_VERSION_TABLE} is empty; refusing to run "
                    "migrations on an unversioned schema. Recreate the database "
                    "from an empty state (e.g. `docker compose down -v` for "
                    "local stacks) or restore from a governed backup."
                )
            return

        if not app_tables:
            return

        bypass = config.attributes.get(INIT_LOCAL_STACK_BYPASS_ATTRIBUTE) is True
        if not bypass:
            raise MigrationSchemaError(
                "schema contains application tables but no "
                f"{ALEMBIC_VERSION_TABLE} table; refusing to run migrations on "
                "an unversioned non-empty schema. Adopting a schema by stamping "
                "cannot hide drift: recreate the database from an empty state "
                "(e.g. `docker compose down -v` for local stacks) or restore "
                "from a governed backup. The only permitted in-process "
                "create_all+stamp bypass is the local-stack bootstrap "
                "(cygnus.runtime.bootstrap.init_local_stack)."
            )
    finally:
        if not was_in_transaction and connection.in_transaction():
            connection.rollback()


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection: Connection) -> None:
    _guard_schema_state(connection)
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    supplied_connection = cast(Connection | None, config.attributes.get("connection"))
    if supplied_connection is not None:
        _run_migrations(supplied_connection)
        return
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
