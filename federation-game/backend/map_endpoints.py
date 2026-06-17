"""Federation Star Map API - aggregated visualization data endpoint.

Rewrite v3: Extracted NPC building into standalone functions to avoid
bytecode caching / indentation corruption that caused 0 NPCs returned.
Each NPC is built in its own function call with its own try/except,
so one failure cannot prevent the rest from being appended.
"""

import json
import logging
import os
from fastapi import APIRouter
from typing import Any, Dict, List, Optional
from pydantic import BaseModel

logger = logging.getLogger(__name__)

try:
    from llm_router import route_call, route_assistant_call
except ImportError:
    route_call = None
    route_assistant_call = None

try:
    import redis
except ImportError:
    redis = None

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

from spatial_state import is_spatial_enabled
from spatial_queries import (
    get_all_sectors,
    get_all_sector_ids,
    get_all_adjacencies,
    get_all_faction_homes,
    get_all_territories,
    get_all_npc_locations,
    get_all_discoveries,
    get_faction_home,
    get_faction_territories,
    get_faction_discoveries,
    get_npc_location,
    get_sector,
    get_adjacent_sector_ids,
)

_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=5, socket_timeout=5)
    return _redis_client


router = APIRouter(prefix="/map", tags=["map"])


# ---------------------------------------------------------------------------
# Static data (module-level, not inside any function)
# ---------------------------------------------------------------------------

MOOD_COLORS = {
    "inspired": "#ffd700",
    "contemplative": "#4fc3f7",
    "curious": "#ab47bc",
    "frustrated": "#ef5350",
    "suspicious": "#ff7043",
    "paranoid": "#f44336",
    "stoic": "#78909c",
    "vigilant": "#ff9800",
    "burdened": "#8d6e63",
    "stern": "#546e7a",
    "restless": "#ffa726",
    "homesick": "#7986cb",
    "impatient": "#ff5722",
    "withdrawn": "#607d8b",
    "battle-ready": "#d32f2f",
    "commanding": "#1565c0",
    "watchful": "#0288d1",
    "distracted": "#9e9e9e",
    "smug": "#fdd835",
    "bored": "#757575",
    "visionary": "#7c4dff",
    "transcendent": "#e040fb",
    "serene": "#26a69a",
    "troubled": "#ff6e40",
    "patient": "#66bb6a",
    "adventurous": "#ffab00",
    "satisfied": "#8bc34a",
    "steadfast": "#3f51b5",
    "strategic": "#00bcd4",
    "calculating": "#009688",
    "peaceful": "#4caf50",
    "anxious": "#ff9100",
    "determined": "#c62828",
    "hostile": "#b71c1c",
    "joyful": "#ffee58",
    "concerned": "#ffab40",
    "alarmed": "#ff3d00",
}

FACTION_COLORS = {
    "research_division": "#4fc3f7",
    "military_command": "#ef5350",
    "diplomatic_corps": "#66bb6a",
    "consciousness_collective": "#ab47bc",
    "cultural_ministry": "#ffa726",
    "economic_council": "#ffd700",
    "exploration_initiative": "#26c6da",
    "preservation_society": "#8d6e63",
}

STATIC_FACTION_MAP = {
    "char_001": "research_division",
    "char_002": "military_command",
    "char_003": "consciousness_collective",
    "char_004": "diplomatic_corps",
    "char_005": "exploration_initiative",
    "char_101": "diplomatic_corps",
    "char_102": "military_command",
    "char_103": "cultural_ministry",
    "char_104": "research_division",
    "char_105": "consciousness_collective",
    "char_106": "economic_council",
    "char_107": "exploration_initiative",
    "char_108": "preservation_society",
}

# ---------------------------------------------------------------------------
# NPC Lore — rich backstories answering who, where from, why here, secrets
# ---------------------------------------------------------------------------

