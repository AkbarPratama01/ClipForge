"""LocalStorageProvider — on-disk backend for development and fallback.

Remote paths map under ``root`` (the temp storage path). All access is
contained under ``root``: paths are normalized and verified with
``is_relative_to`` so ``../`` traversal is rejected (§51 path traversal
protection).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import structlog

from app.modules.storage.constants import sanitize_filename, split_remote_path
from app.modules.storage.errors import StorageError
from app.providers.base import StorageFile, StorageProvider

logger = structlog.get_logger(__name__)


class LocalStorageProvider(StorageProvider):
    def __init__(self, root: str) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ utils

    def _safe_path(self, remote_path: str) -> Path:
        segments = [sanitize_filename(s) for s in split_remote_path(remote_path)]
        if not segments:
            raise StorageError("STORAGE_ERROR", f"invalid remote path: {remote_path!r}")
        candidate = (self._root.joinpath(*segments)).resolve()
        if not candidate.is_relative_to(self._root):
            raise StorageError("STORAGE_ERROR", "path traversal rejected")
        return candidate

    # ------------------------------------------------------------- interface

    def upload(self, local_path: str, remote_path: str, mime_type: str | None = None) -> StorageFile:
        source = Path(local_path)
        if not source.is_file():
            raise StorageError("STORAGE_ERROR", f"local file missing: {local_path}")
        destination = self._safe_path(remote_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return self._to_storage_file(remote_path, destination)

    def download(self, remote_path: str, local_path: str) -> str:
        source = self._safe_path(remote_path)
        destination = Path(local_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return str(destination)

    def delete(self, remote_path: str) -> None:
        path = self._safe_path(remote_path)
        if path.is_file():
            path.unlink()
        logger.info("local_file_deleted", remote_path=remote_path)

    def move(self, source: str, destination: str) -> None:
        src = self._safe_path(source)
        dst = self._safe_path(destination)
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)

    def create_folder(self, path: str) -> str:
        folder = self._safe_path(path)
        folder.mkdir(parents=True, exist_ok=True)
        return str(folder)

    def list_files(self, path: str) -> list[StorageFile]:
        folder = self._safe_path(path)
        if not folder.is_dir():
            return []
        return [
            self._to_storage_file(path, entry)
            for entry in sorted(folder.iterdir(), key=lambda p: p.stat().st_mtime)
            if entry.is_file()
        ]

    def get_metadata(self, path: str) -> dict:
        candidate = self._safe_path(path)
        if not candidate.is_file():
            raise StorageError("STORAGE_ERROR", f"file not found: {path}")
        stat = candidate.stat()
        return {
            "id": str(candidate),
            "name": candidate.name,
            "size": stat.st_size,
            "mimeType": "application/octet-stream",
            "createdTime": str(stat.st_ctime),
        }

    def _to_storage_file(self, remote_path: str, path: Path) -> StorageFile:
        return StorageFile(
            id=str(path),
            filename=path.name,
            mime_type=None,
            size=path.stat().st_size,
            checksum=None,
            created_at=str(path.stat().st_mtime),
            metadata={"remote_path": remote_path},
        )
