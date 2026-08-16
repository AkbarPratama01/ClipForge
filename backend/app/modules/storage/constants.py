"""Google Drive folder structure (§8) and remote-path helpers."""

from __future__ import annotations

# The top-level folder created on the user's Drive, and its children.
DRIVE_ROOT_FOLDER = "ClipForge"
DRIVE_FOLDERS = [
    "01_Inbox",
    "02_Processing",
    "03_Projects",
    "04_Clips",
    "05_Published",
    "06_Archive",
    "07_Transcripts",
    "08_Thumbnails",
    "09_Metadata",
]

# Rendered Shorts are synced here (Phase 7, §8).
CLIPS_FOLDER = "04_Clips"


def render_remote_path(video_id: int, candidate_id: int) -> str:
    """Drive path for a rendered Short: ``04_Clips/<video_id>/clip-<candidate_id>.mp4``.

    One folder per source video keeps every render of the same video together;
    the candidate id makes each Short unique (idempotent re-uploads).
    """
    return f"{CLIPS_FOLDER}/{video_id}/clip-{candidate_id}.mp4"


def split_remote_path(path: str) -> list[str]:
    """Split a remote path like ``ClipForge/01_Inbox/video.mp4`` into segments.

    Normalizes Windows-style backslashes and collapses empty segments.
    """
    return [part for part in path.replace("\\", "/").split("/") if part]


def sanitize_filename(name: str) -> str:
    """Strip characters that are unsafe in file names / Drive lookups."""
    return "".join(ch for ch in name if ch not in '<>:"/\\|?*').strip() or "file"
