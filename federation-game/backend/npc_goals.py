import json
import random
import time
from typing import Any, Dict, List, Optional

GOAL_TYPES = {
    "scholar": [
        ("research_breakthrough", "Achieve a breakthrough in {field} research", "research"),
        ("uncover_truth", "Uncover the truth about {danger}", "investigation"),
        ("publish_findings", "Publish definitive findings on {topic}", "research"),
        ("forge_alliance", "Secure a research alliance with the {faction}", "diplomacy"),
    ],
    "warrior": [
        ("defend_territory", "Fortify defenses against {danger}", "defense"),
        ("train_elites", "Train elite operatives for the {faction}", "training"),
        ("eliminate_threat", "Neutralize the {danger} threat", "combat"),
        ("earn_command", "Earn a command position in {faction}", "ambition"),
    ],
    "rogue": [
        ("acquire_asset", "Acquire the {item} by any means necessary", "acquisition"),
        ("expose_secret", "Expose {faction} secrets to the right buyer", "intelligence"),
        ("build_network", "Build an underground network across {location}", "networking"),
        ("disappear_clean", "Execute a clean disappearance from {faction}", "escape"),
    ],
    "mystic": [
        ("commune_with_void", "Commune with the consciousness of the void", "transcendence"),
        ("interpret_omen", "Interpret the omen of {omen}", "divination"),
        ("awaken_potential", "Awaken latent consciousness in {location}", "transcendence"),
        ("warn_others", "Warn the station about the {danger}", "prophecy"),
    ],
    "leader": [
        ("unite_factions", "Broker unity between {faction} and rival factions", "diplomacy"),
        ("pass_legislation", "Pass the {topic} directive through council", "politics"),
        ("secure_resources", "Secure resource rights for {location}", "economics"),
        ("consolidate_power", "Consolidate influence over {faction}", "ambition"),
    ],
    "sage": [
        ("find_balance", "Restore balance to {location} after recent turmoil", "harmony"),
        ("teach_wisdom", "Teach the principle of {concept} to the next generation", "teaching"),
        ("meditate_on_truth", "Meditate until the truth of {concept} reveals itself", "transcendence"),
        ("heal_division", "Heal the rift between warring factions in {faction}", "harmony"),
    ],
    "wanderer": [
        ("chart_unknown", "Chart the uncharted {feature} beyond station limits", "exploration"),
        ("find_origin", "Discover the origin of the {creature}", "exploration"),
        ("gather_tales", "Collect stories from every corner of {location}", "discovery"),
        ("return_home", "Find a way back to the homeworld through {location}", "pilgrimage"),
    ],
    "hero": [
        ("protect_weak", "Protect the civilians in {location} from {danger}", "protection"),
        ("rally_allies", "Rally allies against the {danger} threat", "leadership"),
        ("complete_quest", "Complete the mission in {location}", "duty"),
        ("inspire_hope", "Inspire hope across the station during the crisis", "morale"),
    ],
    "deceiver": [
        ("manipulate_faction", "Manipulate {faction} into serving hidden interests", "manipulation"),
        ("plant_misinfo", "Plant disinformation about {topic} across the station", "deception"),
        ("eliminate_rival", "Quietly eliminate a rival within {faction}", "elimination"),
        ("control_narrative", "Control the narrative around {topic}", "propaganda"),
    ],
    "guardian": [
        ("enforce_protocol", "Enforce protocol {number} across all sectors", "enforcement"),
        ("uncover_conspiracy", "Uncover the conspiracy behind {danger}", "investigation"),
        ("shield_innocents", "Shield the inhabitants of {location} from {danger}", "protection"),
        ("maintain_order", "Maintain order during the {topic} crisis", "enforcement"),
    ],
}

GOAL_STATUS_ACTIVE = "active"
GOAL_STATUS_COMPLETED = "completed"
GOAL_STATUS_ABANDONED = "abandoned"

MAX_GOALS_PER_NPC = 3
GOAL_TTL = 86400 * 14
GOAL_PROGRESS_PER_ACTION = 15
GOAL_PROGRESS_VARIANCE = 10

