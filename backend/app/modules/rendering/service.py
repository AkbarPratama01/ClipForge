"""Rendering service (Phase 6/7): 9:16 smart crop + burned-in subtitles +
hook, then sync the rendered Short to Drive ``04_Clips`` (Phase 7).

``render_clip`` is the worker-facing entry point: it creates/updates the
``clip_renders`` row, writes the ASS subtitle file, runs FFmpeg (input
seeking, args list — no shell, §51), probes the output and applies the
Phase 6 quality gate, then best-effort uploads the result to Drive (Phase 7,
recorded in ``storage_files``). Failures leave the candidate ``approved`` so
the user can retry; success moves it to ``rendered`` (state machine §61).
"""

from __future__ import annotations

import os
import subprocess

import structlog
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.analysis.models import ClipCandidate
from app.modules.rendering.errors import RenderError
from app.modules.rendering.geometry import (
    build_ffmpeg_command,
    parse_probe,
    probe_video,
    quality_check,
)
from app.modules.rendering.models import ClipRender
from app.modules.rendering.music import music_dir, select_music_track
from app.modules.rendering.subtitles import build_ass
from app.modules.storage.constants import render_remote_path
from app.modules.storage.errors import StorageError
from app.modules.storage.models import StorageFile
from app.modules.transcription.service import get_transcript
from app.providers.storage.factory import get_storage_provider

logger = structlog.get_logger(__name__)

ASS_FILENAME = "subs.ass"
OUTPUT_FILENAME = "clip.mp4"
SUBTITLE_FONT = "DejaVu Sans"


def render_workdir(candidate_id: int) -> str:
    """Per-candidate working directory under the shared temp storage."""
    return os.path.join(settings.temp_storage_path, "renders", str(candidate_id))


def get_render(db: Session, candidate_id: int) -> ClipRender | None:
    return (
        db.query(ClipRender).filter(ClipRender.candidate_id == candidate_id).first()
    )


def render_payload(render: ClipRender) -> dict:
    return {
        "id": render.id,
        "candidate_id": render.candidate_id,
        "video_id": render.video_id,
        "status": render.status,
        "filesize": render.filesize,
        "width": render.width,
        "height": render.height,
        "duration": render.duration,
        "quality_passed": render.quality_passed,
        "remote_path": render.remote_path,
        "error_code": render.error_code,
        "created_at": render.created_at.isoformat() if render.created_at else None,
    }


def _run_ffmpeg(cmd: list[str], cwd: str, timeout: int) -> None:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RenderError(
            "FFMPEG_FAILED", f"ffmpeg render failed: {proc.stderr[-500:]}"
        )


def _upload_render_to_drive(
    db: Session, render: ClipRender, output_path: str
) -> str | None:
    """Sync the rendered Short to Drive ``04_Clips`` and record ``storage_files``.

    Best-effort (Phase 7): an unconnected/errored Drive backend must not fail
    the render — the quality-checked Short already exists locally and the
    preview keeps working. Returns the remote path, or None when Drive is
    unavailable.
    """
    try:
        provider = get_storage_provider(db)
        remote_path = render_remote_path(render.video_id, render.candidate_id)
        remote = provider.upload(output_path, remote_path, mime_type="video/mp4")
        db.add(
            StorageFile(
                provider=settings.storage_provider,
                provider_file_id=remote.id,
                local_path=output_path,
                remote_path=remote_path,
                filename=remote.filename,
                mime_type="video/mp4",
                size=render.filesize,
                checksum=remote.checksum,
                status="uploaded",
                video_id=render.video_id,
            )
        )
        db.commit()
        logger.info(
            "render_synced_to_drive",
            render_id=render.id,
            candidate_id=render.candidate_id,
            remote_path=remote_path,
        )
        return remote_path
    except Exception as exc:
        code = exc.code if isinstance(exc, StorageError) else type(exc).__name__
        logger.warning(
            "render_drive_sync_skipped",
            render_id=render.id,
            candidate_id=render.candidate_id,
            code=code,
            error=str(exc)[:300],
        )
        return None

