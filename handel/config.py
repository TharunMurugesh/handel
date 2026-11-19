"""Runtime settings, read from environment variables prefixed ``HANDEL_``.

Secrets live only in the environment (``.env`` locally, never committed).
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PROD_DEMO = "prod-demo"


class ModelMode(StrEnum):
    """How the LLM and speech ports behave (architecture §11.2, §12.4).

    - ``replay``: answer only from recorded fixtures; a missing fixture is an error.
      Default everywhere except when someone deliberately spends free-tier quota.
    - ``record``: call the live provider and save the answer as a fixture.
    - ``live``: call the live provider, save nothing.
    """

    REPLAY = "replay"
    RECORD = "record"
    LIVE = "live"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HANDEL_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    env: Environment = Environment.LOCAL
    database_url: str = "postgresql+asyncpg://handel:handel@localhost:5432/handel"
    model_mode: ModelMode = ModelMode.REPLAY
    fixtures_dir: Path = Path("tests/fixtures")

    worker_heartbeat_seconds: float = 30.0

    # Object storage (MinIO locally, Cloudflare R2 in the cloud).
    s3_endpoint_url: str = "http://localhost:9000"
    s3_bucket: str = "handel-media"
    s3_access_key: SecretStr = SecretStr("")
    s3_secret_key: SecretStr = SecretStr("")

    # External services. Empty until the accounts in docs/accounts.md exist.
    telegram_bot_token: SecretStr = SecretStr("")
    telegram_webhook_secret: SecretStr = SecretStr("")
    groq_api_key: SecretStr = SecretStr("")
    gemini_api_key: SecretStr = SecretStr("")
    openrouter_api_key: SecretStr = SecretStr("")
    sarvam_api_key: SecretStr = SecretStr("")


@lru_cache
def get_settings() -> Settings:
    return Settings()
