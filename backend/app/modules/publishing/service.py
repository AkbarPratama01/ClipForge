"""Publishing service (Phase 8-9).

YouTube OAuth persistence (Fernet-encrypted, same key as Drive), account
status, publication history (§65), scheduling validation, and the
worker-facing ``publish_clip`` orchestration. Default title/description come
from the approved candidate; scheduled publishing uses YouTube's native
``publishAt`` (requires ``privacy=private``).
"""

from __future__ import annotations

import datetime
import json
import os

import structlog
from cryptography.fernet import InvalidToken
from google.oauth2.credentials import Credentials
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import decrypt_token, encrypt_token, require_token_encryption_key
from app.core.settings_error import UnsetSettingError
from app.modules.analysis.models import ClipCandidate
from app.modules.publishing.errors import PublishingError, YouTubeNotConnected
from app.modules.publishing.models import (
    YOUTUBE_PRIVACY,
    Publication,
    YouTubeAccount,
)
from app.modules.rendering.models import ClipRender
from app.providers.publishing.youtube import YOUTUBE_SCOPES

logger = structlog.get_logger(__name__)


# ------------------------------------------------------------ OAuth persistence

def save_youtube_credentials(
    db: Session,
    credentials_json: str,
    channel_name: str | None,
    channel_id: str | None,
) -> YouTubeAccount:
    """Persist (encrypted) YouTube OAuth credentials, replacing the previous account."""
    require_token_encryption_key()  # never store tokens under an ephemeral key
    account = db.query(YouTubeAccount).order_by(YouTubeAccount.id.desc()).first()
    encrypted = encrypt_token(credentials_json)
    if account is None:
        account = YouTubeAccount(
            channel_name=channel_name,
            channel_id=channel_id,
            credentials_encrypted=encrypted,
            status="connected",
        )
        db.add(account)
    else:
        account.channel_name = channel_name
        account.channel_id = channel_id
        account.credentials_encrypted = encrypted
        account.status = "connected"
    db.commit()
    db.refresh(account)
    logger.info("youtube_account_saved", account_id=account.id, channel=channel_name)
    return account


def get_youtube_account(db: Session) -> YouTubeAccount | None:
    return db.query(YouTubeAccount).order_by(YouTubeAccount.id.desc()).first()


def get_youtube_credentials(db: Session) -> Credentials:
    """Decrypt and materialize the active account's credentials."""
    account = get_youtube_account(db)
    if account is None:
        raise YouTubeNotConnected()
    try:
        token_json = decrypt_token(account.credentials_encrypted)
    except InvalidToken as exc:
        raise PublishingError(
            "TOKEN_DECRYPTION_FAILED",
            "Stored YouTube token cannot be decrypted (key changed?). Reconnect the account.",
        ) from exc
    return Credentials.from_authorized_user_info(json.loads(token_json), scopes=YOUTUBE_SCOPES)


def oauth_config_available() -> None:
    """Raise a clear error when YouTube OAuth is not configured in .env."""
    missing = [
        name
        for name, value in (
            ("YOUTUBE_CLIENT_ID", settings.youtube_client_id),
            ("YOUTUBE_CLIENT_SECRET", settings.youtube_client_secret),
            ("YOUTUBE_REDIRECT_URI", settings.youtube_redirect_uri),
        )
        if not value
    ]
    if missing:
        raise UnsetSettingError(
            "YOUTUBE_OAUTH_NOT_CONFIGURED",
            "Set " + ", ".join(missing) + " in .env (see README → YouTube Setup).",
        )


def youtube_account_status(db: Session) -> dict:
    """Connection status + channel name (mirrors the Drive status endpoint)."""
    try:
        account = get_youtube_account(db)
    except Exception:
        logger.warning("youtube_status_db_unavailable")
        return {"connected": False, "error": "database_unavailable"}

    if account is None:
        return {"connected": False}

    try:
        from app.providers.publishing.factory import get_publishing_provider

        info = get_publishing_provider(db).channel_info()
        if not info:
            return {"connected": True, "channel_name": account.channel_name}
        return {"connected": True, "channel_name": info.get("channel_name") or account.channel_name}
    except Exception as exc:
        logger.warning("youtube_status_failed", error=str(exc))
        return {"connected": True, "channel_name": account.channel_name, "error": "token_invalid"}


# --------------------------------------------------------------- publications

def validate_privacy(privacy: str) -> str:
    if privacy not in YOUTUBE_PRIVACY:
        raise PublishingError(
            "INVALID_PRIVACY",
            f"privacy must be one of {sorted(YOUTUBE_PRIVACY)}, got {privacy!r}.",
        )
    return privacy


def validate_schedule(scheduled_at: datetime.datetime | None) -> None:
    """YouTube's publishAt scheduling requires private privacy + a future date."""
    if scheduled_at is None:
        return
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=datetime.timezone.utc)
    if scheduled_at <= datetime.datetime.now(datetime.timezone.utc):
        raise PublishingError(
            "SCHEDULE_IN_PAST", "scheduled_at must be in the future."
        )


