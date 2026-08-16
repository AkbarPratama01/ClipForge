"""Storage provider factory — selects the backend from ``STORAGE_PROVIDER``.

Application code only ever depends on the :class:`StorageProvider` interface,
so the backend can be swapped via environment variable (§11, §58).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.storage.errors import StorageError
from app.providers.base import StorageProvider


def get_storage_provider(db: Session) -> StorageProvider:
    provider = settings.storage_provider
    if provider == "local":
        from app.providers.storage.local import LocalStorageProvider

        return LocalStorageProvider(settings.temp_storage_path)

    if provider == "google_drive":
        from app.modules.storage.service import get_google_credentials
        from app.providers.storage.google_drive import GoogleDriveProvider

        return GoogleDriveProvider(credentials=get_google_credentials(db))

    raise StorageError(
        "STORAGE_PROVIDER_UNSUPPORTED",
        f"Unknown STORAGE_PROVIDER={provider!r} (supported: google_drive, local)",
    )
