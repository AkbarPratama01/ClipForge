"""GoogleDriveProvider — Drive API v3 over OAuth 2.0 (Phase 2).

Implements the :class:`StorageProvider` contract with the official Google
Drive REST API. Media flows:

- upload   : resumable upload in 8 MiB chunks, verified by size + md5Checksum
- download : streamed to local disk, verified by size
- delete   : moves to trash (reversible) — permanent delete is explicit
- move     : Drive "move" = change parents (and optionally rename)
- folders  : resolved/created by walking the remote path from the ClipForge
             root folder, all idempotent
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import structlog
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials

from app.core.config import settings
from app.modules.storage.constants import DRIVE_ROOT_FOLDER, sanitize_filename, split_remote_path
from app.modules.storage.errors import DriveApiError, StorageError
from app.providers.base import StorageFile, StorageProvider

logger = structlog.get_logger(__name__)

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]
API_BASE = "https://www.googleapis.com/drive/v3"
UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3/files"
FILE_FIELDS = "id,name,mimeType,size,md5Checksum,createdTime"
FOLDER_MIME = "application/vnd.google-apps.folder"
CHUNK_SIZE = 8 * 1024 * 1024  # 8 MiB


class GoogleDriveProvider(StorageProvider):
    def __init__(self, credentials: Credentials, root_folder: str | None = None) -> None:
        self._credentials = credentials
        self._root_folder = root_folder or settings.google_drive_root_folder or DRIVE_ROOT_FOLDER
        self._session: AuthorizedSession | None = None
        self._root_id: str | None = None

    # ------------------------------------------------------------------ utils

    def _get_session(self) -> AuthorizedSession:
        if self._session is None:
            self._session = AuthorizedSession(self._credentials)
        return self._session

    @staticmethod
    def _check(resp: Any, *, what: str) -> None:
        """Raise DriveApiError unless the response is OK."""
        if resp.ok:
            return
        try:
            detail = resp.json().get("error", {}).get("message") or resp.text
        except ValueError:
            detail = resp.text
        code = "DRIVE_FILE_NOT_FOUND" if resp.status_code == 404 else "DRIVE_API_ERROR"
        logger.warning("drive_api_error", what=what, status=resp.status_code, code=code)
        raise DriveApiError(f"{what}: HTTP {resp.status_code} — {detail}")

    def _resolve_root(self) -> str:
        """Find the ClipForge root folder under My Drive; create it if missing."""
        if self._root_id is not None:
            return self._root_id
        session = self._get_session()
        resp = session.get(
            f"{API_BASE}/files",
            params={
                "q": f"name = '{self._root_folder}' and 'root' in parents "
                f"and mimeType = '{FOLDER_MIME}' and trashed = false",
                "fields": "files(id)",
                "pageSize": 1,
            },
        )
        self._check(resp, what="resolve root folder")
        files = resp.json().get("files", [])
        if files:
            self._root_id = files[0]["id"]
            return self._root_id

        resp = session.post(
            f"{API_BASE}/files",
            json={"name": self._root_folder, "mimeType": FOLDER_MIME, "parents": ["root"]},
            params={"fields": "id"},
        )
        self._check(resp, what="create root folder")
        self._root_id = resp.json()["id"]
        logger.info("drive_root_folder_created", folder=self._root_folder, id=self._root_id)
        return self._root_id

    def _normalize_path(self, remote_path: str) -> str:
        segments = split_remote_path(remote_path)
        if segments and segments[0] == self._root_folder:
            segments = segments[1:]
        return "/".join(segments)

    def _find_child(self, parent_id: str, name: str, *, folder: bool = False) -> str | None:
        session = self._get_session()
        mime_clause = f" and mimeType = '{FOLDER_MIME}'" if folder else ""
        resp = session.get(
            f"{API_BASE}/files",
            params={
                "q": f"name = '{name}' and '{parent_id}' in parents "
                f"and trashed = false{mime_clause}",
                "fields": "files(id)",
                "pageSize": 1,
            },
        )
        self._check(resp, what=f"find child '{name}'")
        files = resp.json().get("files", [])
        return files[0]["id"] if files else None

    def _ensure_folder(self, path: str) -> str:
        """Walk ``path`` from the root, creating missing folders; return leaf id."""
        parent_id = self._resolve_root()
        session = self._get_session()
        for segment in split_remote_path(path):
            child_id = self._find_child(parent_id, segment, folder=True)
            if child_id is None:
                resp = session.post(
                    f"{API_BASE}/files",
                    json={"name": segment, "mimeType": FOLDER_MIME, "parents": [parent_id]},
                    params={"fields": "id"},
                )
                self._check(resp, what=f"create folder '{segment}'")
                child_id = resp.json()["id"]
                logger.info("drive_folder_created", folder=segment, parent=parent_id)
            parent_id = child_id
        return parent_id

    def _resolve_file_id(self, remote_path: str) -> str:
        segments = split_remote_path(self._normalize_path(remote_path))
        if not segments:
            raise DriveApiError(f"cannot resolve empty remote path: {remote_path!r}")
        folder_path, filename = "/".join(segments[:-1]), segments[-1]
        parent_id = self._ensure_folder(folder_path)
        file_id = self._find_child(parent_id, filename)
        if file_id is None:
            raise DriveApiError(f"file not found at {remote_path!r}")
        return file_id

    @staticmethod
    def _to_storage_file(item: dict) -> StorageFile:
        return StorageFile(
            id=item["id"],
            filename=item.get("name", ""),
            mime_type=item.get("mimeType"),
            size=item.get("size"),
            checksum=item.get("md5Checksum"),
            created_at=item.get("createdTime"),
        )

    # ------------------------------------------------------------- interface

    def upload(
        self, local_path: str, remote_path: str, mime_type: str | None = None
    ) -> StorageFile:
        local = Path(local_path)
        if not local.is_file():
            raise StorageError("STORAGE_ERROR", f"local file missing: {local_path}")

        segments = split_remote_path(self._normalize_path(remote_path))
        if not segments:
            raise DriveApiError(f"invalid remote path: {remote_path!r}")
        folder_path, filename = "/".join(segments[:-1]), sanitize_filename(segments[-1])
        parent_id = self._ensure_folder(folder_path)

        mime = mime_type or "application/octet-stream"
        size = local.stat().st_size
        session = self._get_session()

        start = session.post(
            f"{UPLOAD_BASE}?uploadType=resumable&fields={FILE_FIELDS}",
            json={"name": filename, "mimeType": mime, "parents": [parent_id]},
            headers={
                "X-Upload-Content-Type": mime,
                "X-Upload-Content-Length": str(size),
            },
        )
        self._check(start, what="start resumable upload")
        session_uri = start.headers["Location"]

        offset = 0
        with open(local, "rb") as fh:
            while offset < size:
                chunk = fh.read(CHUNK_SIZE)
                if not chunk:
                    break
                end = offset + len(chunk) - 1
                resp = session.put(
                    session_uri,
                    content=chunk,
                    headers={"Content-Range": f"bytes {offset}-{end}/{size}"},
                )
                offset = end + 1
        # Final 200 response carries the file metadata.
        if resp.status_code != 200:
            self._check(resp, what="finish resumable upload")

        item = resp.json()
        remote_file = self._to_storage_file(item)

        # Verify the upload: size and Drive's md5Checksum must match the local
        # file before we report success (§28 "don't delete before verification").
        from app.modules.storage.checksum import md5_file

        local_md5 = md5_file(local)
        if remote_file.size is not None and int(remote_file.size) != size:
            raise StorageError(
                "DRIVE_UPLOAD_FAILED",
                f"size mismatch after upload: local={size} remote={remote_file.size}",
            )
        if remote_file.checksum and remote_file.checksum != local_md5:
            raise StorageError(
                "DRIVE_UPLOAD_FAILED",
                "md5Checksum mismatch after upload — file corrupted in transit",
            )

        logger.info(
            "drive_upload_completed",
            remote_path=f"{self._root_folder}/{remote_path}",
            file_id=item["id"],
            size=size,
            checksum=remote_file.checksum,
        )
        return remote_file

    def download(self, remote_path: str, local_path: str) -> str:
        file_id = self._resolve_file_id(remote_path)
        return self.download_by_id(file_id, local_path)

    def download_by_id(self, file_id: str, local_path: str) -> str:
        session = self._get_session()
        destination = Path(local_path)
        destination.parent.mkdir(parents=True, exist_ok=True)

        meta_resp = session.get(f"{API_BASE}/files/{file_id}", params={"fields": FILE_FIELDS})
        self._check(meta_resp, what="download metadata")
        meta = meta_resp.json()

        resp = session.get(f"{API_BASE}/files/{file_id}?alt=media", stream=True)
        self._check(resp, what="download media")

        written = 0
        with open(destination, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                fh.write(chunk)
                written += len(chunk)

        expected = meta.get("size")
        if expected is not None and written != int(expected):
            raise StorageError(
                "DRIVE_DOWNLOAD_FAILED",
                f"size mismatch after download: got={written} expected={expected}",
            )

        logger.info(
            "drive_download_completed",
            file_id=file_id,
            local_path=str(destination),
            size=written,
        )
        return str(destination)

    def delete(self, remote_path: str) -> None:
        file_id = self._resolve_file_id(remote_path)
        session = self._get_session()
        resp = session.post(f"{API_BASE}/files/{file_id}/trash")
        self._check(resp, what="trash file")
        logger.info("drive_file_trashed", file_id=file_id, remote_path=remote_path)

    def move(self, source: str, destination: str) -> None:
        session = self._get_session()
        file_id = self._resolve_file_id(source)

        dest_segments = split_remote_path(self._normalize_path(destination))
        if not dest_segments:
            raise DriveApiError(f"invalid destination path: {destination!r}")
        dest_folder, new_name = "/".join(dest_segments[:-1]), dest_segments[-1]
        new_parent_id = self._ensure_folder(dest_folder)

        # Drive "move" = add the new parent and remove the current ones. Fetch
        # the source parents first (they are not necessarily "root").
        meta_resp = session.get(
            f"{API_BASE}/files/{file_id}", params={"fields": "id,parents,name"}
        )
        self._check(meta_resp, what="read source parents")
        old_parents = [
            p for p in meta_resp.json().get("parents", []) if p != new_parent_id
        ]

        params = {
            "addParents": new_parent_id,
            "fields": "id,parents,name",
        }
        if old_parents:
            params["removeParents"] = ",".join(old_parents)

        # Rename when the destination file name differs.
        resp = session.patch(
            f"{API_BASE}/files/{file_id}",
            params=params,
            json={"name": new_name},
        )
        self._check(resp, what="move file")
        logger.info("drive_file_moved", file_id=file_id, source=source, destination=destination)

    def create_folder(self, path: str) -> str:
        folder_id = self._ensure_folder(self._normalize_path(path))
        logger.info("drive_folder_ensured", path=path, id=folder_id)
        return folder_id

    def list_files(self, path: str) -> list[StorageFile]:
        folder_id = self._ensure_folder(self._normalize_path(path))
        session = self._get_session()
        resp = session.get(
            f"{API_BASE}/files",
            params={
                "q": f"'{folder_id}' in parents and trashed = false "
                f"and mimeType != '{FOLDER_MIME}'",
                "fields": f"files({FILE_FIELDS})",
                "pageSize": 1000,
                "orderBy": "createdTime",
            },
        )
        self._check(resp, what="list files")
        return [self._to_storage_file(item) for item in resp.json().get("files", [])]

    def get_metadata(self, path: str) -> dict:
        return self.get_metadata_by_id(self._resolve_file_id(path))

    def get_metadata_by_id(self, file_id: str) -> dict:
        session = self._get_session()
        resp = session.get(f"{API_BASE}/files/{file_id}", params={"fields": FILE_FIELDS})
        self._check(resp, what="get metadata")
        return resp.json()

    def about(self) -> dict:
        """Account + storage quota (§69 dashboard storage management)."""
        session = self._get_session()
        resp = session.get(
            f"{API_BASE}/about", params={"fields": "user(emailAddress),storageQuota"}
        )
        self._check(resp, what="get about")
        return resp.json()
