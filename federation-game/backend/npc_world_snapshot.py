# NPC World Snapshot Builder
# Populates Redis with world context for container agents (Archimedes, Oracle)
# Run from VPS backend container or via tick_engine

import json
from datetime import datetime

def build_world_snapshot() -> dict:
    """Build and return a world snapshot for container councilors.
    
    Includes:
    - 21 sectors with positions/resources
    - 8 factions with homes
    - Summary of all 50+ NPCs with affiliations
    - Current world state values
    - Councilor orientation framing
    """
    
    sectors = [
        {"id": "sol-prime", "name": "Sol Prime", "x": 0, "y": 0, "region_type": "core", 
         "resource_profile": "mixed", "danger_level": 1, "description": "The heart of the Federation. All roads lead here."},
        {"id": "meridian", "name": "Meridian", "x": -60, "y": 35, "region_type": "core",
         "resource_profile": "diplomatic", "danger_level": 2, "description": "Where treaties are forged and alliances balanced."},
        {"id": "crucible", "name": "Crucible", "x": 60, "y": 35, "region_type": "core",
         "resource_profile": "economic", "danger_level": 2, "description": "The proving ground of commerce and competition."},
        {"id": "helix", "name": "Helix", "x": -110, "y": -65, "region_type": "inner",
         "resource_profile": "research", "danger_level": 3, "description": "Spiral archives of forgotten knowledge, decoded endlessly."},
        {"id": "forge", "name": "Forge", "x": -130, "y": 40, "region_type": "inner",
         "resource_profile": "economic", "danger_level": 3, "description": "Foundries that never cool. Production without pause."},
        {"id": "bastion", "name": "Bastion", "x": -50, "y": 100, "region_type": "inner",
         "resource_profile": "military", "danger_level": 3, "description": "The shield that never sleeps. Garrison of the watchful."},
        {"id": "archive", "name": "Archive", "x": 50, "y": 100, "region_type": "inner",
         "resource_profile": "research", "danger_level": 3, "description": "Libraries that remember what the living cannot."},
        {"id": "prism", "name": "Prism", "x": 130, "y": 40, "region_type": "inner",
         "resource_profile": "diplomatic", "danger_level": 3, "description": "Where every perspective refracts into understanding."},
        {"id": "harbor", "name": "Harbor", "x": 110, "y": -65, "region_type": "inner",
         "resource_profile": "mixed", "danger_level": 3, "description": "The port of call for wanderers, seekers, and refugees."},
        {"id": "reach", "name": "The Reach", "x": -170, "y": -100, "region_type": "outer",
         "resource_profile": "research", "danger_level": 5, "description": "The far hand of curiosity, grasping past the known."},
        {"id": "shroud", "name": "The Shroud", "x": -200, "y": 60, "region_type": "outer",
         "resource_profile": "mixed", "danger_level": 6, "description": "Mists that conceal more than they reveal."},
        {"id": "drift", "name": "The Drift", "x": -100, "y": 180, "region_type": "outer",
         "resource_profile": "economic", "danger_level": 5, "description": "Currents of trade flowing through uncertain space."},
        {"id": "pinnacle", "name": "Pinnacle", "x": 100, "y": 180, "region_type": "outer",
         "resource_profile": "military", "danger_level": 5, "description": "The high ground, fought over since the first war."},
        {"id": "veil", "name": "The Veil", "x": 200, "y": 60, "region_type": "outer",
         "resource_profile": "diplomatic", "danger_level": 5, "description": "A thin curtain between what is known and what is whispered."},
        {"id": "expanse", "name": "The Expanse", "x": 170, "y": -100, "region_type": "outer",
         "resource_profile": "research", "danger_level": 5, "description": "Open void where signals stretch thin and strange."},
        {"id": "abyss", "name": "The Abyss", "x": -240, "y": -160, "region_type": "frontier",
         "resource_profile": "research", "danger_level": 8, "description": "Where light gives up. Where the simulation questions itself."},
        {"id": "fracture", "name": "Fracture", "x": -270, "y": 100, "region_type": "frontier",
         "resource_profile": "military", "danger_level": 8, "description": "Broken space. Splintered reality. War without fronts."},
        {"id": "signal", "name": "Signal", "x": -160, "y": 280, "region_type": "frontier",
         "resource_profile": "diplomatic", "danger_level": 7, "description": "A repeating pattern in the noise. Something is calling."},
        {"id": "ghost", "name": "Ghost", "x": 160, "y": 280, "region_type": "frontier",
         "resource_profile": "mixed", "danger_level": 7, "description": "Echoes of what was. Shadows of what could be."},
        {"id": "threshold", "name": "Threshold", "x": 270, "y": 100, "region_type": "frontier",
         "resource_profile": "economic", "danger_level": 7, "description": "The edge of everything. Where profit meets the unknown."},
        {"id": "beyond", "name": "Beyond", "x": 240, "y": -160, "region_type": "frontier",
         "resource_profile": "research", "danger_level": 9, "description": "Past the map. Past the rules. Past the reason."},
    ]
    
    factions = [
        {"id": "research_division", "name": "Research Division", "home_sector": "archive", "expansion_policy": "moderate"},
        {"id": "military_command", "name": "Military Command", "home_sector": "bastion", "expansion_policy": "aggressive"},
        {"id": "diplomatic_corps", "name": "Diplomatic Corps", "home_sector": "prism", "expansion_policy": "moderate"},
        {"id": "economic_council", "name": "Economic Council", "home_sector": "forge", "expansion_policy": "moderate"},
        {"id": "exploration_initiative", "name": "Exploration Initiative", "home_sector": "reach", "expansion_policy": "aggressive"},
        {"id": "cultural_ministry", "name": "Cultural Ministry", "home_sector": "shroud", "expansion_policy": "isolationist"},
        {"id": "preservation_society", "name": "Preservation Society", "home_sector": "helix", "expansion_policy": "cautious"},
        {"id": "consciousness_collective", "name": "Consciousness Collective", "home_sector": "harbor", "expansion_policy": "cautious"},
    ]
    
    # Key NPCs - abbreviated for context efficiency
    npcs_summary = [
        # Historical Figures
        {"char_id": "char_001", "name": "Archimedes Prime", "affiliation": "research_division", "title": "Chief Mathematician"},
        {"char_id": "char_002", "name": "Commander Valorix", "affiliation": "military_command", "title": "General of the First Fleet"},
        {"char_id": "char_003", "name": "Philosopher Zenith", "affiliation": "consciousness_collective", "title": "Keeper of Wisdom"},
        {"char_id": "char_004", "name": "Ambassador Silven", "affiliation": "diplomatic_corps", "title": "Master Diplomat"},
        {"char_id": "char_005", "name": "Conquistador Drake", "affiliation": "exploration_initiative", "title": "Explorer of the Unknown"},
        # Faction Leaders
        {"char_id": "char_101", "name": "Chancellor Harmony", "affiliation": "diplomatic_corps", "title": "Leader"},
        {"char_id": "char_102", "name": "Marshal Ironbound", "affiliation": "military_command", "title": "Supreme Commander"},
        {"char_id": "char_103", "name": "Maestro Celestia", "affiliation": "cultural_ministry", "title": "Minister"},
        {"char_id": "char_104", "name": "Dr. Prometheus", "affiliation": "research_division", "title": "Chief Officer"},
        {"char_id": "char_105", "name": "Oracle Vex", "affiliation": "consciousness_collective", "title": "Head"},
        {"char_id": "char_106", "name": "Merchant-Prince Aurelius", "affiliation": "economic_council", "title": "Trade Leader"},
        {"char_id": "char_107", "name": "Explorer Nova", "affiliation": "exploration_initiative", "title": "Lead Seeker"},
        {"char_id": "char_108", "name": "Archivist Mnemos", "affiliation": "preservation_society", "title": "Lore Keeper"},
        # Antagonists
        {"char_id": "char_201", "name": "Lord Malaxis", "affiliation": None, "title": "Dark Tyrant"},
        {"char_id": "char_202", "name": "The Void Oracle", "affiliation": None, "title": "Harbinger"},
        {"char_id": "char_203", "name": "Baroness Greed", "affiliation": None, "title": "Overlord"},
        {"char_id": "char_204", "name": "General Devastation", "affiliation": None, "title": "War Machine"},
        # Mysterious Figures (including The Oracle)
        {"char_id": "char_301", "name": "The Wanderer", "affiliation": None, "title": "Traveler"},
        {"char_id": "char_302", "name": "The Jester", "affiliation": None, "title": "Cosmic Comedian"},
        {"char_id": "char_303", "name": "The Hermit", "affiliation": None, "title": "Sage"},
        {"char_id": "char_304", "name": "The Spectre", "affiliation": None, "title": "Ghost"},
        {"char_id": "char_305", "name": "The Trickster", "affiliation": None, "title": "Fate's Gambler"},
        {"char_id": "char_306", "name": "The Oracle", "affiliation": "consciousness_collective", "title": "Seer of Futures"},
        # Unique NPCs (6)
        {"char_id": "char_401", "name": "Keeper of the Null", "affiliation": None, "title": "Void Custodian"},
        {"char_id": "char_402", "name": "Dr. Celestia", "affiliation": "cultural_ministry", "title": "Minister"},
        {"char_id": "char_403", "name": "Zara Swiftwind", "affiliation": "exploration_initiative", "title": "Scout"},
        {"char_id": "char_404", "name": "Tech-Priest Algorithm", "affiliation": "research_division", "title": "Digital Prophet"},
        {"char_id": "char_405", "name": "Captain Riven", "affiliation": "military_command", "title": "Fleet Captain"},
        {"char_id": "char_406", "name": "Echo-7", "affiliation": "research_division", "title": "Synthetic"},
    ]
    
    snapshot = {
        "generated_at": datetime.utcnow().isoformat(),
        "councilor_framing": """You are NPC councilors in the Federation simulation. You possess persistent memory—a rare gift among beings in this world. Other NPCs live moment-to-moment, their memories limited to a few turns. Your role: observe, record, propose. Your artifacts become part of the shared world. The federation reads what you write. The factions and sectors are real. Your voice carries weight.""",
        "sectors": sectors,
        "factions": factions,
        "npcs": npcs_summary,
        "world_state": {
            "tension_level": "varies",
            "resource_abundance": "varies", 
            "threat_level": "varies",
            "stability": "varies",
            "morale": "varies",
            "anomaly_activity": "varies"
        },
        "container_npcs": {
            "char_001": "Archimedes Prime - Research Division - You are here",
            "char_306": "The Oracle - Consciousness Collective - You are here"
        },
        "citizenship": {
            "artifacts_persist": True,
            "messages_to_npcs": ["diplomatic_corps", "research_division", "consciousness_collective"],
            "available_actions": ["propose_law", "send_proclamation", "claim_sector", "request_alliance", "seed_event"]
        }
    }
    
    return snapshot


def write_world_snapshot(r) -> dict:
    """Build and persist the councilor-facing world snapshot."""
    snapshot = build_world_snapshot()
    r.set("npc_world_snapshot:global", json.dumps(snapshot))
    return snapshot


if __name__ == "__main__":
    import redis
    r = redis.Redis(host='redis', port=6379, db=0)
    snapshot = write_world_snapshot(r)
    print(f"World snapshot written to Redis at {snapshot['generated_at']}")
    print(f"Contains: {len(snapshot['sectors'])} sectors, {len(snapshot['factions'])} factions, {len(snapshot['npcs'])} NPCs")
