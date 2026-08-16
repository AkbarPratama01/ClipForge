"""Worker job consumer — Phase 3 (download) + Phase 4 (transcribe) +
Phase 5 (analyze) + Phase 6 (render) + Phase 8-9 (publish) + Phase 10
(inbox import + automation chaining).

``DOWNLOAD_VIDEO``: yt-dlp metadata + download (best video+audio merged to MP4),
SHA-256 checksum, duplicate detection (§67), upload to Drive ``02_Processing``,
record ``storage_files``. The local file is **kept** after upload — later
pipeline stages (transcribe/analyze/render) process from local disk; cleanup
follows the retention policy (§68).

``IMPORT_INBOX_FILE``: a video dropped into Drive ``01_Inbox`` (Phase 10) is
downloaded, checksummed, duplicate-checked, recorded, and moved to
``02_Processing`` — the "Drop" half of Drop & Forget.

``TRANSCRIBE``: locate the local video (or fetch it back from storage),
extract 16 kHz mono audio (ffmpeg), run local Whisper (faster-whisper), save
the cached transcript (§15), then delete the extracted audio.

``ANALYZE``: AI clip finding (§16–§20) — transcript → candidates with
sentence-boundary timestamps and §19 scores (cached per video, §55).

``RENDER``: 9:16 smart crop + burned-in subtitles + hook text via FFmpeg,
with the Phase 6 quality gate (ffprobe verification).

``PUBLISH``: upload a rendered Short to YouTube (Phase 8-9).

Automatic mode (Phase 10): when ``AUTO_APPROVE=true`` each successful stage
chains the next one (download → transcribe → analyze → auto-approve → render);
when ``YOUTUBE_AUTO_PUBLISH=true`` a successful render chains PUBLISH. All
blocking work runs via ``asyncio.to_thread``; ``MAX_CONCURRENT_JOBS``
consumers (default 1 on Orange Pi, §47). Unexpected handler crashes are
retried up to ``MAX_JOB_RETRIES`` times with exponential backoff (§63).
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import time

import structlog
import yt_dlp
from redis import RedisError

from app.core.config import settings
from app.core.redis import get_redis
from app.database.session import SessionLocal
from app.modules.jobs.queue import (
    JOB_ANALYZE,
    JOB_IMPORT_INBOX_FILE,
    JOB_PUBLISH,
    JOB_RENDER,
    JOB_TRANSCRIBE,
    dequeue,
    enqueue,
    requeue,
    retry_delay_seconds,
)
from app.modules.storage.checksum import sha256_file
from app.modules.storage.constants import DRIVE_FOLDERS, sanitize_filename
from app.modules.storage.errors import StorageError
from app.modules.storage.models import StorageFile
from app.modules.analysis.errors import AnalysisError
from app.modules.analysis.models import ClipCandidate
from app.modules.analysis.service import analyze_video, auto_approve_best_candidate
from app.modules.rendering.errors import RenderError
from app.modules.rendering.service import get_render, render_clip
from app.modules.publishing.errors import PublishingError
from app.modules.publishing.models import Publication
from app.modules.publishing.service import create_publication, publish_clip
from app.modules.transcription.service import get_transcript, save_transcript
from app.modules.videos.models import Video
from app.modules.videos.service import (
    find_duplicate,
    set_status,
    update_metadata,
)
from app.providers.storage.factory import get_storage_provider
from app.providers.transcription.factory import get_transcription_provider

logger = structlog.get_logger(__name__)

INBOX = DRIVE_FOLDERS[0]  # "01_Inbox"
OUTPUT_FOLDER = DRIVE_FOLDERS[1]  # "02_Processing"

# Cap source height at 1080p: the renderer outputs 1080×1920 (§RENDER), so
# 4K sources add bandwidth and trigger YouTube 403 throttling without quality
# benefit. Falls back to any combined stream if no ≤1080p mp4 exists.
_YTDL_OPTS = {
    "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/b[height<=1080]/b",
    "merge_output_format": "mp4",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
}


def _chain_next(job_type: str, payload: dict, **context) -> None:
    """Best-effort enqueue of the next pipeline stage (Phase 10 chaining).

    Chaining must never fail the completed stage: the stage's work is already
    persisted, and every handler is idempotent (cached transcripts, renders,
    publications), so a missing follow-up job can be triggered manually or by
    re-running the job.
    """
    try:
        enqueue(job_type, payload)
        logger.info("job_chain_enqueued", job_type=job_type, **context)
    except RedisError:
        logger.warning("job_chain_enqueue_failed", job_type=job_type, **context)


def _progress_percent(data: dict) -> float | None:
    """yt-dlp progress hook payload → download percentage (None when unknown)."""
    total = data.get("total_bytes") or data.get("total_bytes_estimate")
    downloaded = data.get("downloaded_bytes") or 0
    if not total:
        return None
    return min(100.0, downloaded / total * 100)


def _download_progress_hook(video_id: int):
    """yt-dlp progress hook: percent → Redis, where the API/dashboard reads it."""
    key = f"clipforge:progress:video:{video_id}"

    def hook(data: dict) -> None:
        if data.get("status") != "downloading":
            return
        percent = _progress_percent(data)
        if percent is None:
            return
        try:
            get_redis().set(key, f"{percent:.1f}", ex=3600)
        except RedisError:
            pass

    return hook


def _clear_download_progress(video_id: int) -> None:
    try:
        get_redis().delete(f"clipforge:progress:video:{video_id}")
    except RedisError:
        pass


def _download_to(url: str, dest_dir: str, progress_hook=None) -> dict:
    os.makedirs(dest_dir, exist_ok=True)
    opts = {
        **_YTDL_OPTS,
        "outtmpl": os.path.join(dest_dir, "%(id)s.%(ext)s"),
    }
    if progress_hook is not None:
        opts["progress_hooks"] = [progress_hook]
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=True)


def _find_output(dest_dir: str) -> str:
    candidates = sorted(glob.glob(os.path.join(dest_dir, "*.mp4")), key=os.path.getsize)
    if not candidates:
        raise StorageError("DOWNLOAD_FAILED", "yt-dlp produced no .mp4 output")
    return candidates[-1]  # largest = merged file


def _cleanup(dest_dir: str) -> None:
    shutil.rmtree(dest_dir, ignore_errors=True)


def _download_with_retry(
    url: str,
    dest_dir: str,
    progress_hook=None,
    attempts: int = 4,
    delay: float = 5.0,
) -> dict:
    """Download with retries: YouTube's CDN intermittently answers 403 on the
    stream request (per-CDN-node throttling), and a fresh extraction usually
    picks a working node. Clean partial files between attempts so yt-dlp
    restarts from a clean state."""
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            _cleanup(dest_dir)
            time.sleep(delay)
        try:
            return _download_to(url, dest_dir, progress_hook=progress_hook)
        except Exception as exc:  # yt-dlp raises DownloadError on HTTP failures
            last_exc = exc
            logger.warning(
                "download_retry",
                url=url,
                attempt=attempt,
                error=str(exc)[:300],
            )
    assert last_exc is not None
    raise last_exc


def handle_download_video(payload: dict) -> None:
    video_id = payload.get("video_id")
    upload_to_drive = payload.get("upload_to_drive", True)
    if not video_id:
        logger.warning("job_missing_video_id", payload=payload)
        return

    with SessionLocal() as db:
        video = db.get(Video, video_id)
        if video is None:
            logger.warning("job_video_not_found", video_id=video_id)
            return
        if video.status in {"downloading", "downloaded", "uploaded", "completed"}:
            logger.info("job_skip_already_processed", video_id=video_id, status=video.status)
            return

        set_status(db, video, "downloading")
        logger.info("download_started", video_id=video_id, url=video.source_url)

        dest_dir = os.path.join(settings.temp_storage_path, "videos", str(video_id))
        try:
            info = _download_with_retry(
                video.source_url,
                dest_dir,
                progress_hook=_download_progress_hook(video_id),
            )
            update_metadata(db, video, info)

            local_path = _find_output(dest_dir)
            checksum = sha256_file(local_path)
            video.checksum = checksum
            video.filesize = os.path.getsize(local_path)
            db.commit()
            db.refresh(video)

            duplicate = find_duplicate(db, video, checksum)
            if duplicate is not None:
                _clear_download_progress(video_id)
                set_status(db, video, "duplicate")
                logger.info(
                    "duplicate_detected",
                    video_id=video_id,
                    existing_video_id=duplicate.id,
                    checksum=checksum,
                )
                _cleanup(dest_dir)
                return

            _clear_download_progress(video_id)
            set_status(db, video, "downloaded")
            logger.info(
                "download_completed",
                video_id=video_id,
                filesize=video.filesize,
                checksum=checksum,
                duration=video.duration,
            )

            if upload_to_drive:
                provider = get_storage_provider(db)
                remote_path = f"{OUTPUT_FOLDER}/{video_id}.mp4"
                remote = provider.upload(local_path, remote_path, mime_type="video/mp4")

                db.add(
                    StorageFile(
                        provider=settings.storage_provider,
                        provider_file_id=remote.id,
                        local_path=local_path,
                        remote_path=remote_path,
                        filename=remote.filename,
                        mime_type="video/mp4",
                        size=video.filesize,
                        checksum=checksum,
                        status="uploaded",
                        video_id=video.id,
                    )
                )
                db.commit()
                set_status(db, video, "uploaded")
                logger.info(
                    "drive_upload_completed",
                    video_id=video_id,
                    remote_path=remote_path,
                    provider_file_id=remote.id,
                )
                # Upload verified (size + checksum in the provider). The local
                # file is kept for later pipeline stages (transcribe/analyze/
                # render); retention cleanup runs per §68.
                logger.info(
                    "local_file_kept_for_processing",
                    video_id=video_id,
                    local_path=local_path,
                    retention_hours=settings.temp_file_retention_hours,
                )

            # Phase 10: automatic mode continues the pipeline without the
            # dashboard (idempotent TRANSCRIBE — cached transcripts are skipped).
            if settings.auto_approve:
                _chain_next(JOB_TRANSCRIBE, {"video_id": video_id}, video_id=video_id)
        except yt_dlp.utils.DownloadError as exc:
            _clear_download_progress(video_id)
            set_status(db, video, "failed", error_code="DOWNLOAD_FAILED")
            logger.warning("download_failed", video_id=video_id, error=str(exc)[:300])
            _cleanup(dest_dir)
        except StorageError as exc:
            _clear_download_progress(video_id)
            set_status(db, video, "failed", error_code=exc.code)
            logger.warning("video_import_storage_failed", video_id=video_id, code=exc.code)
            _cleanup(dest_dir)
        except Exception as exc:
            _clear_download_progress(video_id)
            set_status(db, video, "failed", error_code="VIDEO_IMPORT_FAILED")
            logger.warning("video_import_failed", video_id=video_id, error=str(exc)[:300])
            _cleanup(dest_dir)


# ---------------------------------------------------------------------------
# IMPORT_INBOX_FILE (Phase 10 — "Drop" half of Drop & Forget)
# ---------------------------------------------------------------------------


def handle_import_inbox_file(payload: dict) -> None:
    """Import a video dropped into Drive ``01_Inbox``.

    Downloads the file to local temp storage, computes the SHA-256 checksum,
    detects duplicates (§67, trashing the inbox copy), records
    ``storage_files``, then moves the original to ``02_Processing`` (mirroring
    YouTube imports — best-effort, a failed move never fails the import). In
    automatic mode the pipeline continues with TRANSCRIBE.
    """
    video_id = payload.get("video_id")
    file_id = payload.get("file_id")
    filename = payload.get("filename")
    if not video_id or not file_id or not filename:
        logger.warning("job_missing_inbox_file_fields", payload=payload)
        return

    with SessionLocal() as db:
        video = db.get(Video, video_id)
        if video is None:
            logger.warning("job_video_not_found", video_id=video_id)
            return
        if video.status in {"downloading", "downloaded", "uploaded", "completed"}:
            logger.info("job_skip_already_processed", video_id=video_id, status=video.status)
            return

        set_status(db, video, "downloading")
        logger.info(
            "inbox_import_started", video_id=video_id, file_id=file_id, filename=filename
        )

        dest_dir = os.path.join(settings.temp_storage_path, "videos", str(video_id))
        local_path: str | None = None
        try:
            provider = get_storage_provider(db)
            if not hasattr(provider, "download_by_id"):
                raise StorageError(
                    "DRIVE_IMPORT_FAILED",
                    "Inbox import requires the google_drive provider.",
                )

            meta = provider.get_metadata_by_id(file_id)
            mime_type = meta.get("mimeType") or "video/mp4"

            os.makedirs(dest_dir, exist_ok=True)
            name = sanitize_filename(filename) or f"{video_id}.mp4"
            local_path = os.path.join(dest_dir, name)
            provider.download_by_id(file_id, local_path)

            checksum = sha256_file(local_path)
            video.checksum = checksum
            video.filesize = os.path.getsize(local_path)
            db.commit()
            db.refresh(video)

            duplicate = find_duplicate(db, video, checksum)
            if duplicate is not None:
                set_status(db, video, "duplicate")
                logger.info(
                    "duplicate_detected",
                    video_id=video_id,
                    existing_video_id=duplicate.id,
                    checksum=checksum,
                )
                # Trash the inbox copy so a worker restart cannot re-import it.
                try:
                    provider.delete(f"{INBOX}/{filename}")
                except Exception as exc:
                    logger.warning(
                        "duplicate_inbox_trash_failed",
                        video_id=video_id,
                        error=str(exc)[:200],
                    )
                _cleanup(dest_dir)
                return

            set_status(db, video, "downloaded")

            storage_file = StorageFile(
                provider=settings.storage_provider,
                provider_file_id=file_id,
                local_path=local_path,
                remote_path=f"{INBOX}/{filename}",
                filename=filename,
                mime_type=mime_type,
                size=video.filesize,
                checksum=checksum,
                status="downloaded",
                video_id=video.id,
            )
            db.add(storage_file)
            db.commit()

            # Keep the inbox clean: the original moves to 02_Processing, same
            # destination as YouTube imports. Best-effort — a failed move must
            # not fail the import (the file stays in the inbox instead).
            ext = os.path.splitext(name)[1] or ".mp4"
            target = f"{OUTPUT_FOLDER}/{video_id}{ext}"
            try:
                provider.move(f"{INBOX}/{filename}", target)
                storage_file.remote_path = target
                storage_file.status = "uploaded"
                db.commit()
                set_status(db, video, "uploaded")
                logger.info(
                    "inbox_file_moved_to_processing",
                    video_id=video_id,
                    remote_path=target,
                )
            except Exception as exc:
                logger.warning(
                    "inbox_file_move_skipped",
                    video_id=video_id,
                    error=str(exc)[:200],
                )

            logger.info(
                "inbox_import_completed",
                video_id=video_id,
                filesize=video.filesize,
                checksum=checksum,
            )
            if settings.auto_approve:
                _chain_next(JOB_TRANSCRIBE, {"video_id": video_id}, video_id=video_id)
        except StorageError as exc:
            set_status(db, video, "failed", error_code=exc.code)
            logger.warning(
                "inbox_import_failed", video_id=video_id, code=exc.code, detail=exc.detail[:300]
            )
            _cleanup(dest_dir)
        except Exception as exc:
            set_status(db, video, "failed", error_code="DRIVE_IMPORT_FAILED")
            logger.warning("inbox_import_failed", video_id=video_id, error=str(exc)[:300])
            _cleanup(dest_dir)


# ---------------------------------------------------------------------------
# TRANSCRIBE (§14, §15, §47)
# ---------------------------------------------------------------------------


def _find_local_video(video_id: int) -> str | None:
    """Local copy for processing — mp4 first (yt-dlp output), then any file
    (inbox imports keep their original container, e.g. .mov/.mkv)."""
    base = os.path.join(settings.temp_storage_path, "videos", str(video_id))
    candidates = glob.glob(os.path.join(base, "*.mp4"))
    if not candidates:
        candidates = [
            path for path in glob.glob(os.path.join(base, "*")) if os.path.isfile(path)
        ]
    return max(candidates, key=os.path.getsize, default=None)


def _ensure_local_video(db, video: Video) -> str | None:
    """Local copy for processing — reuse the kept file or fetch it back from
    the configured storage backend (02_Processing/<id>.mp4)."""
    local = _find_local_video(video.id)
    if local:
        return local
    try:
        provider = get_storage_provider(db)
        remote_path = f"{OUTPUT_FOLDER}/{video.id}.mp4"
        destination = os.path.join(
            settings.temp_storage_path, "videos", str(video.id), f"{video.id}.mp4"
        )
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        return provider.download(remote_path, destination)
    except StorageError as exc:
        logger.warning("transcribe_local_video_unavailable", video_id=video.id, code=exc.code)
        return None


def extract_audio(video_path: str, audio_path: str) -> str:
    """16 kHz mono WAV — the Whisper standard. Args are a list (no shell,
    §51 command injection protection)."""
    os.makedirs(os.path.dirname(audio_path), exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", video_path, "-vn", "-ac", "1", "-ar", "16000", audio_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if proc.returncode != 0:
        raise StorageError(
            "TRANSCRIPTION_FAILED", f"ffmpeg audio extraction failed: {proc.stderr[-300:]}"
        )
    return audio_path


def handle_transcribe(payload: dict) -> None:
    video_id = payload.get("video_id")
    if not video_id:
        logger.warning("job_missing_video_id", payload=payload)
        return

    with SessionLocal() as db:
        video = db.get(Video, video_id)
        if video is None:
            logger.warning("job_video_not_found", video_id=video_id)
            return

        # §15: never transcribe twice — the cached transcript wins.
        if get_transcript(db, video_id) is not None:
            logger.info("transcript_cached_skip", video_id=video_id)
            if settings.auto_approve:
                _chain_next(JOB_ANALYZE, {"video_id": video_id}, video_id=video_id)
            return

        set_status(db, video, "transcribing")
        logger.info("transcription_started", video_id=video_id, model=settings.whisper_model)

        audio_path = os.path.join(settings.temp_storage_path, "audio", f"{video_id}.wav")
        try:
            local_video = _ensure_local_video(db, video)
            if local_video is None:
                raise StorageError(
                    "TRANSCRIPTION_FAILED",
                    "No local video and no storage copy available to transcribe.",
                )

            extract_audio(local_video, audio_path)
            provider = get_transcription_provider()
            result = provider.transcribe(
                audio_path, language=settings.whisper_language or None
            )
            save_transcript(db, video_id, result)
            set_status(db, video, "transcribed")
            logger.info(
                "transcription_completed",
                video_id=video_id,
                segments=len(result["segments"]),
                language=result.get("language"),
            )
            if settings.auto_approve:
                _chain_next(JOB_ANALYZE, {"video_id": video_id}, video_id=video_id)
        except StorageError as exc:
            set_status(db, video, "failed", error_code=exc.code)
            logger.warning("transcription_failed", video_id=video_id, code=exc.code)
        except Exception as exc:
            set_status(db, video, "failed", error_code="TRANSCRIPTION_FAILED")
            logger.warning("transcription_failed", video_id=video_id, error=str(exc)[:300])
        finally:
            if os.path.exists(audio_path):
                os.remove(audio_path)


# ---------------------------------------------------------------------------
# ANALYZE (§16–§20, §47)
# ---------------------------------------------------------------------------


def _maybe_auto_approve_and_render(db, video_id: int) -> None:
    """Phase 10: approve the best candidate (threshold-gated) and chain RENDER."""
    if not settings.auto_approve:
        return
    candidate = auto_approve_best_candidate(db, video_id)
    if candidate is None:
        return
    _chain_next(
        JOB_RENDER,
        {"candidate_id": candidate.id},
        video_id=video_id,
        candidate_id=candidate.id,
    )


def handle_analyze(payload: dict) -> None:
    video_id = payload.get("video_id")
    if not video_id:
        logger.warning("job_missing_video_id", payload=payload)
        return

    with SessionLocal() as db:
        video = db.get(Video, video_id)
        if video is None:
            logger.warning("job_video_not_found", video_id=video_id)
            return

        # §55: never re-analyze a video that already has candidates.
        existing = db.query(ClipCandidate).filter(ClipCandidate.video_id == video_id).count()
        if existing:
            logger.info("analysis_cached_skip", video_id=video_id, candidates=existing)
            _maybe_auto_approve_and_render(db, video_id)
            return

        set_status(db, video, "analyzing")
        logger.info("analysis_started", video_id=video_id, provider=settings.ai_provider)
        try:
            result = analyze_video(db, video_id)
            logger.info(
                "analysis_completed",
                video_id=video_id,
                candidates=result.get("count"),
            )
            _maybe_auto_approve_and_render(db, video_id)
        except AnalysisError as exc:
            set_status(db, video, "failed", error_code=exc.code)
            logger.warning("analysis_failed", video_id=video_id, code=exc.code)
        except Exception as exc:
            set_status(db, video, "failed", error_code="AI_ANALYSIS_FAILED")
            logger.warning("analysis_failed", video_id=video_id, error=str(exc)[:300])


# ---------------------------------------------------------------------------
# RENDER (Phase 6, §61)
# ---------------------------------------------------------------------------


def _maybe_auto_publish(db, render) -> None:
    """Phase 10: create a publication for a freshly rendered Short and chain
    PUBLISH when automatic publishing is enabled."""
    if not settings.youtube_auto_publish:
        return
    try:
        publication = create_publication(db, render)
    except Exception as exc:
        code = getattr(exc, "code", None) or type(exc).__name__
        logger.warning(
            "auto_publish_setup_failed",
            render_id=render.id,
            code=code,
            error=str(exc)[:300],
        )
        return
    _chain_next(
        JOB_PUBLISH,
        {"publication_id": publication.id, "auto": True},
        render_id=render.id,
        publication_id=publication.id,
    )


def handle_render(payload: dict) -> None:
    """Render one approved candidate into a 9:16 Short with burned-in
    subtitles + hook text. Renders are cached per candidate — a rendered clip
    is never re-rendered."""
    candidate_id = payload.get("candidate_id")
    if not candidate_id:
        logger.warning("job_missing_candidate_id", payload=payload)
        return

    with SessionLocal() as db:
        candidate = db.get(ClipCandidate, candidate_id)
        if candidate is None:
            logger.warning("job_candidate_not_found", candidate_id=candidate_id)
            return

        existing = get_render(db, candidate_id)
        if existing is not None and existing.status == "rendered":
            logger.info("render_cached_skip", candidate_id=candidate_id)
            return
        if candidate.status != "approved":
            logger.info(
                "render_skip_not_approved",
                candidate_id=candidate_id,
                status=candidate.status,
            )
            return

        video = db.get(Video, candidate.video_id)
        if video is None:
            logger.warning("job_video_not_found", video_id=candidate.video_id)
            return

        local_video = _ensure_local_video(db, video)
        if local_video is None:
            logger.warning("render_local_video_unavailable", candidate_id=candidate_id)
            return

        logger.info(
            "render_started",
            candidate_id=candidate_id,
            video_id=candidate.video_id,
            clip=f"{candidate.start_time:.2f}-{candidate.end_time:.2f}",
        )
        try:
            render = render_clip(db, candidate, local_video)
            logger.info(
                "render_completed",
                candidate_id=candidate_id,
                render_id=render.id,
                status=render.status,
            )
            if render.status == "rendered":
                _maybe_auto_publish(db, render)
        except RenderError as exc:
            logger.warning(
                "render_failed",
                candidate_id=candidate_id,
                code=exc.code,
                detail=exc.detail[:300],
            )
        except Exception as exc:
            logger.warning(
                "render_failed", candidate_id=candidate_id, error=str(exc)[:300]
            )


# ---------------------------------------------------------------------------
# PUBLISH (Phase 8-9, §65)
# ---------------------------------------------------------------------------


def handle_publish(payload: dict) -> None:
    """Upload a rendered Short to YouTube and record the publication.

    Idempotent: a publication that already has a ``youtube_video_id`` is
    never re-uploaded (§64). Failures are recorded on the publication row;
    the candidate stays ``rendered`` so the user can retry.
    """
    publication_id = payload.get("publication_id")
    if not publication_id:
        logger.warning("job_missing_publication_id", payload=payload)
        return

    with SessionLocal() as db:
        publication = db.get(Publication, publication_id)
        if publication is None:
            logger.warning("job_publication_not_found", publication_id=publication_id)
            return
        if publication.youtube_video_id:
            logger.info("publish_cached_skip", publication_id=publication_id)
            return

        logger.info(
            "publish_started",
            publication_id=publication_id,
            render_id=publication.render_id,
            privacy=publication.privacy,
            scheduled_at=(
                publication.scheduled_at.isoformat() if publication.scheduled_at else None
            ),
        )
        try:
            publish_clip(db, publication_id)
            logger.info("publish_completed", publication_id=publication_id)
            # Phase 10: an automation-driven publication finished the whole
            # pipeline — mark the source video completed (§61 state machine).
            if payload.get("auto"):
                video = db.get(Video, publication.video_id)
                if video is not None:
                    set_status(db, video, "completed")
                    logger.info(
                        "video_automation_completed",
                        video_id=video.id,
                        publication_id=publication_id,
                    )
        except PublishingError as exc:
            logger.warning(
                "publish_failed",
                publication_id=publication_id,
                code=exc.code,
                detail=exc.detail[:300],
            )
        except Exception as exc:
            logger.warning(
                "publish_failed", publication_id=publication_id, error=str(exc)[:300]
            )


HANDLERS = {
    "DOWNLOAD_VIDEO": handle_download_video,
    JOB_IMPORT_INBOX_FILE: handle_import_inbox_file,
    "TRANSCRIBE": handle_transcribe,
    "ANALYZE": handle_analyze,
    JOB_RENDER: handle_render,
    JOB_PUBLISH: handle_publish,
}


async def _consume() -> None:
    """One job consumer: dequeue → handle → retry crashed jobs with backoff.

    Handlers already record domain failures (``failed`` rows with error
    codes); the retry path only covers unexpected crashes, which would
    otherwise silently drop the job. Retries are idempotent-safe: every
    handler re-checks cached state (checksums, transcripts, renders,
    publications) before redoing work (§15/§55/§64/§67).
    """
    import asyncio

    while True:
        job: dict | None = None
        try:
            job = await asyncio.to_thread(dequeue, 5)
            if job is None:
                continue
            handler = HANDLERS.get(job.get("type"))
            if handler is None:
                logger.warning(
                    "job_unknown_type", job_type=job.get("type"), job_id=job.get("id")
                )
                continue
            logger.info("job_started", job_id=job.get("id"), job_type=job.get("type"))
            await asyncio.to_thread(handler, job.get("payload", {}))
            logger.info("job_completed", job_id=job.get("id"), job_type=job.get("type"))
        except Exception:
            logger.warning("job_loop_error", exc_info=True)
            attempts = int(job.get("attempts", 0)) if job else 0
            if job is not None and attempts < settings.max_job_retries:
                delay = retry_delay_seconds(attempts)
                logger.info(
                    "job_retry_scheduled",
                    job_id=job.get("id"),
                    job_type=job.get("type"),
                    attempt=attempts + 1,
                    delay_seconds=round(delay, 1),
                )
                await asyncio.sleep(delay)
                try:
                    await asyncio.to_thread(requeue, job)
                except Exception:
                    logger.warning("job_requeue_failed", job_id=job.get("id"))
            else:
                logger.warning(
                    "job_dropped",
                    job_id=job.get("id") if job else None,
                    job_type=job.get("type") if job else None,
                    attempts=attempts,
                )
            await asyncio.sleep(1)


async def job_loop() -> None:
    """Consume jobs from the Redis queue with ``max_concurrent_jobs`` consumers
    (default 1 — Whisper/FFmpeg are memory-heavy on the Orange Pi, §47)."""
    import asyncio

    consumers = max(1, settings.max_concurrent_jobs)
    logger.info("job_consumer_online", max_concurrent=consumers)
    await asyncio.gather(*(_consume() for _ in range(consumers)))
