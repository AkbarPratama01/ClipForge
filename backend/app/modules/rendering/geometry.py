"""Smart-crop geometry and ffmpeg/ffprobe helpers for 9:16 Shorts (Phase 6).

The renderer never stretches or letterboxes: it crops the source frame to the
target 9:16 aspect — a centered vertical slice for landscape video, a
centered horizontal slice for portrait/tall video — then scales to the target
size. Crop dimensions are rounded to even numbers (h264 requires even
widths/heights).
"""

from __future__ import annotations

import json
import os
import subprocess

from app.modules.rendering.errors import RenderError

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"

PROBE_TIMEOUT_SECONDS = 60


def crop_geometry(
    src_width: int, src_height: int, out_width: int = 1080, out_height: int = 1920
) -> dict:
    """Return the filter fragment converting one source frame into the target.

    Returns ``{"crop": str | None, "scale": str | None}`` — either fragment is
    None when it is a no-op for the given source dimensions.
    """
    if src_width <= 0 or src_height <= 0 or out_width <= 0 or out_height <= 0:
        raise ValueError("dimensions must be positive")

    target_ratio = out_width / out_height
    src_ratio = src_width / src_height

    crop: str | None = None
    post_w, post_h = src_width, src_height

    if src_ratio > target_ratio + 1e-6:
        # Wider than 9:16 → crop a centered vertical slice.
        crop_w = int(round(src_height * target_ratio / 2) * 2)
        crop_w = max(2, min(crop_w, src_width))
        if crop_w < src_width:
            crop_x = ((src_width - crop_w) // 2) & ~1
            crop = f"crop={crop_w}:{src_height}:{crop_x}:0"
            post_w, post_h = crop_w, src_height
    elif src_ratio < target_ratio - 1e-6:
        # Taller than 9:16 → crop a centered horizontal slice.
        crop_h = int(round(src_width / target_ratio / 2) * 2)
        crop_h = max(2, min(crop_h, src_height))
        if crop_h < src_height:
            crop_y = ((src_height - crop_h) // 2) & ~1
            crop = f"crop={src_width}:{crop_h}:0:{crop_y}"
            post_w, post_h = src_width, crop_h

    scale = None
    if (post_w, post_h) != (out_width, out_height):
        scale = f"scale={out_width}:{out_height}"

    return {"crop": crop, "scale": scale}


def probe_video(path: str) -> dict:
    """ffprobe JSON summary: streams + format (duration/size)."""
    cmd = [
        FFPROBE,
        "-v", "error",
        "-show_entries", "stream=index,codec_type,codec_name,width,height,duration",
        "-show_entries", "format=duration,size",
        "-of", "json",
        path,
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=PROBE_TIMEOUT_SECONDS
    )
    if proc.returncode != 0:
        raise RenderError(
            "SOURCE_PROBE_FAILED", f"ffprobe failed: {proc.stderr[-300:]}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RenderError("SOURCE_PROBE_FAILED", "ffprobe returned invalid JSON") from exc


def parse_probe(data: dict) -> dict:
    """Normalize ffprobe output into render quality fields."""
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    fmt = data.get("format", {})

    def _to_int(value: object) -> int | None:
        try:
            return int(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    duration = (video.get("duration") if video else None) or fmt.get("duration")
    try:
        duration_f = float(duration) if duration not in (None, "") else 0.0
    except (TypeError, ValueError):
        duration_f = 0.0

    return {
        "width": _to_int(video.get("width")) if video else None,
        "height": _to_int(video.get("height")) if video else None,
        "duration": duration_f,
        "size": _to_int(fmt.get("size")) or 0,
        "has_audio": has_audio,
        "codec": (video.get("codec_name") if video else None),
    }


def quality_check(
    info: dict,
    expected_duration: float,
    *,
    out_width: int = 1080,
    out_height: int = 1920,
) -> tuple[bool, list[str]]:
    """Phase 6 quality gate: correct 9:16 frame, non-empty, sane duration.

    The duration window is generous because input seeking may add a short
    keyframe lead-in or frame-alignment tail.
    """
    problems: list[str] = []
    if info["width"] != out_width:
        problems.append(f"width {info['width']} != {out_width}")
    if info["height"] != out_height:
        problems.append(f"height {info['height']} != {out_height}")
    if info["size"] <= 0:
        problems.append("output file is empty")
    if info["duration"] < expected_duration - 2.0:
        problems.append(f"duration {info['duration']:.2f}s too short")
    if info["duration"] > expected_duration + 8.0:
        problems.append(f"duration {info['duration']:.2f}s too long")
    return (not problems, problems)


def build_ffmpeg_command(
    video_path: str,
    output_path: str,
    clip_start: float,
    clip_duration: float,
    src_width: int,
    src_height: int,
    *,
    ass_file: str = "subs.ass",
    out_width: int = 1080,
    out_height: int = 1920,
    crf: int = 23,
    preset: str = "veryfast",
    audio_bitrate: str = "128k",
    music_path: str | None = None,
    music_volume: float = 0.15,
) -> tuple[list[str], str]:
    """Build the render command as an argument list (no shell, §51).

    Returns ``(cmd, cwd)`` — the process runs in the output directory so the
    ``ass`` filter can reference a bare filename, avoiding path-escaping
    pitfalls in the filtergraph. PTS is normalized to start at 0 so libass
    matches the clip-relative ASS timeline; ``-ss`` before ``-i`` keeps
    seeking fast on long source videos.

    With ``music_path`` (Phase 11) a second, looped audio input is mixed
    under the original audio (``amix``, ``duration=first``, both branches
    normalized to 48 kHz stereo so amix never fails on mismatched formats).
    The command switches to a single ``-filter_complex`` graph; the plain
    ``-vf``/``-af`` path is used unchanged when no music is configured.
    """
    geometry = crop_geometry(src_width, src_height, out_width, out_height)
    video_filters = ["setpts=PTS-STARTPTS"]
    video_filters += [f for f in (geometry["crop"], geometry["scale"]) if f]
    video_filters.append(f"ass={ass_file}")

    cmd = [
        FFMPEG, "-y", "-loglevel", "error",
        "-ss", f"{clip_start:.3f}", "-i", video_path,
    ]
    if music_path:
        # Loop the track forever; amix (duration=first) ends it with the clip.
        cmd += ["-stream_loop", "-1", "-i", music_path]
    cmd += ["-t", f"{clip_duration:.3f}"]

    if music_path:
        volume = max(0.0, min(float(music_volume), 1.0))
        cmd += [
            "-filter_complex",
            f"[0:v]{','.join(video_filters)}[vout];"
            "[0:a]asetpts=PTS-STARTPTS,aformat="
            "sample_rates=48000:channel_layouts=stereo[a0];"
            f"[1:a]volume={volume:.3f},aformat="
            "sample_rates=48000:channel_layouts=stereo[mus];"
            "[a0][mus]amix=inputs=2:duration=first:dropout_transition=3[aout]",
            "-map", "[vout]",
            "-map", "[aout]",
        ]
    else:
        cmd += [
            "-vf", ",".join(video_filters),
            "-af", "asetpts=PTS-STARTPTS",
        ]

    cmd += [
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", audio_bitrate,
        "-movflags", "+faststart",
        output_path,
    ]
    return cmd, os.path.dirname(output_path)
