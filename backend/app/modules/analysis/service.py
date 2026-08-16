"""Analysis service — AI clip detection (§16–§20).

Pipeline: transcript → candidate generation (AI) → Pydantic validation with
one retry (§18) → sentence-boundary timestamp correction (§20) → §19 scoring →
persist ``clip_candidates``. Candidates are cached per video (§55: never
re-analyze an unchanged transcript).
"""

from __future__ import annotations

import structlog
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.analysis.errors import AnalysisError
from app.modules.analysis.models import ClipCandidate
from app.modules.transcription.service import get_transcript
from app.modules.videos.models import Video
from app.modules.videos.service import set_status
from app.providers.ai.factory import get_ai_provider

logger = structlog.get_logger(__name__)


class ClipCandidateIn(BaseModel):
    """§18 — the exact AI JSON contract, validated by Pydantic."""

    start_time: float = Field(gt=0)
    end_time: float = Field(gt=0)
    title: str = Field(min_length=1, max_length=512)
    hook: str = ""
    reason: str = ""
    score: int = Field(default=0, ge=0, le=100)
    hook_score: int = Field(default=0, ge=0, le=100)
    content_score: int = Field(default=0, ge=0, le=100)
    context_score: int = Field(default=0, ge=0, le=100)
    emotion_score: int = Field(default=0, ge=0, le=100)
    standalone_score: int = Field(default=0, ge=0, le=100)
    retention_score: int = Field(default=0, ge=0, le=100)


def compute_overall_score(
    hook_score: int,
    content_score: int,
    context_score: int,
    emotion_score: int,
    standalone_score: int,
    retention_score: int,
) -> int:
    """§19 overall_score formula."""
    return round(
        hook_score * 0.25
        + content_score * 0.20
        + context_score * 0.15
        + emotion_score * 0.10
        + standalone_score * 0.15
        + retention_score * 0.15
    )


def correct_timestamps(
    start: float, end: float, segments: list[dict], duration: float
) -> tuple[float, float] | None:
    """§20 — snap AI timestamps to sentence (segment) boundaries.

    The AI must never cut mid-sentence: start snaps back to the nearest
    segment boundary at-or-before it, end snaps forward to the nearest
    boundary at-or-after it. Out-of-range or degenerate clips are dropped.
    """
    if duration <= 0:
        return None
    boundaries = sorted(
        {0.0, float(duration)}
        | {float(s["start"]) for s in segments}
        | {float(s["end"]) for s in segments}
    )

    new_start = max((b for b in boundaries if b <= start + 0.5), default=0.0)
    new_end = min((b for b in boundaries if b >= end - 0.5), default=float(duration))

    new_start = max(0.0, min(new_start, float(duration)))
    new_end = max(new_start + 1.0, min(new_end, float(duration)))

    clip_len = new_end - new_start
    if clip_len < 8.0 or clip_len > 120.0:
        return None
    return round(new_start, 3), round(new_end, 3)


def _validate_and_build(
    raw: object, segments: list[dict], duration: float
) -> list[dict]:
    """Validate the AI response item-by-item; return ORM-ready dicts."""
    if not isinstance(raw, dict) or not isinstance(raw.get("clips"), list):
        return []

    built: list[dict] = []
    for item in raw["clips"]:
        try:
            clip = ClipCandidateIn(**item)
        except ValidationError as exc:
            logger.warning("ai_candidate_invalid", error=str(exc)[:200])
            continue

        corrected = correct_timestamps(clip.start_time, clip.end_time, segments, duration)
        if corrected is None:
            logger.warning("ai_candidate_timestamps_rejected", start=clip.start_time, end=clip.end_time)
            continue

        start, end = corrected
        built.append(
            {
                "start_time": start,
                "end_time": end,
                "title": clip.title[:512],
                "hook": clip.hook,
                "reason": clip.reason,
                "score": compute_overall_score(
                    clip.hook_score,
                    clip.content_score,
                    clip.context_score,
                    clip.emotion_score,
                    clip.standalone_score,
                    clip.retention_score,
                ),
                "hook_score": clip.hook_score,
                "content_score": clip.content_score,
                "context_score": clip.context_score,
                "emotion_score": clip.emotion_score,
                "standalone_score": clip.standalone_score,
                "retention_score": clip.retention_score,
            }
        )
    return built


