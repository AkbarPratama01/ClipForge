"""Analysis route behavior offline (no MySQL/Redis)."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_analyze_degrades_when_database_down() -> None:
    resp = client.post("/api/videos/1/analyze")
    assert resp.status_code in (400, 404, 503)


def test_candidates_degrades_when_database_down() -> None:
    resp = client.get("/api/videos/1/candidates")
    assert resp.status_code in (400, 404, 503)


def test_approve_degrades_when_database_down() -> None:
    resp = client.post("/api/candidates/1/approve")
    assert resp.status_code in (404, 503)


def test_reject_degrades_when_database_down() -> None:
    resp = client.post("/api/candidates/1/reject")
    assert resp.status_code in (404, 503)