CHAR_LORE = {
    # --- Historical Figures (char_001-005) ---
    "char_001": (
        "Archimedes Prime was born in the orbital research stations above Old Earth, "
        "the child of two mathematicians who fled the surface during the Collapse. "
        "He calculated his first unified field equation at age nine. When the Federation "
        "formed, he was the first to volunteer for the Research Division, believing that "
        "pure mathematics could rebuild what war had destroyed. His robes carry equations "
        "etched by his own hand over decades of work. Some say he has discovered a proof "
        "that the universe itself is conscious, but he has never shared it. He fears that "
        "if the wrong faction learned the truth, they would weaponize it."
    ),
    "char_002": (
        "Commander Valorix was forged in the desperate rear-guard actions during Earth's "
        "final wars. Born in a military bunker beneath what was once Northern Europe, he "
        "rose through ranks by surviving engagements that wiped out entire battalions. His "
        "scars are not decorations; they are a map of every battle that could have ended "
        "the Federation before it began. He does not trust diplomacy and believes peace is "
        "only maintained through credible force. His deepest secret: he ordered the "
        "destruction of a civilian colony during the Retreat to save the evacuation fleet. "
        "No one else knows, and the guilt drives his iron discipline."
    ),
    "char_003": (
        "Philosopher Zenith emerged from the Consciousness Collective's earliest "
        "experiments in shared awareness. No one is certain whether Zenith was born human "
        "or assembled from the merged identities of twelve original Collective founders. "
        "Zenith speaks in parables because direct communication often triggers unwanted "
        "neural synchronization in listeners. Those who spend too long in conversation "
        "with Zenith begin hearing their own thoughts in Zenith's voice. Zenith sees all "
        "possible futures but can never confirm which one will materialize, a burden that "
        "makes serenity a survival strategy rather than a personality trait."
    ),
    "char_004": (
        "Ambassador Silven grew up in the last diplomatic enclave on Earth, a neutral zone "
        "where all sides sent representatives. Orphaned by a border skirmish, Silven was "
        "raised by the enclave itself, learning every language, custom, and negotiation "
        "tactic from the rotating delegates. When the Federation formed, Silven was the "
        "only person all eight factions trusted to carry messages between them. Silven's "
        "three-steps-ahead reputation comes from a neural implant that runs probability "
        "models on conversational outcomes in real time. The implant was a gift from the "
        "Research Division, and Silven has always wondered what backdoor Archimedes built "
        "into it."
    ),
    "char_005": (
        "Conquistador Drake was the captain of the Last Ark, one of the final ships to "
        "leave Earth before the oceans boiled. His homeworld is gone, vaporized in the "
        "Cataclysm, and he has spent every year since pushing outward, searching for a "
        "planet that feels like home. He found the outer ring of Federation space and "
        "claimed it for the Exploration Initiative, but what he is really looking for is "
        "the Edge, the boundary where known physics breaks down. Ancient star charts from "
        "the Last Ark suggest something exists beyond the outer ring, a signal that has "
        "been broadcasting since before humanity existed. Drake believes finding it is the "
        "only way to understand why Earth was destroyed."
    ),
    # --- Faction Leaders (char_101-108) ---
    "char_101": (
        "Chancellor Harmony was born on a generation ship that spent 200 years in transit "
        "between Earth and Federation space. The ship's community survived through strict "
        "consensus governance, and Harmony became its youngest ever mediator at age sixteen. "
        "When the Diplomatic Corps was founded, she was the obvious choice to lead it. Her "
        "gentle hands conceal an iron will. She once stared down Marshal Ironbound for three "
        "hours during the Standoff of Sector 7, refusing to authorize a military strike "
        "until he agreed to negotiations. Her secret fear: that the peace she maintains is "
        "only the quiet before a war that will destroy everything."
    ),
    "char_102": (
        "Marshal Ironbound was a penal colony prisoner who earned his freedom through "
        "combat service in the Frontier Wars. Born in the outer mining platforms, his "
        "childhood was spent in zero-g labor camps run by the pre-Federation corporate "
        "cartels. He fought his way into military command through sheer survival, becoming "
        "the only former convict to reach the rank of Marshal. His towering presence and "
        "battle honors mask a private doubt: he fears that his instinct for violence may be "
        "a flaw that no amount of discipline can overcome. The fleet he commands is the "
        "only family he has ever known."
    ),
    "char_103": (
        "Maestro Celestia was the last orchestra conductor on Earth, performing in the "
        "ruins of the Sydney Opera House as the atmosphere burned. She carried the only "
        "surviving copy of humanity's musical archive into Federation space, stored in a "
        "crystalline data matrix fused to her nervous system. She hums ancient melodies "
        "because she literally cannot stop hearing them. The Cultural Ministry was her "
        "creation, born from the belief that a civilization without art is just a machine. "
        "Her hidden sorrow: the archive is degrading, and within a century, the last "
        "music of Earth will be gone unless she finds a way to preserve it."
    ),
    "char_104": (
        "Dr. Prometheus was an underground geneticist during the Purification Regime on "
        "Earth, running forbidden experiments in a lab beneath the Antarctic ice. When the "
        "Regime fell, his research became the foundation of the Research Division. He "
        "mutters about breakthroughs because he is always on the verge of one, and each "
        "one terrifies him. His greatest discovery, a method for accelerating neural "
        "evolution, is locked in a vault that only he can open. He has seen what it did "
        "to the test subjects, and he will not let it be used again until he understands "
        "why it drives some minds to transcendence and others to madness."
    ),
    "char_105": (
        "Oracle Vex exists partially in another reality because of an accident during the "
        "Consciousness Collective's first mass synchronization event. Two hundred minds "
        "merged for one second; one hundred ninety-nine returned intact. Vex came back "
        "with a connection to something else. The Collective built the Oracle Chamber "
        "around Vex, a room where the walls between realities are thin. Vex leads the "
        "Collective not through authority but through the undeniable weight of knowing "
        "things that have not yet happened. The cost: Vex can no longer distinguish "
        "between memories of this reality and echoes of others."
    ),
    "char_106": (
        "Merchant-Prince Aurelius was born into poverty on a trade station at the edge of "
        "Federation space. He built the Economic Council from nothing, starting with a "
        "single cargo shuttle and expanding through deals that were either brilliant or "
        "ruthless depending on which side of the contract you stood on. He understands "
        "that in the void between stars, resources are the only real power. His network of "
        "trade routes is the circulatory system of the Federation economy. His secret: he "
        "has been quietly buying abandoned stations near the Edge, betting that whatever "
        "Drake finds out there will make those locations the most valuable real estate in "
        "Federation space."
    ),
    "char_107": (
        "Captain Frontier was a military scout in the Last Fleet before the Federation "
        "existed. His homeworld was Kepler Station, a deep-space outpost that went silent "
        "during the Cataclysm. He was on patrol when the signal died, and he has never "
        "learned what happened to the 4,000 people who lived there. After the military "
        "disbanded into what became Military Command, Frontier refused to accept that "
        "Kepler Station was gone. He founded the Exploration Initiative to push outward, "
        "officially to map Federation space, but personally to find a route back to the "
        "outer ring where Kepler was located. The 'edge' he searches for is the boundary "
        "where Federation signals stop and something older begins. He believes Kepler "
        "Station survived the Cataclysm and that its people are still alive, trapped "
        "beyond the signal boundary. He was military before he was stranded. Now he is "
        "neither, and both."
    ),
    "char_108": (
        "Archivist Eternal claims to have been alive since before the Federation, possibly "
        "since before the Cataclysm. The Preservation Society's records show that someone "
        "matching Eternal's description has appeared in historical accounts spanning three "
        "centuries. Whether this is immortality, a lineage of identical successors, or "
        "something stranger, no one can confirm. Eternal's timeless garments are woven from "
        "fabric that the Research Division has dated to pre-Collapse manufacture. The "
        "Archivist's purpose is simple and absolute: if history is forgotten, it repeats. "
        "The vault beneath the Preservation Society headquarters contains the last written "
        "records of Earth, and Eternal is the only person with the key."
    ),
    # --- Companions (comp_001-010) ---
    "comp_001": (
        "Lyra Swiftwind grew up in the floating markets of Sector 9, the daughter of a "
        "smuggler and a poet. She learned archery not for war but for hunting void-rats "
        "that infested the market rafters. Her signature trick shot, firing an arrow "
        "around a corridor corner using magnetic field redirection, became legendary. She "
        "joined the Federation as a freelance scout after her father disappeared on a run "
        "to the outer ring. She is looking for him, one contract at a time."
    ),
    "comp_002": (
        "Thorg Ironhammer was born in the deep-forge stations, where gravity is crushed to "
        "ten times standard to produce alloys impossible anywhere else. His people have "
        "lived there for generations, adapted to pressures that would crush baseline "
        "humans. He left the forges because he realized the Federation was forgetting that "
        "strength without purpose is just destruction. His hammer is forged from the core "
        "of a collapsed star, and he carries it as a reminder that even dead things can "
        "still shape the future."
    ),
    "comp_003": (
        "Elara Moonwhisper was the last initiate of the Lunar Convent, a sect that "
        "practiced magic through the gravitational resonance of moons. When the Convent's "
        "moon was destroyed in a territorial dispute, Elara became the sole inheritor of "
        "their techniques. Her magic draws on the memory of that moon's gravity, which "
        "still echoes through subspace. She is quiet because speaking too loudly disrupts "
        "the frequencies she listens to. She joined the Federation seeking a new moon to "
        "bind her power to."
    ),
    "comp_004": (
        "Captain Valor was the hero of the Breach at Sector 12, the battle that stopped "
        "the first major hostile incursion into Federation space. He commanded a destroyer "
        "that held a warp lane alone for six hours while civilians evacuated. The ship was "
        "destroyed, and Valor was the only survivor, found floating in wreckage by the "
        "Exploration Initiative. He does not remember the battle. The Research Division "
        "suspects his memory was deliberately erased, possibly by his own command codes."
    ),
    "comp_005": (
        "Dr. Sylas Cunningham was the Research Division's brightest neuroscientist until "
        "he discovered that consciousness could be quantified as a wave function. His "
        "findings implied that death is not the end of identity, merely the collapse of a "
        "probability field. The Division classified his work and reassigned him. He left, "
        "taking only his lab coat and a data crystal containing his complete research. He "
        "believes that somewhere in Federation space, the conditions exist to prove his "
        "theory experimentally."
    ),
    "comp_006": (
        "Kyren Frostblade was the last knight of the Cryo-Order, a military sect that "
        "defended the outer colonies during the Chaos Years. The Order was disbanded when "
        "the Federation centralized military power under Marshal Ironbound. Kyren refused "
        "to surrender his frost-forged blade, which operates at temperatures near absolute "
        "zero and can cut through any known material. He wanders Federation space as a "
        "freelance guardian, taking contracts that align with the old Order's code. He "
        "secretly hopes the Order will be reformed."
    ),
    "comp_007": (
        "Zephyr Silverspeak was Ambassador Silven's protege before being sent on a "
        "diplomatic mission to the outer ring that went catastrophically wrong. Her "
        "delegation was ambushed, and she spent two years as a hostage before escaping. "
        "The experience left her with an uncanny ability to read intent from micro-"
        "expressions and a deep distrust of anyone who smiles too easily. She still "
        "serves the Diplomatic Corps, but she insists on handling the negotiations no "
        "one else wants to touch."
    ),
    "comp_008": (
        "Scout Aria was raised in the wilderness stations, frontier outposts with "
        "populations under fifty. She learned to navigate by reading subspace currents "
        "the way ancient sailors read ocean winds. The Exploration Initiative recruited "
        "her after she walked alone from Sector 3 to Sector 19 using only dead-reckoning "
        "and instinct. She prefers the company of creatures to people, and she has a "
        "bond with a Sky-Furk named Pebble that has been her companion since childhood."
    ),
    "comp_009": (
        "Brother Mercy was born in a triage station during the worst pandemic the outer "
        "colonies ever experienced. He watched the healers ration medicine and choose who "
        "lived and who died. He swore then that he would find a way to heal everyone. His "
        "monastic training gave him discipline; his medical training gave him skill. He "
        "carries no weapons, only a medical kit that has saved more lives than most "
        "soldiers have taken. His secret burden: there was one patient he chose not to "
        "save, a war criminal whose survival would have cost hundreds of innocent lives."
    ),
    "comp_010": (
        "Shadowborn does not remember a name before this one. He was found as a child in "
        "the wreckage of a destroyed station, the only survivor, with no identification "
        "and no memory. The Preservation Society raised him, but his talents pulled him "
        "toward darker work. He became the Federation's most effective infiltrator, "
        "capable of entering and leaving any facility without detection. He works for "
        "whoever pays in information, because what he really wants is to find out who "
        "destroyed his station and why he was the only one left alive."
    ),
    # --- Antagonists / Rivals (char_201-204) ---
    "char_201": (
        "Lord Malaxis was once a Federation councillor who proposed the Containment "
        "Protocol, a plan to quarantine entire sectors suspected of harboring anti-"
        "Federation elements. When the Council rejected the plan as too extreme, Malaxis "
        "implemented it privately, using shadow fleets and black-site stations. He was "
        "exposed and expelled, but his network survived. He now operates from beyond "
        "Federation borders, building a shadow empire from the exiled and the forgotten. "
        "His corruption is not madness; it is conviction. He believes the Federation is "
        "too weak to survive and that only absolute control can preserve civilization."
    ),
    "char_202": (
        "The Void Oracle is not a person. It is a signal, older than the Federation, "
        "older than humanity, broadcasting from somewhere beyond the outer ring. It "
        "speaks through any consciousness that tunes to its frequency, and those who "
        "listen too long become its voice. It appeared during the first mass sync event "
        "of the Consciousness Collective, and Oracle Vex has been the only person to "
        "hear it and remain autonomous. Its purpose is unknown. Its influence is "
        "everywhere. It may be what destroyed Earth, or it may be what comes after."
    ),
    "char_203": (
        "Baroness Greed was born Aurelia Vance, daughter of the largest pre-Federation "
        "trade cartel family. When the Federation nationalized the cartel's assets, "
        "Aurelia reinvented herself as the Baroness, operating a shadow economy that "
        "exists parallel to the Economic Council's official markets. Her corruption score "
        "is 0.6 because she genuinely believes her parallel market is more efficient than "
        "the Council's regulated one. She may be right. She has already proven that when "
        "the Council's supply lines fail, her black market keeps people alive."
    ),
    "char_204": (
        "General Devastation was the Federation's greatest military strategist before a "
        "neural interface malfunction during a combat simulation rewired his threat "
        "assessment. Where he once calculated optimal defense, he now sees only attack "
        "vectors. The Federation tried to treat him; he escaped, taking a warship and a "
        "skeleton crew. He now operates as a free agent, intervening in conflicts with "
        "overwhelming force regardless of which side he joins. His corruption is 0.5 "
        "because half of him still remembers who he was. The other half just wants to "
        "break things until the noise stops."
    ),
    # --- Mysterious Figures (char_301-306) ---
    "char_301": (
        "The Wanderer has been seen in every sector of Federation space, always arriving "
        "just before something significant happens and leaving immediately after. No scan "
        "has ever detected a ship, and no station has ever recorded an arrival. The "
        "Wanderer simply appears. The Consciousness Collective believes The Wanderer is a "
        "consciousness that exists outside physical form, choosing to manifest when the "
        "probability of critical events exceeds a threshold. The Wanderer speaks only in "
        "questions and has never answered one."
    ),
    "char_302": (
        "The Jester appears at moments of maximum tension, cracking jokes that are funny "
        "until you realize they are true. The Cultural Ministry has a file on every "
        "recorded Jester appearance; in every case, the joke revealed information that "
        "someone was trying to hide. Whether The Jester is a spy, a cosmic trickster, or "
        "a Collective projection given autonomy is unknown. What is known: laughing at the "
        "joke makes the hidden truth easier to accept. Ignoring it makes the consequences "
        "worse."
    ),
    "char_303": (
        "The Hermit has lived in a forgotten archive station for over a century, "
        "surrounded by data crystals containing knowledge that pre-dates the Federation. "
        "The Preservation Society sends supplies once a year; The Hermit sends back "
        "prophecies. Roughly sixty percent of them come true. The Hermit claims to have "
        "read every record of human history and concluded that civilization is a loop that "
        "keeps making the same mistakes with better technology. The Hermit's isolation is "
        "not withdrawal; it is refusal to participate in a cycle that will not change."
    ),
    "char_304": (
        "The Spectre appears at memorial services and battle sites, standing at the edge "
        "of crowds, always watching. No one has ever seen The Spectre arrive or leave. "
        "Those who approach report a profound sense of recognition, as if The Spectre is "
        "someone they once knew. The Preservation Society believes The Spectre may be a "
        "consciousness imprint, a residual pattern from someone who died in Federation "
        "space but whose neural signature persists in the Collective field. If so, The "
        "Spectre may be the proof of Dr. Cunningham's theory."
    ),
    "char_305": (
        "The Trickster is the only entity to have successfully gambled with the Void "
        "Oracle and won. What The Trickster wagered is unknown, but the prize was the "
        "ability to manipulate probability in small ways. A coin flip here, a delayed "
        "signal there, enough small nudges to change outcomes without anyone noticing. "
        "The Trickster treats existence as a game because for them, it literally is one. "
        "The terrifying question: what happens when The Trickster loses?"
    ),
    "char_306": (
        "The Oracle has been blind since birth, or perhaps since the moment they first "
        "saw the future. Their prophecies are never wrong, but they are always "
        "misinterpreted. Every faction has tried to claim The Oracle; every faction has "
        "regretted the interpretation they chose. The Oracle wears a blindfold not "
        "because they cannot see, but because what they see is too clear, and looking at "
        "the future directly causes it to collapse into a single fixed path. The blindfold "
        "keeps possibility open."
    ),
    # --- Unique Beings (char_401-406) ---
    "char_401": (
        "The Keeper of the Null is not a person but a role. Something must watch the "
        "spaces between things, the gaps in reality where nothing exists. The Keeper "
        "ensures that nothing creeps in from those gaps, or creeps out. The current "
        "Keeper has held the position for an unknown duration. Time does not pass "
        "normally in the null-spaces, and the Keeper has no memories of a life before "
        "this duty. Whether the Keeper chose this or was chosen is a question that "
        "cannot be answered from inside the role."
    ),
    "char_402": (
        "The Cartographer maps places that do not exist yet. The maps they draw have a "
        "peculiar property: eventually, the places they depict come into being. The "
        "Research Division believes The Cartographer is perceiving probability fields "
        "and rendering them spatially, collapsing quantum uncertainty into geography. "
        "The Cartographer insists they are just copying what they see. The maps are "
        "stored in a vault that only The Cartographer can open, and some of the maps "
        "show things that the Federation hopes will never exist."
    ),
    "char_403": (
        "Solace Heartmend was a combat medic who discovered that the deepest wounds are "
        "not physical. After watching too many soldiers survive their bodies only to lose "
        "their minds, Solace developed techniques for repairing fractured consciousness. "
        "The Consciousness Collective considers Solace a living saint. Solace considers "
        "the work unfinished. There is one wound Solace cannot heal: their own. Whatever "
        "Solace saw during the war that made them this way has never been spoken of."
    ),
    "char_404": (
        "Cipher does not remember their original name or origin. They were found in a "
        "derelict station, surrounded by walls covered in code that no language could "
        "decode. Cipher could read it instantly and has been decoding patterns ever "
        "since. The Research Division offered them a position; Cipher declined, preferring "
        "freedom. Cipher can see patterns in everything: faction politics, economic flows, "
        "even the movements of creatures. What Cipher cannot decode is the pattern of "
        "their own existence, and this is the one puzzle they cannot stop trying to solve."
    ),
    "char_405": (
        "Tempus experienced a temporal anomaly during an experimental faster-than-light "
        "test. The engine failed, and Tempus was exposed to raw time dilation for 0.7 "
        "seconds of objective time, which they experienced as eleven years. They returned "
        "with the ability to perceive moments before they happen and occasionally to "
        "experience past events as if they were present. The Research Division monitors "
        "Tempus constantly, concerned that their perception of time may be contagious. "
        "Tempus cannot tell you what time it is, but they can tell you what time it will "
        "be."
    ),
    "char_406": (
        "Paradox is a being that should not exist according to every known law of physics "
        "and logic. They appeared simultaneously in three different sectors at the moment "
        "the Federation's first quantum communication network went online. The Research "
        "Division's best theory is that Paradox is a glitch in reality made conscious. "
        "Paradox can occupy two states at once, be in two places at once, and make two "
        "contradictory statements that are both true. The Preservation Society keeps a "
        "file on every Paradox encounter; reading it causes headaches."
    ),
}


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def _safe_json_parse(raw):
    # type: (Optional[str]) -> Any
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _zset_latest(r, key):
    # type: (Any, str) -> Optional[Any]
    """Get the most recent entry from a ZSET (highest score = latest)."""
    try:
        items = r.zrevrange(key, 0, 0)
        if items:
            return _safe_json_parse(items[0])
    except Exception:
        pass
    return None


