"""Integration fixtures: a migrated Postgres, truncated before every test."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ("core", "cases", "network", "privacy", "ops")
PHONE_ENC_KEY = "test-encryption-key-0123456789"
PHONE_HASH_KEY = "test-hash-key-abcdefghijklmnop"


@pytest.fixture(scope="session")
def migrated_url() -> str:
    import os

    url = os.environ.get("HANDEL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("integration test: set HANDEL_TEST_DATABASE_URL")
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        cwd=REPO_ROOT,
        env={"HANDEL_DATABASE_URL": url, "PATH": ""},
    )
    return url


async def truncate_all(conn: AsyncConnection) -> None:
    rows = await conn.execute(
        text("SELECT schemaname || '.' || tablename FROM pg_tables WHERE schemaname = ANY(:s)"),
        {"s": list(SCHEMAS)},
    )
    tables = [r[0] for r in rows]
    if tables:
        await conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def engine(migrated_url: str) -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(migrated_url)
    async with eng.begin() as conn:
        await truncate_all(conn)
    try:
        yield eng
    finally:
        await eng.dispose()


async def add_unit(conn: AsyncConnection, unit_id: str, name: str | None = None) -> None:
    await conn.execute(
        text(
            "INSERT INTO core.unit (id, name, itc_eligible, cost_of_money_monthly) "
            "VALUES (:id, :name, true, 0.015)"
        ),
        {"id": unit_id, "name": name or f"Demo unit {unit_id}"},
    )
