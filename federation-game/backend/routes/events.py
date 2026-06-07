"""Event route handlers — extracted from main.py"""
import logging
import random
from uuid import uuid4

from fastapi import APIRouter

from state import (
    PENDING_CHOICE_TTL_SECONDS,
    build_governance_event,
    enrich_event,
    game_state,
)

router = APIRouter(prefix="", tags=["events"])
logger = logging.getLogger("federation_game")

try:
    from data.events import (
        EVENTS,
        CODEX_EVENT_TEMPLATES,
        RIVAL_EVENTS,
        QUEST_EVENTS,
        NPC_EVENTS,
        ERA_EVENTS,
        CONSCIOUSNESS_EVENTS,
    )
except ImportError:
    EVENTS = []
    CODEX_EVENT_TEMPLATES = []
    RIVAL_EVENTS = []
    QUEST_EVENTS = []
    NPC_EVENTS = []
    ERA_EVENTS = []
    CONSCIOUSNESS_EVENTS = []


def _event_error(message: str):
    return {
        "id": "event_unavailable",
        "title": "Event generation unavailable",
        "description": "The federation could not generate a new event right now.",
        "choices": [],
        "error": message,
    }


def _issue_choice_token(event: dict):
    game_state.sweep_expired_pending_choices(ttl_seconds=PENDING_CHOICE_TTL_SECONDS)
    choice_token = str(uuid4())
    game_state.register_pending_choice(choice_token, event)
    game_state.current_event = event
    response = dict(event)
    response["choice_token"] = choice_token
    return response


@router.get("/event")
async def get_random_event():
    try:
        turn = game_state.turn
        difficulty_weight = min(1.0, turn / 50.0)
        candidates = []

        if (
            game_state.public_trust < 45
            or game_state.council_support < 45
            or game_state.federation_stability < 45
            or game_state.constitutional_integrity < 50
            or game_state.rights_protection < 50
            or game_state.emergency_powers > 60
            or turn % 4 == 0
        ):
            candidates.append(("governance", 3.0 + difficulty_weight * 2.0))

        if turn % 3 == 0:
            candidates.append(("codex", 2.0))

        candidates.append(("standard", 4.0 - difficulty_weight))

        if game_state.rival_simulator:
            try:
                hostile_count = sum(
                    1
                    for r in game_state.rival_simulator.rivals.values()
                    if r.relationships.get("player", "neutral") == "hostile"
                )
                if hostile_count > 0 or turn > 5:
                    rival_weight = 1.5 + (hostile_count * 0.5) + (difficulty_weight * 2.0)
                    candidates.append(("rival", rival_weight))
            except Exception:
                if turn > 8:
                    candidates.append(("rival", 1.0 + difficulty_weight))

        if game_state.consciousness_sheet:
            try:
                cs = game_state.consciousness_sheet
                if cs.anxiety > 0.6 or cs.identity < 0.4 or cs.expansion_hunger > 0.7:
                    candidates.append(("consciousness", 2.0 + difficulty_weight))
                elif turn > 15 and turn % 5 == 0:
                    candidates.append(("consciousness", 1.0))
            except Exception:
                logger.warning(
                    "Consciousness sheet evaluation failed during event candidate selection"
                )

        if turn >= 8:
            candidates.append(("quest", 1.0 + difficulty_weight * 0.5))
        if turn >= 6:
            candidates.append(("npc", 0.8 + difficulty_weight * 0.5))

        available_era = [e for e in ERA_EVENTS if turn >= e.get("min_turn", 0)]
        if available_era:
            candidates.append(("era", 1.5))

        # Fallback to governance if candidates list somehow empty
        if not candidates:
            ev = build_governance_event()
            return _issue_choice_token(ev)

        categories = [c[0] for c in candidates]
        weights = [c[1] for c in candidates]
        category = random.choices(categories, weights=weights, k=1)[0]

        recent_ids = []
        try:
            recent_ids = [
                r.get("event_id", "")
                for r in game_state.engine_systems.get("event_registry", {}).get(
                    "events_seen", []
                )[-10:]
            ]
        except Exception:
            pass

        def _pick(pool, avoid_ids):
            if not pool:
                return build_governance_event()
            unique = [e for e in pool if e.get("id", "") not in avoid_ids]
            return random.choice(unique or pool)

        if category == "governance":
            event = build_governance_event()
        elif category == "codex":
            event = _pick(CODEX_EVENT_TEMPLATES, recent_ids)
        elif category == "standard":
            event = _pick(EVENTS, recent_ids)
        elif category == "rival":
            event = _pick(RIVAL_EVENTS, recent_ids)
        elif category == "consciousness":
            event = _pick(CONSCIOUSNESS_EVENTS, recent_ids)
        elif category == "quest":
            event = _pick(QUEST_EVENTS, recent_ids)
        elif category == "npc":
            event = _pick(NPC_EVENTS, recent_ids)
        elif category == "era":
            event = _pick(available_era, recent_ids)
        else:
            event = random.choice(EVENTS) if EVENTS else build_governance_event()

        try:
            event = enrich_event(event)
        except Exception:
            logger.warning("enrich_event failed, returning raw event", exc_info=True)

        return _issue_choice_token(event)

    except Exception as e:
        logger.error("get_random_event failed: %s", e, exc_info=True)
        try:
            fallback = build_governance_event()
            return _issue_choice_token(fallback)
        except Exception:
            return _event_error("Event generation unavailable")