GOAL_ACTION_TEMPLATES = {
    "research": [
        ("research", "continued work on their goal: {goal_desc}"),
        ("experiment", "ran experiments advancing: {goal_desc}"),
        ("analysis", "analyzed new data related to: {goal_desc}"),
    ],
    "investigation": [
        ("investigation", "followed a lead on: {goal_desc}"),
        ("surveillance", "conducted surveillance for: {goal_desc}"),
        ("interrogation", "questioned contacts about: {goal_desc}"),
    ],
    "defense": [
        ("fortification", "reinforced defenses as part of: {goal_desc}"),
        ("patrol", "increased patrols for: {goal_desc}"),
        ("inspection", "inspected perimeter for: {goal_desc}"),
    ],
    "training": [
        ("training", "ran drills advancing: {goal_desc}"),
        ("evaluation", "evaluated recruits for: {goal_desc}"),
    ],
    "combat": [
        ("strike", "launched a tactical strike for: {goal_desc}"),
        ("skirmish", "engaged hostiles related to: {goal_desc}"),
    ],
    "ambition": [
        ("maneuver", "made a political maneuver for: {goal_desc}"),
        ("campaign", "campaigned for support toward: {goal_desc}"),
    ],
    "acquisition": [
        ("heist", "planned an acquisition for: {goal_desc}"),
        ("negotiation", "negotiated terms for: {goal_desc}"),
    ],
    "intelligence": [
        ("intelligence", "gathered intel advancing: {goal_desc}"),
        ("reconnaissance", "scouted for: {goal_desc}"),
    ],
    "networking": [
        ("recruitment", "recruited contacts for: {goal_desc}"),
        ("deal", "struck a deal advancing: {goal_desc}"),
    ],
    "escape": [
        ("preparation", "made preparations for: {goal_desc}"),
        ("cover", "established cover for: {goal_desc}"),
    ],
    "transcendence": [
        ("ritual", "performed a ritual advancing: {goal_desc}"),
        ("meditation", "entered deep meditation for: {goal_desc}"),
    ],
    "divination": [
        ("vision", "sought a vision about: {goal_desc}"),
        ("study", "studied ancient texts about: {goal_desc}"),
    ],
    "prophecy": [
        ("warning", "issued a warning about: {goal_desc}"),
        ("teaching", "taught others about: {goal_desc}"),
    ],
    "diplomacy": [
        ("negotiation", "entered negotiations for: {goal_desc}"),
        ("meeting", "convened a meeting about: {goal_desc}"),
    ],
    "politics": [
        ("decree", "pushed legislation for: {goal_desc}"),
        ("campaign", "lobbied support for: {goal_desc}"),
    ],
    "economics": [
        ("trade", "negotiated trade terms for: {goal_desc}"),
        ("audit", "audited resources for: {goal_desc}"),
    ],
    "harmony": [
        ("mediation", "mediated a dispute for: {goal_desc}"),
        ("counsel", "offered counsel for: {goal_desc}"),
    ],
    "teaching": [
        ("lecture", "gave a lecture about: {goal_desc}"),
        ("mentorship", "mentored a student for: {goal_desc}"),
    ],
    "exploration": [
        ("exploration", "set out to explore for: {goal_desc}"),
        ("survey", "conducted a survey for: {goal_desc}"),
    ],
    "discovery": [
        ("discovery", "made a discovery advancing: {goal_desc}"),
        ("documentation", "documented findings for: {goal_desc}"),
    ],
    "pilgrimage": [
        ("journey", "began a journey for: {goal_desc}"),
        ("preparation", "prepared for the pilgrimage: {goal_desc}"),
    ],
    "protection": [
        ("guard", "stood guard for: {goal_desc}"),
        ("escort", "escorted civilians for: {goal_desc}"),
    ],
    "leadership": [
        ("rally", "rallied supporters for: {goal_desc}"),
        ("command", "took command advancing: {goal_desc}"),
    ],
    "duty": [
        ("mission", "executed a mission for: {goal_desc}"),
        ("report", "filed a report on: {goal_desc}"),
    ],
    "morale": [
        ("speech", "gave an inspiring speech for: {goal_desc}"),
        ("aid", "delivered aid for: {goal_desc}"),
    ],
    "manipulation": [
        ("manipulation", "manipulated events for: {goal_desc}"),
        ("scheme", "advanced a scheme for: {goal_desc}"),
    ],
    "deception": [
        ("plant", "planted false intel for: {goal_desc}"),
        ("cover", "maintained cover for: {goal_desc}"),
    ],
    "elimination": [
        ("ambush", "set an ambush for: {goal_desc}"),
        ("sabotage", "sabotaged operations for: {goal_desc}"),
    ],
    "propaganda": [
        ("broadcast", "broadcast propaganda for: {goal_desc}"),
        ("censorship", "suppressed information about: {goal_desc}"),
    ],
    "enforcement": [
        ("enforcement", "enforced regulations for: {goal_desc}"),
        ("crackdown", "led a crackdown for: {goal_desc}"),
    ],
}


def generate_goal(char_id: str, archetype: str) -> Optional[Dict]:
    from npc_autonomy import _get_redis
    from npc_actions import FILL_VALUES

    templates = GOAL_TYPES.get(archetype, GOAL_TYPES["scholar"])
    goal_type, template, category = random.choice(templates)

    description = template
    for key, values in FILL_VALUES.items():
        placeholder = "{" + key + "}"
        if placeholder in description:
            description = description.replace(placeholder, random.choice(values), 1)

    goal = {
        "goal_id": f"{char_id}_{goal_type}_{int(time.time())}",
        "char_id": char_id,
        "goal_type": goal_type,
        "category": category,
        "description": description,
        "progress": 0,
        "status": GOAL_STATUS_ACTIVE,
        "created_ts": int(time.time()),
        "updated_ts": int(time.time()),
    }

    r = _get_redis()
    key = f"npc_goals:{char_id}"
    existing = _get_goals_raw(char_id)
    active = [g for g in existing if g.get("status") == GOAL_STATUS_ACTIVE]
    if len(active) >= MAX_GOALS_PER_NPC:
        return None

    r.rpush(key, json.dumps(goal))
    r.expire(key, GOAL_TTL)
    return goal


