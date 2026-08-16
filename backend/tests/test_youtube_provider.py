"""Phase 8-9 YouTube provider tests (pure — no network)."""

import datetime

import pytest

from app.modules.publishing.errors import YouTubeApiError
from app.providers.publishing.youtube import (
    build_video_body,
    format_publish_at,
)


def test_format_publish_at_utc_aware() -> None:
    dt = datetime.datetime(2026, 8, 20, 9, 0, tzinfo=datetime.timezone.utc)
    assert format_publish_at(dt) == "2026-08-20T09:00:00Z"


def test_format_publish_at_naive_assumed_utc() -> None:
    dt = datetime.datetime(2026, 8, 20, 9, 0)
    assert format_publish_at(dt) == "2026-08-20T09:00:00Z"


def test_build_video_body_minimal() -> None:
    body = build_video_body("My Short", privacy="unlisted")
    assert body["snippet"]["title"] == "My Short"
    assert body["snippet"]["categoryId"] == "22"
    assert body["status"]["privacyStatus"] == "unlisted"
    assert body["status"]["selfDeclaredMadeForKids"] is False
    assert "tags" not in body["snippet"]


def test_build_video_body_truncates_title_and_description() -> None:
    body = build_video_body("x" * 250, description="y" * 6000)
    assert len(body["snippet"]["title"]) == 100
    assert len(body["snippet"]["description"]) == 5000


def test_build_video_body_parses_tags() -> None:
    body = build_video_body("T", tags="shorts,  clipforge ,, cooking")
    assert body["snippet"]["tags"] == ["shorts", "clipforge", "cooking"]


def test_build_video_body_schedule_forces_private() -> None:
    when = datetime.datetime(2026, 8, 20, 9, 0, tzinfo=datetime.timezone.utc)
    body = build_video_body("T", privacy="public", publish_at=when)
    assert body["status"]["privacyStatus"] == "private"  # publishAt requirement
    assert body["status"]["publishAt"] == "2026-08-20T09:00:00Z"


def test_build_video_body_no_schedule_keeps_privacy() -> None:
    body = build_video_body("T", privacy="public")
    assert body["status"]["privacyStatus"] == "public"
    assert "publishAt" not in body["status"]


def test_publish_missing_local_file_raises() -> None:
    from google.oauth2.credentials import Credentials

    from app.providers.publishing.youtube import YouTubeProvider

    provider = YouTubeProvider(Credentials(token="x"))
    with pytest.raises(YouTubeApiError):
        provider.publish("/nonexistent/file.mp4", {"title": "T"})
