#!/usr/bin/env python3
import json
import time
import logging
import redis
import os
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

NPC_EVENT_LOG_KEY = 'npc:events:log'
NPC_EVENT_LOG_MAX = 10000
NPC_EVENT_TTL = 86400 * 30

def _get_redis():
    return redis.Redis.from_url(
        os.environ.get('REDIS_URL', 'redis://redis:6379/0'),
        decode_responses=True
    )

def _now():
    return time.time()

def log_npc_event(
    npc_id: str,
    tick_id: int,
    event_type: str,
    action: str,
    decision: str = '',
    result: str = 'PENDING',
    risk: float = 0.0,
    fuel_before: float = None,
    fuel_after: float = None,
    metadata: dict = None,
):
    r = _get_redis()
    now_ts = time.time()
    event = {
        'timestamp': now_ts,
        'npc_id': npc_id,
        'tick_id': tick_id,
        'event_type': event_type,
        'action': action,
        'decision': decision,
        'result': result,
        'risk': float(risk) if risk else 0.0,
        'fuel_before': fuel_before,
        'fuel_after': fuel_after,
        'metadata': metadata or {},
    }
    event_json = json.dumps(event, default=str)
    r = _get_redis()
    r.zadd('npc:events:log', {json.dumps(event, default=str): event['timestamp']})
    r.zremrangebyrank('npc:events:log', 0, -(10000 + 1))
    r.expire('npc:events:log', 86400 * 30)
    return event

def log_decision_event(
    npc_id: str,
    tick_id: int,
    decision: dict,
    result: str = 'SUCCESS',
):
    category = decision.get('category', 'unknown')
    action = decision.get('action_desc', decision.get('description', category))
    return log_npc_event(
        npc_id=npc_id,
        tick_id=tick_id,
        event_type='DECISION',
        action=action,
        decision=category,
        result=result,
        risk=0.3,
        metadata={'full_decision': decision},
    )

def log_watchdog_event(tick_id: int, action: str, result: str, risk: float = 0.0, metadata: dict = None):
    return log_npc_event(
        npc_id='WATCHDOG',
        tick_id=tick_id,
        event_type='WATCHDOG',
        action=action,
        decision='watchdog_recovery',
        result=result,
        risk=risk,
        metadata=metadata,
    )

def log_starmap_event(
    npc_id: str, tick_id: int, action: str, decision: str, result: str,
    risk: float, fuel_before: float, fuel_after: float, metadata: dict = None
):
    return log_npc_event(
        npc_id=npc_id,
        tick_id=tick_id,
        event_type='STARMAP',
        action=action,
        decision=decision,
        result=result,
        risk=risk,
        fuel_before=fuel_before,
        fuel_after=fuel_after,
        metadata=metadata,
    )

def log_system_event(tick_id: int, action: str, decision: str, result: str = 'SUCCESS', metadata: dict = None):
    return log_npc_event(
        npc_id='SYSTEM',
        tick_id=tick_id,
        event_type='SYSTEM',
        action=action,
        decision=decision,
        result=result,
        risk=0.0,
        metadata=metadata,
    )

def get_npc_events(npc_id=None, tick_id=None, event_type=None, start_ts=None, end_ts=None, limit=100):
    r = _get_redis()
    raw_events = r.zrevrange('npc:events:log', 0, limit * 5 - 1)
    events = []
    for item in raw_events:
        try:
            event = json.loads(item)
        except (ValueError, TypeError):
            continue
        if npc_id and event.get('npc_id') != npc_id: continue
        if tick_id and event.get('tick_id') != tick_id: continue
        if event_type and event.get('event_type') != event_type: continue
        if start_ts and event.get('timestamp', 0) < start_ts: continue
        if end_ts and event.get('timestamp', 0) > end_ts: continue
        events.append(event)
        if len(events) >= limit: break
    return events

def get_npc_event_stats():
    r = _get_redis()
    total = r.zcard('npc:events:log')
    sample = r.zrevrange('npc:events:log', 0, 999)
    type_counts = {}
    npc_counts = {}
    for item in sample:
        try:
            event = json.loads(item)
        except: continue
        etype = event.get('event_type', 'UNKNOWN')
        type_counts[etype] = type_counts.get(etype, 0) + 1
        nid = event.get('npc_id', 'UNKNOWN')
        npc_counts[nid] = npc_counts.get(nid, 0) + 1
    return {'total_events': total, 'type_distribution': type_counts, 'top_npcs': dict(sorted(npc_counts.items(), key=lambda x: x[1], reverse=True)[:10])}

def clear_event_log():
    r = _get_redis()
    return r.delete('npc:events:log')

def log_from_broadcast_event(event: dict, tick_id: int):
    char_id = event.get('source_char_id', '')
    char_name = event.get('source_char_name', '')
    category = event.get('decision_category', '')
    return log_npc_event(
        npc_id=char_id,
        tick_id=tick_id,
        event_type='DECISION',
        action=event.get('description', category),
        decision=category,
        result='SUCCESS',
        risk=event.get('significance', 0.5),
        metadata={
            'source_char_name': char_name,
            'source_affiliation': event.get('source_affiliation', ''),
            'visibility': event.get('visibility', 'public'),
            'target_faction': event.get('target_faction', ''),
            'original_event': event,
        },
    )