def analyze_video(db: Session, video_id: int, force: bool = False) -> dict:
    """Run AI analysis and persist candidates. Cached per video (§55)."""
    result = get_transcript(db, video_id)
    if result is None:
        raise AnalysisError("TRANSCRIPT_REQUIRED", "Transcribe the video before analyzing it.")
    transcript, segments = result

    existing = db.query(ClipCandidate).filter(ClipCandidate.video_id == video_id).count()
    if existing and not force:
        return {"status": "already_analyzed", "count": existing}

    segs = [
        {"start": seg.start_time, "end": seg.end_time, "text": seg.text}
        for seg in segments
    ]
    payload = {
        "language": transcript.language,
        "duration": transcript.duration,
        "segments": segs,
    }
    provider = get_ai_provider()

    raw = provider.analyze_transcript(payload)
    candidates = _validate_and_build(raw, segs, transcript.duration or 0.0)
    if not candidates:
        # §18: one retry before giving up.
        logger.warning("ai_response_invalid_retry", video_id=video_id)
        raw = provider.analyze_transcript(payload)
        candidates = _validate_and_build(raw, segs, transcript.duration or 0.0)
    if not candidates:
        raise AnalysisError(
            "AI_ANALYSIS_FAILED", "AI returned no valid clip candidates after retry."
        )

    if force:
        db.query(ClipCandidate).filter(ClipCandidate.video_id == video_id).delete()
    for candidate in candidates:
        db.add(ClipCandidate(video_id=video_id, **candidate))
    db.commit()

    video = db.get(Video, video_id)
    if video is not None:
        set_status(db, video, "analyzed")

    logger.info("analysis_completed", video_id=video_id, candidates=len(candidates))
    return {"status": "analyzed", "count": len(candidates)}


# ------------------------------------------------------------------ candidates

def get_candidates(db: Session, video_id: int) -> list[ClipCandidate]:
    return (
        db.query(ClipCandidate)
        .filter(ClipCandidate.video_id == video_id)
        .order_by(ClipCandidate.score.desc(), ClipCandidate.id)
        .all()
    )


def set_candidate_status(db: Session, candidate_id: int, status: str) -> ClipCandidate | None:
    candidate = db.get(ClipCandidate, candidate_id)
    if candidate is None:
        return None
    candidate.status = status
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    logger.info("candidate_status_changed", candidate_id=candidate_id, status=status)
    return candidate


# ------------------------------------------------------------------ automation

def select_best_candidate(
    candidates: list[ClipCandidate], threshold: int
) -> ClipCandidate | None:
    """Best auto-approvable candidate (Phase 10).

    Picks the highest-scoring candidate still awaiting review (status
    ``candidate``) and returns it only when its §19 overall score reaches
    ``threshold``. Below the threshold nothing is approved — the clips stay
    for manual review rather than publishing a weak moment.
    """
    reviewable = [c for c in candidates if c.status == "candidate"]
    if not reviewable:
        return None
    best = max(reviewable, key=lambda c: (c.score, c.id))
    return best if best.score >= threshold else None


def auto_approve_best_candidate(db: Session, video_id: int) -> ClipCandidate | None:
    """Auto-approve the best candidate of a video (worker-facing, Phase 10).

    No-op when automatic mode is disabled (``settings.auto_approve`` false) or
    when no candidate reaches the threshold. Returns the approved candidate
    or None.
    """
    if not settings.auto_approve:
        return None
    best = select_best_candidate(get_candidates(db, video_id), settings.auto_approve_threshold)
    if best is None:
        logger.info(
            "auto_approve_none",
            video_id=video_id,
            threshold=settings.auto_approve_threshold,
        )
        return None
    set_candidate_status(db, best.id, "approved")
    logger.info(
        "auto_approve_completed",
        video_id=video_id,
        candidate_id=best.id,
        score=best.score,
    )
    return best


def candidate_payload(candidate: ClipCandidate) -> dict:
    return {
        "id": candidate.id,
        "video_id": candidate.video_id,
        "start_time": candidate.start_time,
        "end_time": candidate.end_time,
        "title": candidate.title,
        "hook": candidate.hook,
        "reason": candidate.reason,
        "score": candidate.score,
        "hook_score": candidate.hook_score,
        "content_score": candidate.content_score,
        "context_score": candidate.context_score,
        "emotion_score": candidate.emotion_score,
        "standalone_score": candidate.standalone_score,
        "retention_score": candidate.retention_score,
        "status": candidate.status,
    }
