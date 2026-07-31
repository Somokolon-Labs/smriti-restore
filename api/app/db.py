"""Async engine / session wiring, dialect-portable between SQLite and Neon."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import settings

log = logging.getLogger(__name__)


def _engine_kwargs() -> dict[str, Any]:
    if settings.is_postgres:
        return {
            "pool_size": settings.db_pool_size,
            "max_overflow": settings.db_max_overflow,
            "pool_pre_ping": True,
            "pool_recycle": 300,
            # Neon's pooler does not support prepared statement caching.
            "connect_args": {"statement_cache_size": 0},
        }
    return {"connect_args": {"timeout": 30}}


engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
    **_engine_kwargs(),
)

SessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


if not settings.is_postgres:

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, rolled back on error."""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Create tables and indexes. Idempotent; safe on every boot."""
    from . import models

    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
    log.info("database ready (%s)", "postgres" if settings.is_postgres else "sqlite")


async def ping() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # pragma: no cover - surfaced via /health
        log.warning("database ping failed: %s", exc)
        return False


async def dispose_db() -> None:
    await engine.dispose()