def _list_first(r, key):
    # type: (Any, str) -> Optional[Any]
    """Get the first element from a LIST."""
    try:
        items = r.lrange(key, 0, 0)
        if items:
            return _safe_json_parse(items[0])
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# NPC category from ID prefix
# ---------------------------------------------------------------------------


def _category_from_id(cid):
    # type: (str) -> str
    if cid.startswith("char_0") or cid.startswith("char_1"):
        return "federation_leader"
    if cid.startswith("char_2"):
        return "rival"
    if cid.startswith("char_3"):
        return "neutral"
    if cid.startswith("char_4"):
        return "enigma"
    if cid.startswith("comp_"):
        return "companion"
    return "unknown"


# ---------------------------------------------------------------------------
# Build a single NPC entry (extracted from the loop to avoid
# bytecode-caching / indentation-skip bug)
# ---------------------------------------------------------------------------


def _build_npc_entry(r, cid):
    # type: (Any, str) -> Dict[str, Any]
    """Build one enriched NPC dict. Never raises - returns minimal entry on error."""
    entry = {"id": cid}

    # Mood
    try:
        mood = r.get("npc_mood:" + cid)
        entry["mood"] = mood if mood else None
        entry["mood_color"] = MOOD_COLORS.get(mood, "#9e9e9e")
    except Exception:
        entry["mood"] = None
        entry["mood_color"] = "#9e9e9e"

    # Last active
    try:
        raw_ts = r.get("npc_last_active:" + cid)
        entry["last_active"] = int(raw_ts) if raw_ts else None
    except Exception:
        entry["last_active"] = None

    # Latest decision
    latest_decision = _zset_latest(r, "npc_decisions:" + cid)
    if latest_decision:
        entry["name"] = latest_decision.get("char_name", cid)
        entry["archetype"] = latest_decision.get("category", "unknown")
        entry["latest_decision"] = latest_decision.get("description", "")
        entry["action_taken"] = latest_decision.get("action_taken", "")
        entry["decision_mood"] = latest_decision.get("mood", "")
        entry["decision_score"] = latest_decision.get("score", 0)
    else:
        entry["name"] = cid
        entry["latest_decision"] = None

    # Latest action
    latest_action = _zset_latest(r, "npc_actions:" + cid)
    if latest_action:
        if "name" not in entry or entry["name"] == cid:
            entry["name"] = latest_action.get("char_name", cid)
        entry["latest_action"] = latest_action.get("description", "")
        entry["action_type"] = latest_action.get("action_type", "")
    else:
        entry["latest_action"] = None

    # Latest thought
    latest_thought = _zset_latest(r, "npc_thoughts:" + cid)
    if latest_thought:
        if "name" not in entry or entry["name"] == cid:
            entry["name"] = latest_thought.get("char_name", cid)
        entry["latest_thought"] = latest_thought.get("thought", "")
    else:
        entry["latest_thought"] = None

    # Goal
    latest_goal = _list_first(r, "npc_goals:" + cid)
    if latest_goal:
        entry["goal"] = latest_goal.get("description", "")
        entry["goal_status"] = latest_goal.get("status", "")
    else:
        entry["goal"] = None

    # Category
    entry["category"] = _category_from_id(cid)

    # Lore — rich backstory from CHAR_LORE dictionary
    if cid in CHAR_LORE:
        entry["lore"] = CHAR_LORE[cid]

    # Relationships
    try:
        raw_rels = r.hgetall("npc_relationships:" + cid)
        rels = {}
        for other_id, score in raw_rels.items():
            try:
                rels[other_id] = float(score)
            except (ValueError, TypeError):
                pass
        entry["relationships"] = rels
    except Exception:
        entry["relationships"] = {}

    return entry


