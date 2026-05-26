#!/usr/bin/env python3
"""Add debug logging to P24b bridge function in simulation_engine.py"""

import py_compile

filepath = "S:/federation/federation-game/backend/simulation_engine.py"

with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

# Add debug logging after faction_members building
old_check = """    if len(faction_members) < 2:
        return bridge_result"""

new_check = """    if len(faction_members) < 2:
        logger.warning(
            "[Diplomacy->NPC Bridge] Insufficient faction members: %d factions, %d total NPCs",
            len(faction_members), len(npc_list),
        )
        return bridge_result
    
    logger.info(
        "[Diplomacy->NPC Bridge] Faction members map: %s",
        {fid: len(members) for fid, members in faction_members.items()},
    )"""

if old_check in content:
    content = content.replace(old_check, new_check, 1)
    print("1. Added faction_members debug log")
else:
    print("ERROR: Could not find faction_members check")

# Add debug logging for event collection
old_events_check = """    if not events:
        return bridge_result"""

new_events_check = """    if not events:
        logger.info(
            "[Diplomacy->NPC Bridge] No events to process. diplo_result keys: %s, proposals: %d, expirations: %d, rejections: %d",
            list(diplomacy_result.keys()) if isinstance(diplomacy_result, dict) else type(diplomacy_result).__name__,
            len(diplomacy_result.get("proposals", [])) if isinstance(diplomacy_result, dict) else -1,
            len(diplomacy_result.get("expirations", [])) if isinstance(diplomacy_result, dict) else -1,
            len(diplomacy_result.get("rejections", [])) if isinstance(diplomacy_result, dict) else -1,
        )
        return bridge_result
    
    logger.info(
        "[Diplomacy->NPC Bridge] Processing %d events: %s",
        len(events),
        [f"{e['type']}:{e['faction_a']}-{e['faction_b']}:{e['treaty_type']}" for e in events],
    )"""

if old_events_check in content:
    content = content.replace(old_events_check, new_events_check, 1)
    print("2. Added events debug log")
else:
    print("ERROR: Could not find events check")

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)

py_compile.compile(filepath, doraise=True)
print("VALIDATION: simulation_engine.py compiles OK")
