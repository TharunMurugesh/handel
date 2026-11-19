from __future__ import annotations

import os
from pathlib import Path

import pytest

from handel.config import Environment, ModelMode, Settings

UNREACHABLE_DB = "postgresql+asyncpg://nobody:nothing@127.0.0.1:1/none"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings that never touch a real database or live API."""
    return Settings(
        env=Environment.TEST,
        database_url=UNREACHABLE_DB,
        model_mode=ModelMode.REPLAY,
        fixtures_dir=tmp_path / "fixtures",
        worker_heartbeat_seconds=0.01,
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("HANDEL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("integration test: set HANDEL_TEST_DATABASE_URL")
    return url
