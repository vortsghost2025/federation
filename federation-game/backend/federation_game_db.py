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
                Base.metadata.create_all(self._engine)
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


db_manager = DatabaseManager()
