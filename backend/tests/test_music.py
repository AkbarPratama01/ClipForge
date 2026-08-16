"""Phase 11 background music tests (pure — no ffmpeg binary)."""

import os

import pytest

from app.core.config import settings
from app.modules.rendering.music import (
    list_music_tracks,
    music_dir,
    select_music_track,
)


@pytest.fixture
def track_dir(tmp_path):
    (tmp_path / "a.mp3").write_bytes(b"x")
    (tmp_path / "b.wav").write_bytes(b"x")
    (tmp_path / "c.ogg").write_bytes(b"x")
    (tmp_path / "notes.txt").write_bytes(b"x")
    (tmp_path / "cover.jpg").write_bytes(b"x")
    return str(tmp_path)


def test_list_music_tracks_filters_and_sorts(track_dir) -> None:
    tracks = list_music_tracks(track_dir)
    assert [os.path.basename(t) for t in tracks] == ["a.mp3", "b.wav", "c.ogg"]


def test_list_music_tracks_missing_dir() -> None:
    assert list_music_tracks("/nonexistent/music") == []


def test_list_music_tracks_empty_dir(tmp_path) -> None:
    assert list_music_tracks(str(tmp_path)) == []


def test_select_music_track_deterministic(track_dir) -> None:
    assert select_music_track(track_dir, seed=1) == select_music_track(track_dir, seed=1)
    assert os.path.basename(select_music_track(track_dir, seed=0)) == "a.mp3"
    assert os.path.basename(select_music_track(track_dir, seed=2)) == "c.ogg"


def test_select_music_track_cycles_by_seed(track_dir) -> None:
    picked = {select_music_track(track_dir, seed) for seed in range(3)}
    assert len(picked) == 3  # three different tracks for three candidates


def test_select_music_track_no_tracks(tmp_path) -> None:
    assert select_music_track(str(tmp_path), seed=0) is None


def test_music_dir_default_under_temp(monkeypatch) -> None:
    monkeypatch.setattr(settings, "background_music_path", "")
    assert music_dir() == os.path.join(settings.temp_storage_path, "music")


def test_music_dir_explicit_override(monkeypatch) -> None:
    monkeypatch.setattr(settings, "background_music_path", "/data/music")
    assert music_dir() == "/data/music"
