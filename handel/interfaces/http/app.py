"""API service (architecture §2.2). P0: health endpoints only."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, status
from pydantic import BaseModel

from handel import __version__
from handel.adapters.postgres.db import make_engine, ping
from handel.config import Settings, get_settings


class Health(BaseModel):
    status: str
    version: str
    env: str
    database: str | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = make_engine(settings.database_url)
        try:
            yield
        finally:
            await app.state.engine.dispose()

    app = FastAPI(title="Handel", version=__version__, lifespan=lifespan)

    @app.get("/health", response_model=Health)
    async def health() -> Health:
        """Liveness: the process is up. Never touches dependencies."""
        return Health(status="ok", version=__version__, env=settings.env.value)

    @app.get("/health/ready", response_model=Health)
    async def ready(request: Request, response: Response) -> Health:
        """Readiness: the database answers. 503 otherwise, so Caddy/compose can wait."""
        db_ok = await ping(request.app.state.engine)
        if not db_ok:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return Health(
            status="ok" if db_ok else "degraded",
            version=__version__,
            env=settings.env.value,
            database="ok" if db_ok else "unreachable",
        )

    return app
