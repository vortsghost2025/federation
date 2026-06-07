"""initial schema - game_snapshots

Revision ID: 001_initial
Revises: None
Create Date: 2026-06-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "game_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("snapshot_type", sa.String(length=32), nullable=False, server_default="auto"),
        sa.Column("game_state_json", sa.Text(), nullable=True),
        sa.Column("federation_state_json", sa.Text(), nullable=True),
        sa.Column("history_arc_json", sa.Text(), nullable=True),
        sa.Column("turn_log_json", sa.Text(), nullable=True),
        sa.Column("state_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("game_snapshots")
