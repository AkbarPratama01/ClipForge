"""Background music for rendered Shorts (Phase 11).

Tracks live in a music directory (``BACKGROUND_MUSIC_PATH``, default
``<temp_storage_path>/music``). ``select_music_track`` picks one track
**deterministically per candidate** (seed = candidate id), so re-rendering a
clip always produces the same audio bed. When the directory is empty or
music is not configured the render simply proceeds without music.
"""

from __future__ import annotations

import os

from app.core.config import settings

# Containers ffmpeg can decode; keep the list deliberately small.
AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac", ".opus"}


def music_dir() -> str:
    """Resolve the music directory: explicit path, else temp/music."""
    return settings.background_music_path or os.path.join(
        settings.temp_storage_path, "music"
    )


def list_music_tracks(track_dir: str) -> list[str]:
    """Sorted absolute paths of playable tracks; [] when the dir is missing/empty."""
    if not os.path.isdir(track_dir):
        return []
    tracks = [
        os.path.join(track_dir, name)
        for name in os.listdir(track_dir)
        if os.path.splitext(name)[1].lower() in AUDIO_EXTENSIONS
        and os.path.isfile(os.path.join(track_dir, name))
    ]
    return sorted(tracks)


def select_music_track(track_dir: str, seed: int) -> str | None:
    """Deterministic per-render track: same seed → same track (re-render
    stability), different candidates cycle through the library."""
    tracks = list_music_tracks(track_dir)
    if not tracks:
        return None
    return tracks[seed % len(tracks)]
