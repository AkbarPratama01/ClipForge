"""Google Drive OAuth 2.0 + storage endpoints (§60).

Flow: ``POST /api/google-drive/connect`` returns Google's authorization URL
(server-side web flow, ``state`` kept in Redis). Google redirects to
``GET /api/google-drive/callback``, which exchanges the code, encrypts the
token, stores it in MySQL, then redirects the browser back to the dashboard.

Tokens never appear in logs or in API responses.
"""

from __future__ import annotations

import secrets

import structlog
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, RedirectResponse
from google.auth.transport.requests import AuthorizedSession
from google_auth_oauthlib.flow import Flow
from redis import RedisError
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.redis import get_redis
from app.core.settings_error import UnsetSettingError
from app.database.session import get_db
from app.modules.storage.errors import StorageError
from app.modules.storage.models import StorageFile
from app.modules.storage.service import (
    account_status,
    ensure_folder_structure,
    oauth_config_available,
    save_google_credentials,
)
from app.providers.storage.factory import get_storage_provider
from app.providers.storage.google_drive import DRIVE_SCOPES, GoogleDriveProvider

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/google-drive", tags=["google-drive"])

_STATE_TTL_SECONDS = 600


def _build_flow() -> Flow:
    return Flow.from_client_config(
        client_config={
            "web": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=DRIVE_SCOPES,
        redirect_uri=settings.google_redirect_uri,
    )


def _error_response(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "detail": detail}})


def _storage_error_response(exc: Exception) -> JSONResponse:
    """Map storage/database failures to an HTTP error without leaking secrets."""
    if isinstance(exc, StorageError):
        return _error_response(400, exc.code, exc.detail)
    if isinstance(exc, OperationalError):
        logger.warning("storage_db_unavailable", error=str(exc).split("\n")[0])
        return _error_response(503, "STORAGE_ERROR", "Database is unavailable.")
    logger.warning("storage_route_failed", error=str(exc))
    return _error_response(500, "STORAGE_ERROR", "Unexpected storage error.")


@router.post("/connect", summary="Start Google Drive OAuth flow")
def connect() -> JSONResponse:
    try:
        oauth_config_available()
    except UnsetSettingError as exc:
        return _error_response(400, exc.code, exc.detail)

    state = secrets.token_urlsafe(32)
    try:
        get_redis().set(f"oauth:drive:{state}", "pending", ex=_STATE_TTL_SECONDS)
    except RedisError as exc:
        logger.warning("drive_connect_redis_unavailable", error=str(exc))
        return _error_response(503, "STORAGE_ERROR", "Redis is unavailable; cannot start OAuth.")

    flow = _build_flow()
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    logger.info("drive_oauth_started")
    return JSONResponse({"auth_url": auth_url})


@router.get("/callback", summary="Google Drive OAuth callback", include_in_schema=False)
def callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    frontend_url = settings.frontend_public_url

    if error:
        logger.warning("drive_oauth_error", error=error)
        return RedirectResponse(f"{frontend_url}/?drive=error", status_code=303)

    if not state:
        return RedirectResponse(f"{frontend_url}/?drive=error", status_code=303)

    try:
        # One-time state; fail closed if unknown or already consumed.
        redis = get_redis()
        if redis.get(f"oauth:drive:{state}") != "pending":
            logger.warning("drive_oauth_state_invalid")
            return RedirectResponse(f"{frontend_url}/?drive=error", status_code=303)
        redis.delete(f"oauth:drive:{state}")
    except RedisError as exc:
        logger.warning("drive_callback_redis_unavailable", error=str(exc))
        return RedirectResponse(f"{frontend_url}/?drive=error", status_code=303)

    if not code:
        logger.warning("drive_oauth_missing_code")
        return RedirectResponse(f"{frontend_url}/?drive=error", status_code=303)

    try:
        flow = _build_flow()
        flow.fetch_token(code=code)
        credentials = flow.credentials

        # Resolve the connected account's email via the Drive API.
        session = AuthorizedSession(credentials)
        about = session.get(
            "https://www.googleapis.com/drive/v3/about",
            params={"fields": "user(emailAddress)"},
        )
        email = about.json().get("user", {}).get("emailAddress") if about.ok else None

        save_google_credentials(db, credentials.to_json(), email)
        logger.info("drive_oauth_completed", email=email)
        return RedirectResponse(f"{frontend_url}/?drive=connected", status_code=303)
    except Exception as exc:
        logger.warning("drive_oauth_failed", error=str(exc))
        return RedirectResponse(f"{frontend_url}/?drive=error", status_code=303)


@router.get("/status", summary="Google Drive connection status")
def status(db: Session = Depends(get_db)) -> JSONResponse:
    return JSONResponse(account_status(db))


@router.post("/bootstrap", summary="Create the ClipForge Drive folder structure (§8)")
def bootstrap(db: Session = Depends(get_db)) -> JSONResponse:
    try:
        provider = get_storage_provider(db)
        folders = ensure_folder_structure(provider)
        return JSONResponse({"folders": folders})
    except Exception as exc:
        return _storage_error_response(exc)


@router.get("/files", summary="List files in a Drive folder (default 01_Inbox)")
def list_files(
    folder: str = Query("01_Inbox", description="Folder name under the ClipForge root"),
    db: Session = Depends(get_db),
) -> JSONResponse:
    try:
        provider = get_storage_provider(db)
        files = provider.list_files(folder)
        return JSONResponse(
            {
                "folder": folder,
                "files": [
                    {
                        "id": f.id,
                        "filename": f.filename,
                        "mime_type": f.mime_type,
                        "size": f.size,
                        "created_at": f.created_at,
                    }
                    for f in files
                ],
            }
        )
    except Exception as exc:
        return _storage_error_response(exc)


@router.post("/files/{file_id}/download", summary="Download a Drive file to local temp storage")
def download_file(file_id: str, db: Session = Depends(get_db)) -> JSONResponse:
    """Phase 2 acceptance: prove ClipForge can *read* videos from Drive.

    Streams the file into ``/data/temp``, computes its SHA-256, and records a
    ``storage_files`` row so the database knows where every file lives (§49).
    """
    try:
        provider = get_storage_provider(db)
        if not isinstance(provider, GoogleDriveProvider):
            return _error_response(
                400, "STORAGE_ERROR", "Download-by-id requires the google_drive provider."
            )
        meta = provider.get_metadata_by_id(file_id)
        filename = meta.get("name", file_id)
        mime_type = meta.get("mimeType")

        local_dir = f"{settings.temp_storage_path}/downloads"
        local_path = provider.download_by_id(file_id, f"{local_dir}/{filename}")

        from app.modules.storage.checksum import sha256_file

        checksum = sha256_file(local_path)

        row = StorageFile(
            provider="google_drive",
            provider_file_id=file_id,
            local_path=local_path,
            remote_path=f"{settings.google_drive_root_folder}/{filename}",
            filename=filename,
            mime_type=mime_type,
            size=meta.get("size"),
            checksum=checksum,
            status="downloaded",
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        return JSONResponse(
            {
                "file_id": file_id,
                "filename": filename,
                "local_path": local_path,
                "size": meta.get("size"),
                "checksum": checksum,
                "storage_file_id": row.id,
            }
        )
    except Exception as exc:
        return _storage_error_response(exc)
