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
                self._engine = create_engine(database_url, pool_pre_ping=True)
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


db_manager = DatabaseManager()
