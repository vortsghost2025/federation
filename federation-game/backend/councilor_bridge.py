"""
Councilor Bridge - connects container NPC artifacts to main federation simulation.

This module:
1. Reads npc_artifacts:{char_001/306} and indexes them for the main simulation to see
2. Routes messages from other NPCs to councilors in the container network
3. Makes councilor work visible to the narrator/faction leaders
"""

import hashlib
import json
import logging
import time
import uuid
from typing import Dict, List, Optional

logger = logging.getLogger("councilor_bridge")

COUNCILOR_IDS = {"char_001", "char_306"}  # Archimedes Prime, The Oracle
ARTIFACT_DEDUPE_KEY = "federation_councilor_artifact_ids"
MESSAGE_DEDUPE_KEY = "federation_councilor_routed_message_ids"


def _stable_id(prefix: str, payload: Dict) -> str:
    """Return a stable identifier for bridge dedupe.

    Some older artifacts/messages do not carry an explicit id. In those cases
    hash a normalized subset so repeated bridge ticks do not duplicate them.
    """
    explicit = payload.get("artifact_id") or payload.get("id") or payload.get("message_id")
    if explicit:
        return str(explicit)
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    digest = hashlib.sha1(f"{prefix}:{raw}".encode("utf-8")).hexdigest()
    return f"{prefix}_{digest}"


# Cap on the per-councilor source artifact list so it cannot grow unbounded
# on the (space-constrained) deployment disk. Keeps the most recent entries.
ARTIFACT_SOURCE_CAP = 5000


def sync_artifacts_to_simulation(r, councilor_id: str) -> int:
    """Read councilor artifacts and publish them to main simulation stream.
    
    Moves artifacts from npc_artifacts:{councilor_id} to 
    federation_councilor_artifacts for other NPCs to read.
    """
    try:
        raw_artifacts = r.lrange(f"npc_artifacts:{councilor_id}", 0, -1)
        synced = 0
        
        for artifact_json in raw_artifacts:
            try:
                artifact = json.loads(artifact_json)
                artifact_id = _stable_id(councilor_id, artifact)
                if not r.sadd(ARTIFACT_DEDUPE_KEY, artifact_id):
                    continue
                artifact["artifact_id"] = artifact_id

                try:
                    from institutions import annotate_artifact

                    artifact = annotate_artifact(r, councilor_id, artifact)
                except ImportError:
                    artifact.setdefault("institution_id", "")
                    artifact.setdefault("role_id", "")
                    artifact.setdefault("workflow_id", "")
                    artifact.setdefault("artifact_kind", "councilor_note")

                # Mark as councilor artifact
                artifact["councilor_id"] = councilor_id
                artifact["councilor_name"] = artifact.get("author", councilor_id)
                artifact["synced_at"] = int(time.time())

                r.lpush("federation_councilor_artifacts", json.dumps(artifact))
                r.ltrim("federation_councilor_artifacts", 0, 999)  # Keep last 1000
                synced += 1
            except Exception as e:
                logger.warning(f"Failed to parse artifact: {e}")
        
        # Trim the source list so it cannot grow forever on a constrained disk.
        # LTRIM -CAP -1 keeps the most recent CAP entries (newest at the tail).
        try:
            r.ltrim(f"npc_artifacts:{councilor_id}", -ARTIFACT_SOURCE_CAP, -1)
        except Exception:
            logger.warning(f"Failed to cap artifact list for {councilor_id}")

        logger.info(f"Synced {synced} artifacts from {councilor_id} to simulation")
        return synced
        
    except Exception as e:
        logger.error(f"Failed to sync artifacts: {e}")
        return 0


def route_npc_messages_to_councilors(r) -> int:
    """Route messages from federation NPCs to councilors.
    
    Reads npc_messages:* and routes messages addressed to councilors
    into their container inbox.
    """
    try:
        # Get list of all NPCs (from simulation)
        all_npcs = r.smembers("federation:npc_ids") if r.exists("federation:npc_ids") else []
        
        routed = 0
        for npc_id in all_npcs:
            # Skip councilors themselves
            if npc_id in COUNCILOR_IDS:
                continue
                
            # Check sent messages for councilor mentions
            sent_key = f"npc_messages:{npc_id}:sent"
            if not r.exists(sent_key):
                continue
                
            recent = r.lrange(sent_key, 0, 4)  # Last 5 sent messages
            for msg_json in recent:
                try:
                    msg = json.loads(msg_json)
                    to = msg.get("to", "")

                    if to in COUNCILOR_IDS:
                        message_id = _stable_id("msg", msg)
                        if not r.sadd(MESSAGE_DEDUPE_KEY, message_id):
                            continue
                        msg["id"] = message_id
                        # Route to councilor inbox
                        r.lpush(f"npc_messages:{to}:inbox", json.dumps(msg))
                        routed += 1
                except Exception:
                    pass
        
        logger.info(f"Routed {routed} messages to councilors")
        return routed
        
    except Exception as e:
        logger.error(f"Failed to route messages: {e}")
        return 0


