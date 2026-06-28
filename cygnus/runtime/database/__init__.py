"""
SQLAlchemy async engine and session factory.
"""

from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from cygnus.runtime.config import Settings, get_settings


def create_engine_from_settings(
    app_settings: Settings | None = None,
) -> AsyncEngine:
    """Build the async engine from the resolved backend settings."""
    resolved_settings = app_settings or get_settings()
    return create_async_engine(
        resolved_settings.database_url,
        pool_size=20,
        max_overflow=10,
        pool_pre_ping=True,
        echo=False,
    )


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
