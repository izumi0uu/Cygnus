"""
Production object-storage bootstrap (CYG-128).

Narrow deploy-time step that ONLY validates the configured MinIO settings and
ensures the configured bucket exists. It deliberately never touches the
database schema: no ``create_all``, no alembic stamp, no admin seeding, no
adoption bypass. Schema is owned exclusively by ``alembic upgrade head``
(run by the same one-shot migrator, first).

Usage:
    python -m cygnus.runtime.bootstrap.ensure_storage
"""

from __future__ import annotations

import asyncio

from loguru import logger

from cygnus.runtime.config import Settings, get_settings
from cygnus.runtime.services.storage_service import StorageService

_REQUIRED_MINIO_SETTINGS = (
    "minio_endpoint",
    "minio_access_key",
    "minio_secret_key",
    "minio_bucket",
)


def validate_storage_settings(app_settings: Settings) -> None:
    """Fail fast when required object-storage settings are missing or empty."""
    missing = [
        name
        for name in _REQUIRED_MINIO_SETTINGS
        if not str(getattr(app_settings, name, "")).strip()
    ]
    if missing:
        raise RuntimeError(
            "production object-storage settings missing: " + ", ".join(sorted(missing))
        )


async def ensure_storage(
    *,
    app_settings: Settings | None = None,
    attempts: int = 20,
    delay_seconds: float = 2.0,
) -> None:
    """Validate settings and ensure the configured bucket exists (idempotent).

    Retries with a bounded backoff so the migrator tolerates MinIO being slow
    to accept connections right after container start; a persistent failure
    raises and aborts the deploy before any rollout.
    """
    resolved_settings = app_settings or get_settings()
    validate_storage_settings(resolved_settings)
    storage = StorageService(settings_provider=lambda: resolved_settings)

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            await storage.ensure_bucket()
            logger.success("Cygnus production object storage ready")
            return
        except Exception as exc:  # pragma: no cover - exercised via deploy gate
            last_error = exc
            logger.info(
                f"Waiting for object storage to accept bucket bootstrap "
                f"({attempt}/{attempts}): {exc}"
            )
            await asyncio.sleep(delay_seconds)

    assert last_error is not None
    raise last_error


def main() -> None:
    asyncio.run(ensure_storage())


if __name__ == "__main__":
    main()
