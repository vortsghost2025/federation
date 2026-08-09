"""
Core route handlers — extracted from main.py
9 routes: /, /state, /atlas, /engine-status, /choose/{choice_id}, /healthz, /reset, /log, /systems-overview

NOTE: /event and /choose/{choice_id} are included but depend on event constants
(CODEX_EVENT_TEMPLATES, EVENTS, RIVAL_EVENTS, etc.) which still live in main.py.
Once those data blocks are extracted to data/events.py, update the imports here.
"""

import json
import random
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from state import (
    game_state,
    get_governance_status,
    FEDERATION_ATLAS,
    LEDGER_METRICS,
    build_explainability,
    GameState,
    PERCENT_METRICS,
    clamp_percent,
    VICTORY_TURN,
    apply_governance_pressure,
)
from federation_game_db import db_manager

# Event constants now live in data/events.py
_events_loaded = True
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
    _events_loaded = False

router = APIRouter(prefix="", tags=["core"])


# ============================================================================
# ROUTE: /
# ============================================================================


@router.get("/")
async def root():
    return {"message": "Federation Game API", "status": "operational"}


# ============================================================================
# ROUTE: /state
# ============================================================================


@router.get("/state")
async def get_state():
    gs = game_state
    return {
        "turn": gs.turn,
        "credits": gs.credits,
        "fuel": gs.fuel,
        "shields": gs.shields,
        "hull": gs.hull,
        "crew_morale": gs.crew_morale,
        "discovered_sectors": gs.discovered_sectors,
        "allies": gs.allies,
        "federation_stability": gs.federation_stability,
        "public_trust": gs.public_trust,
        "council_support": gs.council_support,
        "constitutional_integrity": gs.constitutional_integrity,
        "rights_protection": gs.rights_protection,
        "emergency_powers": gs.emergency_powers,
        "governance_status": get_governance_status(),
        "active_policy": gs.active_policy,
        "proposal_history": gs.proposal_history[-5:],
        "decision_ledger": gs.decision_ledger[-8:],
        "last_decision": gs.last_decision,
        "technologies_unlocked": gs.technologies_unlocked,
        "federation_name": gs.federation_name,
    }


# ============================================================================
# ROUTE: /atlas
# ============================================================================


@router.get("/atlas")
async def get_atlas():
    return FEDERATION_ATLAS


# ============================================================================
# ROUTE: /engine-status
# ============================================================================


