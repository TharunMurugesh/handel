"""Async database engine. Repositories, queue, outbox and timers arrive in P2."""

from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

# One schema per module (architecture §5).
SCHEMAS = ("core", "cases", "network", "privacy", "ops")


def make_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, pool_pre_ping=True, pool_size=5, max_overflow=5)


async def ping(engine: AsyncEngine, timeout_seconds: float = 2.0) -> bool:
    """True if the database answers ``SELECT 1`` within the timeout."""

    async def _probe() -> bool:
        async with engine.connect() as conn:
            value: object = (await conn.execute(text("SELECT 1"))).scalar_one()
            return value == 1

    try:
        return await asyncio.wait_for(_probe(), timeout_seconds)
    except Exception:
        return False
