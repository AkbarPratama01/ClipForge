"""Rendering endpoints (Phase 6): queue a render, status, download the Short."""

from __future__ import annotations

import os

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, JSONResponse
from redis import RedisError
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.modules.analysis.models import ClipCandidate
from app.modules.jobs.queue import JOB_RENDER, enqueue
from app.modules.rendering.models import ClipRender
from app.modules.rendering.service import get_render, render_payload

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["rendering"])


def _db_error() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"error": {"code": "STORAGE_ERROR", "detail": "Database is unavailable."}},
    )


@router.post("/candidates/{candidate_id}/render", summary="Queue a render (§Phase 6)")
def render_candidate(candidate_id: int, db: Session = Depends(get_db)) -> JSONResponse:
    try:
        candidate = db.get(ClipCandidate, candidate_id)
        existing = get_render(db, candidate_id) if candidate is not None else None
    except OperationalError:
        return _db_error()
    if candidate is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "code": "CANDIDATE_NOT_FOUND",
                    "detail": f"Candidate {candidate_id} not found.",
                }
            },
        )
    if existing is not None and existing.status == "rendered":
        return JSONResponse(
            {
                "candidate_id": candidate_id,
                "render": render_payload(existing),
                "status": "already_rendered",
                "message": "Clip is already rendered — the render is cached.",
            }
        )
    if candidate.status != "approved":
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "CANDIDATE_NOT_APPROVED",
                    "detail": (
                        "Approve the candidate before rendering it "
                        f"(current status: {candidate.status})."
                    ),
                }
            },
        )

    try:
        enqueue(JOB_RENDER, {"candidate_id": candidate_id})
    except RedisError:
        logger.warning("render_queue_unavailable", candidate_id=candidate_id)
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "QUEUE_UNAVAILABLE", "detail": "Redis is unavailable."}},
        )

    logger.info("render_queued", candidate_id=candidate_id)
    return JSONResponse(
        {"candidate_id": candidate_id, "status": "queued", "message": "Render queued."}
    )


@router.get("/candidates/{candidate_id}/render", summary="Render status for a candidate")
def render_status(candidate_id: int, db: Session = Depends(get_db)) -> JSONResponse:
    try:
        render = get_render(db, candidate_id)
    except OperationalError:
        return _db_error()
    return JSONResponse(
        {"candidate_id": candidate_id, "render": render_payload(render) if render else None}
    )


@router.get("/renders/{render_id}/file", summary="Download the rendered Short")
def render_file(render_id: int, db: Session = Depends(get_db)):
    try:
        render = db.get(ClipRender, render_id)
    except OperationalError:
        return _db_error()
    if render is None or render.status != "rendered" or not render.local_path:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "code": "RENDER_NOT_FOUND",
                    "detail": f"Rendered file for render {render_id} not found.",
                }
            },
        )
    if not os.path.exists(render.local_path):
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "code": "RENDER_FILE_MISSING",
                    "detail": "The rendered file is no longer on disk.",
                }
            },
        )
    return FileResponse(
        render.local_path,
        media_type="video/mp4",
        filename=f"clip-{render.candidate_id}.mp4",
    )
