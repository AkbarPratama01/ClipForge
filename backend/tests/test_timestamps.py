"""§20 smart-timestamp tests: AI timestamps snap to sentence boundaries."""

from app.modules.analysis.service import correct_timestamps

SEGMENTS = [
    {"start": 0.0, "end": 5.0, "text": "First sentence."},
    {"start": 5.0, "end": 12.0, "text": "Second sentence."},
    {"start": 12.0, "end": 20.0, "text": "Third sentence."},
    {"start": 20.0, "end": 30.0, "text": "Fourth sentence."},
]
DURATION = 30.0


def test_snaps_start_to_boundary() -> None:
    # AI asks 6.2–18.0 (mid-sentence) → snaps to 5.0–20.0
    assert correct_timestamps(6.2, 18.0, SEGMENTS, DURATION) == (5.0, 20.0)


def test_exact_boundaries_kept() -> None:
    assert correct_timestamps(5.0, 20.0, SEGMENTS, DURATION) == (5.0, 20.0)


def test_small_tolerance() -> None:
    # 4.7 is within 0.5s of the 5.0 boundary — snaps to 5.0
    assert correct_timestamps(4.7, 19.6, SEGMENTS, DURATION) == (5.0, 20.0)


def test_clamped_to_duration() -> None:
    start, end = correct_timestamps(24.0, 99.0, SEGMENTS, DURATION)
    assert end <= DURATION
    assert end == 30.0


def test_too_short_clip_dropped() -> None:
    # start == end is degenerate; the 8 s floor drops it.
    assert correct_timestamps(12.0, 12.0, SEGMENTS, DURATION) is None


def test_too_long_clip_dropped() -> None:
    # A window longer than the 120 s cap is rejected.
    long_segments = [
        {"start": 0.0, "end": 5.0, "text": "A"},
        {"start": 5.0, "end": 220.0, "text": "B"},
    ]
    assert correct_timestamps(0.0, 220.0, long_segments, 220.0) is None


def test_zero_duration_rejected() -> None:
    assert correct_timestamps(1.0, 10.0, SEGMENTS, 0.0) is None
