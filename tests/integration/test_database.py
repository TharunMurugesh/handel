"""Needs a real Postgres: set HANDEL_TEST_DATABASE_URL (CI provides one)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from handel.adapters.postgres.db import SCHEMAS
from handel.config import Settings
from handel.interfaces.http.app import create_app

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]


def _alembic(database_url: str, *args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        check=True,
        cwd=REPO_ROOT,
        env={"HANDEL_DATABASE_URL": database_url, "PATH": ""},
    )


async def _schemas(database_url: str) -> set[str]:
    engine = create_async_engine(database_url)
    async with engine.connect() as conn:
        rows = await conn.execute(text("SELECT schema_name FROM information_schema.schemata"))
        names = {r[0] for r in rows}
    await engine.dispose()
    return names & set(SCHEMAS)


async def test_migrations_upgrade_and_downgrade_cleanly(database_url: str) -> None:
    _alembic(database_url, "downgrade", "base")
    assert await _schemas(database_url) == set()
    _alembic(database_url, "upgrade", "head")
    assert await _schemas(database_url) == set(SCHEMAS)
    _alembic(database_url, "downgrade", "base")
    assert await _schemas(database_url) == set()
    _alembic(database_url, "upgrade", "head")  # leave the database migrated


def test_readiness_is_ok_with_real_database(settings: Settings, database_url: str) -> None:
    with TestClient(create_app(settings.model_copy(update={"database_url": database_url}))) as c:
        r = c.get("/health/ready")
    assert r.status_code == 200
    assert r.json()["database"] == "ok"