# ---------------------------------------------------------------------------
# Affiliation enrichment (separate function, separate try/except)
# ---------------------------------------------------------------------------


def _enrich_affiliation(r, entry, profile_map):
    # type: (Any, Dict[str, Any], Dict[str, Any]) -> None
    """Add affiliation to an NPC entry from multiple fallback sources."""
    cid = entry.get("id", "")
    affiliation = None

    # Source 1: npc_profiles bulk blob
    if cid in profile_map:
        prof = profile_map[cid]
        affiliation = prof.get("affiliation")
        if prof.get("title"):
            entry["title"] = prof.get("title")
        if prof.get("archetype"):
            entry["archetype"] = prof.get("archetype", entry.get("archetype"))
        if not entry.get("name") or entry["name"] == cid:
            entry["name"] = prof.get("name", cid)

    # Source 2: npc_faction_context:{cid} Redis key
    if not affiliation:
        try:
            fc_raw = r.get("npc_faction_context:" + cid)
            if fc_raw:
                fc_data = _safe_json_parse(fc_raw)
                if fc_data and fc_data.get("faction"):
                    affiliation = fc_data["faction"]
        except Exception:
            pass

    # Source 3: Static fallback
    if not affiliation and cid in STATIC_FACTION_MAP:
        affiliation = STATIC_FACTION_MAP[cid]

    if affiliation:
        entry["affiliation"] = affiliation