def render_clip(
    db: Session,
    candidate: ClipCandidate,
    local_video_path: str,
) -> ClipRender:
    """Render one approved candidate. Raises RenderError on failure."""
    render = get_render(db, candidate.id)
    if render is None:
        render = ClipRender(
            candidate_id=candidate.id, video_id=candidate.video_id, status="rendering"
        )
        db.add(render)
    else:
        render.status = "rendering"
        render.error_code = None
        render.remote_path = None
    candidate.status = "rendering"
    db.commit()
    db.refresh(render)

    workdir = render_workdir(candidate.id)
    os.makedirs(workdir, exist_ok=True)
    output_path = os.path.join(workdir, OUTPUT_FILENAME)
    clip_duration = candidate.end_time - candidate.start_time

    try:
        source = parse_probe(probe_video(local_video_path))
        if not source["width"] or not source["height"]:
            raise RenderError("SOURCE_INVALID", "Source video has no video stream.")

        transcript = get_transcript(db, candidate.video_id)
        segments = (
            [
                {"start": s.start_time, "end": s.end_time, "text": s.text}
                for s in transcript[1]
            ]
            if transcript is not None
            else []
        )
        ass = build_ass(
            candidate.hook or "",
            segments,
            candidate.start_time,
            candidate.end_time,
            width=settings.render_width,
            height=settings.render_height,
            font=SUBTITLE_FONT,
        )
        with open(os.path.join(workdir, ASS_FILENAME), "w", encoding="utf-8") as fh:
            fh.write(ass)

        # Phase 11: optional background music bed — one deterministic track
        # per candidate (same candidate always re-renders identically).
        music_path: str | None = None
        if settings.background_music:
            music_path = select_music_track(music_dir(), candidate.id)
            if music_path:
                logger.info(
                    "render_music_selected",
                    candidate_id=candidate.id,
                    track=os.path.basename(music_path),
                )

        def _build(music: str | None) -> tuple[list[str], str]:
            return build_ffmpeg_command(
                local_video_path,
                output_path,
                candidate.start_time,
                clip_duration,
                source["width"],
                source["height"],
                ass_file=ASS_FILENAME,
                out_width=settings.render_width,
                out_height=settings.render_height,
                crf=settings.render_crf,
                preset=settings.render_preset,
                audio_bitrate=settings.render_audio_bitrate,
                music_path=music,
                music_volume=settings.background_music_volume,
            )

        cmd, cwd = _build(music_path)
        try:
            _run_ffmpeg(cmd, cwd, timeout=settings.render_timeout_seconds)
        except RenderError as exc:
            if music_path is None:
                raise
            # A corrupt/undecodable track must not sink the render: retry
            # once without music and keep the Short.
            logger.warning(
                "render_music_fallback",
                candidate_id=candidate.id,
                track=os.path.basename(music_path),
                error=str(exc)[:200],
            )
            cmd, cwd = _build(None)
            _run_ffmpeg(cmd, cwd, timeout=settings.render_timeout_seconds)

        output_info = parse_probe(probe_video(output_path))
        if settings.render_quality_check:
            passed, problems = quality_check(
                output_info,
                clip_duration,
                out_width=settings.render_width,
                out_height=settings.render_height,
            )
            if not passed:
                raise RenderError("QUALITY_CHECK_FAILED", "; ".join(problems))

        render.status = "rendered"
        render.local_path = output_path
        render.filesize = output_info["size"]
        render.width = output_info["width"]
        render.height = output_info["height"]
        render.duration = output_info["duration"]
        render.quality_passed = True
        render.error_code = None
        render.remote_path = _upload_render_to_drive(db, render, output_path)
        candidate.status = "rendered"
        db.commit()
        db.refresh(render)

        logger.info(
            "render_completed",
            candidate_id=candidate.id,
            render_id=render.id,
            filesize=render.filesize,
            width=render.width,
            height=render.height,
            duration=round(render.duration or 0, 2),
            remote_path=render.remote_path,
        )
        return render
    except RenderError as exc:
        render.status = "failed"
        render.error_code = exc.code
        render.quality_passed = False
        db.commit()
        candidate.status = "approved"
        db.commit()
        raise
    except subprocess.TimeoutExpired as exc:
        logger.warning(
            "render_timeout",
            candidate_id=candidate.id,
            timeout_seconds=settings.render_timeout_seconds,
        )
        render.status = "failed"
        render.error_code = "RENDER_TIMEOUT"
        render.quality_passed = False
        db.commit()
        candidate.status = "approved"
        db.commit()
        raise RenderError("RENDER_TIMEOUT", str(exc)) from exc
    except Exception as exc:
        logger.warning("render_failed", candidate_id=candidate.id, exc_info=True)
        render.status = "failed"
        render.error_code = "RENDER_FAILED"
        render.quality_passed = False
        db.commit()
        candidate.status = "approved"
        db.commit()
        raise RenderError("RENDER_FAILED", str(exc)) from exc
