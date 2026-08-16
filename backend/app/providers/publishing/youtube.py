"""YouTubeProvider — YouTube Data API v3 over OAuth 2.0 (Phase 8-9).

Implements the :class:`PublishingProvider` contract with the official
YouTube Data API. Media flow mirrors the Drive provider: resumable upload in
8 MiB chunks via ``AuthorizedSession`` (no extra dependency), verified by the
final response carrying the new video id.

Scheduling uses YouTube's native ``publishAt`` — the API only allows it when
``privacyStatus`` is ``private``, so a scheduled publication is forced
private and YouTube flips it to public at the given time.
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path
from typing import Any

import structlog
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials

from app.modules.publishing.errors import YouTubeApiError
from app.providers.base import PublishingProvider

logger = structlog.get_logger(__name__)

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]
API_BASE = "https://www.googleapis.com/youtube/v3"
UPLOAD_BASE = "https://www.googleapis.com/upload/youtube/v3/videos"
CHUNK_SIZE = 8 * 1024 * 1024  # 8 MiB, same as the Drive provider
# People & Blogs — the default category for Shorts.
DEFAULT_CATEGORY_ID = "22"
# YouTube hard limits.
MAX_TITLE_LENGTH = 100
MAX_DESCRIPTION_LENGTH = 5000
MAX_TAGS = 25


def format_publish_at(value: datetime.datetime) -> str:
    """RFC 3339 (UTC, ``Z`` suffix) — the format YouTube's ``publishAt`` expects."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_video_body(
    title: str,
    description: str = "",
    tags: str | None = None,
    privacy: str = "private",
    publish_at: datetime.datetime | None = None,
) -> dict:
    """Build the ``snippet``/``status`` request body for the upload API.

    Pure function — the YouTube API contract, pinned down for tests. A
    ``publish_at`` schedules via YouTube's native mechanism and therefore
    forces ``privacyStatus=private`` (API requirement).
    """
    snippet: dict[str, Any] = {
        "title": (title or "")[:MAX_TITLE_LENGTH],
        "description": (description or "")[:MAX_DESCRIPTION_LENGTH],
        "categoryId": DEFAULT_CATEGORY_ID,
    }
    if tags:
        cleaned = [t.strip() for t in tags.split(",") if t.strip()][:MAX_TAGS]
        if cleaned:
            snippet["tags"] = cleaned

    status: dict[str, Any] = {
        "privacyStatus": privacy,
        "selfDeclaredMadeForKids": False,
    }
    if publish_at is not None:
        status["privacyStatus"] = "private"
        status["publishAt"] = format_publish_at(publish_at)

    return {"snippet": snippet, "status": status}


class YouTubeProvider(PublishingProvider):
    def __init__(self, credentials: Credentials) -> None:
        self._credentials = credentials
        self._session: AuthorizedSession | None = None

    def _get_session(self) -> AuthorizedSession:
        if self._session is None:
            self._session = AuthorizedSession(self._credentials)
        return self._session

    @staticmethod
    def _check(resp: Any, *, what: str) -> None:
        """Raise YouTubeApiError unless the response is OK (no secrets leaked)."""
        if resp.ok:
            return
        try:
            detail = resp.json().get("error", {}).get("message") or resp.text
        except ValueError:
            detail = resp.text
        raise YouTubeApiError(f"{what}: {str(detail)[:300]}")

    def publish(self, video_path: str, metadata: dict) -> dict:
        """Upload ``video_path`` with metadata; return the YouTube video id."""
        path = Path(video_path)
        if not path.is_file():
            raise YouTubeApiError(f"local file missing: {video_path}")

        body = build_video_body(**metadata)
        size = path.stat().st_size
        session = self._get_session()

        start = session.post(
            f"{UPLOAD_BASE}?uploadType=resumable&part=snippet,status",
            json=body,
            headers={
                "X-Upload-Content-Type": "video/*",
                "X-Upload-Content-Length": str(size),
            },
        )
        self._check(start, what="start resumable upload")
        session_uri = start.headers["Location"]

        offset = 0
        resp: Any = None
        with open(path, "rb") as fh:
            while offset < size:
                chunk = fh.read(CHUNK_SIZE)
                if not chunk:
                    break
                end = offset + len(chunk) - 1
                resp = session.put(
                    session_uri,
                    data=chunk,
                    headers={"Content-Range": f"bytes {offset}-{end}/{size}"},
                )
                offset = end + 1

        if resp is None or resp.status_code not in (200, 201):
            if resp is None:
                raise YouTubeApiError("empty upload response")
            self._check(resp, what="finish resumable upload")

        item = resp.json()
        video_id = item.get("id")
        if not video_id:
            raise YouTubeApiError("upload response missing video id")
        logger.info(
            "youtube_upload_completed",
            video_id=video_id,
            title=item.get("snippet", {}).get("title"),
        )
        return {
            "external_id": video_id,
            "upload_status": item.get("status", {}).get("uploadStatus"),
        }

    def status(self, external_id: str) -> dict:
        """Return YouTube's current status for a video id."""
        resp = self._get_session().get(
            f"{API_BASE}/videos",
            params={"part": "status,snippet", "id": external_id},
        )
        self._check(resp, what="fetch video status")
        items = resp.json().get("items", [])
        if not items:
            return {"external_id": external_id, "status": "missing"}
        item = items[0]
        return {
            "external_id": external_id,
            "title": item.get("snippet", {}).get("title"),
            "privacy": item.get("status", {}).get("privacyStatus"),
            "upload_status": item.get("status", {}).get("uploadStatus"),
        }

    def channel_info(self) -> dict:
        """Resolve the connected channel id/name (for account status)."""
        resp = self._get_session().get(
            f"{API_BASE}/channels", params={"part": "snippet", "mine": "true"}
        )
        self._check(resp, what="fetch channel info")
        items = resp.json().get("items", [])
        if not items:
            return {}
        return {
            "channel_id": items[0].get("id"),
            "channel_name": items[0].get("snippet", {}).get("title"),
        }