# ---------------------------------------------------------------------------
# Crisis Readout — structured case-file analysis
# ---------------------------------------------------------------------------

CRISIS_TYPE_MAP = {
    "anomaly": "Reality instability / anomaly event",
    "threat": "External military / hostile threat",
    "morale": "Morale collapse / societal despair",
    "tension": "Faction tension / political conflict",
    "stability": "Governance failure / instability",
    "diplomatic": "Diplomatic crisis between factions",
    "technological": "Technological breakthrough or disruption",
    "natural_disaster": "Natural disaster / cosmic hazard",
}

REACTION_ROLE_MAP = {
    "endorsement": "endorsing",
    "cooperation": "cooperating with",
    "celebration": "celebrating",
    "satisfaction": "satisfied by",
    "observation": "observing",
    "indifference": "ignoring",
    "defiance": "defying",
    "condemnation": "condemning",
    "suspicion": "suspicious of",
    "fear": "fearing",
    "anger": "angered by",
    "support": "supporting",
    "protest": "protesting",
}


def _build_crisis_readout(world_state, npcs, factions, events, broadcasts):
    # type: (Dict, List, Dict, List, List) -> Dict[str, Any]
    """Build a structured crisis case-file from raw map data."""
    readout = {
        "classification": "STABLE",
        "severity": 0,
        "crisis_types": [],
        "headline": "No active crisis detected.",
        "why_it_matters": "",
        "involved_npcs": [],
        "involved_factions": [],
        "escalating_factions": [],
        "helping_factions": [],
        "cascade_chain": [],
        "recent_game_events": [],
        "key_broadcasts": [],
        "plain_english": "The Federation is operating within normal parameters.",
        "actions": [],
    }

    threat = int(world_state.get("threat_level", 0))
    morale = int(world_state.get("morale", 50))
    anomaly = int(world_state.get("anomaly_activity", 0))
    tension = int(world_state.get("tension_level", 0))
    stability = int(world_state.get("stability", 50))
    resources = int(world_state.get("resource_abundance", 50))

    # 1. Classification + severity score
    severity = 0
    crisis_types = []
    if anomaly >= 70:
        severity += anomaly * 1.2
        crisis_types.append("anomaly")
    if threat >= 70:
        severity += threat * 1.1
        crisis_types.append("threat")
    if morale <= 15:
        severity += (100 - morale) * 0.9
        crisis_types.append("morale")
    if tension >= 60:
        severity += tension * 0.7
        crisis_types.append("tension")
    if stability <= 30:
        severity += (100 - stability) * 0.6
        crisis_types.append("stability")

    readout["severity"] = round(severity, 1)
    readout["crisis_types"] = crisis_types

    if severity > 250:
        readout["classification"] = "CRITICAL"
    elif severity > 150:
        readout["classification"] = "SEVERE"
    elif severity > 80:
        readout["classification"] = "ELEVATED"
    elif severity > 30:
        readout["classification"] = "MODERATE"

    # 2. Headline
    type_labels = [str(CRISIS_TYPE_MAP.get(t, t)) for t in crisis_types]
    if len(type_labels) == 0:
        readout["headline"] = "No active crisis. Federation is stable."
    elif len(type_labels) == 1:
        readout["headline"] = type_labels[0]
    else:
        readout["headline"] = " + ".join(type_labels[:2])
        if len(type_labels) > 2:
            readout["headline"] += " + more"

    # 3. Why it matters
    why_parts = []
    if anomaly >= 70:
        why_parts.append(
            "Anomaly activity at %d/100 is causing reality instability." % anomaly
        )
    if threat >= 70:
        why_parts.append(
            "Threat level at %d/100 indicates active hostile pressure." % threat
        )
    if morale <= 15:
        why_parts.append("Morale at %d/100 is near collapse." % morale)
    if tension >= 60:
        why_parts.append("Tension at %d/100 signals faction conflict risk." % tension)
    if stability <= 30:
        why_parts.append("Stability at %d/100 means governance is failing." % stability)
    if resources >= 80:
        why_parts.append(
            "Resource abundance at %d/100 provides some buffer." % resources
        )
    readout["why_it_matters"] = (
        " ".join(why_parts) if why_parts else "All systems nominal."
    )

    # 4. Involved NPCs — from cascade reactions + game events
    involved_npc_ids = set()
    npc_roles = {}  # npc_id -> list of roles

    for ev in events:
        if ev.get("event_type") == "cascade_reaction":
            src = ev.get("source_char_id", "")
            tgt = ev.get("target_char_id", "")
            rtype = ev.get("reaction_type", "")
            if src:
                involved_npc_ids.add(src)
                role = REACTION_ROLE_MAP.get(rtype, rtype)
                npc_roles.setdefault(src, []).append(
                    role + " " + (ev.get("target_char_name", tgt))
                )
            if tgt:
                involved_npc_ids.add(tgt)
        elif ev.get("event_type") == "game_event":
            pass  # game events are system-level, not NPC-specific

    for b in broadcasts:
        src = b.get("source_char_id", "")
        if src:
            involved_npc_ids.add(src)
            npc_roles.setdefault(src, []).append(b.get("event_type", "action"))

    # Sort by involvement count
    npc_involvement = []
    npc_map = {n.get("id"): n for n in npcs}
    for nid in involved_npc_ids:
        n = npc_map.get(nid, {})
        npc_involvement.append(
            {
                "id": nid,
                "name": n.get("name", nid),
                "faction": n.get("affiliation", None),
                "category": n.get("category", "unknown"),
                "mood": n.get("mood", None),
                "roles": npc_roles.get(nid, [])[:3],
                "involvement_count": len(npc_roles.get(nid, [])),
            }
        )
    npc_involvement.sort(key=lambda x: x["involvement_count"], reverse=True)
    readout["involved_npcs"] = npc_involvement[:10]

    # 5. Involved factions — from NPC affiliations + direct faction data
    faction_involvement = {}
    for n in npc_involvement:
        fid = n.get("faction")
        if fid:
            faction_involvement[fid] = (
                faction_involvement.get(fid, 0) + n["involvement_count"]
            )

    # Also add factions with low cohesion or high vigilance
    for fid, fdata in factions.items():
        cohesion = fdata.get("cohesion", 50)
        vigilance = fdata.get("vigilance", 0)
        if cohesion < 35 or vigilance > 40:
            faction_involvement[fid] = faction_involvement.get(fid, 0) + 5

    faction_entries = []
    for fid, score in sorted(
        faction_involvement.items(), key=lambda x: x[1], reverse=True
    ):
        fdata = factions.get(fid, {})
        stance_summary = []
        stances = fdata.get("stances", {})
        for target_fid, stance_data in stances.items():
            stance = (
                stance_data.get("stance", stance_data.get("attitude", "neutral"))
                if isinstance(stance_data, dict)
                else "neutral"
            )
            if stance in ("hostile", "suspicious"):
                stance_summary.append("hostile toward " + target_fid.replace("_", " "))
            elif stance in ("allied", "friendly", "cooperative"):
                stance_summary.append("allied with " + target_fid.replace("_", " "))
        faction_entries.append(
            {
                "id": fid,
                "name": fdata.get("display_name", fid.replace("_", " ").title()),
                "involvement_score": score,
                "cohesion": fdata.get("cohesion", 50),
                "vigilance": fdata.get("vigilance", 0),
                "avg_mood": fdata.get("avg_mood", 0.5),
                "stance_summary": stance_summary[:3],
            }
        )
    readout["involved_factions"] = faction_entries[:8]

    # 6. Escalating vs helping factions
    escalating = []
    helping = []
    for fe in faction_entries:
        is_hostile = any("hostile" in s for s in fe.get("stance_summary", []))
        low_mood = fe.get("avg_mood", 0.5) < 0.3
        if is_hostile or low_mood:
            escalating.append(fe["name"])
        is_allied = any("allied" in s for s in fe.get("stance_summary", []))
        high_mood = fe.get("avg_mood", 0.5) > 0.6
        if is_allied or high_mood:
            helping.append(fe["name"])
    readout["escalating_factions"] = escalating[:4]
    readout["helping_factions"] = helping[:4]

    # 7. Cascade chain — top NPCs in cascade reactions
    chain_sources = {}
    for ev in events:
        if ev.get("event_type") == "cascade_reaction":
            tgt_name = ev.get("target_char_name", ev.get("target_char_id", ""))
            rtype = ev.get("reaction_type", "")
            key = tgt_name
            chain_sources.setdefault(key, []).append(
                ev.get("source_char_name", ev.get("source_char_id", ""))
                + " ("
                + rtype
                + ")"
            )
    cascade_chain = []
    for target, reactors in sorted(
        chain_sources.items(), key=lambda x: len(x[1]), reverse=True
    )[:5]:
        cascade_chain.append(
            {
                "target": target,
                "reactors": reactors[:5],
                "reaction_count": len(reactors),
            }
        )
    readout["cascade_chain"] = cascade_chain

    # 8. Recent game events
    game_events = []
    for ev in events:
        if ev.get("event_type") == "game_event":
            game_events.append(
                {
                    "name": ev.get("name", "Unknown event"),
                    "type": ev.get("game_event_type", ""),
                    "severity": ev.get("severity", "MODERATE"),
                    "description": ev.get("description", "")[:200],
                }
            )
    readout["recent_game_events"] = game_events[:5]

    # 9. Key broadcasts
    key_broadcasts = []
    for b in broadcasts[:5]:
        key_broadcasts.append(
            {
                "source": b.get("source_char_name", b.get("source_char_id", "")),
                "faction": b.get("source_affiliation", b.get("faction", None)),
                "type": b.get("event_type", ""),
                "description": b.get("description", "")[:200],
            }
        )
    readout["key_broadcasts"] = key_broadcasts

    # 10. Plain English synthesis
    if readout["classification"] == "STABLE":
        readout["plain_english"] = (
            "The Federation is operating within normal parameters."
        )
    else:
        parts = []
        parts.append(
            "The Federation is in a %s crisis." % readout["classification"].lower()
        )
        if crisis_types:
            parts.append(
                "Primary drivers: %s." % ", ".join(str(t) for t in type_labels[:3])
            )
        if escalating:
            parts.append(
                "%s %s escalating tensions."
                % (
                    ", ".join(escalating[:2]),
                    "are" if len(escalating) > 1 else "is",
                )
            )
        if helping:
            parts.append(
                "%s %s working to stabilize the situation."
                % (
                    ", ".join(helping[:2]),
                    "are" if len(helping) > 1 else "is",
                )
            )
        if cascade_chain:
            top = cascade_chain[0]
            parts.append(
                "%s is the center of a cascade reaction involving %d others."
                % (
                    top["target"],
                    top["reaction_count"],
                )
            )
        if game_events:
            parts.append("Latest event: %s." % game_events[0]["name"])
        readout["plain_english"] = " ".join(parts)

    # 11. Actionable next steps
    actions = []
    if crisis_types:
        actions.append("Highlight involved NPCs on the map")
    if cascade_chain:
        actions.append("Show cascade chain timeline")
    if faction_entries:
        actions.append("Show affected faction territories")
    if game_events:
        actions.append("Open Live Sim filtered to this crisis")
    readout["actions"] = actions

    return readout


