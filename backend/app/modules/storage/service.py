"""Storage service — Google account persistence (encrypted), status, bootstrap."""

from __future__ import annotations

import json

import structlog
from cryptography.fernet import InvalidToken
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_token, encrypt_token
from app.core.config import settings
from app.core.settings_error import UnsetSettingError
from app.modules.storage.constants import DRIVE_FOLDERS
from app.modules.storage.errors import StorageError, StorageNotConnected
from app.modules.storage.models import GoogleDriveAccount
from app.providers.storage.google_drive import DRIVE_SCOPES

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------- persistence

def save_google_credentials(db: Session, credentials_json: str, email: str | None) -> GoogleDriveAccount:
    """Persist (encrypted) OAuth credentials, replacing the previous account."""
    account = db.query(GoogleDriveAccount).order_by(GoogleDriveAccount.id.desc()).first()
    encrypted = encrypt_token(credentials_json)
    if account is None:
        account = GoogleDriveAccount(
            email=email,
            credentials_encrypted=encrypted,
            status="connected",
        )
        db.add(account)
    else:
        account.email = email
        account.credentials_encrypted = encrypted
        account.status = "connected"
    db.commit()
    db.refresh(account)
    logger.info("google_account_saved", account_id=account.id, email=email)
    return account


def get_google_account(db: Session) -> GoogleDriveAccount | None:
    return db.query(GoogleDriveAccount).order_by(GoogleDriveAccount.id.desc()).first()


def get_google_credentials(db: Session) -> Credentials:
    """Decrypt and materialize the active account's credentials."""
    account = get_google_account(db)
    if account is None:
        raise StorageNotConnected()
    try:
        token_json = decrypt_token(account.credentials_encrypted)
    except InvalidToken as exc:
        raise StorageError(
            "TOKEN_DECRYPTION_FAILED",
            "Stored Google token cannot be decrypted (key changed?). Reconnect the account.",
        ) from exc
    return Credentials.from_authorized_user_info(json.loads(token_json), scopes=DRIVE_SCOPES)


# -------------------------------------------------------------------- status

def account_status(db: Session) -> dict:
    """Connection status + account info + storage quota (§69)."""
    try:
        account = get_google_account(db)
    except Exception:  # database unreachable — report gracefully, don't 500
        logger.warning("drive_status_db_unavailable")
        return {"connected": False, "error": "database_unavailable"}

    if account is None:
        return {"connected": False}

    try:
        credentials = get_google_credentials(db)
        session = AuthorizedSession(credentials)
        about = session.get(
            "https://www.googleapis.com/drive/v3/about",
            params={"fields": "user(emailAddress),storageQuota"},
        )
        if not about.ok:
            logger.warning("drive_status_about_failed", status=about.status_code)
            return {"connected": False, "error": "token_invalid"}
        quota = about.json().get("storageQuota", {})
        return {
            "connected": True,
            "email": about.json().get("user", {}).get("emailAddress"),
            "storage_used": quota.get("usage"),
            "storage_limit": quota.get("limit"),
        }
    except Exception as exc:
        logger.warning("drive_status_failed", error=str(exc))
        return {"connected": False, "error": "storage_error"}


# ------------------------------------------------------------------ bootstrap

def ensure_folder_structure(provider) -> dict[str, str]:
    """Create the ClipForge folder tree (§8); returns {folder_name: drive_id}."""
    root_id = provider.create_folder("")
    folders = {settings.google_drive_root_folder: root_id}
    for folder in DRIVE_FOLDERS:
        folders[folder] = provider.create_folder(folder)
    logger.info("drive_folder_structure_ensured", folders=list(folders))
    return folders


def oauth_config_available() -> None:
    """Raise a clear error when Google OAuth is not configured in .env."""
    missing = [
        name
        for name, value in (
            ("GOOGLE_CLIENT_ID", settings.google_client_id),
            ("GOOGLE_CLIENT_SECRET", settings.google_client_secret),
            ("GOOGLE_REDIRECT_URI", settings.google_redirect_uri),
        )
        if not value
    ]
    if missing:
        raise UnsetSettingError(
            "GOOGLE_OAUTH_NOT_CONFIGURED",
            "Set " + ", ".join(missing) + " in .env (see README → Google Drive Setup).",
        )