@router.get("/engine-status")
async def get_engine_status():
    gs = game_state
    tl = gs.timeline
    cs = tl.consciousness
    return {
        "turn": gs.turn,
        "game_phase": tl.current_era.value,
        "current_year": tl.current_year,
        "engine_systems_loaded": {
            key: {"loaded": value["loaded"]} for key, value in gs.engine_systems.items()
        },
        "quest_system": {
            "active_quests": len(gs.quest_system.active_quests),
            "completed_quests": sum(
                len(v) for v in gs.quest_system.completed_quests.values()
            ),
            "total_registered": len(gs.quest_system.quests),
            "status": "system_available"
            if gs.engine_systems["quest_system"]["loaded"]
            else "not_loaded",
        },
        "faction_system": {
            "known_factions": len(gs.faction_system.factions),
            "player_standing": gs.engine_systems["faction_system"]["player_standing"],
            "status": "system_available"
            if gs.engine_systems["faction_system"]["loaded"]
            else "not_loaded",
        },
        "technology_tree": {
            "research_points": gs.engine_systems["technology_tree"]["research_points"],
            "unlocked_technologies": gs.engine_systems["technology_tree"][
                "unlocked_techs"
            ],
            "status": "system_available"
            if gs.engine_systems["technology_tree"]["loaded"]
            else "not_loaded",
        },
        "npc_system": {
            "known_npcs": len(gs.npc_system.characters),
            "companions": len(gs.npc_system.companions),
            "creatures": len(gs.npc_system.creatures),
            "recruited": sum(
                1 for c in gs.npc_system.companions.values() if c.is_recruited
            ),
            "active_relationships": {
                char_id: rel
                for char_id, rel in gs.npc_system.characters.items()
                if rel.relationship_to_player != 0.0
            },
            "status": "system_available"
            if gs.engine_systems["npc_system"]["loaded"]
            else "not_loaded",
        },
        "event_registry": {
            "total_events": gs.engine_systems["event_registry"]["total_events"],
            "events_seen": gs.engine_systems["event_registry"]["events_seen"],
            "status": "system_available"
            if gs.engine_systems["event_registry"]["loaded"]
            else "not_loaded",
        },
        "consciousness_metrics": {
            "coherence": cs.coherence,
            "stability": cs.stability,
            "complexity": cs.complexity,
            "awakeness": cs.awakeness,
            "memories_recorded": cs.memories_recorded,
            "awakeness_description": tl._describe_consciousness(),
            "status": "system_available"
            if gs.engine_systems["consciousness_metrics"]["loaded"]
            else "not_loaded",
        },
        "turn_progression": {
            "current_phase": tl.current_era.value,
            "current_year": tl.current_year,
            "turns_in_phase": gs.engine_systems["turn_progression"]["turns_in_phase"],
            "narrative_memories": len(tl.narrative_memory),
            "divergences_triggered": sum(
                1 for d in tl.divergence_points if d.triggered
            ),
            "status": "system_available"
            if gs.engine_systems["turn_progression"]["loaded"]
            else "not_loaded",
        },
        "persistence": {
            "last_checkpoint": gs.engine_systems["persistence"]["last_checkpoint"],
            "save_slots": gs.engine_systems["persistence"]["save_slots"],
            "status": "system_available"
            if gs.engine_systems["persistence"]["loaded"]
            else "not_loaded",
        },
        "rival_simulator": {
            "active_rivals": len(gs.rival_simulator.rivals)
            if gs.rival_simulator and hasattr(gs.rival_simulator, "rivals")
            else 0,
            "status": "system_available" if gs.rival_simulator else "not_loaded",
        },
        "consciousness_sheet": {
            "morale": gs.consciousness_sheet.morale if gs.consciousness_sheet else 0,
            "identity": gs.consciousness_sheet.identity
            if gs.consciousness_sheet
            else 0,
            "anxiety": gs.consciousness_sheet.anxiety if gs.consciousness_sheet else 0,
            "status": "system_available" if gs.consciousness_sheet else "not_loaded",
        },
        "history_arc": {
            "current_era": str(getattr(gs.history_arc, "current_era", "unknown"))
            if gs.history_arc
            else "not_loaded",
            "year": getattr(gs.history_arc, "current_year", 0)
            if gs.history_arc and hasattr(gs.history_arc, "current_year")
            else 0,
            "status": "system_available" if gs.history_arc else "not_loaded",
        },
        "political_engine": {
            "status": "system_available" if gs.political_engine else "not_loaded",
        },
    }


# ============================================================================
# ROUTE: /choose/{choice_id}
# NOTE: Full handler is ~560 lines. For this first pass, a stub is provided.
#       The complete handler will be moved to data/events.py logic + this route
#       once the event data blocks are extracted.
# ============================================================================


def _snapshot_metrics(gs):
    return {field: getattr(gs, field) for field in LEDGER_METRICS}


def _calculate_deltas(before, after):
    return {
        field: after[field] - before[field]
        for field in LEDGER_METRICS
        if after[field] != before[field]
    }


def _build_explainability(event, choice, deltas):
    return build_explainability(event, choice, deltas)


