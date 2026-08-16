"""Transcription endpoints (§60).

``POST /api/videos/{id}/transcribe`` — checks the transcript cache (§15) and
enqueues a ``TRANSCRIBE`` job; the worker extracts audio and runs local
Whisper. ``GET /api/videos/{id}/transcript`` — returns the cached transcript
and timestamped segments (§15), or ``transcript: null`` when not yet done.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from redis import RedisError
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.modules.jobs.queue import JOB_TRANSCRIBE, enqueue
from app.modules.transcription.service import (
    get_transcript,
    transcript_payload,
)
from app.modules.videos.service import get_video

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/videos/{video_id}", tags=["transcription"])


@router.post("/transcribe", summary="Queue transcription for a video")
def transcribe_video(video_id: int, db: Session = Depends(get_db)) -> JSONResponse:
    try:
        video = get_video(db, video_id)
    except OperationalError:
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "STORAGE_ERROR", "detail": "Database is unavailable."}},
        )
    if video is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "VIDEO_NOT_FOUND", "detail": f"Video {video_id} not found."}},
        )

    if get_transcript(db, video_id) is not None:
        return JSONResponse(
            {"video_id": video_id, "status": "already_transcribed", "message": "Transcript cached (§15)."}
        )

    try:
        enqueue(JOB_TRANSCRIBE, {"video_id": video_id})
    except RedisError:
        logger.warning("transcribe_queue_unavailable", video_id=video_id)
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "QUEUE_UNAVAILABLE", "detail": "Redis is unavailable."}},
        )

    logger.info("transcribe_queued", video_id=video_id)
    return JSONResponse({"video_id": video_id, "status": "queued", "message": "Transcription queued."})


@router.get("/transcript", summary="Cached transcript with timestamped segments")
def transcript(video_id: int, db: Session = Depends(get_db)) -> JSONResponse:
    try:
        result = get_transcript(db, video_id)
    except OperationalError:
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "STORAGE_ERROR", "detail": "Database is unavailable."}},
        )
    if result is None:
        return JSONResponse({"video_id": video_id, "transcript": None, "segments": []})
    return JSONResponse(transcript_payload(video_id, result))
