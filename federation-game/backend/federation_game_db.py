#!/usr/bin/env python3
"""
Federation Game - PostgreSQL Persistence Layer
SQLAlchemy ORM module for saving/restoring game state to survive backend restarts.
"""

import json
import hashlib
import logging
import time
import os
from datetime import datetime
from typing import Optional, Dict, Any, List

from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    String,
    Boolean,
    DateTime,
    Text,
    create_engine,
    Index,
    JSON,
)
from sqlalchemy.orm import Session, declarative_base, sessionmaker

logger = logging.getLogger("federation.db")

Base = declarative_base()


class GameSnapshot(Base):
    __tablename__ = "game_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_type = Column(String(32), nullable=False, default="auto")
    game_state_json = Column(Text, nullable=True)
    federation_state_json = Column(Text, nullable=True)
    history_arc_json = Column(Text, nullable=True)
    turn_log_json = Column(Text, nullable=True)
    state_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_current = Column(Boolean, default=False, nullable=False)


class NpcActionLog(Base):
    __tablename__ = "npc_action_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    char_id = Column(String(32), nullable=False, index=True)
    entry_type = Column(String(32), nullable=False, index=True)
    timestamp = Column(Integer, nullable=False, index=True)
    data_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_npc_action_logs_composite", "char_id", "entry_type", "timestamp"),
    )


class NpcTurn(Base):
    __tablename__ = "npc_turns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    turn_id = Column(String(64), nullable=False, unique=True, index=True)
    trace_id = Column(String(64), nullable=False, index=True)
    npc_id = Column(String(32), nullable=False, index=True)
    session_id = Column(String(64), nullable=True, index=True)
    timestamp = Column(Integer, nullable=False, index=True)
    task_class = Column(String(32), nullable=True, index=True)
    model_provider = Column(String(32), nullable=True, index=True)
    model_name = Column(String(128), nullable=True)
    input_text = Column(Text, nullable=True)
    system_prompt_version = Column(String(64), nullable=True)
    system_prompt_text = Column(Text, nullable=True)
    memory_context_ids = Column(JSON, nullable=True)
    retrieved_facts = Column(JSON, nullable=True)
    tool_calls = Column(JSON, nullable=True)
    output_text = Column(Text, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    token_in = Column(Integer, nullable=True)
    token_out = Column(Integer, nullable=True)
    error_code = Column(String(128), nullable=True, index=True)
    fallback_used = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_npc_turns_npc_time", "npc_id", "timestamp"),
        Index("ix_npc_turns_provider_time", "model_provider", "timestamp"),
    )


