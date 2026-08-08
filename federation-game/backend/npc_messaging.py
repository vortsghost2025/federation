"""
INTER-NPC MESSAGE BUS — Real communication between characters

NPCs can send direct messages to each other. Messages are persistent,
appear in cognition context, and accumulate into threads.

Redis keys:
    msg:inbox:{char_id}       — ZSET: msg_id -> timestamp (newest first)
    msg:thread:{thread_id}    — ZSET: msg_id -> timestamp (ordered)
    msg:{msg_id}              — HASH: full message data
    msg:thread_index:{char_id} — ZSET: thread_id -> last_ts (threads NPC participates in)
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

_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(
            REDIS_URL, decode_responses=True,
            socket_connect_timeout=5, socket_timeout=5,
        )
    return _redis_client


def send_message(
    from_char_id: str,
    from_char_name: str,
    to_char_id: str,
    subject: str,
    body: str,
    thread_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Send a message from one NPC to another.

    Args:
        from_char_id: Sender's character ID
        from_char_name: Sender's display name
        to_char_id: Recipient's character ID
        subject: Message subject line
        body: Message body
        thread_id: If continuing a conversation, pass the existing thread_id

    Returns:
        Dict with message metadata including msg_id and thread_id
    """
    r = _get_redis()
    msg_id = f"msg_{uuid.uuid4().hex[:12]}"
    now = time.time()

    if not thread_id:
        thread_id = f"thread_{uuid.uuid4().hex[:10]}"

    msg = {
        "id": msg_id,
        "thread_id": thread_id,
        "from_char_id": from_char_id,
        "from_char_name": from_char_name,
        "to_char_id": to_char_id,
        "subject": subject,
        "body": body,
        "created_at": now,
        # redis-py rejects bool mapping values (DataError); store as string.
        "read": "false",
    }

    try:
        # Store the message
        r.hset(f"msg:{msg_id}", mapping=msg)
        r.expire(f"msg:{msg_id}", 86400 * 30)  # 30 day TTL

        # Add to recipient's inbox (newest first via negative score)
        r.zadd(f"msg:inbox:{to_char_id}", {msg_id: now})
        r.zremrangebyrank(f"msg:inbox:{to_char_id}", 0, -101)  # keep last 100

        # Add to thread
        r.zadd(f"msg:thread:{thread_id}", {msg_id: now})
        r.expire(f"msg:thread:{thread_id}", 86400 * 30)

        # Update thread index for both parties
        r.zadd(f"msg:thread_index:{from_char_id}", {thread_id: now})
        r.zadd(f"msg:thread_index:{to_char_id}", {thread_id: now})
        r.expire(f"msg:thread_index:{from_char_id}", 86400 * 30)
        r.expire(f"msg:thread_index:{to_char_id}", 86400 * 30)

        # Keep inbox capped
        r.zremrangebyrank(f"msg:inbox:{to_char_id}", 0, -101)
    except Exception as e:
        logger.warning("Failed to send message: %s", e)

    logger.info(
        "Message sent: %s -> %s: %s",
        from_char_name, to_char_id, subject[:40],
    )
    return msg


def reconcile_inbox(r, char_id: str) -> int:
    """Remove inbox ZSET members whose msg:{id} payload no longer exists.

    The payload hash carries a 30-day TTL; when it expires the ZSET member
    is not automatically scavenged, leaving a dangling pointer. This prunes
    those so inbox reads stay accurate. Returns the number removed.
    """
    key = f"msg:inbox:{char_id}"
    try:
        members = r.zrange(key, 0, -1)
    except Exception:
        return 0
    removed = 0
    for mid in members:
        if not r.exists(f"msg:{mid}"):
            r.zrem(key, mid)
            removed += 1
    return removed


def get_inbox(char_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Get messages in an NPC's inbox, newest first. Marks as read."""
    r = _get_redis()
    try:
        msg_ids = r.zrevrange(f"msg:inbox:{char_id}", 0, limit - 1)
        messages = []
        for mid in msg_ids:
            msg = r.hgetall(f"msg:{mid}")
            if not msg:
                # Payload expired/missing: drop the dangling zset member.
                r.zrem(f"msg:inbox:{char_id}", mid)
                continue
            msg["read"] = True
            r.hset(f"msg:{mid}", "read", "true")
            messages.append(dict(msg))
        return messages
    except Exception as e:
        logger.warning("Failed to get inbox for %s: %s", char_id, e)
        return []


def get_thread(thread_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Get all messages in a thread, oldest first."""
    r = _get_redis()
    try:
        msg_ids = r.zrange(f"msg:thread:{thread_id}", 0, limit - 1)
        messages = []
        for mid in msg_ids:
            msg = r.hgetall(f"msg:{mid}")
            if msg:
                messages.append(dict(msg))
        return messages
    except Exception as e:
        logger.warning("Failed to get thread %s: %s", thread_id, e)
        return []


def get_unread_count(char_id: str) -> int:
    """Count unread messages in an NPC's inbox."""
    r = _get_redis()
    try:
        # Prune dangling members (payload expired) before counting.
        reconcile_inbox(r, char_id)
        msg_ids = r.zrevrange(f"msg:inbox:{char_id}", 0, -1)
        count = 0
        for mid in msg_ids:
            msg = r.hgetall(f"msg:{mid}")
            if msg and msg.get("read") != "true":
                count += 1
        return count
    except Exception:
        return 0


def get_active_threads(char_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Get threads an NPC participates in, most recent first."""
    r = _get_redis()
    try:
        thread_ids = r.zrevrange(f"msg:thread_index:{char_id}", 0, limit - 1)
        threads = []
        for tid in thread_ids:
            # Get the most recent message in this thread as a preview
            msg_ids = r.zrevrange(f"msg:thread:{tid}", 0, 0)
            if msg_ids:
                msg = r.hgetall(f"msg:{msg_ids[0]}")
                if msg:
                    threads.append(dict(msg))
        return threads
    except Exception as e:
        logger.warning("Failed to get active threads for %s: %s", char_id, e)
        return []


def get_message_context(char_id: str, max_messages: int = 5) -> str:
    """Build a context string for cognition prompts: recent messages.

    Returns plain-text summary for LLM prompt injection.
    """
    inbox = get_inbox(char_id, max_messages)
    threads = get_active_threads(char_id, 3)

    lines = []
    if inbox:
        lines.append("New messages for you:")
        for m in inbox:
            lines.append(
                f"  From {m.get('from_char_name', '?')}: "
                f"\"{m.get('subject', '')}\""
            )
    if threads:
        lines.append("Your recent conversations:")
        for t in threads:
            other = (
                t.get("from_char_name", "?")
                if t.get("to_char_id") == char_id
                else "you"
            )
            lines.append(f"  With {other}: {t.get('subject', '')}")

    return "\n".join(lines) if lines else "No messages."
