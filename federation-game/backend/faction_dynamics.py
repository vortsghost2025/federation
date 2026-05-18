import json, time, random, math
from typing import Dict, List, Optional, Tuple

try:
    import redis
except ImportError:
    redis = None

FACTION_DYNAMICS_KEY = "faction_dynamics"
FACTION_STANCES_KEY = "faction_stances"
FACTION_HISTORY_KEY = "faction_history"
FACTION_TTL = 86400 * 7
MAX_FACTION_HISTORY = 50

KNOWN_FACTIONS = [
    "research_division",
    "military_command",
    "diplomatic_corps",
    "economic_council",
    "exploration_initiative",
    "cultural_ministry",
    "preservation_society",
    "consciousness_collective",
]

FACTION_DISPLAY = {
    "research_division": "Research Division",
    "military_command": "Military Command",
    "diplomatic_corps": "Diplomatic Corps",
    "economic_council": "Economic Council",
    "exploration_initiative": "Exploration Initiative",
    "cultural_ministry": "Cultural Ministry",
    "preservation_society": "Preservation Society",
    "consciousness_collective": "Consciousness Collective",
}

STANCE_LABELS = {
    (0.0, 0.2): "hostile",
    (0.2, 0.4): "tense",
    (0.4, 0.6): "neutral",
    (0.6, 0.8): "cordial",
    (0.8, 1.01): "allied",
}


def _get_redis():
    if redis is None:
        return None
    return redis.Redis(host="redis", port=6379, decode_responses=True)


def compute_faction_dynamics(
    npc_list: List[Dict], tick_decisions: List[Dict], broadcast_events: List[Dict]
) -> Dict:
    faction_members = {}
    for npc in npc_list:
        aff = npc.get("affiliation") or "independent"
        if aff == "independent":
            continue
        if aff not in faction_members:
            faction_members[aff] = []
        faction_members[aff].append(npc)

    dynamics = {}
    for faction, members in faction_members.items():
        member_ids = {m.get("char_id") or m.get("id", "") for m in members}
        faction_decisions = [
            d for d in tick_decisions if d.get("char_id") in member_ids
        ]
        faction_events = [
            e for e in broadcast_events if e.get("source_affiliation") == faction
        ]

        num_members = max(1, len(members))
        num_decisions = len(faction_decisions)
        num_events = len(faction_events)

        confront_count = sum(
            1 for d in faction_decisions if d.get("category") == "confront_rival"
        )
        help_count = sum(
            1 for d in faction_decisions if d.get("category") == "help_ally"
        )
        social_count = sum(
            1 for d in faction_decisions if d.get("category") == "socialize"
        )
        investigate_count = sum(
            1 for d in faction_decisions if d.get("category") == "investigate"
        )
        rest_count = sum(1 for d in faction_decisions if d.get("category") == "rest")
        advance_count = sum(
            1 for d in faction_decisions if d.get("category") == "advance_goal"
        )

        r = _get_redis()
        mood_scores = []
        for m in members:
            cid = m.get("char_id") or m.get("id", "")
            mood = r.get(f"npc_mood:{cid}") if r else "contemplative"
            mood_scores.append(_mood_valence(mood or "contemplative"))

        avg_mood = sum(mood_scores) / max(1, len(mood_scores)) if mood_scores else 0.5

        cohesion = 50.0
        cohesion += (social_count / max(1, num_decisions)) * 20 if num_decisions else 0
        cohesion += (help_count / max(1, num_decisions)) * 15 if num_decisions else 0
        cohesion -= (
            (confront_count / max(1, num_decisions)) * 25 if num_decisions else 0
        )
        cohesion += avg_mood * 10
        cohesion += random.uniform(-5, 5)
        cohesion = max(0, min(100, int(cohesion)))

        influence = 30.0
        influence += num_decisions * 2
        influence += num_events * 1.5
        influence += (
            (advance_count / max(1, num_decisions)) * 15 if num_decisions else 0
        )
        influence += len(members) * 3
        influence += random.uniform(-3, 3)
        influence = max(0, min(100, int(influence)))

        standing = 50.0
        standing += avg_mood * 15
        standing += (help_count / max(1, num_decisions)) * 10 if num_decisions else 0
        standing -= (
            (confront_count / max(1, num_decisions)) * 12 if num_decisions else 0
        )
        standing += random.uniform(-5, 5)
        standing = max(0, min(100, int(standing)))

        activity_rate = num_decisions / max(1, num_members)
        vigilance = 30.0
        vigilance += (
            (investigate_count / max(1, num_decisions)) * 25 if num_decisions else 0
        )
        vigilance += activity_rate * 5
        vigilance += random.uniform(-5, 5)
        vigilance = max(0, min(100, int(vigilance)))

        dynamics[faction] = {
            "faction": faction,
            "display_name": FACTION_DISPLAY.get(faction, faction),
            "member_count": num_members,
            "cohesion": cohesion,
            "influence": influence,
            "standing": standing,
            "vigilance": vigilance,
            "avg_mood": round(avg_mood, 2),
            "activity_rate": round(activity_rate, 2),
            "decisions_this_tick": num_decisions,
            "events_this_tick": num_events,
            "ts": int(time.time()),
        }

    for faction in KNOWN_FACTIONS:
        if faction not in dynamics:
            dynamics[faction] = {
                "faction": faction,
                "display_name": FACTION_DISPLAY.get(faction, faction),
                "member_count": 0,
                "cohesion": 50,
                "influence": 20,
                "standing": 50,
                "vigilance": 30,
                "avg_mood": 0.5,
                "activity_rate": 0.0,
                "decisions_this_tick": 0,
                "events_this_tick": 0,
                "ts": int(time.time()),
            }

    return dynamics


