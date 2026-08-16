"""ORM models for YouTube publishing (Phase 8-9).

- ``youtube_accounts`` — one row per connected YouTube channel; the OAuth
  token is stored **encrypted** (Fernet, same key as Drive) and never logged.
- ``publications`` — publication history (§65): one row per publish attempt,
  with scheduling (YouTube ``publishAt``) and the external video id.
"""

from __future__ import annotations

import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base

# Publication state machine (§61 continuation): queued → uploading →
# published | scheduled | failed. ``scheduled`` means the video was uploaded
# with YouTube's publishAt and will go live automatically.
PUBLICATION_STATUSES = {"queued", "uploading", "published", "scheduled", "failed"}

YOUTUBE_PRIVACY = {"private", "unlisted", "public"}


class YouTubeAccount(Base):
    __tablename__ = "youtube_accounts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    channel_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    channel_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    credentials_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="connected")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Publication(Base):
    __tablename__ = "publications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    render_id: Mapped[int] = mapped_column(
        ForeignKey("clip_renders.id"), nullable=False, index=True
    )
    video_id: Mapped[int] = mapped_column(
        ForeignKey("videos.id"), nullable=False, index=True
    )
    youtube_video_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    privacy: Mapped[str] = mapped_column(
        String(16), nullable=False, default="private"
    )
    scheduled_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    published_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
