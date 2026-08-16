"""Publishing provider factory — selects the backend from ``PUBLISHING_PROVIDER``.

YouTube is the only publishing backend today (Phase 8-9); Instagram/TikTok
arrive later behind the same :class:`PublishingProvider` contract (§59).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.publishing.errors import PublishingError
from app.providers.base import PublishingProvider


def get_publishing_provider(db: Session) -> PublishingProvider:
    provider = settings.publishing_provider
    if provider == "youtube":
        from app.modules.publishing.service import get_youtube_credentials
        from app.providers.publishing.youtube import YouTubeProvider

        return YouTubeProvider(credentials=get_youtube_credentials(db))

    raise PublishingError(
        "PUBLISHING_PROVIDER_UNSUPPORTED",
        f"Unknown PUBLISHING_PROVIDER={provider!r} (supported: youtube)",
    )
