"""Rendering route behavior offline (no MySQL/Redis)."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_render_degrades_when_database_down() -> None:
    resp = client.post("/api/candidates/1/render")
    assert resp.status_code in (400, 404, 503)


def test_render_status_degrades_when_database_down() -> None:
    resp = client.get("/api/candidates/1/render")
    assert resp.status_code in (200, 503)


def test_render_file_degrades_when_database_down() -> None:
    resp = client.get("/api/renders/1/file")
    assert resp.status_code in (404, 503)
