"""Publishing route behavior offline (no MySQL/Redis)."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_youtube_connect_degrades_without_config() -> None:
    resp = client.post("/api/youtube/connect")
    assert resp.status_code in (400, 503)


def test_youtube_status_degrades_when_database_down() -> None:
    resp = client.get("/api/youtube/status")
    assert resp.status_code == 200


def test_publish_degrades_when_database_down() -> None:
    resp = client.post("/api/renders/1/publish", json={})
    assert resp.status_code in (400, 404, 503)


def test_publications_list_degrades_when_database_down() -> None:
    resp = client.get("/api/publications")
    assert resp.status_code in (200, 503)


def test_publication_detail_degrades_when_database_down() -> None:
    resp = client.get("/api/publications/1")
    assert resp.status_code in (404, 503)