def compute_faction_stances(
    faction_dynamics: Dict, broadcast_events: List[Dict]
) -> Dict:
    stances = {}
    factions = [f for f in KNOWN_FACTIONS if f in faction_dynamics]

    for fa in factions:
        stances[fa] = {}
        for fb in factions:
            if fa == fb:
                stances[fa][fb] = {"value": 1.0, "label": "self", "trend": 0}
                continue

            base = 0.5
            fa_events_toward_fb = sum(
                1
                for e in broadcast_events
                if e.get("source_affiliation") == fa
                and fb in (e.get("description") or "").lower().replace(" ", "_")
            )
            fb_events_toward_fa = sum(
                1
                for e in broadcast_events
                if e.get("source_affiliation") == fb
                and fa in (e.get("description") or "").lower().replace(" ", "_")
            )

            confront_from_a = sum(
                1
                for e in broadcast_events
                if e.get("source_affiliation") == fa
                and e.get("decision_category") == "confront_rival"
            )
            confront_from_b = sum(
                1
                for e in broadcast_events
                if e.get("source_affiliation") == fb
                and e.get("decision_category") == "confront_rival"
            )

            help_from_a = sum(
                1
                for e in broadcast_events
                if e.get("source_affiliation") == fa
                and e.get("decision_category") == "help_ally"
            )
            help_from_b = sum(
                1
                for e in broadcast_events
                if e.get("source_affiliation") == fb
                and e.get("decision_category") == "help_ally"
            )

            total_events = max(1, len(broadcast_events))
            confront_pressure = (confront_from_a + confront_from_b) / total_events
            help_pressure = (help_from_a + help_from_b) / total_events
            cross_mention = (fa_events_toward_fb + fb_events_toward_fa) / total_events

            value = (
                base
                + help_pressure * 0.3
                - confront_pressure * 0.4
                + cross_mention * 0.1
            )
            value += random.uniform(-0.05, 0.05)
            value = max(0.0, min(1.0, value))

            label = "neutral"
            for (lo, hi), lbl in STANCE_LABELS.items():
                if lo <= value < hi:
                    label = lbl
                    break

            trend = round(help_pressure - confront_pressure, 3)

            stances[fa][fb] = {
                "value": round(value, 3),
                "label": label,
                "trend": trend,
            }

    return stances


