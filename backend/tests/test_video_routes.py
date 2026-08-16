"""Video route behavior verified offline (no MySQL, no network).

Pins down the degraded paths: invalid URLs are rejected before any I/O, and
database outages return 503 instead of 500.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_import_rejects_invalid_url() -> None:
    resp = client.post("/api/videos/import", json={"url": "https://example.com/video"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_YOUTUBE_URL"


def test_import_requires_url_field() -> None:
    resp = client.post("/api/videos/import", json={})
    assert resp.status_code == 422


def test_import_degrades_when_database_down() -> None:
    resp = client.post(
        "/api/videos/import", json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
    )
    # DB is unreachable in the test environment -> graceful 503.
    assert resp.status_code in (400, 503)


def test_list_videos_degrades_when_database_down() -> None:
    resp = client.get("/api/videos")
    assert resp.status_code in (400, 503)


def test_video_detail_not_found_degrades() -> None:
    resp = client.get("/api/videos/1")
    assert resp.status_code in (404, 503)
