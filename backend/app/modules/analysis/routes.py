"""Analysis endpoints (§60): analyze, candidates, approve/reject (§31, §42)."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from redis import RedisError
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.modules.analysis.models import ClipCandidate
from app.modules.analysis.service import (
    candidate_payload,
    get_candidates,
    set_candidate_status,
)
from app.modules.jobs.queue import JOB_ANALYZE, enqueue
from app.modules.transcription.service import get_transcript
from app.modules.videos.service import get_video

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["analysis"])


def _db_error() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"error": {"code": "STORAGE_ERROR", "detail": "Database is unavailable."}},
    )


@router.post("/videos/{video_id}/analyze", summary="Queue AI clip analysis (§16–18)")
def analyze_video_route(video_id: int, db: Session = Depends(get_db)) -> JSONResponse:
    try:
        video = get_video(db, video_id)
    except OperationalError:
        return _db_error()
    if video is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "VIDEO_NOT_FOUND", "detail": f"Video {video_id} not found."}},
        )

    if get_transcript(db, video_id) is None:
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "TRANSCRIPT_REQUIRED",
                    "detail": "Transcribe the video before analyzing it (§16).",
                }
            },
        )

    existing = (
        db.query(ClipCandidate).filter(ClipCandidate.video_id == video_id).count()
    )
    if existing:
        return JSONResponse(
            {
                "video_id": video_id,
                "status": "already_analyzed",
                "count": existing,
                "message": "Candidates already exist — analysis is cached (§55).",
            }
        )

    try:
        enqueue(JOB_ANALYZE, {"video_id": video_id})
    except RedisError:
        logger.warning("analyze_queue_unavailable", video_id=video_id)
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "QUEUE_UNAVAILABLE", "detail": "Redis is unavailable."}},
        )

    logger.info("analyze_queued", video_id=video_id)
    return JSONResponse(
        {"video_id": video_id, "status": "queued", "message": "Analysis queued."}
    )


@router.get("/videos/{video_id}/candidates", summary="List clip candidates (§42)")
def list_candidates(video_id: int, db: Session = Depends(get_db)) -> JSONResponse:
    try:
        candidates = get_candidates(db, video_id)
    except OperationalError:
        return _db_error()
    return JSONResponse(
        {
            "video_id": video_id,
            "candidates": [candidate_payload(c) for c in candidates],
        }
    )


@router.post("/candidates/{candidate_id}/approve", summary="Approve a candidate (§31)")
def approve_candidate(candidate_id: int, db: Session = Depends(get_db)) -> JSONResponse:
    try:
        candidate = set_candidate_status(db, candidate_id, "approved")
    except OperationalError:
        return _db_error()
    if candidate is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {"code": "CANDIDATE_NOT_FOUND", "detail": f"Candidate {candidate_id} not found."}
            },
        )
    return JSONResponse({"candidate_id": candidate_id, "status": "approved"})


@router.post("/candidates/{candidate_id}/reject", summary="Reject a candidate (§31)")
def reject_candidate(candidate_id: int, db: Session = Depends(get_db)) -> JSONResponse:
    try:
        candidate = set_candidate_status(db, candidate_id, "rejected")
    except OperationalError:
        return _db_error()
    if candidate is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {"code": "CANDIDATE_NOT_FOUND", "detail": f"Candidate {candidate_id} not found."}
            },
        )
    return JSONResponse({"candidate_id": candidate_id, "status": "rejected"})
