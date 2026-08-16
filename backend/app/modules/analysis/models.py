"""ORM model for AI clip candidates (Phase 5, §18/§42/§61).

Candidates carry the per-dimension scores and the §19 overall score. The
clip state machine (§61): candidate → approved → rendering → rendered →
ready_to_publish → publishing → published; users can reject candidates.
"""

from __future__ import annotations

import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class ClipCandidate(Base):
    __tablename__ = "clip_candidates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id"), nullable=False, index=True)
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    hook: Mapped[str] = mapped_column(Text, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hook_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    context_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    emotion_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    standalone_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retention_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="candidate")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
