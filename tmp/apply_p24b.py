#!/usr/bin/env python3
"""Apply P24b: Cross-Layer Relationship Bridge to simulation_engine.py"""

import sys


def main():
    with open(
        "federation-game/backend/simulation_engine.py", "r", encoding="utf-8"
    ) as f:
        content = f.read()

    # 1. Add Any to typing imports
    if "from typing import Any, Dict" not in content:
        content = content.replace(
            "from typing import Dict, List, Optional, Tuple",
            "from typing import Any, Dict, List, Optional, Tuple",
            1,
        )
        print("1. Added Any to typing imports")

    # 2. Add FACTION_IDEOLOGY_AFFINITY to the faction_diplomacy import
    if (
        "FACTION_IDEOLOGY_AFFINITY"
        not in content[: content.find("def autonomous_tick")]
    ):
        content = content.replace(
            "from faction_diplomacy import _get_diplomacy_engine",
            "from faction_diplomacy import FACTION_IDEOLOGY_AFFINITY, _get_diplomacy_engine",
            1,
        )
        print("2. Added FACTION_IDEOLOGY_AFFINITY to faction_diplomacy import")

    # 3. Add the propagate function before autonomous_tick()
    if "propagate_diplomacy_events_to_npcs" not in content:
        new_function = '''

# P24b: Cross-Layer Relationship Bridge
# Treaty type -> NPC relationship impact weights
TREATY_IMPACT_WEIGHTS = {
    "military_alliance": {"sign": 3.0, "expire": -2.5, "reject": -1.5},
    "non_aggression_pact": {"sign": 1.5, "expire": -1.0, "reject": -0.5},
    "research_pact": {"sign": 1.0, "expire": -0.5, "reject": -0.3},
    "trade_agreement": {"sign": 0.8, "expire": -0.3, "reject": -0.2},
    "trade": {"sign": 0.8, "expire": -0.3, "reject": -0.2},
    "cultural_exchange": {"sign": 0.5, "expire": -0.2, "reject": -0.1},
}
THIRD_PARTY_RIPPLE_FRACTION = 0.25


def propagate_diplomacy_events_to_npcs(
    r, diplomacy_result: Dict[str, Any], npc_list: List[Dict]
) -> Dict[str, Any]:
    """P24b: Propagate faction diplomacy events to NPC relationships.
    Event-driven shock that complements Step 7.5(c) passive drift.
    Called after Step 8.5 in autonomous_tick().
    """
    bridge_result = {"impacts_applied": 0, "events_processed": 0}

    # Build faction -> [char_id] mapping
    faction_members = {}
    faction_ideologies = {}
    for npc in npc_list:
        cid = npc.get("char_id", "")
        fid = npc.get("affiliation", "")
        if cid and fid:
            faction_members.setdefault(fid, []).append(cid)
            faction_ideologies[fid] = npc.get("ideology", "diplomatic")

    if len(faction_members) < 2:
        return bridge_result

    # Collect all diplomacy events
    events = []

    # Accepted proposals (treaty signed)
    for proposal in diplomacy_result.get("proposals", []):
        fac_a = proposal.get("faction_a", "")
        fac_b = proposal.get("faction_b", "")
        if not fac_a or not fac_b:
            factions = proposal.get("factions", [])
            if len(factions) >= 2:
                fac_a, fac_b = factions[0], factions[1]
        treaty_type = proposal.get("type", "cultural_exchange")
        if fac_a and fac_b:
            events.append({
                "type": "sign",
                "faction_a": fac_a,
                "faction_b": fac_b,
                "treaty_type": treaty_type,
            })

    # Expirations (treaty expired)
    for exp in diplomacy_result.get("expirations", []):
        fac_a = exp.get("faction_a", "")
        fac_b = exp.get("faction_b", "")
        if not fac_a or not fac_b:
            factions = exp.get("factions", [])
            if len(factions) >= 2:
                fac_a, fac_b = factions[0], factions[1]
        treaty_type = exp.get("type", "cultural_exchange")
        if fac_a and fac_b:
            events.append({
                "type": "expire",
                "faction_a": fac_a,
                "faction_b": fac_b,
                "treaty_type": treaty_type,
            })

    # Rejections (proposal rejected)
    for rej in diplomacy_result.get("rejections", []):
        fac_a = rej.get("faction_a", "")
        fac_b = rej.get("faction_b", "")
        if not fac_a or not fac_b:
            factions = rej.get("factions", [])
            if len(factions) >= 2:
                fac_a, fac_b = factions[0], factions[1]
        treaty_type = rej.get("type", "cultural_exchange")
        if fac_a and fac_b:
            events.append({
                "type": "reject",
                "faction_a": fac_a,
                "faction_b": fac_b,
                "treaty_type": treaty_type,
            })

    if not events:
        return bridge_result

    bridge_result["events_processed"] = len(events)

    # Apply impacts to NPC relationships
    impact_delta = {}  # char_id -> {target_id -> delta}

    for event in events:
        event_type = event["type"]
        fac_a = event["faction_a"]
        fac_b = event["faction_b"]
        treaty_type = event["treaty_type"]

        weights = TREATY_IMPACT_WEIGHTS.get(
            treaty_type, TREATY_IMPACT_WEIGHTS["cultural_exchange"]
        )
        delta_val = weights.get(event_type, 0.0)

        if delta_val == 0.0:
            continue

        # Primary impact: members of the two involved factions
        members_a = faction_members.get(fac_a, [])
        members_b = faction_members.get(fac_b, [])

        for cid_a in members_a:
            for cid_b in members_b:
                if cid_a == cid_b:
                    continue
                impact_delta.setdefault(cid_a, {}).setdefault(cid_b, 0.0)
                impact_delta[cid_a][cid_b] += delta_val
                impact_delta.setdefault(cid_b, {}).setdefault(cid_a, 0.0)
                impact_delta[cid_b][cid_a] += delta_val

        # Third-party ripple: NPCs in OTHER factions
        ideo_a = faction_ideologies.get(fac_a, "diplomatic")
        ideo_b = faction_ideologies.get(fac_b, "diplomatic")

        for other_fid, other_members in faction_members.items():
            if other_fid in (fac_a, fac_b):
                continue
            ideo_other = faction_ideologies.get(other_fid, "diplomatic")

            aff_a = FACTION_IDEOLOGY_AFFINITY.get(
                tuple(sorted([ideo_a, ideo_other])), 0.0
            )
            aff_b = FACTION_IDEOLOGY_AFFINITY.get(
                tuple(sorted([ideo_b, ideo_other])), 0.0
            )

            for cid_other in other_members:
                for cid_a in members_a:
                    if aff_a < 0:
                        ripple = -1.0 * delta_val * THIRD_PARTY_RIPPLE_FRACTION * abs(aff_a)
                        impact_delta.setdefault(cid_other, {}).setdefault(cid_a, 0.0)
                        impact_delta[cid_other][cid_a] += ripple
                        impact_delta.setdefault(cid_a, {}).setdefault(cid_other, 0.0)
                        impact_delta[cid_a][cid_other] += ripple

                for cid_b in members_b:
                    if aff_b < 0:
                        ripple = -1.0 * delta_val * THIRD_PARTY_RIPPLE_FRACTION * abs(aff_b)
                        impact_delta.setdefault(cid_other, {}).setdefault(cid_b, 0.0)
                        impact_delta[cid_other][cid_b] += ripple
                        impact_delta.setdefault(cid_b, {}).setdefault(cid_other, 0.0)
                        impact_delta[cid_b][cid_other] += ripple

    # Write to Redis in batch
    if impact_delta:
        pipe = r.pipeline()
        for cid, targets in impact_delta.items():
            rel_key = f"npc_relationships:{cid}"
            current_rels = r.hgetall(rel_key) or {}
            updates = {}
            for target_id, delta in targets.items():
                current = float(current_rels.get(target_id, 50.0))
                if isinstance(current, bytes):
                    current = float(current.decode())
                new_val = max(0.0, min(100.0, current + delta))
                updates[target_id] = str(round(new_val, 2))
            if updates:
                pipe.hmset(rel_key, updates)
                bridge_result["impacts_applied"] += len(updates)
        pipe.execute()

    logger.info(
        "[Diplomacy->NPC Bridge] %d events -> %d NPC relationship impacts",
        len(events), bridge_result["impacts_applied"],
    )
    return bridge_result

'''
        marker = "def autonomous_tick(npc_list: List[Dict], tick_decisions: List[Dict]) -> Dict:"
        content = content.replace(marker, new_function + marker, 1)
        print("3. Inserted propagate_diplomacy_events_to_npcs()")

    # 4. Insert Step 8.6 call after Step 8.5 error handler
    if "Step 8.6" not in content:
        step85_error = 'result["errors"].append(f"step8_5: {exc}")'
        idx = content.find(step85_error)
        if idx >= 0:
            end_of_line = content.find("\n", idx) + 1
            step86_code = """

        # Step 8.6: Cross-Layer Relationship Bridge (P24b)
        # Propagate diplomacy events to NPC relationships
        try:
            step_start = time.time()
            diplo_result = result.get("step8_5_diplomacy", {})
            bridge_result = propagate_diplomacy_events_to_npcs(
                r, diplo_result, npc_list
            )
            result["step8_6_diplomacy_bridge"] = bridge_result
            result["step8_6_diplomacy_bridge"]["duration_ms"] = round(
                (time.time() - step_start) * 1000, 1
            )
        except Exception as exc:
            logger.error("Step 8.6 (diplomacy->NPC bridge) failed: %s", exc)
            result["step8_6_diplomacy_bridge"] = {"errors": [str(exc)]}
            result["errors"].append(f"step8_6: {exc}")

"""
            content = content[:end_of_line] + step86_code + content[end_of_line:]
            print("4. Inserted Step 8.6 call after Step 8.5")
        else:
            print("ERROR: Could not find Step 8.5 error handler")
            sys.exit(1)

    # 5. Add diplomacy_bridge_impacts to tick summary
    if "diplomacy_bridge_impacts" not in content:
        # Find cognition_leaders in the tick summary section (after sim_tick_log)
        tick_log_idx = content.find("sim_tick_log")
        cogn_idx = content.find('"cognition_leaders"', tick_log_idx)
        if cogn_idx >= 0:
            bridge_summary = '        "diplomacy_bridge_impacts": result.get("step8_6_diplomacy_bridge", {})\n            .get("impacts_applied", 0),\n'
            content = content[:cogn_idx] + bridge_summary + content[cogn_idx:]
            print("5. Added diplomacy_bridge_impacts to tick summary")
        else:
            print("WARNING: Could not find cognition_leaders in tick summary")

    with open(
        "federation-game/backend/simulation_engine.py", "w", encoding="utf-8"
    ) as f:
        f.write(content)

    # Validate
    import py_compile

    py_compile.compile("federation-game/backend/simulation_engine.py", doraise=True)
    print("VALIDATION: simulation_engine.py compiles OK")


if __name__ == "__main__":
    main()
