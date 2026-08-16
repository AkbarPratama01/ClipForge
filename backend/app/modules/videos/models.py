"""ORM model for imported videos (Phase 3). Metadata per §13."""

from __future__ import annotations

import datetime

from sqlalchemy import BigInteger, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base

# Status flow (§61): pending → downloading → downloaded → transcribing →
# transcribed → analyzing → analyzed → … → completed (rendering stages arrive
# with later phases). Terminal failures use `failed` with an error code;
# `duplicate` marks checksum duplicates (§67).
VIDEO_STATUSES = {
    "pending",
    "downloading",
    "downloaded",
    "transcribing",
    "transcribed",
    "analyzing",
    "analyzed",
    "uploaded",
    "completed",
    "duplicate",
    "failed",
}


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_url: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel: Mapped[str | None] = mapped_column(String(512), nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    codec: Mapped[str | None] = mapped_column(String(64), nullable=True)
    filesize: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    thumbnail: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
