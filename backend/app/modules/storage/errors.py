"""Storage error types.

Every storage failure carries an error code (§62) so the dashboard can display
and retry failures without the whole pipeline crashing.
"""

from __future__ import annotations


class StorageError(Exception):
    """Base storage error with a machine-readable code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class StorageNotConnected(StorageError):
    """No usable storage account is connected."""

    def __init__(self) -> None:
        super().__init__("STORAGE_NOT_CONNECTED", "No Google Drive account is connected.")


class DriveApiError(StorageError):
    """Google Drive API call failed."""

    def __init__(self, detail: str) -> None:
        super().__init__("DRIVE_API_ERROR", detail)
