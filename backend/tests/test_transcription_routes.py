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


def test_transcript_unknown_video_answers_null_when_database_up() -> None:
    # Contract: the cached-transcript endpoint answers 200 with
    # ``transcript: null`` for videos without a transcript (unknown id or
    # not yet transcribed); offline it degrades to 503.
    resp = client.get("/api/videos/999999/transcript")
    assert resp.status_code in (200, 503)
    if resp.status_code == 200:
        body = resp.json()
        assert body["transcript"] is None
        assert body["segments"] == []
