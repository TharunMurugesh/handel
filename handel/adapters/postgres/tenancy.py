"""Unit-scoped database sessions (architecture §5, §9: row-level security on ``unit_id``).

Inside ``unit_scope`` the transaction runs as ``handel_app`` with ``app.unit_id`` set, so
Postgres itself hides other units' rows and refuses writes for them. Both settings are
``LOCAL``: they end with the transaction, so a pooled connection never leaks a scope.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

APP_ROLE = "handel_app"


async def enter_unit_scope(conn: AsyncConnection, unit_id: str) -> None:
    if not unit_id:
        raise ValueError("unit_id is required")
    await conn.execute(text(f"SET LOCAL ROLE {APP_ROLE}"))
    await conn.execute(text("SELECT set_config('app.unit_id', :u, true)"), {"u": unit_id})


@asynccontextmanager
async def unit_scope(engine: AsyncEngine, unit_id: str) -> AsyncIterator[AsyncConnection]:
    async with engine.begin() as conn:
        await enter_unit_scope(conn, unit_id)
        yield conn
