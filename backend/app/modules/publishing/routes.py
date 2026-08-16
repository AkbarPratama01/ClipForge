"""YouTube OAuth + publication endpoints (Phase 8-9).

Flow: ``POST /api/youtube/connect`` returns YouTube's authorization URL
(server-side web flow, ``state`` in Redis). YouTube redirects to
``GET /api/youtube/callback``, which exchanges the code, resolves the channel
name, encrypts the token, stores it in MySQL, then redirects back to the
dashboard. Tokens never appear in logs or responses.
"""

from __future__ import annotations

import datetime
import secrets

import structlog
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, RedirectResponse
from google_auth_oauthlib.flow import Flow
from pydantic import BaseModel, Field
from redis import RedisError
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.redis import get_redis
from app.core.settings_error import UnsetSettingError
from app.database.session import get_db
from app.modules.jobs.queue import JOB_PUBLISH, enqueue
from app.modules.publishing.errors import PublishingError
from app.modules.publishing.service import (
    create_publication,
    get_publication,
    list_publications,
    oauth_config_available,
    publication_payload,
    save_youtube_credentials,
    youtube_account_status,
)
from app.modules.rendering.models import ClipRender
from app.providers.publishing.youtube import YOUTUBE_SCOPES

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["publishing"])
youtube_router = APIRouter(prefix="/youtube", tags=["youtube"])

_STATE_TTL_SECONDS = 600


class PublishRequest(BaseModel):
    """Optional overrides; defaults come from the approved candidate (§65)."""

    title: str | None = Field(default=None, max_length=512)
    description: str | None = None
    tags: str | None = Field(default=None, max_length=1024)
    privacy: str | None = None
    # ISO 8601. Scheduling uses YouTube publishAt and therefore forces
    # privacy=private (validated in the service).
    scheduled_at: datetime.datetime | None = None


def _error_response(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "detail": detail}})


def _publishing_error_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, PublishingError):
        return _error_response(400, exc.code, exc.detail)
    if isinstance(exc, OperationalError):
        logger.warning("publishing_db_unavailable", error=str(exc).split("\n")[0])
        return _error_response(503, "STORAGE_ERROR", "Database is unavailable.")
    logger.warning("publishing_route_failed", error=str(exc))
    return _error_response(500, "PUBLISHING_ERROR", "Unexpected publishing error.")


