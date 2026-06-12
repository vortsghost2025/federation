"""create npc turn trace tables

Revision ID: 003_npc_turn_traces
Revises: 002_npc_action_logs
Create Date: 2026-06-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "003_npc_turn_traces"
down_revision: Union[str, None] = "002_npc_action_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "npc_turns",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("turn_id", sa.String(length=64), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("npc_id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("timestamp", sa.Integer(), nullable=False),
        sa.Column("task_class", sa.String(length=32), nullable=True),
        sa.Column("model_provider", sa.String(length=32), nullable=True),
        sa.Column("model_name", sa.String(length=128), nullable=True),
        sa.Column("input_text", sa.Text(), nullable=True),
        sa.Column("system_prompt_version", sa.String(length=64), nullable=True),
        sa.Column("system_prompt_text", sa.Text(), nullable=True),
        sa.Column("memory_context_ids", sa.JSON(), nullable=True),
        sa.Column("retrieved_facts", sa.JSON(), nullable=True),
        sa.Column("tool_calls", sa.JSON(), nullable=True),
        sa.Column("output_text", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("token_in", sa.Integer(), nullable=True),
        sa.Column("token_out", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("fallback_used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("turn_id", name="uq_npc_turns_turn_id"),
    )
    op.create_index("ix_npc_turns_turn_id", "npc_turns", ["turn_id"], unique=False)
    op.create_index("ix_npc_turns_trace_id", "npc_turns", ["trace_id"], unique=False)
    op.create_index("ix_npc_turns_npc_id", "npc_turns", ["npc_id"], unique=False)
    op.create_index("ix_npc_turns_session_id", "npc_turns", ["session_id"], unique=False)
    op.create_index("ix_npc_turns_timestamp", "npc_turns", ["timestamp"], unique=False)
    op.create_index("ix_npc_turns_task_class", "npc_turns", ["task_class"], unique=False)
    op.create_index("ix_npc_turns_model_provider", "npc_turns", ["model_provider"], unique=False)
    op.create_index("ix_npc_turns_error_code", "npc_turns", ["error_code"], unique=False)
    op.create_index("ix_npc_turns_npc_time", "npc_turns", ["npc_id", "timestamp"], unique=False)
    op.create_index("ix_npc_turns_provider_time", "npc_turns", ["model_provider", "timestamp"], unique=False)

    op.create_table(
        "npc_memory_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("memory_id", sa.String(length=64), nullable=False),
        sa.Column("npc_id", sa.String(length=32), nullable=False),
        sa.Column("turn_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["turn_id"], ["npc_turns.turn_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("memory_id", name="uq_npc_memory_events_memory_id"),
    )
    op.create_index("ix_npc_memory_events_memory_id", "npc_memory_events", ["memory_id"], unique=False)
    op.create_index("ix_npc_memory_events_npc_id", "npc_memory_events", ["npc_id"], unique=False)
    op.create_index("ix_npc_memory_events_turn_id", "npc_memory_events", ["turn_id"], unique=False)
    op.create_index("ix_npc_memory_events_event_type", "npc_memory_events", ["event_type"], unique=False)

    op.create_table(
        "npc_tool_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tool_event_id", sa.String(length=64), nullable=False),
        sa.Column("turn_id", sa.String(length=64), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=True),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["turn_id"], ["npc_turns.turn_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tool_event_id", name="uq_npc_tool_events_tool_event_id"),
    )
    op.create_index("ix_npc_tool_events_tool_event_id", "npc_tool_events", ["tool_event_id"], unique=False)
    op.create_index("ix_npc_tool_events_turn_id", "npc_tool_events", ["turn_id"], unique=False)
    op.create_index("ix_npc_tool_events_tool_name", "npc_tool_events", ["tool_name"], unique=False)
    op.create_index("ix_npc_tool_events_status", "npc_tool_events", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_npc_tool_events_status", table_name="npc_tool_events")
    op.drop_index("ix_npc_tool_events_tool_name", table_name="npc_tool_events")
    op.drop_index("ix_npc_tool_events_turn_id", table_name="npc_tool_events")
    op.drop_index("ix_npc_tool_events_tool_event_id", table_name="npc_tool_events")
    op.drop_table("npc_tool_events")

    op.drop_index("ix_npc_memory_events_event_type", table_name="npc_memory_events")
    op.drop_index("ix_npc_memory_events_turn_id", table_name="npc_memory_events")
    op.drop_index("ix_npc_memory_events_npc_id", table_name="npc_memory_events")
    op.drop_index("ix_npc_memory_events_memory_id", table_name="npc_memory_events")
    op.drop_table("npc_memory_events")

    op.drop_index("ix_npc_turns_provider_time", table_name="npc_turns")
    op.drop_index("ix_npc_turns_npc_time", table_name="npc_turns")
    op.drop_index("ix_npc_turns_error_code", table_name="npc_turns")
    op.drop_index("ix_npc_turns_model_provider", table_name="npc_turns")
    op.drop_index("ix_npc_turns_task_class", table_name="npc_turns")
    op.drop_index("ix_npc_turns_timestamp", table_name="npc_turns")
    op.drop_index("ix_npc_turns_session_id", table_name="npc_turns")
    op.drop_index("ix_npc_turns_npc_id", table_name="npc_turns")
    op.drop_index("ix_npc_turns_trace_id", table_name="npc_turns")
    op.drop_index("ix_npc_turns_turn_id", table_name="npc_turns")
    op.drop_table("npc_turns")
