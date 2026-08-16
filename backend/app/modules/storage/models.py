"""ORM models for the storage module (Phase 2).

- ``google_drive_accounts`` — one row per connected Google account; the OAuth
  token is stored **encrypted** (Fernet) and never logged.
- ``storage_files`` — registry of every file ClipForge knows about on any
  storage backend (§49): provider, remote id/path, size, checksum, status.
"""

from __future__ import annotations

import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class GoogleDriveAccount(Base):
    __tablename__ = "google_drive_accounts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    credentials_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="connected")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class StorageFile(Base):
    __tablename__ = "storage_files"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="google_drive")
    provider_file_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    local_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    remote_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="uploaded")
    video_id: Mapped[int | None] = mapped_column(
        ForeignKey("videos.id"), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
