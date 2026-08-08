"""
Local Docker/dev stack bootstrap for Cygnus runtime infrastructure.

Ownership:
- local schema bootstrap for compose/dev stacks lives here
- this is a development convenience, not a replacement for production migrations
"""

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config

from loguru import logger
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from cygnus.runtime.config import Settings, get_settings
from cygnus.runtime.database import create_engine_from_settings
from cygnus.runtime.database import models as _runtime_models  # noqa: F401
from cygnus.runtime.database import oauth_models as _oauth_models  # noqa: F401

from cygnus.runtime.services.storage_service import StorageService

Base = _runtime_models.Base
_oauth_model_registration = _oauth_models.OAuthClient


async def _ensure_object_storage_ready(
    *,
    app_settings: Settings,
    attempts: int = 20,
    delay_seconds: float = 2.0,
) -> None:
    """Create the default MinIO bucket for the local stack.

    The compose stack only needs one bootstrap authority for bucket creation.
    Keeping it here avoids a separate init-sidecar container while preserving a
    clear dev-stack recovery point.
    """
    storage = StorageService(settings_provider=lambda: app_settings)

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            await storage.ensure_bucket()
            logger.success("Cygnus local stack object storage ready")
            return
        except Exception as exc:  # pragma: no cover - exercised via compose smoke
            last_error = exc
            logger.info(
                f"Waiting for local object storage to accept bucket bootstrap ({attempt}/{attempts}): {exc}"
            )
            await asyncio.sleep(delay_seconds)

    assert last_error is not None
    raise last_error


def _migration_config(app_settings: Settings) -> Config:
    repository_root = Path(__file__).resolve().parents[3]
    config = Config(str(repository_root / "alembic.ini"))
    config.set_main_option("script_location", str(repository_root / "migrations"))
    config.attributes["database_url"] = app_settings.database_url
    return config


def _has_existing_application_schema(connection: Connection) -> bool:
    return inspect(connection).has_table("wiki_page_drafts")


def _upgrade_existing_schema(connection: Connection, config: Config) -> None:
    config.attributes["connection"] = connection
    command.upgrade(config, "head")


def _stamp_fresh_schema(connection: Connection, config: Config) -> None:
    config.attributes["connection"] = connection
    command.stamp(config, "head")


async def bootstrap_local_stack(app_settings: Settings | None = None) -> None:
    """Prepare the Postgres schema required by the local Docker stack."""
    resolved_settings = app_settings or get_settings()
    migration_config = _migration_config(resolved_settings)
    runtime_engine = create_engine_from_settings(resolved_settings)

    try:
        logger.info("Bootstrapping Cygnus local stack database schema...")
        async with runtime_engine.begin() as conn:
            _ = await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            has_existing_schema = await conn.run_sync(_has_existing_application_schema)
            if has_existing_schema:
                await conn.run_sync(_upgrade_existing_schema, migration_config)
                # Local/dev keeps create_all as a convenience for unrelated
                # substrate tables that predate the migration baseline.
                await conn.run_sync(Base.metadata.create_all)
            else:
                await conn.run_sync(Base.metadata.create_all)
                await conn.run_sync(_stamp_fresh_schema, migration_config)
        await _ensure_object_storage_ready(app_settings=resolved_settings)
        logger.success("Cygnus local stack database schema ready")
    finally:
        await runtime_engine.dispose()


def main() -> None:
    asyncio.run(bootstrap_local_stack())


if __name__ == "__main__":
    main()