def _mood_valence(mood: str) -> float:
    negative = {
        "frustrated",
        "aggressive",
        "suspicious",
        "anxious",
        "alarmed",
        "worried",
        "unsettled",
        "weary",
        "melancholic",
        "paranoid",
        "burdened",
    }
    positive = {
        "satisfied",
        "inspired",
        "serene",
        "peaceful",
        "hopeful",
        "excited",
        "confident",
        "enlightened",
        "adventurous",
        "free",
        "determined",
        "resolute",
        "valiant",
        "steadfast",
        "patient",
    }
    if mood in negative:
        return 0.2
    if mood in positive:
        return 0.8
    return 0.5


def store_faction_dynamics(dynamics: Dict, stances: Dict):
    r = _get_redis()
    if not r:
        return
    r.hset(
        FACTION_DYNAMICS_KEY, mapping={k: json.dumps(v) for k, v in dynamics.items()}
    )
    r.expire(FACTION_DYNAMICS_KEY, FACTION_TTL)

    for fa, targets in stances.items():
        stance_key = f"{FACTION_STANCES_KEY}:{fa}"
        r.hset(stance_key, mapping={k: json.dumps(v) for k, v in targets.items()})
        r.expire(stance_key, FACTION_TTL)

    now = int(time.time())
    snapshot = {
        "dynamics": {
            k: {
                "cohesion": v["cohesion"],
                "influence": v["influence"],
                "standing": v["standing"],
                "vigilance": v["vigilance"],
            }
            for k, v in dynamics.items()
            if v["member_count"] > 0
        },
        "ts": now,
    }
    r.zadd(FACTION_HISTORY_KEY, {json.dumps(snapshot): now})
    r.zremrangebyrank(FACTION_HISTORY_KEY, 0, -(MAX_FACTION_HISTORY + 1))
    r.expire(FACTION_HISTORY_KEY, FACTION_TTL)


def get_faction_dynamics() -> Dict:
    r = _get_redis()
    if not r:
        return {}
    stored = r.hgetall(FACTION_DYNAMICS_KEY)
    result = {}
    for faction, data in stored.items():
        try:
            result[faction] = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            continue
    return result


def get_faction_detail(faction: str) -> Optional[Dict]:
    r = _get_redis()
    if not r:
        return None
    data = r.hget(FACTION_DYNAMICS_KEY, faction)
    if data:
        try:
            return json.loads(data)
        except (json.JSONDecodeError, TypeError):
            pass  # Faction dynamics data corrupt; returning None
    return None


def get_faction_stances(faction: Optional[str] = None) -> Dict:
    r = _get_redis()
    if not r:
        return {}
    if faction:
        stance_key = f"{FACTION_STANCES_KEY}:{faction}"
        stored = r.hgetall(stance_key)
        result = {}
        for target, data in stored.items():
            try:
                result[target] = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                continue
        return result
    all_stances = {}
    for f in KNOWN_FACTIONS:
        stance_key = f"{FACTION_STANCES_KEY}:{f}"
        stored = r.hgetall(stance_key)
        f_stances = {}
        for target, data in stored.items():
            try:
                f_stances[target] = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                continue
        if f_stances:
            all_stances[f] = f_stances
    return all_stances


def get_faction_history(limit: int = 10) -> List[Dict]:
    r = _get_redis()
    if not r:
        return []
    raw = r.zrevrange(FACTION_HISTORY_KEY, 0, limit - 1)
    history = []
    for item in raw:
        try:
            history.append(json.loads(item))
        except (json.JSONDecodeError, TypeError):
            continue
    return history


def get_faction_context_for_npc(affiliation: str) -> Optional[Dict]:
    if not affiliation or affiliation == "independent":
        return None
    detail = get_faction_detail(affiliation)
    stances = get_faction_stances(affiliation)
    if detail:
        detail["stances"] = stances
    return detail