def _build_flow() -> Flow:
    return Flow.from_client_config(
        client_config={
            "web": {
                "client_id": settings.youtube_client_id,
                "client_secret": settings.youtube_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=YOUTUBE_SCOPES,
        redirect_uri=settings.youtube_redirect_uri,
    )


# ------------------------------------------------------------------ OAuth flow


@youtube_router.post("/connect", summary="Start YouTube OAuth flow")
def connect() -> JSONResponse:
    try:
        oauth_config_available()
    except UnsetSettingError as exc:
        return _error_response(400, exc.code, exc.detail)

    state = secrets.token_urlsafe(32)
    try:
        get_redis().set(f"oauth:youtube:{state}", "pending", ex=_STATE_TTL_SECONDS)
    except RedisError as exc:
        logger.warning("youtube_connect_redis_unavailable", error=str(exc))
        return _error_response(503, "PUBLISHING_ERROR", "Redis is unavailable; cannot start OAuth.")

    flow = _build_flow()
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    logger.info("youtube_oauth_started")
    return JSONResponse({"auth_url": auth_url})


@youtube_router.get("/callback", summary="YouTube OAuth callback", include_in_schema=False)
def callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    frontend_url = settings.frontend_public_url

    if error:
        logger.warning("youtube_oauth_error", error=error)
        return RedirectResponse(f"{frontend_url}/?youtube=error", status_code=303)

    if not state:
        return RedirectResponse(f"{frontend_url}/?youtube=error", status_code=303)

    try:
        redis = get_redis()
        if redis.get(f"oauth:youtube:{state}") != "pending":
            logger.warning("youtube_oauth_state_invalid")
            return RedirectResponse(f"{frontend_url}/?youtube=error", status_code=303)
        redis.delete(f"oauth:youtube:{state}")
    except RedisError as exc:
        logger.warning("youtube_callback_redis_unavailable", error=str(exc))
        return RedirectResponse(f"{frontend_url}/?youtube=error", status_code=303)

    if not code:
        logger.warning("youtube_oauth_missing_code")
        return RedirectResponse(f"{frontend_url}/?youtube=error", status_code=303)

    try:
        flow = _build_flow()
        flow.fetch_token(code=code)
        credentials = flow.credentials

        from app.providers.publishing.youtube import YouTubeProvider

        info = YouTubeProvider(credentials).channel_info()
        save_youtube_credentials(
            db,
            credentials.to_json(),
            channel_name=info.get("channel_name"),
            channel_id=info.get("channel_id"),
        )
        logger.info("youtube_oauth_completed", channel=info.get("channel_name"))
        return RedirectResponse(f"{frontend_url}/?youtube=connected", status_code=303)
    except Exception as exc:
        logger.warning("youtube_oauth_failed", error=str(exc))
        return RedirectResponse(f"{frontend_url}/?youtube=error", status_code=303)


@youtube_router.get("/status", summary="YouTube connection status")
def status(db: Session = Depends(get_db)) -> JSONResponse:
    return JSONResponse(youtube_account_status(db))


# ------------------------------------------------------------- publications


@router.post("/renders/{render_id}/publish", summary="Queue publishing a rendered Short")
def publish_render(
    render_id: int,
    body: PublishRequest,
    db: Session = Depends(get_db),
) -> JSONResponse:
    try:
        render = db.get(ClipRender, render_id)
    except OperationalError:
        return _error_response(503, "STORAGE_ERROR", "Database is unavailable.")
    if render is None:
        return _error_response(404, "RENDER_NOT_FOUND", f"Render {render_id} not found.")
    if render.status != "rendered":
        return _error_response(
            400, "RENDER_NOT_READY", f"Render is {render.status!r}; publish a rendered clip."
        )

    try:
        publication = create_publication(
            db,
            render,
            title=body.title,
            description=body.description,
            tags=body.tags,
            privacy=body.privacy,
            scheduled_at=body.scheduled_at,
        )
    except PublishingError as exc:
        return _error_response(400, exc.code, exc.detail)
    except OperationalError:
        return _error_response(503, "STORAGE_ERROR", "Database is unavailable.")

    try:
        enqueue(JOB_PUBLISH, {"publication_id": publication.id})
    except RedisError:
        logger.warning("publish_queue_unavailable", publication_id=publication.id)
        return _error_response(503, "QUEUE_UNAVAILABLE", "Redis is unavailable.")

    logger.info("publish_queued", publication_id=publication.id, render_id=render_id)
    return JSONResponse(
        {
            "publication_id": publication.id,
            "render_id": render_id,
            "status": "queued",
            "message": "Publication queued.",
        }
    )


@router.get("/publications", summary="Publication history (§65)")
def publications(
    video_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> JSONResponse:
    try:
        items = list_publications(db, video_id=video_id)
    except OperationalError:
        return _error_response(503, "STORAGE_ERROR", "Database is unavailable.")
    return JSONResponse(
        {"publications": [publication_payload(p) for p in items]}
    )


@router.get("/publications/{publication_id}", summary="Single publication")
def publication_detail(publication_id: int, db: Session = Depends(get_db)) -> JSONResponse:
    try:
        publication = get_publication(db, publication_id)
    except OperationalError:
        return _error_response(503, "STORAGE_ERROR", "Database is unavailable.")
    if publication is None:
        return _error_response(404, "PUBLICATION_NOT_FOUND", f"Publication {publication_id} not found.")
    return JSONResponse(publication_payload(publication))