class NpcMemoryEvent(Base):
    __tablename__ = "npc_memory_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    memory_id = Column(String(64), nullable=False, unique=True, index=True)
    npc_id = Column(String(32), nullable=False, index=True)
    turn_id = Column(String(64), ForeignKey("npc_turns.turn_id"), nullable=False, index=True)
    event_type = Column(String(32), nullable=False, index=True)
    content = Column(Text, nullable=True)
    source = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class NpcToolEvent(Base):
    __tablename__ = "npc_tool_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tool_event_id = Column(String(64), nullable=False, unique=True, index=True)
    turn_id = Column(String(64), ForeignKey("npc_turns.turn_id"), nullable=False, index=True)
    tool_name = Column(String(128), nullable=False, index=True)
    input_json = Column(JSON, nullable=True)
    output_json = Column(JSON, nullable=True)
    status = Column(String(32), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class DatabaseManager:
    def __init__(self):
        self._engine = None
        self._SessionLocal = None
        self._initialized = False

    def initialize(self) -> bool:
        if self._initialized:
            return True

        database_url = os.environ.get(
            "DATABASE_URL",
            "postgresql://federation:federation_pwd@postgres:5432/federation_game",
        )

        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(
                    "DB init attempt %d/%d — connecting to Postgres",
                    attempt,
                    max_attempts,
                )
                self._engine = create_engine(database_url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
                self._run_alembic_upgrade(database_url)
                self._SessionLocal = sessionmaker(bind=self._engine)
                self._initialized = True
                logger.info("DB initialized successfully on attempt %d", attempt)
                return True
            except Exception as exc:
                logger.warning("DB init attempt %d failed: %s", attempt, exc)
                if attempt < max_attempts:
                    time.sleep(5)

        logger.error("DB initialization failed after %d attempts", max_attempts)
        self._engine = None
        self._SessionLocal = None
        self._initialized = False
        return False

    def _run_alembic_upgrade(self, database_url: str) -> None:
        try:
            from alembic.config import Config as AlembicConfig
            from alembic.script import ScriptDirectory
            from alembic.runtime.migration import MigrationContext
            from sqlalchemy import inspect as sa_inspect

            alembic_cfg = AlembicConfig()
            alembic_cfg.set_main_option("script_location", "alembic")
            alembic_cfg.set_main_option("sqlalchemy.url", database_url)

            with self._engine.connect() as conn:
                context = MigrationContext.configure(conn)
                current_rev = context.get_current_revision()

            script = ScriptDirectory.from_config(alembic_cfg)
            head_rev = script.get_current_head()

            if current_rev is None:
                inspector = sa_inspect(self._engine)
                existing_tables = inspector.get_table_names()
                if "game_snapshots" in existing_tables:
                    from alembic import command
                    logger.info("Existing tables found — stamping Alembic at %s", head_rev)
                    command.stamp(alembic_cfg, head_rev)
                else:
                    from alembic import command
                    logger.info("No existing tables — running Alembic upgrade to %s", head_rev)
                    command.upgrade(alembic_cfg, head_rev)
            elif current_rev != head_rev:
                from alembic import command
                logger.info("Migrating from %s to %s", current_rev, head_rev)
                command.upgrade(alembic_cfg, head_rev)
            else:
                logger.info("Alembic already at head (%s)", head_rev)
        except Exception as exc:
            logger.warning("Alembic migration skipped (non-fatal): %s", exc)
            Base.metadata.create_all(self._engine)

    def save_snapshot(
        self,
        game_state_json: Optional[str] = None,
        federation_state_json: Optional[str] = None,
        history_arc_json: Optional[str] = None,
        turn_log_json: Optional[str] = None,
        state_hash: Optional[str] = None,
        snapshot_type: str = "auto",
    ) -> bool:
        if not self._initialized:
            logger.warning("save_snapshot called but DB not initialized — skipping")
            return False

        try:
            with self._SessionLocal() as session:
                session.query(GameSnapshot).update({GameSnapshot.is_current: False})

                snapshot = GameSnapshot(
                    snapshot_type=snapshot_type,
                    game_state_json=game_state_json,
                    federation_state_json=federation_state_json,
                    history_arc_json=history_arc_json,
                    turn_log_json=turn_log_json,
                    state_hash=state_hash,
                    is_current=True,
                )
                session.add(snapshot)
                session.commit()

                old = (
                    session.query(GameSnapshot)
                    .order_by(GameSnapshot.id.desc())
                    .offset(50)
                    .all()
                )
                for row in old:
                    session.delete(row)
                session.commit()

            logger.info("Snapshot saved (type=%s, hash=%s)", snapshot_type, state_hash)
            return True
        except Exception as exc:
            logger.error("save_snapshot failed: %s", exc)
            return False

    def load_latest_snapshot(self) -> Optional[Dict[str, Any]]:
        if not self._initialized:
            logger.warning(
                "load_latest_snapshot called but DB not initialized — returning None"
            )
            return None

        try:
            with self._SessionLocal() as session:
                # Prefer decision/reset/auto snapshots over manual (periodic) ones
                row = (
                    session.query(GameSnapshot)
                    .filter(GameSnapshot.snapshot_type != "manual")
                    .order_by(GameSnapshot.id.desc())
                    .first()
                )
                if row is None:
                    # Fallback to the most recent snapshot of any type
                    row = (
                        session.query(GameSnapshot)
                        .order_by(GameSnapshot.id.desc())
                        .first()
                    )

                if row is None:
                    logger.info("No snapshots found in DB")
                    return None

                result = {
                    "id": row.id,
                    "snapshot_type": row.snapshot_type,
                    "game_state_json": row.game_state_json,
                    "federation_state_json": row.federation_state_json,
                    "history_arc_json": row.history_arc_json,
                    "turn_log_json": row.turn_log_json,
                    "state_hash": row.state_hash,
                    "created_at": row.created_at.isoformat()
                    if row.created_at
                    else None,
                    "is_current": row.is_current,
                }
                logger.info("Loaded snapshot id=%d type=%s", row.id, row.snapshot_type)
                return result
        except Exception as exc:
            logger.error("load_latest_snapshot failed: %s", exc)
            return None

    def get_snapshot_count(self) -> int:
        if not self._initialized:
            return 0
        try:
            with self._SessionLocal() as session:
                return session.query(GameSnapshot).count()
        except Exception:
            return 0

    def cleanup_old_snapshots(self, keep: int = 10) -> int:
        if not self._initialized:
            return 0
        try:
            with self._SessionLocal() as session:
                ids_to_keep = [
                    row[0]
                    for row in session.query(GameSnapshot.id)
                    .order_by(GameSnapshot.id.desc())
                    .limit(keep)
                    .all()
                ]
                if not ids_to_keep:
                    return 0
                deleted = (
                    session.query(GameSnapshot)
                    .filter(GameSnapshot.id.notin_(ids_to_keep))
                    .delete(synchronize_session=False)
                )
                session.commit()
                logger.info("Cleaned up %d old snapshots (kept %d)", deleted, keep)
                return deleted
        except Exception as exc:
            logger.error("cleanup_old_snapshots failed: %s", exc)
            return 0

    def log_npc_action(
        self,
        char_id: str,
        entry_type: str,
        data_json: Optional[Dict[str, Any]] = None,
        timestamp: Optional[int] = None,
    ) -> bool:
        """
        Log an NPC action to PostgreSQL.

        Args:
            char_id: NPC character ID
            entry_type: One of 'cognition', 'interaction', 'decision', 'chat'
            data_json: Entry-specific data (will be stored as JSON)
            timestamp: Unix timestamp (defaults to now)

        Returns:
            True if logged, False if failed
        """
        if not self._initialized:
            logger.warning("log_npc_action called but DB not initialized — skipping")
            return False

        try:
            ts = timestamp or int(time.time())
            with self._SessionLocal() as session:
                log_entry = NpcActionLog(
                    char_id=char_id,
                    entry_type=entry_type,
                    timestamp=ts,
                    data_json=data_json,
                )
                session.add(log_entry)
                session.commit()
            logger.debug("Logged NPC action: char_id=%s type=%s ts=%d", char_id, entry_type, ts)
            return True
        except Exception as exc:
            logger.error("log_npc_action failed: %s", exc)
            return False

    def log_npc_turn(
        self,
        turn: Dict[str, Any],
        memory_events: Optional[List[Dict[str, Any]]] = None,
        tool_events: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[str]:
        """Persist a full NPC LLM turn trace plus optional child events."""
        if not self._initialized:
            logger.warning("log_npc_turn called but DB not initialized — skipping")
            return None

        try:
            import uuid

            ts = int(turn.get("timestamp") or time.time())
            turn_id = turn.get("turn_id") or f"turn_{uuid.uuid4().hex}"
            trace_id = turn.get("trace_id") or turn_id
            npc_id = turn.get("npc_id") or turn.get("char_id") or "unknown"

            with self._SessionLocal() as session:
                session.add(
                    NpcTurn(
                        turn_id=turn_id,
                        trace_id=trace_id,
                        npc_id=npc_id,
                        session_id=turn.get("session_id"),
                        timestamp=ts,
                        task_class=turn.get("task_class"),
                        model_provider=turn.get("model_provider"),
                        model_name=turn.get("model_name"),
                        input_text=turn.get("input_text"),
                        system_prompt_version=turn.get("system_prompt_version"),
                        system_prompt_text=turn.get("system_prompt_text"),
                        memory_context_ids=turn.get("memory_context_ids"),
                        retrieved_facts=turn.get("retrieved_facts"),
                        tool_calls=turn.get("tool_calls"),
                        output_text=turn.get("output_text"),
                        latency_ms=turn.get("latency_ms"),
                        token_in=turn.get("token_in"),
                        token_out=turn.get("token_out"),
                        error_code=turn.get("error_code"),
                        fallback_used=bool(turn.get("fallback_used", False)),
                    )
                )
                session.flush()

                for event in memory_events or []:
                    session.add(
                        NpcMemoryEvent(
                            memory_id=event.get("memory_id") or f"mem_{uuid.uuid4().hex}",
                            npc_id=event.get("npc_id") or npc_id,
                            turn_id=turn_id,
                            event_type=event.get("event_type") or "retrieve",
                            content=event.get("content"),
                            source=event.get("source"),
                        )
                    )

                for event in tool_events or []:
                    session.add(
                        NpcToolEvent(
                            tool_event_id=event.get("tool_event_id") or f"tool_{uuid.uuid4().hex}",
                            turn_id=turn_id,
                            tool_name=event.get("tool_name") or "unknown",
                            input_json=event.get("input"),
                            output_json=event.get("output"),
                            status=event.get("status") or "unknown",
                        )
                    )

                session.commit()

            logger.debug("Logged NPC turn: npc_id=%s turn_id=%s", npc_id, turn_id)
            return turn_id
        except Exception as exc:
            logger.error("log_npc_turn failed: %s", exc)
            return None

    def get_npc_turns(
        self,
        npc_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        include_events: bool = False,
    ) -> List[Dict[str, Any]]:
        """Retrieve full NPC turn traces from PostgreSQL."""
        if not self._initialized:
            logger.warning("get_npc_turns called but DB not initialized — returning empty list")
            return []

        try:
            with self._SessionLocal() as session:
                query = session.query(NpcTurn)
                if npc_id:
                    query = query.filter(NpcTurn.npc_id == npc_id)

                rows = (
                    query.order_by(NpcTurn.timestamp.desc(), NpcTurn.id.desc())
                    .limit(limit)
                    .offset(offset)
                    .all()
                )

                memory_by_turn: Dict[str, List[Dict[str, Any]]] = {}
                tool_by_turn: Dict[str, List[Dict[str, Any]]] = {}
                if include_events and rows:
                    turn_ids = [row.turn_id for row in rows]
                    for event in session.query(NpcMemoryEvent).filter(NpcMemoryEvent.turn_id.in_(turn_ids)).all():
                        memory_by_turn.setdefault(event.turn_id, []).append(
                            {
                                "memory_id": event.memory_id,
                                "npc_id": event.npc_id,
                                "event_type": event.event_type,
                                "content": event.content,
                                "source": event.source,
                                "created_at": event.created_at.isoformat() if event.created_at else None,
                            }
                        )
                    for event in session.query(NpcToolEvent).filter(NpcToolEvent.turn_id.in_(turn_ids)).all():
                        tool_by_turn.setdefault(event.turn_id, []).append(
                            {
                                "tool_event_id": event.tool_event_id,
                                "tool_name": event.tool_name,
                                "input": event.input_json,
                                "output": event.output_json,
                                "status": event.status,
                                "created_at": event.created_at.isoformat() if event.created_at else None,
                            }
                        )

                results = []
                for row in rows:
                    item = {
                        "turn_id": row.turn_id,
                        "trace_id": row.trace_id,
                        "npc_id": row.npc_id,
                        "session_id": row.session_id,
                        "timestamp": row.timestamp,
                        "task_class": row.task_class,
                        "model_provider": row.model_provider,
                        "model_name": row.model_name,
                        "input_text": row.input_text,
                        "system_prompt_version": row.system_prompt_version,
                        "system_prompt_text": row.system_prompt_text,
                        "memory_context_ids": row.memory_context_ids,
                        "retrieved_facts": row.retrieved_facts,
                        "tool_calls": row.tool_calls,
                        "output_text": row.output_text,
                        "latency_ms": row.latency_ms,
                        "token_in": row.token_in,
                        "token_out": row.token_out,
                        "error_code": row.error_code,
                        "fallback_used": row.fallback_used,
                        "created_at": row.created_at.isoformat() if row.created_at else None,
                    }
                    if include_events:
                        item["memory_events"] = memory_by_turn.get(row.turn_id, [])
                        item["tool_events"] = tool_by_turn.get(row.turn_id, [])
                    results.append(item)
                return results
        except Exception as exc:
            logger.error("get_npc_turns failed: %s", exc)
            return []

    def get_npc_action_log(
        self,
        char_id: str,
        entry_types: Optional[List[str]] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve NPC action logs from PostgreSQL.

        Args:
            char_id: NPC character ID
            entry_types: Optional filter by entry type(s)
            limit: Maximum entries to return (most recent first)
            offset: Number of entries to skip (for pagination)

        Returns:
            List of activity entries, most recent first
        """
        if not self._initialized:
            logger.warning("get_npc_action_log called but DB not initialized — returning empty list")
            return []

        try:
            with self._SessionLocal() as session:
                query = session.query(NpcActionLog).filter(NpcActionLog.char_id == char_id)

                if entry_types:
                    query = query.filter(NpcActionLog.entry_type.in_(entry_types))

                rows = (
                    query.order_by(NpcActionLog.timestamp.desc())
                    .limit(limit)
                    .offset(offset)
                    .all()
                )

                results = []
                for row in rows:
                    results.append({
                        "id": row.id,
                        "char_id": row.char_id,
                        "entry_type": row.entry_type,
                        "timestamp": row.timestamp,
                        "data": row.data_json,
                        "created_at": row.created_at.isoformat() if row.created_at else None,
                    })
                return results
        except Exception as exc:
            logger.error("get_npc_action_log failed: %s", exc)
            return []

    def export_npc_action_log_csv(
        self,
        char_id: str,
        entry_types: Optional[List[str]] = None,
        limit: int = 10000,
    ) -> str:
        """
        Export NPC action logs as CSV string.

        Args:
            char_id: NPC character ID
            entry_types: Optional filter by entry type(s)
            limit: Maximum entries to include

        Returns:
            CSV string with headers: id,char_id,entry_type,timestamp,data_json,created_at
        """
        if not self._initialized:
            return ""

        try:
            with self._SessionLocal() as session:
                query = session.query(NpcActionLog).filter(NpcActionLog.char_id == char_id)

                if entry_types:
                    query = query.filter(NpcActionLog.entry_type.in_(entry_types))

                rows = (
                    query.order_by(NpcActionLog.timestamp.desc())
                    .limit(limit)
                    .all()
                )

                # Build CSV
                import csv
                import io
                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerow(["id", "char_id", "entry_type", "timestamp", "data_json", "created_at"])
                for row in rows:
                    data_str = json.dumps(row.data_json) if row.data_json is not None else ""
                    created_str = row.created_at.isoformat() if row.created_at else ""
                    writer.writerow([row.id, row.char_id, row.entry_type, row.timestamp, data_str, created_str])
                return output.getvalue()
        except Exception as exc:
            logger.error("export_npc_action_log_csv failed: %s", exc)
            return ""

    def commit_npc_daily_logs(self) -> Dict[str, Any]:
        """Aggregate last 24h NPC action logs into a daily summary row.

        Creates/updates npc_daily_summaries table with aggregated counts by NPC
        and entry type. Should be called periodically (e.g., daily cron).

        Returns:
            Dict with 'status', 'date', 'total', 'npc_count' on success,
            or 'status' and 'reason' on skip/error.
        """
        if not self._initialized:
            logger.warning("commit_npc_daily_logs called but DB not initialized")
            return {"status": "skipped", "reason": "DB not initialized"}

        try:
            from sqlalchemy import text
            import datetime

            with self._SessionLocal() as session:
                # Ensure target table exists
                session.execute(text("""
                    CREATE TABLE IF NOT EXISTS npc_daily_summaries (
                        id SERIAL PRIMARY KEY,
                        summary_date DATE NOT NULL UNIQUE,
                        total_entries INTEGER DEFAULT 0,
                        npc_count INTEGER DEFAULT 0,
                        entry_type_breakdown JSONB DEFAULT '{}'::jsonb,
                        npc_breakdown JSONB DEFAULT '{}'::jsonb,
                        created_at TIMESTAMP DEFAULT NOW()
                    )
                """))
                session.commit()

                # Aggregate last 24h entries
                cutoff_ts = int((datetime.datetime.utcnow() - datetime.timedelta(hours=24)).timestamp())
                rows = session.query(NpcActionLog).filter(
                    NpcActionLog.timestamp >= cutoff_ts
                ).all()

                if not rows:
                    logger.info("No NPC action logs in last 24h, skipping daily summary")
                    return {"status": "no_data", "date": str(datetime.date.today())}

                # Aggregate by NPC and entry type
                total = len(rows)
                npc_counts = {}
                type_counts = {}
                for row in rows:
                    npc_counts[row.char_id] = npc_counts.get(row.char_id, 0) + 1
                    type_counts[row.entry_type] = type_counts.get(row.entry_type, 0) + 1

                today = datetime.date.today()

                # Upsert summary row
                session.execute(text("""
                    INSERT INTO npc_daily_summaries
                        (summary_date, total_entries, npc_count, entry_type_breakdown, npc_breakdown)
                    VALUES (:date, :total, :npc_count, :types, :npcs)
                    ON CONFLICT (summary_date) DO UPDATE SET
                        total_entries = EXCLUDED.total_entries,
                        npc_count = EXCLUDED.npc_count,
                        entry_type_breakdown = EXCLUDED.entry_type_breakdown,
                        npc_breakdown = EXCLUDED.npc_breakdown
                """), {
                    "date": today,
                    "total": total,
                    "npc_count": len(npc_counts),
                    "types": json.dumps(type_counts),
                    "npcs": json.dumps(npc_counts),
                })
                session.commit()

                logger.info(
                    "Daily NPC summary committed: %d entries, %d NPCs",
                    total, len(npc_counts),
                )
                return {
                    "status": "success",
                    "date": str(today),
                    "total": total,
                    "npc_count": len(npc_counts),
                }
        except Exception as exc:
            logger.error("commit_npc_daily_logs failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    def compact_weekly_logs(self, days: int = 30) -> Dict[str, Any]:
        """Compaction: old entries (age > days) get rolled up by day/NPC/type.

        Aggregates detail rows into npc_action_logs_compacted (with counts + sample data),
        then deletes originals. Use for space management on long-running deployments.

        Args:
            days: Keep full detail for entries newer than this many days. Default 30.

        Returns:
            Dict with 'status', 'compacted' (rows compacted), 'aggregated' (groups).
        """
        if not self._initialized:
            logger.warning("compact_weekly_logs called but DB not initialized")
            return {"status": "skipped", "reason": "DB not initialized"}

        try:
            from sqlalchemy import text
            import datetime
            from collections import defaultdict

            cutoff_ts = int((datetime.datetime.utcnow() - datetime.timedelta(days=days)).timestamp())

            with self._SessionLocal() as session:
                # Ensure target table exists
                session.execute(text("""
                    CREATE TABLE IF NOT EXISTS npc_action_logs_compacted (
                        id SERIAL PRIMARY KEY,
                        bucket_day INTEGER NOT NULL,
                        char_id VARCHAR(64) NOT NULL,
                        entry_type VARCHAR(64) NOT NULL,
                        count INTEGER NOT NULL,
                        sample_data JSONB,
                        created_at TIMESTAMP DEFAULT NOW(),
                        UNIQUE (bucket_day, char_id, entry_type)
                    )
                """))
                session.commit()

                # Find old rows
                old_rows = session.query(NpcActionLog).filter(
                    NpcActionLog.timestamp < cutoff_ts
                ).limit(10000).all()

                if not old_rows:
                    logger.info("No old entries to compact (cutoff=%d days)", days)
                    return {"status": "no_data", "compacted": 0, "aggregated": 0}

                # Group by day bucket / char_id / entry_type
                grouped = defaultdict(lambda: {"count": 0, "sample_data": None})

                for row in old_rows:
                    day_bucket = row.timestamp // 86400  # day since epoch
                    key = (day_bucket, row.char_id, row.entry_type)
                    grouped[key]["count"] += 1
                    if grouped[key]["sample_data"] is None:
                        grouped[key]["sample_data"] = row.data_json

                # Upsert compacted data
                for (day_bucket, char_id, entry_type), data in grouped.items():
                    session.execute(text("""
                        INSERT INTO npc_action_logs_compacted
                            (bucket_day, char_id, entry_type, count, sample_data)
                        VALUES (:bd, :cid, :et, :cnt, :sd)
                        ON CONFLICT (bucket_day, char_id, entry_type) DO UPDATE SET
                            count = npc_action_logs_compacted.count + EXCLUDED.count,
                            sample_data = EXCLUDED.sample_data
                    """), {
                        "bd": day_bucket,
                        "cid": char_id,
                        "et": entry_type,
                        "cnt": data["count"],
                        "sd": json.dumps(data["sample_data"]) if data["sample_data"] else None,
                    })

                # Delete the original detailed rows
                ids_to_delete = [row.id for row in old_rows]
                session.query(NpcActionLog).filter(NpcActionLog.id.in_(ids_to_delete)).delete(
                    synchronize_session=False
                )
                session.commit()

                logger.info(
                    "Compacted %d old NPC rows into %d aggregated entries (older than %d days)",
                    len(old_rows), len(grouped), days,
                )
                return {
                    "status": "success",
                    "compacted": len(old_rows),
                    "aggregated": len(grouped),
                }
        except Exception as exc:
            logger.error("compact_weekly_logs failed: %s", exc)
            return {"status": "error", "error": str(exc)}


db_manager = DatabaseManager()
