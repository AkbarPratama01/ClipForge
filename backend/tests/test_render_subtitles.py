"""Phase 6 ASS subtitle generation tests (pure, no DB/ffmpeg)."""

import pytest

from app.modules.rendering.subtitles import (
    _ts,
    build_ass,
    escape_ass,
)

SEGMENTS = [
    {"start": 0.0, "end": 5.0, "text": "First sentence."},
    {"start": 5.0, "end": 12.0, "text": "Second sentence."},
    {"start": 12.0, "end": 20.0, "text": "Third sentence."},
    {"start": 20.0, "end": 30.0, "text": "Fourth sentence."},
]


def test_escape_ass_braces_and_backslash() -> None:
    assert escape_ass("a{b}c") == "a\\{b\\}c"
    assert escape_ass("a\\b") == "a\\\\b"
    assert escape_ass("a{b\\c}d") == "a\\{b\\\\c\\}d"


def test_escape_ass_newline_becomes_hard_break() -> None:
    assert escape_ass("line1\nline2") == "line1\\Nline2"


def test_ts_formatting() -> None:
    assert _ts(0) == "0:00:00.00"
    assert _ts(61.5) == "0:01:01.50"
    assert _ts(3661.25) == "1:01:01.25"
    assert _ts(59.999) == "0:01:00.00"  # rounds to the next second


def test_build_ass_includes_hook_for_full_clip() -> None:
    ass = build_ass("Wow, watch this!", SEGMENTS, 5.0, 20.0)
    assert "Style: Hook," in ass
    assert "Style: Sub," in ass
    assert "Dialogue: 0,0:00:00.00,0:00:15.00,Hook,,0,0,0,,Wow, watch this!" in ass


def test_build_ass_no_hook_when_empty() -> None:
    ass = build_ass("   ", SEGMENTS, 5.0, 20.0)
    assert "Hook" not in ass.split("[Events]")[1]


def test_build_ass_segments_shifted_to_clip_timeline() -> None:
    ass = build_ass("", SEGMENTS, 5.0, 20.0)
    events = ass.split("[Events]")[1]
    # 5.0–12.0 → 0–7, 12.0–20.0 → 7–15 (segment 0–5 is outside the clip)
    assert "Dialogue: 0,0:00:00.00,0:00:07.00,Sub,,0,0,0,,Second sentence." in events
    assert "Dialogue: 0,0:00:07.00,0:00:15.00,Sub,,0,0,0,,Third sentence." in events
    assert "First sentence." not in events
    assert "Fourth sentence." not in events


def test_build_ass_clamps_partial_segment() -> None:
    partial = [{"start": 2.0, "end": 8.0, "text": "Straddles the start."}]
    ass = build_ass("", partial, 5.0, 20.0)
    events = ass.split("[Events]")[1]
    assert "Dialogue: 0,0:00:00.00,0:00:03.00,Sub,,0,0,0,,Straddles the start." in events


def test_build_ass_merges_overlapping_segments() -> None:
    overlapping = [
        {"start": 5.0, "end": 8.0, "text": "A."},
        {"start": 7.9, "end": 12.0, "text": "B."},
    ]
    ass = build_ass("", overlapping, 5.0, 20.0)
    events = ass.split("[Events]")[1]
    assert "Dialogue: 0,0:00:00.00,0:00:07.00,Sub,,0,0,0,,A. B." in events


def test_build_ass_drops_flash_subtitles() -> None:
    flash = [{"start": 5.0, "end": 5.2, "text": "Too fast."}]
    ass = build_ass("", flash, 5.0, 20.0)
    assert "Too fast." not in ass


def test_build_ass_rejects_invalid_window() -> None:
    with pytest.raises(ValueError):
        build_ass("", SEGMENTS, 10.0, 5.0)
