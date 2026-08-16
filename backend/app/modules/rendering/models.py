"""ORM model for rendered clips (Phase 6).

One row per rendered candidate (``clip_renders``). The clip state machine
(§61) continues: candidate → approved → rendering → rendered →
ready_to_publish → … A failed render keeps the candidate ``approved`` so the
user can retry; ``quality_passed`` records the Phase 6 quality gate result.
"""

from __future__ import annotations

import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class ClipRender(Base):
    __tablename__ = "clip_renders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("clip_candidates.id"), nullable=False, unique=True, index=True
    )
    video_id: Mapped[int] = mapped_column(
        ForeignKey("videos.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    # Local path of the rendered Short (kept for preview; Drive output is
    # Phase 7). Relative paths are resolved against the render workdir.
    local_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Drive path of the synced Short (``04_Clips/...``), set after upload (Phase 7).
    remote_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    filesize: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