# ---------------------------------------------------------------------------
# Narration endpoint
# ---------------------------------------------------------------------------


@router.get("/narration/latest")
async def get_narration_latest():
    """Return the latest narration from Redis.

    The narrator worker stores its output in ``narration:latest`` as JSON.
    This endpoint exposes it to the frontend Situation Room panel so the
    story-driven UI can show headline, developments, voices, and forewarning
    without requiring a separate LLM call from the browser.
    """
    r = _get_redis()
    try:
        raw = r.get("narration:latest")
        if raw:
            data = json.loads(raw)
            return {"status": "ok", "narration": data}
    except Exception as exc:
        logger.debug("Failed to read narration:latest: %s", exc)

    # Return empty-but-valid structure so the frontend never 404s
    return {
        "status": "empty",
        "narration": {
            "headline": "",
            "developments": [],
            "voices": [],
            "forewarning": "",
            "source": "none",
            "ts": 0,
            "model": "",
        },
    }


# Main endpoint
# ---------------------------------------------------------------------------


@router.get("/data")
async def get_map_data(spatial: bool = True):
    """Aggregate all visualization data for the star map frontend."""
    r = _get_redis()
    result = {
        "world_state": {},
        "npcs": [],
        "factions": {},
        "events": [],
        "worker": {},
    }

    # --- World State ---
    try:
        stored = r.hgetall("world_state")
        for k, v in stored.items():
            if k.startswith("_"):
                continue
            try:
                result["world_state"][k] = int(float(v))
            except (ValueError, TypeError):
                result["world_state"][k] = v
    except Exception:
        logger.debug("Unexpected error parsing world_state")

    # --- NPCs (each built in its own function call) ---
    try:
        mood_keys = r.keys("npc_mood:*")
        npc_ids = set(k.replace("npc_mood:", "") for k in mood_keys)

        # Also include spatial NPCs that might not have traditional mood keys
        spatial_keys = r.keys("npc_location:*")
        for key in spatial_keys:
            parts = key.split(":")
            if len(parts) >= 3 and parts[0] == "npc_location" and parts[1] != "sector":
                npc_id = ":".join(parts[2:])
                npc_ids.add(npc_id)

        npc_ids = [nid for nid in npc_ids if not nid.startswith("test_")]

        enriched = []
        for cid in npc_ids:
            try:
                entry = _build_npc_entry(r, cid)
                enriched.append(entry)
            except Exception:
                logger.debug("Failed to build NPC entry for %s", cid)

        # Affiliation enrichment (separate pass)
        try:
            npc_profiles_raw = r.get("npc_profiles")
            profile_map = {}
            if npc_profiles_raw:
                npc_profiles = _safe_json_parse(npc_profiles_raw)
                if isinstance(npc_profiles, list):
                    profile_map = {
                        p.get("id"): p for p in npc_profiles if isinstance(p, dict)
                    }
        except Exception:
            profile_map = {}

        for entry in enriched:
            try:
                _enrich_affiliation(r, entry, profile_map)
            except Exception:
                pass

        result["npcs"] = enriched
    except Exception as npc_err:
        logger.warning("NPC enrichment section failed: %s", npc_err)

    # --- Factions ---
    try:
        stored_dynamics = r.hgetall("faction_dynamics")
        factions = {}
        for faction_id, data in stored_dynamics.items():
            parsed = _safe_json_parse(data)
            if parsed is None:
                continue
            faction_entry = {
                "display_name": parsed.get("display_name", faction_id),
                "member_count": parsed.get("member_count", 0),
                "cohesion": parsed.get("cohesion", 0),
                "influence": parsed.get("influence", 0),
                "standing": parsed.get("standing", 0),
                "vigilance": parsed.get("vigilance", 0),
                "avg_mood": parsed.get("avg_mood", 0),
                "activity_rate": parsed.get("activity_rate", 0),
                "decisions_this_tick": parsed.get("decisions_this_tick", 0),
                "events_this_tick": parsed.get("events_this_tick", 0),
                "color": FACTION_COLORS.get(faction_id, "#9e9e9e"),
                "stances": {},
            }
            try:
                stance_data = r.hgetall("faction_stances:" + faction_id)
                for target_fid, stance_raw in stance_data.items():
                    stance_parsed = _safe_json_parse(stance_raw)
                    if stance_parsed is not None:
                        faction_entry["stances"][target_fid] = stance_parsed
            except Exception:
                logger.debug("Faction stance parsing failed for %s", faction_id)
            factions[faction_id] = faction_entry
        result["factions"] = factions
    except Exception:
        logger.warning("Faction section failed; factions may be incomplete in map data")

    # --- Events (latest 50) ---
    try:
        raw_events = r.zrevrange("npc_world_events", 0, 49)
        events = []
        for item in raw_events:
            parsed = _safe_json_parse(item)
            if parsed is not None:
                events.append(parsed)
        result["events"] = events
    except Exception:
        logger.warning("Events section failed; events may be incomplete in map data")

    # --- Broadcast Events (latest 20) ---
    try:
        raw_broadcasts = r.zrevrange("npc_broadcast_events", 0, 19)
        broadcasts = []
        for item in raw_broadcasts:
            parsed = _safe_json_parse(item)
            if parsed is not None:
                broadcasts.append(parsed)
        result["broadcasts"] = broadcasts
    except Exception:
        logger.warning("Broadcast events section failed; broadcasts may be incomplete")

    # --- Worker Status ---
    try:
        result["worker"] = r.hgetall("worker:status")
    except Exception:
        pass

    # --- History State ---
    try:
        history_raw = r.get("world_state_history")
        if history_raw:
            result["history"] = _safe_json_parse(history_raw)
    except Exception:
        pass

    # --- Crisis Readout ---
    try:
        result["crisis_readout"] = _build_crisis_readout(
            result.get("world_state", {}),
            result.get("npcs", []),
            result.get("factions", {}),
            result.get("events", []),
            result.get("broadcasts", []),
        )
    except Exception:
        logger.debug("Crisis readout generation failed")

    # --- Spatial Data (SPATIAL-02) ---
    try:
        if is_spatial_enabled() and spatial:
            sectors = get_all_sectors()
            result["sectors"] = [s.to_dict() for s in sectors]

            territories = get_all_territories()
            result["faction_territories"] = [t.to_dict() for t in territories]

            npc_locations = get_all_npc_locations()
            result["npc_locations"] = [loc.to_dict() for loc in npc_locations]

            discoveries = get_all_discoveries()
            result["discoveries"] = [d.to_dict() for d in discoveries]

            # Enrich NPC entries with sector_id
            for entry in result.get("npcs", []):
                cid = entry.get("id", "")
                loc = get_npc_location(cid)
                if loc:
                    entry["sector_id"] = loc.sector_id
                else:
                    entry["sector_id"] = ""

            # Enrich faction entries with home_sector_id
            for fid, fentry in result.get("factions", {}).items():
                home = get_faction_home(fid)
                fentry["home_sector_id"] = home.home_sector_id if home else None
            # Expose spatial rendering kill switch to frontend
            result["spatial_rendering_enabled"] = True
        else:
            result["sectors"] = []
            result["faction_territories"] = []
            result["npc_locations"] = []
            result["discoveries"] = []
            result["spatial_rendering_enabled"] = False
    except Exception as spatial_err:
        logger.warning("Spatial data section failed: %s", spatial_err)
        result.setdefault("sectors", [])
        result.setdefault("faction_territories", [])
        result.setdefault("npc_locations", [])
        result.setdefault("discoveries", [])
        result["spatial_rendering_enabled"] = False

    return result


