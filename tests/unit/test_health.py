from __future__ import annotations

from fastapi.testclient import TestClient

from handel import __version__
from handel.config import Settings
from handel.interfaces.http.app import create_app


def test_liveness_is_ok_even_without_database(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": __version__, "env": "test", "database": None}


def test_readiness_reports_503_when_database_unreachable(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        r = client.get("/health/ready")
    assert r.status_code == 503
    assert r.json()["status"] == "degraded"
    assert r.json()["database"] == "unreachable"
