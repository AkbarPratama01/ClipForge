"""Publishing error types (Phase 8-9).

Every publishing failure carries a stable code (§62) so the dashboard can
display and retry failures without the pipeline crashing.
"""

from __future__ import annotations


class PublishingError(Exception):
    """Base publishing error with a machine-readable code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class YouTubeNotConnected(PublishingError):
    """No usable YouTube account is connected."""

    def __init__(self) -> None:
        super().__init__(
            "YOUTUBE_NOT_CONNECTED", "No YouTube account is connected."
        )


class YouTubeApiError(PublishingError):
    """YouTube Data API call failed."""

    def __init__(self, detail: str) -> None:
        super().__init__("YOUTUBE_API_ERROR", detail)
