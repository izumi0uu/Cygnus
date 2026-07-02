"""
Local Docker/dev stack bootstrap for Cygnus runtime infrastructure.

Ownership:
- local schema bootstrap for compose/dev stacks lives here
- this is a development convenience, not a replacement for production migrations
"""

import asyncio

from loguru import logger
from sqlalchemy import text

from cygnus.runtime.config import Settings, get_settings
from cygnus.runtime.database import create_engine_from_settings
from cygnus.runtime.database import models as _runtime_models  # noqa: F401
from cygnus.runtime.database import oauth_models as _oauth_models  # noqa: F401
from cygnus.runtime.database.models import Base
from cygnus.runtime.services.storage_service import StorageService


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
                "Waiting for local object storage to accept bucket bootstrap "
                f"({attempt}/{attempts}): {exc}"
            )
            await asyncio.sleep(delay_seconds)

    assert last_error is not None
    raise last_error


async def bootstrap_local_stack(app_settings: Settings | None = None) -> None:
    """Prepare the Postgres schema required by the local Docker stack."""
    resolved_settings = app_settings or get_settings()
    runtime_engine = create_engine_from_settings(resolved_settings)

    try:
        logger.info("Bootstrapping Cygnus local stack database schema...")
        async with runtime_engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.create_all)
        await _ensure_object_storage_ready(app_settings=resolved_settings)
        logger.success("Cygnus local stack database schema ready")
    finally:
        await runtime_engine.dispose()


def main() -> None:
    asyncio.run(bootstrap_local_stack())


if __name__ == "__main__":
    main()
