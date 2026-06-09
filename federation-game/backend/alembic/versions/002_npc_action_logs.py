"""create npc_action_logs table

Revision ID: 002_npc_action_logs
Revises: 001_initial
Create Date: 2026-06-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "002_npc_action_logs"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "npc_action_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("char_id", sa.String(length=32), nullable=False),
        sa.Column("entry_type", sa.String(length=32), nullable=False),
        sa.Column("timestamp", sa.Integer(), nullable=False),
        sa.Column("data_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create individual indexes for common query patterns
    op.create_index(
        "ix_npc_action_logs_char_id", "npc_action_logs", ["char_id"], unique=False
    )
    op.create_index(
        "ix_npc_action_logs_entry_type", "npc_action_logs", ["entry_type"], unique=False
    )
    op.create_index(
        "ix_npc_action_logs_timestamp", "npc_action_logs", ["timestamp"], unique=False
    )

    # Composite index for the most common query: filter by char_id + entry_type + order by timestamp
    op.create_index(
        "ix_npc_action_logs_composite", "npc_action_logs", ["char_id", "entry_type", "timestamp"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_npc_action_logs_composite", table_name="npc_action_logs")
    op.drop_index("ix_npc_action_logs_timestamp", table_name="npc_action_logs")
    op.drop_index("ix_npc_action_logs_entry_type", table_name="npc_action_logs")
    op.drop_index("ix_npc_action_logs_char_id", table_name="npc_action_logs")
    op.drop_table("npc_action_logs")