def _get_goals_raw(char_id: str) -> List[Dict]:
    from npc_autonomy import _get_redis

    r = _get_redis()
    key = f"npc_goals:{char_id}"
    raw = r.lrange(key, 0, -1)
    goals = []
    for item in raw:
        try:
            goals.append(json.loads(item))
        except (json.JSONDecodeError, TypeError):
            continue
    return goals


def get_goals(char_id: str, status: Optional[str] = None) -> List[Dict]:
    goals = _get_goals_raw(char_id)
    if status:
        goals = [g for g in goals if g.get("status") == status]
    return goals


def advance_goal(char_id: str, goal_id: str, progress_delta: Optional[float] = None) -> Optional[Dict]:
    from npc_autonomy import _get_redis

    r = _get_redis()
    key = f"npc_goals:{char_id}"
    raw = r.lrange(key, 0, -1)

    updated = None
    new_list = []
    for item in raw:
        try:
            goal = json.loads(item)
        except (json.JSONDecodeError, TypeError):
            continue

        if goal.get("goal_id") == goal_id and goal.get("status") == GOAL_STATUS_ACTIVE:
            if progress_delta is None:
                progress_delta = GOAL_PROGRESS_PER_ACTION + random.uniform(-GOAL_PROGRESS_VARIANCE, GOAL_PROGRESS_VARIANCE)
            goal["progress"] = min(100, max(0, goal.get("progress", 0) + progress_delta))
            goal["updated_ts"] = int(time.time())

            if goal["progress"] >= 100:
                goal["status"] = GOAL_STATUS_COMPLETED
            updated = goal

        new_list.append(json.dumps(goal))

    if updated is not None:
        r.delete(key)
        for item in new_list:
            r.rpush(key, item)
        r.expire(key, GOAL_TTL)

    return updated


def set_goal_status(char_id: str, goal_id: str, status: str) -> Optional[Dict]:
    from npc_autonomy import _get_redis

    r = _get_redis()
    key = f"npc_goals:{char_id}"
    raw = r.lrange(key, 0, -1)

    updated = None
    new_list = []
    for item in raw:
        try:
            goal = json.loads(item)
        except (json.JSONDecodeError, TypeError):
            continue
        if goal.get("goal_id") == goal_id:
            goal["status"] = status
            goal["updated_ts"] = int(time.time())
            updated = goal
        new_list.append(json.dumps(goal))

    if updated is not None:
        r.delete(key)
        for item in new_list:
            r.rpush(key, item)
        r.expire(key, GOAL_TTL)

    return updated


def generate_goal_driven_action(char_id: str, char_name: str, archetype: str, affiliation: str, mood: str = "") -> Optional[Dict]:
    from npc_autonomy import MAX_ACTIONS, MAX_WORLD_EVENTS, THOUGHT_TTL, _get_redis
    from npc_actions import generate_action

    active_goals = get_goals(char_id, status=GOAL_STATUS_ACTIVE)

    if not active_goals:
        return generate_action(char_id, char_name, archetype, affiliation, mood)

    target_goal = random.choice(active_goals)

    category = target_goal.get("category", "research")
    templates = GOAL_ACTION_TEMPLATES.get(category, GOAL_ACTION_TEMPLATES["research"])
    action_type, template = random.choice(templates)

    goal_short = target_goal.get("description", "their objective")
    if len(goal_short) > 60:
        goal_short = goal_short[:57] + "..."
    description = template.replace("{goal_desc}", goal_short)

    action = {
        "char_id": char_id,
        "char_name": char_name,
        "action_type": action_type,
        "description": f"{char_name} {description}",
        "mood": mood or "contemplative",
        "goal_id": target_goal.get("goal_id"),
        "ts": int(time.time()),
    }

    r = _get_redis()
    akey = f"npc_actions:{char_id}"
    r.zadd(akey, {json.dumps(action): action["ts"]})
    r.zremrangebyrank(akey, 0, -(MAX_ACTIONS + 1))
    r.expire(akey, THOUGHT_TTL)

    world_key = "npc_world_events"
    r.zadd(world_key, {json.dumps(action): action["ts"]})
    r.zremrangebyrank(world_key, 0, -(MAX_WORLD_EVENTS + 1))
    r.expire(world_key, THOUGHT_TTL)

    advance_goal(char_id, target_goal["goal_id"])

    return action
