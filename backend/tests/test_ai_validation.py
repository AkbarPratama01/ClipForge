"""§18 AI-response validation tests (Pydantic contract)."""

import pytest
from pydantic import ValidationError

from app.modules.analysis.service import ClipCandidateIn, _validate_and_build

VALID_CLIP = {
    "start_time": 5.0,
    "end_time": 20.0,
    "title": "The Big Reveal",
    "hook": "You won't believe this",
    "reason": "Strong payoff",
    "hook_score": 90,
    "content_score": 85,
    "context_score": 80,
    "emotion_score": 75,
    "standalone_score": 88,
    "retention_score": 82,
}


def test_valid_clip_parses() -> None:
    clip = ClipCandidateIn(**VALID_CLIP)
    assert clip.title == "The Big Reveal"


def test_missing_required_field_rejected() -> None:
    with pytest.raises(ValidationError):
        ClipCandidateIn(**{k: v for k, v in VALID_CLIP.items() if k != "title"})


def test_score_out_of_range_rejected() -> None:
    bad = {**VALID_CLIP, "hook_score": 150}
    with pytest.raises(ValidationError):
        ClipCandidateIn(**bad)


def test_non_positive_timestamps_rejected() -> None:
    bad = {**VALID_CLIP, "start_time": -1}
    with pytest.raises(ValidationError):
        ClipCandidateIn(**bad)


def test_build_skips_invalid_items_and_corrects_timestamps() -> None:
    raw = {
        "clips": [
            VALID_CLIP,
            {**VALID_CLIP, "title": ""},  # invalid → skipped
            {**VALID_CLIP, "start_time": 6.2, "end_time": 18.0},  # mid-sentence → snapped
        ]
    }
    segments = [
        {"start": 0.0, "end": 5.0, "text": "A"},
        {"start": 5.0, "end": 12.0, "text": "B"},
        {"start": 12.0, "end": 20.0, "text": "C"},
    ]
    built = _validate_and_build(raw, segments, 20.0)
    assert len(built) == 2
    # third item snapped to 5.0–20.0
    assert built[1]["start_time"] == 5.0
    assert built[1]["end_time"] == 20.0
    # overall score computed by the §19 formula; 84.5 → round → 84 (banker's)
    assert built[0]["score"] == 84


def test_build_rejects_non_dict() -> None:
    assert _validate_and_build("not a dict", [], 10.0) == []
    assert _validate_and_build({"clips": "nope"}, [], 10.0) == []
