"""DriveWatcher — polls the Google Drive inbox for new files (§66).

Phase 2 shipped detection only (``drive_file_detected``); Phase 10 wires
detection into the pipeline: every new **video** file in ``01_Inbox`` is
registered as a ``pending`` video and an ``IMPORT_INBOX_FILE`` job is
enqueued — the "Drop" half of Drop & Forget. With ``AUTO_APPROVE=true`` the
worker then runs the rest of the pipeline unattended (transcribe → analyze →
auto-approve → render, and → publish with ``YOUTUBE_AUTO_PUBLISH=true``).

Non-video files are logged and ignored. Already-imported files (recorded in
``storage_files``) are skipped, so a worker restart never double-imports.

Polling is deliberately non-aggressive (``DRIVE_POLL_INTERVAL`` seconds,
default 60) and degrades to warnings instead of crashing the worker.
"""

from __future__ import annotations

import asyncio
import os

import structlog
from redis import RedisError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.jobs.queue import JOB_IMPORT_INBOX_FILE, enqueue
from app.modules.storage.constants import DRIVE_FOLDERS
from app.modules.storage.models import StorageFile
from app.modules.videos.models import Video
from app.providers.storage.factory import get_storage_provider

logger = structlog.get_logger(__name__)

INBOX = DRIVE_FOLDERS[0]  # "01_Inbox"

# Containers the pipeline can process (ffmpeg reads all of them; yt-dlp output
# is mp4). ``mime_type`` wins when present (Drive reports it reliably).
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mpeg", ".mpg", ".ts"}


def is_video_file(filename: str, mime_type: str | None = None) -> bool:
    """True for files the pipeline can import: a video/ mime type or a known
    video container extension (covers files Drive reports without a mime)."""
    if mime_type:
        if mime_type.startswith("video/"):
            return True
        # Google-native items (folders, docs, shortcuts) are never video.
        if mime_type.startswith("application/vnd.google-apps."):
            return False
    return os.path.splitext(filename)[1].lower() in _VIDEO_EXTENSIONS


class DriveWatcher:
    def __init__(self) -> None:
        self._interval = settings.drive_poll_interval
        self._seen: set[str] = set()

    async def run(self) -> None:
        logger.info(
            "drive_watcher_started",
            interval_seconds=self._interval,
            root=settings.google_drive_root_folder,
            inbox=INBOX,
        )
        while True:
            try:
                await self._poll_once()
            except Exception:
                logger.warning("drive_watch_poll_failed", exc_info=True)
            await asyncio.sleep(self._interval)

    async def _poll_once(self) -> None:
        # list_files is blocking (Drive API); keep the event loop responsive.
        files = await asyncio.to_thread(self._list_inbox)
        for file in files:
            if file.id in self._seen:
                continue
            self._seen.add(file.id)
            if not is_video_file(file.filename, file.mime_type):
                logger.info(
                    "drive_file_ignored",
                    file_id=file.id,
                    filename=file.filename,
                    mime_type=file.mime_type,
                    reason="not a video file",
                )
                continue
            logger.info(
                "drive_file_detected",
                file_id=file.id,
                filename=file.filename,
                mime_type=file.mime_type,
                size=file.size,
            )
            await asyncio.to_thread(self._import_file, file)

    def _import_file(self, file) -> None:
        """Register the inbox video and enqueue its import job (§66 → Phase 10)."""
        from app.database.session import SessionLocal

        with SessionLocal() as db:
            if self._already_imported(db, file.id):
                logger.info(
                    "drive_file_already_imported", file_id=file.id, filename=file.filename
                )
                return
            video = Video(
                source_url=f"{INBOX}/{file.filename}",
                title=file.filename,
                status="pending",
            )
            db.add(video)
            db.commit()
            db.refresh(video)

            try:
                enqueue(
                    JOB_IMPORT_INBOX_FILE,
                    {
                        "video_id": video.id,
                        "file_id": file.id,
                        "filename": file.filename,
                    },
                )
            except RedisError:
                logger.warning(
                    "drive_file_import_queue_failed",
                    video_id=video.id,
                    file_id=file.id,
                    filename=file.filename,
                )
                return

            logger.info(
                "drive_file_import_queued",
                video_id=video.id,
                file_id=file.id,
                filename=file.filename,
            )

    @staticmethod
    def _already_imported(db: Session, file_id: str) -> bool:
        """A ``storage_files`` row for this Drive file means it was already
        imported (or is being processed) — never import it twice."""
        return (
            db.query(StorageFile).filter(StorageFile.provider_file_id == file_id).first()
            is not None
        )

    def _list_inbox(self):
        from app.database.session import SessionLocal

        with SessionLocal() as db:
            return get_storage_provider(db).list_files(INBOX)


def watcher_enabled() -> bool:
    """Drive watching needs google_drive provider + configured OAuth."""
    return bool(
        settings.storage_provider == "google_drive"
        and settings.google_client_id
        and settings.google_client_secret
    )