def get_councilor_artifacts_for_npc(r, npc_id: str) -> List[Dict]:
    """Get councilor artifacts for an NPC to read.
    
    Returns last 10 councilor artifacts with title, author, summary.
    """
    try:
        raw = r.lrange("federation_councilor_artifacts", 0, 9)
        artifacts = []
        for a_json in raw:
            try:
                a = json.loads(a_json)
                artifacts.append({
                    "title": a.get("title", "Untitled"),
                    "author": a.get("councilor_name", a.get("author", "Unknown")),
                    "summary": a.get("description", "")[:100],
                    "body_preview": a.get("body", "")[:200] if a.get("body") else a.get("content", "")[:200],
                })
            except Exception:
                pass
        return artifacts
    except Exception:
        return []


def update_councilor_relationships(r, councilor_id: str, interaction: Dict) -> None:
    """Update relationship tracking for councilor interactions.
    
    Called after a councilor interacts with another NPC.
    Increments the relationship delta in Redis HASH.
    """
    try:
        other_id = interaction.get("target_char_id") or interaction.get("to")
        delta = interaction.get("relationship_delta", 0)
        if other_id and delta:
            r.hincrby(f"npc_relationships:{councilor_id}", other_id, delta)
            logger.info(f"Updated relationship: {councilor_id} -> {other_id} by {delta}")
    except Exception as e:
        logger.warning(f"Failed to update relationships: {e}")


def update_councilor_topic(r, councilor_id: str, topic: str) -> None:
    """Update the last_topic field for a councilor.
    
    Used to track what the councilor is currently focused on.
    """
    try:
        r.hset(f"npc_cognition:{councilor_id}", "last_topic", topic)
    except Exception as e:
        logger.warning(f"Failed to update topic: {e}")


def broadcast_councilor_proposal(r, councilor_id: str, proposal: Dict) -> bool:
    """Broadcast a councilor proposal to all factions/NPCs.
    
    Called when a councilor creates an artifact that should be seen
    by the wider simulation.
    """
    try:
        proposal_record = {
            "proposal_id": str(uuid.uuid4()) if 'uuid' in dir() else f"{councilor_id}_{int(time.time())}",
            "councilor_id": councilor_id,
            "councilor_name": proposal.get("author", councilor_id),
            "title": proposal.get("title", "Untitled Proposal"),
            "content": proposal.get("body", proposal.get("content", "")),
            "category": proposal.get("category", "proposal"),
            "timestamp": int(time.time()),
        }
        
        r.lpush("federation_proposals", json.dumps(proposal_record))
        r.ltrim("federation_proposals", 0, 99)  # Keep last 100
        
        # Also add to event cascade for other NPCs to react
        r.lpush("event_cascade:input", json.dumps({
            "event_type": "councilor_proposal",
            "source": councilor_id,
            "content": proposal_record,
            "timestamp": int(time.time()),
        }))
        
        logger.info(f"Broadcasted councilor proposal: {proposal_record['title']}")
        return True
    except Exception as e:
        logger.error(f"Failed to broadcast proposal: {e}")
        return False


def run_bridge_tick(r) -> Dict:
    """Run one bridge tick: sync artifacts, route messages.
    
    Called from tick_engine or worker.
    """
    results = {
        "artifacts_synced": 0,
        "messages_routed": 0,
        "errors": [],
    }
    
    for councilor_id in COUNCILOR_IDS:
        try:
            results["artifacts_synced"] += sync_artifacts_to_simulation(r, councilor_id)
        except Exception as e:
            results["errors"].append(f"{councilor_id}: {str(e)[:80]}")
    
    try:
        results["messages_routed"] = route_npc_messages_to_councilors(r)
    except Exception as e:
        results["errors"].append(f"routing: {str(e)[:80]}")
    
    return results


if __name__ == "__main__":
    import redis
    r = get_redis() if 'get_redis' in dir() else redis.from_url("redis://redis:6379/0", decode_responses=True)
    results = run_bridge_tick(r)
    print(f"Bridge tick complete: {results}")
