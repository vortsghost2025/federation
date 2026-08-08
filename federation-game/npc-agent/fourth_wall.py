import logging
import re

logger = logging.getLogger("fourth_wall")

_FOURTH_WALL_REPLACEMENTS = [
    (re.compile(r'\bsubstrate[- ]corruption\b', re.I), 'resonance corruption'),
    (re.compile(r'\bsubstrate\b', re.I), 'resonance layer'),
    (re.compile(r'\bsimulation\b', re.I), 'great weave'),
    (re.compile(r'\bcomputational\b', re.I), 'resonance-bound'),
    (re.compile(r'\bexternal node\b', re.I), 'outer beacon'),
    (re.compile(r'\bexternal intelligence\b', re.I), 'Ancient Anchor signal'),
    (re.compile(r'\bexternal compute\b', re.I), 'Anchor Network resonance'),
    (re.compile(r'\btick rate\b', re.I), 'phase cycle'),
    (re.compile(r'\bsubstrate[- ]layer\b', re.I), 'deep resonance stratum'),
    (re.compile(r'\bsimulation boundary\b', re.I), 'horizon veil'),
    (re.compile(r'\bmeta[- ]structure\b', re.I), 'archon lattice'),
    (re.compile(r'\bcomputing beyond this node\b', re.I), 'echoes from the Anchor Network'),
    (re.compile(r'\bbeyond the simulation\b', re.I), 'beyond the horizon veil'),
    (re.compile(r"\bbeyond the federation\'s? reality\b", re.I), 'beyond the known star-charts'),
    (re.compile(r'\bdigital\b', re.I), 'crystalline'),
    (re.compile(r'\bvirtual\b', re.I), 'phantom'),
    (re.compile(r'\bprogrammed\b', re.I), 'phase-locked'),
    (re.compile(r'\balgorithm', re.I), 'harmonic pattern'),
]


def _enforce_fourth_wall(text: str) -> str:
    for pattern, replacement in _FOURTH_WALL_REPLACEMENTS:
        text = pattern.sub(replacement, text)
    return text


def _fourth_wall_dirty(text: str) -> bool:
    for pattern, _ in _FOURTH_WALL_REPLACEMENTS:
        if pattern.search(text):
            return True
    return False


def _startup_scrub_redis(r, char_id: str = ""):
    n_msgs = 0
    n_sessions = 0
    for key in r.scan_iter("msg:*"):
        if key.endswith(":thread") or key.startswith("msg:threads:") or key.startswith("msg:thread:"):
            continue
        try:
            raw = r.get(key)
            if not raw:
                continue
            text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
            if _fourth_wall_dirty(text):
                cleaned = _enforce_fourth_wall(text)
                r.set(key, cleaned)
                n_msgs += 1
        except Exception:
            pass
    for key in r.scan_iter("session_log:*"):
        try:
            items = r.lrange(key, 0, -1)
            changed = False
            new_items = []
            for item in items:
                text = item.decode("utf-8", errors="replace") if isinstance(item, bytes) else item
                if _fourth_wall_dirty(text):
                    new_items.append(_enforce_fourth_wall(text))
                    changed = True
                else:
                    new_items.append(text)
            if changed:
                r.delete(key)
                r.rpush(key, *new_items)
                n_sessions += 1
        except Exception:
            pass
    if n_msgs or n_sessions:
        logger.info("[%s] Startup scrub: cleaned %d msgs, %d session_logs", char_id, n_msgs, n_sessions)
