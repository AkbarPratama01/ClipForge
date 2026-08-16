"""YouTube URL validation (§12 Mode A) and video service helpers."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from sqlalchemy.orm import Session

from app.modules.videos.models import Video

_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "youtube-nocookie.com",
}


def extract_video_id(url: str) -> str | None:
    """Return the YouTube video id for a watch/shorts/you.be URL, else None."""
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None

    host = parsed.netloc.lower()
    if host not in _YOUTUBE_HOSTS:
        return None

    if host == "youtu.be":
        video_id = parsed.path.strip("/")
        return video_id or None

    path = parsed.path
    if path.startswith("/shorts/"):
        parts = [p for p in path.split("/") if p]
        return parts[1] if len(parts) >= 2 else None

    if path in ("/watch", "/watch/"):
        video_id = parse_qs(parsed.query).get("v", [None])[0]
        return video_id or None

    return None


def is_valid_youtube_url(url: str) -> bool:
    return extract_video_id(url) is not None


# ------------------------------------------------------------------ persistence

def create_video(db: Session, source_url: str) -> Video:
    video = Video(source_url=source_url.strip(), status="pending")
    db.add(video)
    db.commit()
    db.refresh(video)
    return video


def get_video(db: Session, video_id: int) -> Video | None:
    return db.get(Video, video_id)


def set_status(db: Session, video: Video, status: str, error_code: str | None = None) -> Video:
    video.status = status
    if error_code:
        video.error_code = error_code
    db.add(video)
    db.commit()
    db.refresh(video)
    return video


def update_metadata(db: Session, video: Video, info: dict) -> Video:
    """Fill §13 metadata from a yt-dlp info dict (no fields overwritten with None)."""
    mapping = {
        "title": "title",
        "description": "description",
        "channel": ("channel", "uploader", "channel_id"),
        "duration": "duration",
        "width": "width",
        "height": "height",
        "fps": "fps",
        "codec": ("vcodec", "acodec"),
        "thumbnail": "thumbnail",
    }
    for column, keys in mapping.items():
        keys_tuple = keys if isinstance(keys, tuple) else (keys,)
        value = next((info.get(k) for k in keys_tuple if info.get(k) is not None), None)
        if value is not None:
            setattr(video, column, value)
    db.add(video)
    db.commit()
    db.refresh(video)
    return video


def find_duplicate(db: Session, video: Video, checksum: str) -> Video | None:
    """§67 — another video with the same content checksum that actually imported.

    Matches any status past a successful download (downloaded, uploaded, and
    every later pipeline stage) — a video mid-pipeline (e.g. ``analyzed``)
    still owns its content, so re-importing the same file must not download
    and upload it a second time. ``pending``/``downloading`` (incomplete),
    ``duplicate`` and ``failed`` rows do not count.
    """
    imported_statuses = [
        "downloaded",
        "uploaded",
        "transcribing",
        "transcribed",
        "analyzing",
        "analyzed",
        "completed",
    ]
    return (
        db.query(Video)
        .filter(
            Video.checksum == checksum,
            Video.id != video.id,
            Video.status.in_(imported_statuses),
        )
        .first()
    )