def create_publication(
    db: Session,
    render: ClipRender,
    *,
    title: str | None = None,
    description: str | None = None,
    tags: str | None = None,
    privacy: str | None = None,
    scheduled_at: datetime.datetime | None = None,
) -> Publication:
    """Create a publication row; defaults come from the candidate (§65)."""
    candidate = db.get(ClipCandidate, render.candidate_id)
    if candidate is None:
        raise PublishingError("CANDIDATE_NOT_FOUND", "Render has no candidate.")

    privacy = validate_privacy(privacy or settings.youtube_default_privacy)
    validate_schedule(scheduled_at)
    if scheduled_at is not None and privacy != "private":
        raise PublishingError(
            "SCHEDULE_REQUIRES_PRIVATE",
            "Scheduled publishing requires privacy=private (YouTube publishAt).",
        )

    publication = Publication(
        render_id=render.id,
        video_id=render.video_id,
        title=(title or candidate.title or candidate.hook or "ClipForge Short")[:512],
        description=(description if description is not None else (candidate.reason or ""))[:5000],
        tags=(tags or "")[:1024],
        privacy=privacy,
        scheduled_at=scheduled_at,
        status="queued",
    )
    db.add(publication)
    db.commit()
    db.refresh(publication)
    logger.info(
        "publication_created",
        publication_id=publication.id,
        render_id=render.id,
        privacy=privacy,
        scheduled_at=scheduled_at.isoformat() if scheduled_at else None,
    )
    return publication


def get_publication(db: Session, publication_id: int) -> Publication | None:
    return db.get(Publication, publication_id)


def list_publications(db: Session, video_id: int | None = None) -> list[Publication]:
    query = db.query(Publication)
    if video_id is not None:
        query = query.filter(Publication.video_id == video_id)
    return query.order_by(Publication.created_at.desc(), Publication.id.desc()).all()


def effective_status(publication: Publication, now: datetime.datetime | None = None) -> str:
    """A scheduled video is 'published' once its publishAt has passed."""
    if publication.status == "scheduled" and publication.scheduled_at is not None:
        now = now or datetime.datetime.now(datetime.timezone.utc)
        scheduled = publication.scheduled_at
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=datetime.timezone.utc)
        if now >= scheduled:
            return "published"
    return publication.status


def publication_payload(publication: Publication) -> dict:
    return {
        "id": publication.id,
        "render_id": publication.render_id,
        "video_id": publication.video_id,
        "youtube_video_id": publication.youtube_video_id,
        "title": publication.title,
        "description": publication.description,
        "tags": publication.tags,
        "privacy": publication.privacy,
        "scheduled_at": publication.scheduled_at.isoformat() if publication.scheduled_at else None,
        "status": effective_status(publication),
        "error_code": publication.error_code,
        "published_at": publication.published_at.isoformat() if publication.published_at else None,
        "created_at": publication.created_at.isoformat() if publication.created_at else None,
    }


# ------------------------------------------------------------------ publishing

def publish_clip(db: Session, publication_id: int) -> Publication:
    """Upload the rendered Short to YouTube; update the publication row.

    Worker-facing. Failures mark the publication ``failed`` (candidate stays
    ``rendered`` for retry); success records the external video id and moves
    the candidate to ``published`` (state machine §61).
    """
    publication = db.get(Publication, publication_id)
    if publication is None:
        raise PublishingError("PUBLICATION_NOT_FOUND", f"Publication {publication_id} not found.")
    if publication.youtube_video_id:
        logger.info("publish_cached_skip", publication_id=publication_id)
        return publication

    render = db.get(ClipRender, publication.render_id)
    if render is None or render.status != "rendered" or not render.local_path:
        raise PublishingError(
            "RENDER_NOT_READY", "Rendered file missing — render the clip first."
        )
    if not os.path.exists(render.local_path):
        raise PublishingError("RENDER_FILE_MISSING", "Rendered file is no longer on disk.")

    candidate = db.get(ClipCandidate, render.candidate_id)

    publication.status = "uploading"
    db.commit()

    try:
        from app.providers.publishing.factory import get_publishing_provider

        provider = get_publishing_provider(db)
        result = provider.publish(
            render.local_path,
            {
                "title": publication.title,
                "description": publication.description,
                "tags": publication.tags,
                "privacy": publication.privacy,
                "publish_at": publication.scheduled_at,
            },
        )
        publication.youtube_video_id = result["external_id"]
        publication.error_code = None
        if publication.scheduled_at is not None:
            publication.status = "scheduled"
        else:
            publication.status = "published"
            publication.published_at = datetime.datetime.now(datetime.timezone.utc)
        if candidate is not None:
            candidate.status = "published"
        db.commit()
        db.refresh(publication)
        logger.info(
            "publish_completed",
            publication_id=publication.id,
            youtube_video_id=publication.youtube_video_id,
            status=publication.status,
        )
        return publication
    except Exception as exc:
        publication.status = "failed"
        publication.error_code = getattr(exc, "code", None) or type(exc).__name__
        db.commit()
        logger.warning(
            "publish_failed",
            publication_id=publication.id,
            code=publication.error_code,
            error=str(exc)[:300],
        )
        raise
