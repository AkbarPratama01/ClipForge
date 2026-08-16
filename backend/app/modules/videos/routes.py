"""Video ingestion endpoints (§60): import / list / detail.

``POST /api/videos/import`` validates the URL, creates a ``pending`` video row
and enqueues a ``DOWNLOAD_VIDEO`` job — the worker downloads with yt-dlp,
computes the checksum, detects duplicates (§67), and uploads the original to
Google Drive (``02_Processing``). Nothing heavy runs in the HTTP request (§26).
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from redis import RedisError
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.core.redis import get_redis
from app.modules.jobs.queue import JOB_DOWNLOAD_VIDEO, enqueue
from app.modules.storage.models import StorageFile
from app.modules.videos.models import Video
from app.modules.videos.service import create_video, get_video, is_valid_youtube_url

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/videos", tags=["videos"])


class ImportRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=1024)
    upload_to_drive: bool = True


def _download_progress(video_id: int) -> float | None:
    """Live download percent reported by the worker into Redis (None when idle)."""
    try:
        raw = get_redis().get(f"clipforge:progress:video:{video_id}")
        return round(float(raw), 1) if raw is not None else None
    except (RedisError, ValueError):
        return None


def _video_dict(video: Video) -> dict:
    return {
        "id": video.id,
        "source_url": video.source_url,
        "title": video.title,
        "channel": video.channel,
        "duration": video.duration,
        "width": video.width,
        "height": video.height,
        "fps": video.fps,
        "codec": video.codec,
        "filesize": video.filesize,
        "thumbnail": video.thumbnail,
        "checksum": video.checksum,
        "status": video.status,
        "error_code": video.error_code,
        "download_progress": _download_progress(video.id),
        "created_at": video.created_at.isoformat() if video.created_at else None,
    }


@router.post("/import", summary="Import a video from a YouTube URL")
def import_video(payload: ImportRequest, db: Session = Depends(get_db)) -> JSONResponse:
    url = payload.url.strip()
    if not is_valid_youtube_url(url):
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "INVALID_YOUTUBE_URL",
                    "detail": "Provide a YouTube watch/shorts/you.be URL.",
                }
            },
        )

    try:
        video = create_video(db, url)
    except OperationalError:
        logger.warning("video_import_db_unavailable")
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "STORAGE_ERROR", "detail": "Database is unavailable."}},
        )

    try:
        enqueue(
            JOB_DOWNLOAD_VIDEO,
            {"video_id": video.id, "upload_to_drive": payload.upload_to_drive},
        )
    except RedisError:
        logger.warning("video_import_queue_unavailable", video_id=video.id)
        from app.modules.videos.service import set_status

        set_status(db, video, "failed", error_code="QUEUE_UNAVAILABLE")
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "QUEUE_UNAVAILABLE",
                    "detail": "Redis is unavailable; the import could not be queued.",
                }
            },
        )

    logger.info("video_import_queued", video_id=video.id, url=url)
    return JSONResponse(
        {
            "video_id": video.id,
            "status": video.status,
            "message": "Import queued — the worker will download and sync it to Google Drive.",
        }
    )


@router.get("", summary="List imported videos")
def list_videos(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> JSONResponse:
    try:
        videos = (
            db.query(Video)
            .order_by(Video.id.desc())
            .limit(limit)
            .all()
        )
    except OperationalError:
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "STORAGE_ERROR", "detail": "Database is unavailable."}},
        )
    return JSONResponse({"videos": [_video_dict(v) for v in videos]})


@router.get("/{video_id}", summary="Video detail + storage files")
def video_detail(video_id: int, db: Session = Depends(get_db)) -> JSONResponse:
    try:
        video = get_video(db, video_id)
    except OperationalError:
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "STORAGE_ERROR", "detail": "Database is unavailable."}},
        )
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")

    files = (
        db.query(StorageFile)
        .filter(StorageFile.video_id == video_id)
        .order_by(StorageFile.id.desc())
        .all()
    )
    return JSONResponse(
        {
            "video": _video_dict(video),
            "files": [
                {
                    "id": f.id,
                    "provider": f.provider,
                    "provider_file_id": f.provider_file_id,
                    "remote_path": f.remote_path,
                    "filename": f.filename,
                    "size": f.size,
                    "checksum": f.checksum,
                    "status": f.status,
                }
                for f in files
            ],
        }
    )
