"""Symmetric encryption for OAuth tokens at rest (Fernet/AES-128-CBC + HMAC).

Tokens are encrypted before they touch the database and never appear in logs.
The encryption key comes from ``TOKEN_ENCRYPTION_KEY`` (base64, 32 bytes).

Run ``python -m app.core.crypto`` to generate a fresh key for .env.
"""

import structlog
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings
from app.core.settings_error import UnsetSettingError

logger = structlog.get_logger(__name__)

_fernet: Fernet | None = None
_fernet_key: str | None = None
_ephemeral_warned = False


def require_token_encryption_key() -> str:
    """Return the configured Fernet key, or fail loudly.

    Storing OAuth tokens under the process-local ephemeral key silently
    breaks every other process (worker) and every restart — the dashboard
    would show "connected" while uploads fail with TOKEN_DECRYPTION_FAILED.
    Production must set ``TOKEN_ENCRYPTION_KEY`` in .env.
    """
    if not settings.token_encryption_key:
        raise UnsetSettingError(
            "TOKEN_ENCRYPTION_KEY_MISSING",
            "TOKEN_ENCRYPTION_KEY is not set in .env — generate one with "
            "`python -m app.core.crypto`, add it to .env, then recreate the "
            "containers (docker compose up -d).",
        )
    return settings.token_encryption_key


def _get_fernet() -> Fernet:
    global _fernet, _fernet_key, _ephemeral_warned

    key = settings.token_encryption_key
    if not key:
        # Development convenience only: an ephemeral key means stored tokens
        # become undecryptable after a restart. Production must set the var.
        if not _ephemeral_warned:
            logger.warning(
                "token_encryption_key_missing",
                detail=(
                    "TOKEN_ENCRYPTION_KEY is not set; using an ephemeral key. "
                    "OAuth tokens will be lost on restart."
                ),
            )
            _ephemeral_warned = True
        # Stable ephemeral key for this process (generated once).
        if _fernet is None:
            _fernet = Fernet(Fernet.generate_key())
        return _fernet

    # Rebuild when the configured key changes (rotation / tests); decrypting
    # tokens produced under the old key will then raise InvalidToken.
    if _fernet is None or _fernet_key != key:
        _fernet = Fernet(key.encode())
        _fernet_key = key
    return _fernet


def encrypt_token(plaintext: str) -> str:
    """Encrypt ``plaintext``; returns a URL-safe base64 token string."""
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_token(token: str) -> str:
    """Decrypt a token produced by :func:`encrypt_token`."""
    try:
        return _get_fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        logger.error("token_decryption_failed", reason="invalid key or corrupted token")
        raise


if __name__ == "__main__":
    # Generate a Fernet key for TOKEN_ENCRYPTION_KEY.
    print(Fernet.generate_key().decode())
