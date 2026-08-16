"""Phase 10 automation tests (pure — no DB/Redis/Drive)."""

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app
from app.modules.analysis.models import ClipCandidate
from app.modules.analysis.service import select_best_candidate
from app.modules.jobs.queue import retry_delay_seconds
from worker.watcher import is_video_file

client = TestClient(app)


def _candidate(cid: int, score: int, status: str = "candidate") -> ClipCandidate:
    return ClipCandidate(
        id=cid,
        video_id=1,
        start_time=10.0,
        end_time=30.0,
        title=f"clip {cid}",
        score=score,
        status=status,
    )


# ------------------------------------------------------------- config defaults


def test_phase10_config_defaults() -> None:
    s = Settings()
    assert s.auto_approve is False
    assert s.auto_approve_threshold == 85
    assert s.youtube_auto_publish is False
    assert s.max_concurrent_jobs == 1
    assert s.max_job_retries == 3


# ---------------------------------------------------------- auto-approve logic


def test_select_best_candidate_picks_highest_score() -> None:
    candidates = [_candidate(1, 70), _candidate(2, 92), _candidate(3, 80)]
    best = select_best_candidate(candidates, threshold=85)
    assert best is not None
    assert best.id == 2


def test_select_best_candidate_below_threshold_returns_none() -> None:
    candidates = [_candidate(1, 84), _candidate(2, 70)]
    assert select_best_candidate(candidates, threshold=85) is None


def test_select_best_candidate_skips_non_reviewable() -> None:
    candidates = [
        _candidate(1, 95, status="approved"),
        _candidate(2, 90, status="rejected"),
        _candidate(3, 88),
    ]
    best = select_best_candidate(candidates, threshold=85)
    assert best is not None
    assert best.id == 3


def test_select_best_candidate_empty() -> None:
    assert select_best_candidate([], threshold=85) is None
    assert select_best_candidate([_candidate(1, 90, status="approved")], threshold=85) is None


def test_select_best_candidate_tie_breaks_by_id() -> None:
    candidates = [_candidate(1, 90), _candidate(2, 90)]
    assert select_best_candidate(candidates, threshold=85).id == 2


def test_select_best_candidate_threshold_zero_approves_any() -> None:
    candidates = [_candidate(1, 1)]
    assert select_best_candidate(candidates, threshold=0) is not None


# ---------------------------------------------------------------- watcher rules


def test_is_video_file_mime() -> None:
    assert is_video_file("clip.mp4", "video/mp4") is True
    assert is_video_file("clip", "video/quicktime") is True


def test_is_video_file_by_extension() -> None:
    for name in ("a.mp4", "b.mov", "c.mkv", "d.webm", "e.m4v", "f.avi", "g.ts"):
        assert is_video_file(name) is True, name


def test_is_video_file_rejects_non_video() -> None:
    assert is_video_file("notes.txt") is False
    assert is_video_file("doc.pdf", "application/pdf") is False
    assert is_video_file("folder", "application/vnd.google-apps.folder") is False
    assert is_video_file("sheet", "application/vnd.google-apps.spreadsheet") is False


def test_is_video_file_case_insensitive() -> None:
    assert is_video_file("CLIP.MP4") is True


# ------------------------------------------------------------------ retry math


def test_retry_delay_doubles() -> None:
    assert retry_delay_seconds(0) == 5.0
    assert retry_delay_seconds(1) == 10.0
    assert retry_delay_seconds(2) == 20.0


def test_retry_delay_capped() -> None:
    assert retry_delay_seconds(10) == 300.0


# --------------------------------------------------------------- status route


def test_automation_status_route() -> None:
    resp = client.get("/api/automation/status")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"auto_approve", "auto_approve_threshold", "youtube_auto_publish"}
    assert isinstance(body["auto_approve"], bool)
    assert isinstance(body["youtube_auto_publish"], bool)
    assert isinstance(body["auto_approve_threshold"], int)