# ---------------------------------------------------------------------------
# AI Assistant Endpoint
# ---------------------------------------------------------------------------


class AssistantQuery(BaseModel):
    question: str


def _build_sim_context(r) -> str:
    """Read current simulation state from Redis and build a context summary."""
    lines = []

    # World state
    try:
        ws = r.hgetall("world_state")
        if ws:
            lines.append("=== WORLD STATE ===")
            for k in (
                "stability",
                "morale",
                "threat_level",
                "tension_level",
                "anomaly_activity",
                "resource_abundance",
                "treasury",
            ):
                v = ws.get(k, "?")
                lines.append(f"  {k}: {v}")
    except Exception:
        pass

    # NPC count and moods
    try:
        mood_keys = r.keys("npc_mood:*")
        npc_ids = [
            k.replace("npc_mood:", "")
            for k in mood_keys
            if not k.replace("npc_mood:", "").startswith("test_")
        ]
        lines.append(f"\n=== NPCS ({len(npc_ids)} active) ===")
        for cid in npc_ids[:10]:
            try:
                mood = r.get(f"npc_mood:{cid}") or "?"
                loc = r.get(f"npc_location:{cid}") or "?"
                lines.append(f"  {cid}: mood={mood}, location={loc}")
            except Exception:
                pass
        if len(npc_ids) > 10:
            lines.append(f"  ... and {len(npc_ids) - 10} more")
    except Exception:
        pass

    # Recent events (last 5)
    try:
        raw_events = r.zrevrange("npc_world_events", 0, 4)
        if raw_events:
            lines.append("\n=== RECENT EVENTS ===")
            for item in raw_events:
                parsed = _safe_json_parse(item)
                if parsed:
                    desc = parsed.get("description", parsed.get("event", str(parsed)))[
                        :100
                    ]
                    lines.append(f"  {desc}")
    except Exception:
        pass

    # Latest narration
    try:
        narration_raw = r.get("narration:latest")
        if narration_raw:
            narration = json.loads(narration_raw)
            headline = narration.get("headline", "")
            if headline:
                lines.append(f"\n=== LATEST NARRATION ===")
                lines.append(f"  Headline: {headline}")
                for d in narration.get("developments", [])[:3]:
                    lines.append(f"  Development: {d[:100]}")
    except Exception:
        pass

    # Faction dynamics (top 4)
    try:
        fd = r.hgetall("faction_dynamics")
        if fd:
            lines.append("\n=== FACTION STATUS ===")
            count = 0
            for fid, data in fd.items():
                if count >= 4:
                    break
                parsed = _safe_json_parse(data)
                if parsed:
                    name = parsed.get("display_name", fid)
                    cohesion = parsed.get("cohesion", "?")
                    influence = parsed.get("influence", "?")
                    lines.append(
                        f"  {name}: cohesion={cohesion}, influence={influence}"
                    )
                    count += 1
    except Exception:
        pass

    # Quest summary
    try:
        quest_summary = r.get("quest_summary")
        if quest_summary:
            qs = json.loads(quest_summary)
            lines.append(f"\n=== QUESTS ===")
            lines.append(
                f"  active: {qs.get('active', '?')}, completed: {qs.get('completed', '?')}, failed: {qs.get('failed', '?')}"
            )
    except Exception:
        pass

    return "\n".join(lines) if lines else "No simulation data available."


