"""YouTube URL validation (§12 Mode A)."""

from app.modules.videos.service import extract_video_id, is_valid_youtube_url


def test_watch_url() -> None:
    assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("https://youtube.com/watch?v=abc123&t=30") == "abc123"
    assert is_valid_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is True


def test_shorts_url() -> None:
    assert extract_video_id("https://www.youtube.com/shorts/9bZkp7q19f0") == "9bZkp7q19f0"


def test_youtu_be_url() -> None:
    assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("https://youtu.be/dQw4w9WgXcQ?si=xyz") == "dQw4w9WgXcQ"


def test_mobile_host() -> None:
    assert extract_video_id("https://m.youtube.com/watch?v=abc123") == "abc123"


def test_invalid_urls() -> None:
    assert extract_video_id("https://example.com/watch?v=abc123") is None
    assert extract_video_id("https://www.youtube.com/") is None
    assert extract_video_id("https://www.youtube.com/watch") is None
    assert extract_video_id("not a url") is None
    assert extract_video_id("") is None
    assert is_valid_youtube_url("https://vimeo.com/123") is False