@router.post("/choose/{choice_id}")
async def make_choice(choice_id: str, choice_token: Optional[str] = Query(None)):
    gs = game_state
    choice_token = choice_token.strip() if isinstance(choice_token, str) else None

    if choice_token:
        event = gs.pop_pending_choice_event(choice_token)
        if not event:
            return {
                "outcome": "",
                "error": "Invalid choice token",
                "reward": {},
                "blocked_by_no_gate": False,
            }
    elif gs.current_event:
        event = gs.current_event
    else:
        # No active event – return minimal JSON to avoid frontend TypeError
        return {
            "outcome": "",
            "error": "No active event",
            "reward": {},
            "blocked_by_no_gate": False,
        }

    choice = next((c for c in event["choices"] if c["id"] == choice_id), None)
    if not choice:
        # Invalid choice – return empty outcome with error detail
        return {
            "outcome": "",
            "error": "Invalid choice",
            "reward": {},
            "blocked_by_no_gate": False,
        }

    if not _events_loaded:
        # Event constants not loaded – inform client without raising exception
        return {
            "outcome": "",
            "error": "Event constants not yet extracted",
            "reward": {},
            "blocked_by_no_gate": False,
        }

    turn_number = gs.turn
    before_metrics = _snapshot_metrics(gs)
    blocked_by_no_gate = bool(choice.get("blocked_by_no_gate"))

    event_record = {
        "turn": gs.turn,
        "event_id": event.get("id", "unknown"),
        "title": event["title"],
        "choice_id": choice_id,
        "timestamp": datetime.now().isoformat(),
    }
    gs.engine_systems["event_registry"]["events_seen"].append(event_record)
    gs.engine_systems["event_registry"]["total_events"] += 1

    reward = choice.get("no_gate_reward" if blocked_by_no_gate else "reward", {})
    for key, value in reward.items():
        if hasattr(gs, key):
            current = getattr(gs, key)
            if isinstance(current, list):
                current.extend(value if isinstance(value, list) else [value])
            else:
                new_value = max(0, current + value)
                if key in PERCENT_METRICS:
                    new_value = clamp_percent(new_value)
                setattr(gs, key, new_value)

    if choice.get("policy"):
        gs.active_policy = choice.get("policy", gs.active_policy)

    faction_affinity = choice.get("faction_affinity", event.get("faction_affinity", {}))
    if faction_affinity:
        for faction_id, delta in faction_affinity.items():
            gs.faction_system.change_reputation("player", faction_id, delta)
        gs.engine_systems["faction_system"]["player_standing"] = {
            fid: gs.faction_system.get_player_reputation("player", fid)
            for fid in gs.faction_system.factions
        }

    if event["id"] == "council_proposal":
        gs.proposal_history.append(
            {
                "turn": gs.turn,
                "proposal": event["title"],
                "decision": choice["text"],
                "policy": gs.active_policy,
                "outcome": choice["outcome"],
                "domain": event.get("domain", "Council"),
                "rights_at_stake": event.get("rights_at_stake", []),
                "constitutional_risk": event.get("constitutional_risk", "unknown"),
                "affected_lane": choice.get(
                    "affected_lane", event.get("affected_lane", "Control Plane")
                ),
                "rationale": choice.get(
                    "rationale",
                    event.get("rationale", "Decision requires governance review."),
                ),
                "next_safe_action": choice.get(
                    "next_safe_action", "Record and verify before continuing."
                ),
                "lesson": choice.get("lesson", "Governance choices leave a memory."),
            }
        )

    apply_governance_pressure(choice)

    log_entry = {
        "turn": gs.turn,
        "event": event["title"],
        "choice": choice["text"],
        "outcome": choice["outcome"],
        "affected_lane": choice.get(
            "affected_lane", event.get("affected_lane", "Control Plane")
        ),
        "blocked_by_no_gate": blocked_by_no_gate,
        "timestamp": datetime.now().isoformat(),
    }
    gs.log.append(log_entry)

    after_metrics = _snapshot_metrics(gs)
    deltas = _calculate_deltas(before_metrics, after_metrics)
    explainability = _build_explainability(event, choice, deltas)

    game_over = None
    if gs.hull <= 0:
        game_over = "HULL DESTROYED - GAME OVER"
    elif gs.fuel <= 0:
        game_over = "OUT OF FUEL - GAME OVER"
    elif gs.federation_stability <= 0:
        game_over = "CONSTITUTIONAL COLLAPSE - GAME OVER"
    elif gs.public_trust <= 0:
        game_over = "PUBLIC TRUST LOST - GAME OVER"
    elif gs.council_support <= 0:
        game_over = "COUNCIL DEADLOCK - GAME OVER"
    elif gs.constitutional_integrity <= 0:
        game_over = "CONSTITUTION ABANDONED - GAME OVER"
    elif gs.rights_protection <= 0:
        game_over = "RIGHTS FAILURE - GAME OVER"
    elif gs.emergency_powers >= 100:
        game_over = "PERMANENT EMERGENCY - GAME OVER"

    game_victory = None
    if gs.turn >= VICTORY_TURN and game_over is None:
        if (
            gs.federation_stability > 30
            and gs.public_trust > 20
            and gs.constitutional_integrity > 20
            and gs.rights_protection > 20
        ):
            game_victory = "THE FEDERATION ENDURES - VICTORY"
        else:
            game_victory = "100 YEARS SURVIVED - PYRRHIC VICTORY"

    # Advance turn
    gs.turn += 1
    base_fuel_drain = 5
    escalation = min(5, gs.turn // 15)
    difficulty_weight = min(1.0, gs.turn / 50.0)
    gs.fuel = max(0, gs.fuel - (base_fuel_drain + escalation))
    if gs.turn > 10 and random.random() < 0.15 * difficulty_weight:
        pressure_type = random.choice(["fuel_leak", "crew_fatigue", "system_strain"])
        if pressure_type == "fuel_leak":
            gs.fuel = max(0, gs.fuel - 3)
        elif pressure_type == "crew_fatigue":
            gs.crew_morale = max(0, gs.crew_morale - 2)
        elif pressure_type == "system_strain":
            gs.shields = max(0, gs.shields - 2)

    # Timeline advancement
    timeline_result = gs.timeline.advance_year()
    gs.engine_systems["turn_progression"]["current_phase"] = (
        gs.timeline.current_era.value
    )
    gs.engine_systems["turn_progression"]["turns_in_phase"] += 1

    emotional_valence = 0.0
    if "crew_morale" in deltas and deltas["crew_morale"] > 0:
        emotional_valence = 0.4
    elif "crew_morale" in deltas and deltas["crew_morale"] < 0:
        emotional_valence = -0.4
    if game_over:
        emotional_valence = -1.0
    gs.timeline.update_consciousness(
        emotional_valence=emotional_valence,
        trauma=game_over is not None,
        breakthrough=any(
            k in deltas and deltas[k] > 10
            for k in ["constitutional_integrity", "rights_protection"]
        ),
    )
    cs = gs.timeline.consciousness
    gs.engine_systems["consciousness_metrics"]["coherence"] = cs.coherence
    gs.engine_systems["consciousness_metrics"]["stability"] = cs.stability
    gs.engine_systems["consciousness_metrics"]["complexity"] = cs.complexity

    # Rival simulator
    rival_effects = {}
    if gs.rival_simulator:
        try:
            context = {
                "player_stability": gs.federation_stability,
                "player_power": gs.credits / 10.0,
                "player_morale": gs.crew_morale,
            }
            results = gs.rival_simulator.act_all_rivals(
                gs.timeline.current_year, context
            )
            gs.engine_systems["rival_simulator"]["active_rivals"] = (
                len(gs.rival_simulator.rivals)
                if hasattr(gs.rival_simulator, "rivals")
                else 0
            )
            for rival_id, action_result in results.items():
                if isinstance(action_result, dict) and "error" not in action_result:
                    rel = action_result.get("relationship_to_player", "neutral")
                    action_type = action_result.get("action", "unknown")
                    success = action_result.get("success", False)
                    if rel == "hostile" and success:
                        if action_type in ("attack", "sabotage"):
                            dmg = int(
                                action_result.get("impact", {}).get("damage", 0) * 5
                            )
                            if dmg > 0:
                                gs.hull = max(0, gs.hull - dmg)
                                gs.federation_stability = max(
                                    0, gs.federation_stability - (dmg // 2)
                                )
                                rival_effects.setdefault(rival_id, {})["damage"] = dmg
                        elif action_type == "propagandize":
                            gs.public_trust = max(0, gs.public_trust - 3)
                            rival_effects.setdefault(rival_id, {})["propaganda"] = -3
                        elif action_type == "infiltrate":
                            gs.constitutional_integrity = max(
                                0, gs.constitutional_integrity - 2
                            )
                            rival_effects.setdefault(rival_id, {})["infiltration"] = -2
                    elif rel == "friendly" and success:
                        if action_type == "ally":
                            gs.crew_morale = min(100, gs.crew_morale + 2)
                            rival_effects.setdefault(rival_id, {})["alliance_bonus"] = 2
                        elif action_type == "research":
                            gs.credits = max(0, gs.credits + 10)
                            rival_effects.setdefault(rival_id, {})["research_bonus"] = (
                                10
                            )
            try:
                threat = gs.rival_simulator.simulation_state.aggregate_threat
                gs.engine_systems["rival_simulator"]["threat_level"] = threat
            except Exception:
                pass
        except Exception:
            pass

    # Consciousness sheet
    if gs.consciousness_sheet:
        try:
            cs = gs.consciousness_sheet
            cs.morale = gs.crew_morale / 100.0
            morale_delta = deltas.get("crew_morale", 0)
            if morale_delta > 0:
                cs.identity = min(1.0, cs.identity + 0.02)
                cs.anxiety = max(0.0, cs.anxiety - 0.01)
            elif morale_delta < 0:
                cs.anxiety = min(1.0, cs.anxiety + 0.02)
                cs.confidence = max(0.0, cs.confidence - 0.01)
            if "discovered_sectors" in deltas and deltas["discovered_sectors"] > 0:
                cs.expansion_hunger = min(1.0, cs.expansion_hunger + 0.03)
            elif event.get("domain") in ("Federalism", "Civic", "Identity"):
                cs.expansion_hunger = max(0.0, cs.expansion_hunger - 0.02)
            if "allies" in deltas and deltas["allies"] > 0:
                cs.diplomacy_tendency = min(1.0, cs.diplomacy_tendency + 0.02)
            elif choice_id in (
                "counterattack",
                "blast",
                "discipline_crew",
                "retaliate_covert",
            ):
                cs.diplomacy_tendency = max(0.0, cs.diplomacy_tendency - 0.03)
            if game_over or gs.hull < 20 or gs.public_trust < 15:
                if hasattr(cs, "traumas"):
                    trauma_text = event.get("title", "unknown crisis")
                    if trauma_text not in cs.traumas[-3:]:
                        cs.traumas.append(trauma_text)
                    if len(cs.traumas) > 10:
                        cs.traumas = cs.traumas[-8:]
            cs.clamp()
            gs.engine_systems["consciousness_sheet"]["coherence"] = cs.identity
            gs.engine_systems["consciousness_sheet"]["stability"] = 1.0 - cs.anxiety
        except Exception:
            pass

    # Political engine
    political_effects = {}
    if gs.political_engine:
        try:
            current_year = gs.timeline.current_year
            fed_state = gs.game_state_v2.federation if gs.game_state_v2 else None
            if fed_state:
                fed_state.morale = gs.crew_morale / 100.0
            laws = gs.political_engine.process_turn(current_year, fed_state)
            for law_name, effect in laws.items():
                if effect == "trust_boost":
                    gs.public_trust = min(100, gs.public_trust + 1)
                    political_effects[law_name] = "trust_boost"
                elif effect == "stability_boost":
                    gs.federation_stability = min(100, gs.federation_stability + 1)
                    political_effects[law_name] = "stability_boost"
                elif effect == "diplomatic_boost":
                    gs.council_support = min(100, gs.council_support + 1)
                    political_effects[law_name] = "diplomatic_boost"
                else:
                    gs.federation_stability = min(100, gs.federation_stability + 1)
                    political_effects[law_name] = "stability_boost"
        except Exception:
            pass

    # History arc
    history_arc_result = {}
    if gs.history_arc:
        try:
            ha_result = gs.history_arc.advance_year()
            history_arc_result = {
                "era": str(getattr(gs.history_arc, "current_era", "unknown")),
                "year": getattr(gs.history_arc, "current_year", 0)
                if hasattr(gs.history_arc, "current_year")
                else 0,
            }
            if ha_result and isinstance(ha_result, dict):
                if ha_result.get("era_changed"):
                    new_era = ha_result.get("new_era", "")
                    gs.crew_morale = min(100, gs.crew_morale + 5)
                    gs.federation_stability = min(100, gs.federation_stability + 3)
                    history_arc_result["era_changed"] = True
                    history_arc_result["new_era"] = new_era
        except Exception:
            pass

    # Timeline narrative
    gs.timeline.record_narrative(
        event_id=event.get("id", "unknown"),
        event_title=event["title"],
        choice_id=choice_id,
        outcome=choice["outcome"],
        emotional_valence=emotional_valence,
        factions_affected=faction_affinity if faction_affinity else {},
        constitutional_impact=deltas.get("constitutional_integrity", 0),
        tags=[
            event.get("domain", "Operations"),
            choice.get("affected_lane", "Control Plane"),
        ],
    )

    # Faction drift
    if timeline_result.get("decade_gate"):
        faction_allies = {
            fid: list(f.ally_factions) for fid, f in gs.faction_system.factions.items()
        }
        faction_enemies = {
            fid: list(f.enemy_factions) for fid, f in gs.faction_system.factions.items()
        }
        current_reps = {
            fid: gs.faction_system.get_player_reputation("player", fid)
            for fid in gs.faction_system.factions
        }
        drifted = gs.timeline.apply_faction_drift(
            current_reps, faction_allies, faction_enemies
        )
        for fid, new_rep in drifted.items():
            gs.faction_system.change_reputation(
                "player", fid, new_rep - current_reps.get(fid, 0.5)
            )
        gs.engine_systems["faction_system"]["player_standing"] = {
            fid: gs.faction_system.get_player_reputation("player", fid)
            for fid in gs.faction_system.factions
        }

    # Divergence
    divergence_metrics = {
        "public_trust": gs.public_trust,
        "constitutional_integrity": gs.constitutional_integrity,
        "federation_stability": gs.federation_stability,
        "consciousness_complexity": cs.complexity,
    }
    rep_values = list(gs.engine_systems["faction_system"]["player_standing"].values())
    if rep_values:
        max_rep, min_rep = max(rep_values), min(rep_values)
        divergence_metrics["faction_polarization"] = (
            max_rep - min_rep if max_rep != min_rep else 0.0
        )
    else:
        divergence_metrics["faction_polarization"] = 0.0
    triggered_divergences = gs.timeline.check_divergence(divergence_metrics)

    decision_record = {
        "turn": turn_number,
        "event": event["title"],
        "choice": choice["text"],
        "result": choice["outcome"],
        "policy": gs.active_policy,
        "affected_lane": choice.get(
            "affected_lane", event.get("affected_lane", "Control Plane")
        ),
        "rationale": choice.get(
            "rationale",
            event.get("rationale", "Decision recorded for state transition review."),
        ),
        "next_safe_action": choice.get(
            "next_safe_action",
            "Record the decision, verify the next state, and continue.",
        ),
        "blocked_by_no_gate": blocked_by_no_gate,
        "no_gate_reason": choice.get("no_gate_reason", ""),
        "deltas": deltas,
        "explainability": explainability,
        "lesson": choice.get("lesson", "Every decision mutates the system."),
        "timestamp": datetime.now().isoformat(),
    }
    gs.last_decision = decision_record
    gs.decision_ledger.append(decision_record)

    try:
        gs.save_to_db(snapshot_type="decision")
    except Exception:
        pass

    gs.current_event = None

    return {
        "outcome": choice["outcome"],
        "reward": reward,
        "lesson": choice.get("lesson", ""),
        "affected_lane": choice.get(
            "affected_lane", event.get("affected_lane", "Control Plane")
        ),
        "rationale": choice.get(
            "rationale",
            event.get("rationale", "Decision recorded for state transition review."),
        ),
        "next_safe_action": choice.get(
            "next_safe_action",
            "Record the decision, verify the next state, and continue.",
        ),
        "blocked_by_no_gate": blocked_by_no_gate,
        "no_gate_reason": choice.get("no_gate_reason", ""),
        "deltas": deltas,
        "explainability": explainability,
        "faction_affinity_applied": faction_affinity,
        "timeline": {
            "year": gs.timeline.current_year,
            "era": gs.timeline.current_era.value,
            "era_changed": timeline_result.get("era_changed", False),
            "decade_gate": timeline_result.get("decade_gate", False),
            "consciousness": {
                "coherence": cs.coherence,
                "stability": cs.stability,
                "complexity": cs.complexity,
                "awakeness": cs.awakeness,
            },
            "divergences_triggered": [
                {"id": d.divergence_id, "description": d.description}
                for d in triggered_divergences
            ],
        },
        "decision": decision_record,
        "game_over": game_over,
        "rival_effects": rival_effects,
        "political_effects": political_effects,
        "history_arc": history_arc_result,
        "game_victory": game_victory,
        "new_state": await get_state(),
    }


# ============================================================================
# ROUTE: /healthz
# ============================================================================


@router.get("/healthz")
async def healthz():
    return {"status": "ok"}


# ============================================================================
# ROUTE: /reset
# ============================================================================


@router.post("/reset")
async def reset_game():
    fresh_state = GameState(load_latest_snapshot=False)
    game_state.__dict__.clear()
    game_state.__dict__.update(fresh_state.__dict__)
    try:
        game_state.save_to_db(snapshot_type="reset")
    except Exception:
        pass
    return {"message": "Game reset", "state": await get_state()}


# ============================================================================
# ROUTE: /log
# ============================================================================


@router.get("/log")
async def get_log():
    return game_state.log[-20:]


# ============================================================================
# ROUTE: /systems-overview
# ============================================================================


@router.get("/systems-overview")
async def get_systems_overview():
    gs = game_state
    overview = {
        "core_systems": {
            "factions": gs.engine_systems.get("faction_system", {}).get(
                "loaded", False
            ),
            "timeline": gs.engine_systems.get("turn_progression", {}).get(
                "loaded", False
            ),
            "npcs": gs.engine_systems.get("npc_system", {}).get("loaded", False),
            "quests": gs.engine_systems.get("quest_system", {}).get("loaded", False),
            "technology": gs.engine_systems.get("technology_tree", {}).get(
                "loaded", False
            ),
            "events": gs.engine_systems.get("event_registry", {}).get("loaded", False),
        },
        "new_systems": {
            "rival_simulator": gs.rival_simulator is not None,
            "consciousness_sheet": gs.consciousness_sheet is not None,
            "history_arc": gs.history_arc is not None,
            "political_engine": gs.political_engine is not None,
            "game_state_v2": gs.game_state_v2 is not None,
            "console_engine": gs.console_engine is not None,
        },
        "integration_status": {"total_systems": 0, "loaded_systems": 0},
        "turn": gs.turn,
    }
    all_systems = {**overview["core_systems"], **overview["new_systems"]}
    overview["integration_status"]["total_systems"] = len(all_systems)
    overview["integration_status"]["loaded_systems"] = sum(
        1 for v in all_systems.values() if v
    )
    return overview


# ============================================================================
# ROUTE: /state/save  (POST) and /state/info  (GET)
# ============================================================================


@router.post("/state/save")
async def save_state():
    snap_type = "manual"
    try:
        ok = game_state.save_to_db(snapshot_type=snap_type)
        if ok:
            return {"status": "saved", "snapshot_type": snap_type}
        else:
            raise HTTPException(status_code=500, detail="save_to_db returned False")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/state/info")
async def state_info():
    try:
        count = db_manager.get_snapshot_count()
        gs = game_state
        return {
            "snapshot_count": count,
            "current_turn": gs.turn,
            "federation_name": gs.federation_name,
            "save_slots": gs.engine_systems.get("persistence", {}).get(
                "save_slots", []
            ),
            "last_checkpoint": gs.engine_systems.get("persistence", {}).get(
                "last_checkpoint"
            ),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
