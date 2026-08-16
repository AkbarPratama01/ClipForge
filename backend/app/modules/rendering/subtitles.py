"""ASS subtitle generation for rendered clips (Phase 6).

Produces the burn-in file for one clip:

- the candidate's **hook text** is shown at the top for the whole clip, and
- transcript sentences inside the clip window are shown at the bottom.

Timestamps are **relative to the clip start** (the filter chain normalizes
PTS with ``setpts``/``asetpts`` so libass sees a 0-based timeline), matching
how the renderer cuts the source with input seeking.

All functions here are pure — the renderer service only has to write the
returned document to disk.
"""

from __future__ import annotations

_SCRIPT_INFO = """[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes"""

_STYLES = """[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,{font},100,&H00FFFFFF,&H000000FF,&H00141414,&H96000000,-1,0,0,0,100,100,0,0,1,5,2,8,50,50,60,1
Style: Sub,{font},52,&H00FFFFFF,&H000000FF,&H00141414,&H96000000,-1,0,0,0,100,100,0,0,1,4,2,2,60,60,36,1"""

_EVENTS_HEADER = """[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"""

# Subtitle windows shorter than this are skipped (they flash by unreadably).
MIN_SUBTITLE_SECONDS = 0.3
# Whisper segments that overlap are merged into one subtitle line; contiguous
# sentences stay separate so the subtitle changes with the speech.
MERGE_OVERLAP_SECONDS = 0.0


def escape_ass(text: str) -> str:
    """Escape ASS override/comment characters so text renders literally.

    Order matters: backslashes first, then braces (a literal ``\\{`` is
    written as ``\\\\{``), then newlines become hard line breaks.
    """
    return (
        text.replace("\\", "\\\\")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("\n", "\\N")
    )


def _ts(seconds: float) -> str:
    """ASS timestamp ``h:mm:ss.cc``."""
    seconds = max(0.0, seconds)
    total_cs = round(seconds * 100)
    cs = total_cs % 100
    total_s = total_cs // 100
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _dialogue(start: float, end: float, style: str, text: str, layer: int = 0) -> str:
    return (
        f"Dialogue: {layer},{_ts(start)},{_ts(end)},{style},,"
        f"0,0,0,,{escape_ass(text)}"
    )


def _clip_segments(
    segments: list[dict], clip_start: float, clip_end: float
) -> list[dict]:
    """Segments overlapping the clip window, clamped to it, text trimmed."""
    clipped: list[dict] = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", 0.0))
        if end <= clip_start or start >= clip_end:
            continue
        clipped.append(
            {
                "start": max(start, clip_start),
                "end": min(end, clip_end),
                "text": text,
            }
        )
    return clipped


def _merge_segments(
    clipped: list[dict], clip_start: float, clip_duration: float
) -> list[dict]:
    """Shift to the clip timeline, then merge overlapping/adjacent windows."""
    merged: list[dict] = []
    for seg in sorted(clipped, key=lambda s: s["start"]):
        start = max(0.0, seg["start"] - clip_start)
        end = min(clip_duration, seg["end"] - clip_start)
        if end - start < MIN_SUBTITLE_SECONDS:
            continue
        if merged and start < merged[-1]["end"] - MERGE_OVERLAP_SECONDS:
            merged[-1]["end"] = max(merged[-1]["end"], end)
            merged[-1]["text"] = f'{merged[-1]["text"]} {seg["text"]}'.strip()
        else:
            merged.append({"start": start, "end": end, "text": seg["text"]})
    return merged


def build_ass(
    hook: str,
    segments: list[dict],
    clip_start: float,
    clip_end: float,
    *,
    width: int = 1080,
    height: int = 1920,
    font: str = "DejaVu Sans",
) -> str:
    """Build the ASS document for one clip (timestamps relative to clip start)."""
    duration = clip_end - clip_start
    if duration <= 0:
        raise ValueError("clip_end must be after clip_start")

    lines = [
        _SCRIPT_INFO.format(width=width, height=height),
        "",
        _STYLES.format(font=font),
        "",
        _EVENTS_HEADER,
    ]

    hook_text = (hook or "").strip()
    if hook_text:
        lines.append(_dialogue(0.0, duration, "Hook", hook_text))

    for seg in _merge_segments(
        _clip_segments(segments, clip_start, clip_end), clip_start, duration
    ):
        lines.append(_dialogue(seg["start"], seg["end"], "Sub", seg["text"]))

    return "\n".join(lines) + "\n"
