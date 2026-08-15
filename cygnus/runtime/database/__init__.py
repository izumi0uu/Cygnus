"""
SQLAlchemy async engine and session factory.
"""

from collections.abc import AsyncGenerator
from functools import lru_cache
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from cygnus.runtime.config import Settings, get_settings


def _record_pool_state(pool: Any, *, errors: int = 0) -> None:
    """Sample the live SQLAlchemy pool without exposing connection data."""
    try:
        from cygnus.observability import record_db_pool

        checked_out = float(pool.checkedout())
        pool_size = float(pool.size())
        overflow = float(pool.overflow())
        record_db_pool(
            pool="primary",
            checked_out=checked_out,
            checked_in=max(pool_size - checked_out, 0.0),
            overflow=max(overflow, 0.0),
            errors=errors,
        )
    except Exception:
        # Pool event hooks must never alter database acquisition semantics.
        return


def _instrument_engine_pool(runtime_engine: AsyncEngine) -> None:
    pool = runtime_engine.sync_engine.pool

    def _sample(*_args: object, **_kwargs: object) -> None:
        _record_pool_state(pool)

    def _sample_error(*_args: object, **_kwargs: object) -> None:
        _record_pool_state(pool, errors=1)

    event.listen(pool, "checkout", _sample)
    event.listen(pool, "checkin", _sample)
    event.listen(runtime_engine.sync_engine, "handle_error", _sample_error)


def create_engine_from_settings(
    app_settings: Settings | None = None,
) -> AsyncEngine:
    """Build the async engine from the resolved backend settings."""
    resolved_settings = app_settings or get_settings()
    runtime_engine = create_async_engine(
        resolved_settings.database_url,
        pool_size=20,
        max_overflow=10,
        pool_pre_ping=True,
        echo=False,
    )
    _instrument_engine_pool(runtime_engine)
    return runtime_engine


@lru_cache(maxsize=1)
def _build_cached_engine() -> AsyncEngine:
    return create_engine_from_settings()


def create_session_factory(
    runtime_engine: AsyncEngine | None = None,
) -> async_sessionmaker[AsyncSession]:
    """Build a session factory around the provided engine."""
    resolved_engine = runtime_engine or get_engine()
    return async_sessionmaker(
        resolved_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


@lru_cache(maxsize=1)
def _build_cached_async_session_factory() -> async_sessionmaker[AsyncSession]:
    return create_session_factory()


def get_engine() -> AsyncEngine:
    """Return the current shared async engine for runtime wiring."""
    return engine


def get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the current shared session factory for runtime wiring."""
    return async_session_factory


async def reset_database_runtime_wiring() -> None:
    """Dispose and rebuild the cached database runtime providers."""
    global engine, async_session_factory

    await engine.dispose()
    _build_cached_async_session_factory.cache_clear()
    _build_cached_engine.cache_clear()
    engine = _build_cached_engine()
    async_session_factory = _build_cached_async_session_factory()


engine = _build_cached_engine()
async_session_factory = _build_cached_async_session_factory()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields an async DB session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
