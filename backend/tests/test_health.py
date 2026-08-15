"""Health endpoint tests. Dependency probes are monkeypatched so the suite
runs without MySQL/Redis."""

from fastapi.testclient import TestClient

from app.api import routes_health as health
from app.main import app

client = TestClient(app)


def test_liveness_healthz() -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_all_ok(monkeypatch) -> None:
    monkeypatch.setattr(health, "check_mysql", lambda: (True, 3.2))
    monkeypatch.setattr(health, "check_redis", lambda: (True, 1.1))

    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["services"]["mysql"]["status"] == "ok"
    assert body["services"]["redis"]["status"] == "ok"
    assert body["version"]


def test_health_degraded_when_dependency_down(monkeypatch) -> None:
    monkeypatch.setattr(health, "check_mysql", lambda: (False, None))
    monkeypatch.setattr(health, "check_redis", lambda: (True, 0.9))

    resp = client.get("/api/health")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["services"]["mysql"]["status"] == "error"