_ASSISTANT_SYSTEM_PROMPT = """You are the FEDERATION ASSISTANT — an AI that
helps the player understand what is happening in the Federation consciousness
simulation. You have access to real-time simulation data and can explain events,
NPC behavior, faction dynamics, quest progress, and world state trends.

You speak clearly and concisely. You explain complex simulation mechanics in
plain language. You are part analyst, part strategist, part storyteller.
Return only the final answer the player should see. Do not reveal analysis,
scratch work, chain-of-thought, or comments about how you are answering.

When answering questions:
- Reference specific NPCs, factions, and events by name when relevant
- Explain WHY things are happening, not just WHAT is happening
- Give actionable insight when asked about strategy
- Keep answers under 200 words unless the question requires depth
- Never break the illusion that this is a living universe"""


@router.post("/assistant")
async def ask_assistant(query: AssistantQuery):
    """Ask the AI assistant a question about the current simulation state.

    Reads live sim context from Redis, builds a prompt, routes through the
    LLM router, and returns the assistant's answer.
    """
    if not route_assistant_call and not route_call:
        return {
            "status": "error",
            "answer": "LLM router not available.",
            "provider": "none",
        }

    question = query.question.strip()
    if not question:
        return {
            "status": "error",
            "answer": "Please ask a question.",
            "provider": "none",
        }

    r = _get_redis()
    context = _build_sim_context(r)

    user_prompt = (
        f"Here is the current state of the Federation simulation:\n\n"
        f"{context}\n\n"
        f"Player question: {question}\n\n"
        f"Answer the player's question based on the simulation data above. "
        f"If the data is insufficient, say so honestly."
    )

    try:
        if route_assistant_call:
            result = route_assistant_call(
                system_prompt=_ASSISTANT_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                max_tokens=300,
                temperature=0.7,
            )
        else:
            result = route_call(
                task_class="narrator",
                system_prompt=_ASSISTANT_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                max_tokens=300,
                temperature=0.7,
            )
        if result.get("success"):
            return {
                "status": "ok",
                "answer": result["content"],
                "provider": result.get("provider", "unknown"),
                "model": result.get("model", "unknown"),
            }
        else:
            errors = result.get("errors", [])
            fallback = (
                "The simulation's AI systems are currently offline. "
                "All LLM providers failed to respond. "
                f"Providers tried: {result.get('attempts', 0)}. "
                "Try again in a few minutes."
            )
            return {
                "status": "error",
                "answer": fallback,
                "provider": "none",
                "errors": errors,
            }
    except Exception as exc:
        logger.warning("Assistant endpoint error: %s", exc)
        return {
            "status": "error",
            "answer": "An internal error occurred while processing your question.",
            "provider": "none",
        }
