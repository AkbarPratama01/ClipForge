"""videos table + storage_files.video_id link

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-15
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "videos",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_url", sa.String(length=512), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("channel", sa.String(length=512), nullable=True),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("fps", sa.Float(), nullable=True),
        sa.Column("codec", sa.String(length=64), nullable=True),
        sa.Column("filesize", sa.BigInteger(), nullable=True),
        sa.Column("thumbnail", sa.String(length=1024), nullable=True),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_videos_source_url", "videos", ["source_url"], unique=False)
    op.create_index("ix_videos_checksum", "videos", ["checksum"], unique=False)

    op.add_column("storage_files", sa.Column("video_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_storage_files_video_id", "storage_files", "videos", ["video_id"], ["id"]
    )


def downgrade() -> None:
    op.drop_constraint("fk_storage_files_video_id", "storage_files", type_="foreignkey")
    op.drop_column("storage_files", "video_id")
    op.drop_index("ix_videos_checksum", table_name="videos")
    op.drop_index("ix_videos_source_url", table_name="videos")
    op.drop_table("videos")
