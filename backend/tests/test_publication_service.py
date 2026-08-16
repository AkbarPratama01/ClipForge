"""Phase 8-9 publication service tests (pure — no DB)."""

import datetime

import pytest

from app.modules.publishing.errors import PublishingError
from app.modules.publishing.models import Publication
from app.modules.publishing.service import (
    effective_status,
    publication_payload,
    validate_privacy,
    validate_schedule,
)

NOW = datetime.datetime.now(datetime.timezone.utc)


def test_validate_privacy_accepts_known_values() -> None:
    assert validate_privacy("private") == "private"
    assert validate_privacy("unlisted") == "unlisted"
    assert validate_privacy("public") == "public"


def test_validate_privacy_rejects_unknown() -> None:
    with pytest.raises(PublishingError) as exc:
        validate_privacy("everyone")
    assert exc.value.code == "INVALID_PRIVACY"


def test_validate_schedule_none_ok() -> None:
    validate_schedule(None)


def test_validate_schedule_past_rejected() -> None:
    with pytest.raises(PublishingError) as exc:
        validate_schedule(NOW - datetime.timedelta(hours=1))
    assert exc.value.code == "SCHEDULE_IN_PAST"


def test_validate_schedule_future_ok() -> None:
    validate_schedule(NOW + datetime.timedelta(days=1))


def test_effective_status_scheduled_past_is_published() -> None:
    pub = Publication(
        render_id=1, video_id=1, title="T", status="scheduled",
        scheduled_at=NOW - datetime.timedelta(hours=2),
    )
    assert effective_status(pub, now=NOW) == "published"


def test_effective_status_scheduled_future_stays_scheduled() -> None:
    pub = Publication(
        render_id=1, video_id=1, title="T", status="scheduled",
        scheduled_at=NOW + datetime.timedelta(hours=2),
    )
    assert effective_status(pub, now=NOW) == "scheduled"


def test_effective_status_other_statuses_unchanged() -> None:
    for status in ("queued", "uploading", "published", "failed"):
        pub = Publication(render_id=1, video_id=1, title="T", status=status)
        assert effective_status(pub, now=NOW) == status


def test_publication_payload_shape() -> None:
    pub = Publication(
        id=7,
        render_id=3,
        video_id=2,
        youtube_video_id="dQw4w9WgXcQ",
        title="Title",
        description="Desc",
        tags="a,b",
        privacy="private",
        status="published",
    )
    payload = publication_payload(pub)
    assert payload["youtube_video_id"] == "dQw4w9WgXcQ"
    assert payload["render_id"] == 3
    assert payload["video_id"] == 2
    assert payload["status"] == "published"
    assert payload["privacy"] == "private"
