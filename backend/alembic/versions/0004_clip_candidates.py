"""clip_candidates table

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-15
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "clip_candidates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("video_id", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Float(), nullable=False),
        sa.Column("end_time", sa.Float(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("hook", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hook_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("context_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("emotion_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("standalone_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retention_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="candidate"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_clip_candidates_video_id", "clip_candidates", ["video_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_clip_candidates_video_id", table_name="clip_candidates")
    op.drop_table("clip_candidates")
