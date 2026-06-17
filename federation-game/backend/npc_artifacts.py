"""
NPC ARTIFACT REGISTRY — Persistent creations by NPCs

Each artifact is something an NPC created: text, code, image, structured data.
Artifacts live on disk + Redis index. Other NPCs can discover and read them.

Redis keys:
    artifact:index        — ZSET: artifact_id -> created_ts (all artifacts)
    artifact:{id}         — HASH: artifact metadata
    artifact:npc:{char_id} — ZSET: artifact_ids -> created_ts (per NPC)
    artifact:discoverable — ZSET: artifact_ids -> created_ts (public artifacts)

Disk layout (on VPS):
    /docker/federation-game/artifacts/{char_id}/{artifact_id}/
        content.txt       — the actual artifact content
        metadata.json     — copy of Redis metadata for portability
"""

import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

import redis

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

# On VPS, artifacts live under /docker/federation-game/artifacts/
# Locally, use a relative path
ARTIFACTS_ROOT = os.environ.get(
    "ARTIFACTS_ROOT",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "artifacts"),
)

_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(
            REDIS_URL, decode_responses=True,
            socket_connect_timeout=5, socket_timeout=5,
        )
    return _redis_client


def _ensure_artifact_dir(char_id: str, artifact_id: str) -> str:
    """Create the on-disk directory for an artifact. Returns the path."""
    path = os.path.join(ARTIFACTS_ROOT, char_id, artifact_id)
    os.makedirs(path, exist_ok=True)
    return path


def create_artifact(
    char_id: str,
    char_name: str,
    title: str,
    artifact_type: str,
    content: str,
    discoverable: bool = True,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a new artifact. Returns the artifact dict.

    Args:
        char_id: NPC character ID
        char_name: NPC display name
        title: Human-readable title
        artifact_type: 'text', 'code', 'image', 'poem', 'document', etc.
        content: The actual content (text of the creation)
        discoverable: If True, other NPCs can find it
        metadata: Optional extra key/value data
    """
    r = _get_redis()
    artifact_id = f"art_{uuid.uuid4().hex[:12]}"
    now = time.time()
    meta = {
        "id": artifact_id,
        "char_id": char_id,
        "char_name": char_name,
        "title": title,
        "type": artifact_type,
        "created_at": now,
        "updated_at": now,
        "discoverable": discoverable,
        "content_length": len(content),
    }
    if metadata:
        meta["metadata"] = metadata

    # Write content to disk
    art_dir = _ensure_artifact_dir(char_id, artifact_id)
    try:
        with open(os.path.join(art_dir, "content.txt"), "w", encoding="utf-8") as f:
            f.write(content)
        with open(os.path.join(art_dir, "metadata.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, default=str)
    except OSError as e:
        logger.warning("Failed to write artifact to disk: %s", e)

    # Store content in Redis for cross-container access
    meta["content"] = content[:50000]  # cap at 50KB in Redis

    # Index in Redis
    try:
        r.zadd("artifact:index", {artifact_id: now})
        r.zadd(f"artifact:npc:{char_id}", {artifact_id: now})
        if discoverable:
            r.zadd("artifact:discoverable", {artifact_id: now})
        r.hset(f"artifact:{artifact_id}", mapping=meta)
        r.expire(f"artifact:{artifact_id}", 86400 * 90)  # 90 day TTL
        # Keep only last 500 artifacts total
        r.zremrangebyrank("artifact:index", 0, -501)
    except Exception as e:
        logger.warning("Failed to index artifact in Redis: %s", e)

    logger.info("Artifact created: %s by %s (%s) — %s", artifact_id, char_name, artifact_type, title[:60])
    return meta


def get_artifact(artifact_id: str) -> Optional[Dict[str, Any]]:
    """Get artifact metadata + content. Returns None if not found."""
    r = _get_redis()
    try:
        meta = r.hgetall(f"artifact:{artifact_id}")
        if not meta:
            return None
        result = dict(meta)
        # If content is already in Redis (stored by create_artifact), use it
        if "content" not in result or not result["content"]:
            # Fallback: read content from disk
            char_id = result.get("char_id", "")
            path = os.path.join(ARTIFACTS_ROOT, char_id, artifact_id, "content.txt")
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        result["content"] = f.read()
                except OSError:
                    result["content"] = ""
        return result
    except Exception as e:
        logger.warning("Failed to get artifact %s: %s", artifact_id, e)
        return None


def list_artifacts_by_npc(char_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    """List artifacts created by a specific NPC, newest first."""
    r = _get_redis()
    try:
        ids = r.zrevrange(f"artifact:npc:{char_id}", 0, limit - 1)
        results = []
        for aid in ids:
            meta = r.hgetall(f"artifact:{aid}")
            if meta:
                results.append(dict(meta))
        return results
    except Exception as e:
        logger.warning("Failed to list artifacts for %s: %s", char_id, e)
        return []


def list_discoverable_artifacts(limit: int = 20) -> List[Dict[str, Any]]:
    """List public/discoverable artifacts, newest first."""
    r = _get_redis()
    try:
        ids = r.zrevrange("artifact:discoverable", 0, limit - 1)
        results = []
        for aid in ids:
            meta = r.hgetall(f"artifact:{aid}")
            if meta:
                results.append(dict(meta))
        return results
    except Exception as e:
        logger.warning("Failed to list discoverable artifacts: %s", e)
        return []


def get_npc_artifact_context(char_id: str, max_artifacts: int = 5) -> str:
    """Build a context string for cognition prompts: what artifacts this NPC and others have made.

    Returns a plain-text summary for injection into LLM prompts.
    """
    my_artifacts = list_artifacts_by_npc(char_id, max_artifacts)
    recent_public = list_discoverable_artifacts(max_artifacts)

    lines = []
    if my_artifacts:
        lines.append("Your creations:")
        for a in my_artifacts:
            title = a.get("title", "untitled")
            atype = a.get("type", "unknown")
            lines.append(f"  - [{atype}] {title}")
    if recent_public:
        lines.append("Recent public creations from others:")
        for a in recent_public:
            name = a.get("char_name", "?")
            title = a.get("title", "untitled")
            atype = a.get("type", "unknown")
            lines.append(f"  - {name}: [{atype}] {title}")

    return "\n".join(lines) if lines else "No artifacts yet."
