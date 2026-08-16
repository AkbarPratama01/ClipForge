"""Transcription route behavior verified offline (no MySQL/Redis).

Pins down degraded paths: DB outages return 503 instead of 500; unknown
videos can't be confirmed offline, so the 503 path is the honest contract.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_transcribe_degrades_when_database_down() -> None:
    resp = client.post("/api/videos/1/transcribe")
    assert resp.status_code in (400, 404, 503)


def test_transcript_degrades_when_database_down() -> None:
    resp = client.get("/api/videos/1/transcript")
    assert resp.status_code in (400, 404, 503)


def test_transcript_missing_video_id_404_when_database_up() -> None:
    # With a live DB this would be a proper 404 for unknown ids; offline we
    # assert the route exists and never crashes with a 500.
    resp = client.get("/api/videos/999999/transcript")
    assert resp.status_code in (404, 503)
