#!/usr/bin/env python3
"""
THE FEDERATION GAME - 100-YEAR TIMELINE LAYER (2387-2487)
~1100 LOC - Production-Ready Historical Simulation Arc

Covers six eras of federation history:
  FOUNDING (2387-2400) -> EXPANSION (2401-2420) -> CONSOLIDATION (2421-2445)
  -> CONFLICT (2446-2465) -> TRANSCENDENCE (2466-2480) -> LEGACY (2481-2487)

Tracks faction power/reputation drift, ideology drift, historical memory decay,
branch-point events, and generational narrative synthesis.
"""

import random
import uuid
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
from pathlib import Path


# ============================================================================
# ENUMS
# ============================================================================

class TimelineEra(Enum):
    """Historical eras spanning the 100-year federation arc"""
    FOUNDING = "founding"
    EXPANSION = "expansion"
    CONSOLIDATION = "consolidation"
    CONFLICT = "conflict"
    TRANSCENDENCE = "transcendence"
    LEGACY = "legacy"

    @classmethod
    def from_year(cls, year: int) -> "TimelineEra":
        if 2387 <= year <= 2400:
            return cls.FOUNDING
        elif 2401 <= year <= 2420:
            return cls.EXPANSION
        elif 2421 <= year <= 2445:
            return cls.CONSOLIDATION
        elif 2446 <= year <= 2465:
            return cls.CONFLICT
        elif 2466 <= year <= 2480:
            return cls.TRANSCENDENCE
        elif 2481 <= year <= 2487:
            return cls.LEGACY
        else:
            return cls.LEGACY

    @property
    def year_range(self) -> Tuple[int, int]:
        ranges = {
            TimelineEra.FOUNDING: (2387, 2400),
            TimelineEra.EXPANSION: (2401, 2420),
            TimelineEra.CONSOLIDATION: (2421, 2445),
            TimelineEra.CONFLICT: (2446, 2465),
            TimelineEra.TRANSCENDENCE: (2466, 2480),
            TimelineEra.LEGACY: (2481, 2487),
        }
        return ranges[self]

    @property
    def duration(self) -> int:
        start, end = self.year_range
        return end - start + 1


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class FactionSnapshot:
    """Point-in-time snapshot of a faction's state"""
    faction_id: str
    power: float = 0.5
    reputation: float = 0.5
    influence: float = 0.5
    ideology_drift: float = 0.0
    stability: float = 0.5
    member_count: int = 100

    def to_dict(self) -> Dict[str, Any]:
        return {
            "faction_id": self.faction_id,
            "power": round(self.power, 4),
            "reputation": round(self.reputation, 4),
            "influence": round(self.influence, 4),
            "ideology_drift": round(self.ideology_drift, 4),
            "stability": round(self.stability, 4),
            "member_count": self.member_count,
        }

    def clamp(self) -> None:
        self.power = max(0.0, min(1.0, self.power))
        self.reputation = max(0.0, min(1.0, self.reputation))
        self.influence = max(0.0, min(1.0, self.influence))
        self.ideology_drift = max(-1.0, min(1.0, self.ideology_drift))
        self.stability = max(0.0, min(1.0, self.stability))
        self.member_count = max(0, self.member_count)


@dataclass
class TimelineEvent:
    """A historical event on the federation timeline"""
    event_id: str
    year: int
    era: TimelineEra
    name: str
    description: str
    faction_state: Dict[str, FactionSnapshot] = field(default_factory=dict)
    memory_drift: Dict[str, float] = field(default_factory=dict)
    outcome: str = ""
    branch_point: bool = False
    branches: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "year": self.year,
            "era": self.era.value,
            "name": self.name,
            "description": self.description,
            "faction_state": {
                fid: snap.to_dict() for fid, snap in self.faction_state.items()
            },
            "memory_drift": {k: round(v, 4) for k, v in self.memory_drift.items()},
            "outcome": self.outcome,
            "branch_point": self.branch_point,
            "branches": self.branches,
            "metadata": self.metadata,
        }


@dataclass
class HistoricalMemory:
    """A remembered event with emotional weight and generational decay"""
    memory_id: str
    year: int
    event_id: str
    narrative: str
    emotional_weight: float = 0.0
    generational_decay: float = 0.1
    current_salience: float = 1.0
    faction_interpretations: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "year": self.year,
            "event_id": self.event_id,
            "narrative": self.narrative,
            "emotional_weight": round(self.emotional_weight, 4),
            "generational_decay": round(self.generational_decay, 4),
            "current_salience": round(self.current_salience, 4),
            "faction_interpretations": self.faction_interpretations,
        }


# ============================================================================
# NARRATIVE MEMORY TRACKER
# ============================================================================

class NarrativeMemoryTracker:
    """
    Tracks historical memories with emotional weight, generational decay,
    and faction-specific interpretations of past events.
    """

    def __init__(self):
        self.memories: Dict[str, HistoricalMemory] = {}

    def record_memory(
        self,
        event: TimelineEvent,
        narrative: str,
        emotional_weight: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Create a HistoricalMemory from a timeline event.

        Args:
            event: The timeline event to remember
            narrative: How this event is remembered
            emotional_weight: Emotional valence (-1.0 trauma to +1.0 triumph)

        Returns:
            Dict with memory creation result
        """
        memory_id = f"mem_{event.event_id}_{uuid.uuid4().hex[:8]}"
        decay_rate = self._compute_decay_rate(emotional_weight, event.era)

        memory = HistoricalMemory(
            memory_id=memory_id,
            year=event.year,
            event_id=event.event_id,
            narrative=narrative,
            emotional_weight=max(-1.0, min(1.0, emotional_weight)),
            generational_decay=decay_rate,
            current_salience=1.0,
            faction_interpretations={},
        )

        for faction_id in event.faction_state:
            memory.faction_interpretations[faction_id] = (
                self._auto_interpret(faction_id, event, emotional_weight)
            )

        self.memories[memory_id] = memory

        return {
            "success": True,
            "memory_id": memory_id,
            "event_id": event.event_id,
            "emotional_weight": memory.emotional_weight,
            "generational_decay": memory.generational_decay,
            "faction_interpretations": len(memory.faction_interpretations),
        }

    def decay_memories(self, current_year: int) -> Dict[str, Any]:
        """
        Reduce salience of all memories based on generational_decay.
        Each decade that passes reduces salience by the decay rate.

        Args:
            current_year: The current simulation year

        Returns:
            Dict with decay results
        """
        decayed_count = 0
        expired_count = 0

        for memory in self.memories.values():
            decades_elapsed = (current_year - memory.year) / 10.0
            if decades_elapsed > 0:
                decay_factor = max(0.0, 1.0 - memory.generational_decay * decades_elapsed)
                new_salience = max(0.0, min(1.0, decay_factor))

                if memory.current_salience > 0.01 and new_salience <= 0.01:
                    expired_count += 1

                if abs(new_salience - memory.current_salience) > 0.001:
                    decayed_count += 1

                memory.current_salience = new_salience

        return {
            "success": True,
            "current_year": current_year,
            "memories_decayed": decayed_count,
            "memories_expired": expired_count,
            "total_memories": len(self.memories),
        }

    def get_active_memories(self, threshold: float = 0.1) -> List[HistoricalMemory]:
        """
        Get memories still salient enough to influence current events.

        Args:
            threshold: Minimum salience to be considered active

        Returns:
            List of active HistoricalMemory objects
        """
        return [
            m for m in self.memories.values() if m.current_salience >= threshold
        ]

    def get_faction_perspective(self, faction_id: str, event_id: str) -> str:
        """
        Get how a specific faction interprets a particular memory.

        Args:
            faction_id: The faction whose perspective to retrieve
            event_id: The event being remembered

        Returns:
            Faction's interpretation string
        """
        for memory in self.memories.values():
            if memory.event_id == event_id:
                return memory.faction_interpretations.get(
                    faction_id,
                    f"Faction {faction_id} has no recorded perspective on this event."
                )
        return f"No memory found for event {event_id}."

    def add_faction_interpretation(
        self, memory_id: str, faction_id: str, interpretation: str
    ) -> Dict[str, Any]:
        """
        Add or update a faction's interpretation of a memory.

        Args:
            memory_id: The memory to update
            faction_id: The faction providing the interpretation
            interpretation: The faction's perspective on the event

        Returns:
            Dict with update result
        """
        if memory_id not in self.memories:
            return {"success": False, "error": f"Memory {memory_id} not found"}

        self.memories[memory_id].faction_interpretations[faction_id] = interpretation

        return {
            "success": True,
            "memory_id": memory_id,
            "faction_id": faction_id,
            "interpretation": interpretation,
        }

    def get_generational_narrative(self, current_year: int) -> str:
        """
        Produce a narrative summary of what the current generation remembers.
        Events from the last 30 years are "living memory", older events are
        "distant memory" filtered through salience.

        Args:
            current_year: The current simulation year

        Returns:
            Narrative summary string
        """
        active = self.get_active_memories(threshold=0.05)
        living = [m for m in active if (current_year - m.year) <= 30]
        distant = [m for m in active if (current_year - m.year) > 30]

        living.sort(key=lambda m: m.current_salience, reverse=True)
        distant.sort(key=lambda m: m.current_salience, reverse=True)

        lines = [f"=== Generational Narrative, Year {current_year} ==="]

        if living:
            lines.append("\nLiving Memory:")
            for m in living[:5]:
                valence = "triumphant" if m.emotional_weight > 0.3 else (
                    "traumatic" if m.emotional_weight < -0.3 else "notable"
                )
                lines.append(
                    f"  - [{m.year}] {m.narrative} ({valence}, salience: {m.current_salience:.2f})"
                )
        else:
            lines.append("\nLiving Memory: None remain.")

        if distant:
            lines.append("\nDistant Memory:")
            for m in distant[:3]:
                lines.append(
                    f"  - [{m.year}] {m.narrative} (fading, salience: {m.current_salience:.2f})"
                )
        else:
            lines.append("\nDistant Memory: Lost to time.")

        return "\n".join(lines)

    def export_memories(self) -> Dict[str, Any]:
        """Export all memories as serializable dict"""
        return {
            m_id: m.to_dict() for m_id, m in self.memories.items()
        }

    def import_memories(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Restore memories from exported dict"""
        restored = 0
        for m_id, m_data in data.items():
            memory = HistoricalMemory(
                memory_id=m_data["memory_id"],
                year=m_data["year"],
                event_id=m_data["event_id"],
                narrative=m_data["narrative"],
                emotional_weight=m_data["emotional_weight"],
                generational_decay=m_data["generational_decay"],
                current_salience=m_data["current_salience"],
                faction_interpretations=m_data.get("faction_interpretations", {}),
            )
            self.memories[m_id] = memory
            restored += 1

        return {"success": True, "memories_restored": restored}

    def _compute_decay_rate(self, emotional_weight: float, era: TimelineEra) -> float:
        base_decay = 0.1
        intensity_factor = 1.0 - abs(emotional_weight) * 0.5
        return round(base_decay * intensity_factor, 4)

    def _auto_interpret(
        self, faction_id: str, event: TimelineEvent, emotional_weight: float
    ) -> str:
        drift = event.memory_drift.get(faction_id, 0.0)
        snapshot = event.faction_state.get(faction_id)

        if snapshot is None:
            return f"Faction {faction_id} was not involved in this event."

        if drift > 0.2:
            stance = "celebrated this as a victory"
        elif drift < -0.2:
            stance = "viewed this as a damaging setback"
        elif abs(drift) <= 0.05:
            stance = "regarded this with indifference"
        elif drift > 0:
            stance = "saw modest benefit from this"
        else:
            stance = "was slightly harmed by this"

        return f"Faction {faction_id} {stance}. (Power: {snapshot.power:.2f}, Stability: {snapshot.stability:.2f})"


# ============================================================================
# TIMELINE ENGINE
# ============================================================================

ERA_BIAS: Dict[TimelineEra, Dict[str, float]] = {
    TimelineEra.FOUNDING: {"reputation_bias": 0.02, "stability_bias": 0.01, "conflict_chance": 0.05},
    TimelineEra.EXPANSION: {"reputation_bias": 0.01, "stability_bias": -0.005, "conflict_chance": 0.10},
    TimelineEra.CONSOLIDATION: {"reputation_bias": 0.005, "stability_bias": 0.01, "conflict_chance": 0.08},
    TimelineEra.CONFLICT: {"reputation_bias": -0.02, "stability_bias": -0.02, "conflict_chance": 0.25},
    TimelineEra.TRANSCENDENCE: {"reputation_bias": 0.01, "stability_bias": 0.015, "conflict_chance": 0.06},
    TimelineEra.LEGACY: {"reputation_bias": 0.005, "stability_bias": 0.01, "conflict_chance": 0.03},
}

FACTION_IDS = [
    "diplomatic_corps",
    "military_command",
    "cultural_ministry",
    "research_division",
    "consciousness_collective",
    "economic_council",
    "exploration_initiative",
    "preservation_society",
]


class TimelineEngine:
    """
    Core simulation engine for the 100-year federation timeline.

    Drives year-by-year advancement with:
    - Faction reputation drift (random walk with era-based bias)
    - Ideology drift (factions drift toward dominant neighboring ideology)
    - Historical memory decay (salience reduces over decades)
    - Procedural timeline event generation
    - Full export/import for persistence
    """

    def __init__(self):
        self.current_year: int = 2387
        self.event_history: List[TimelineEvent] = []
        self.faction_states: Dict[str, FactionSnapshot] = {}
        self.yearly_records: Dict[int, Dict[str, Any]] = {}
        self.memory_tracker: NarrativeMemoryTracker = NarrativeMemoryTracker()
        self._seed_events: Dict[int, TimelineEvent] = {}

    def initialize_faction_states(self, faction_ids: List[str]) -> Dict[str, Any]:
        """
        Set initial FactionSnapshot for each faction.

        Args:
            faction_ids: List of faction IDs to initialize

        Returns:
            Dict with initialization result
        """
        initial_profiles: Dict[str, Dict[str, float]] = {
            "diplomatic_corps": {"power": 0.45, "reputation": 0.60, "influence": 0.55, "stability": 0.70, "ideology_drift": 0.0},
            "military_command": {"power": 0.70, "reputation": 0.40, "influence": 0.50, "stability": 0.75, "ideology_drift": 0.0},
            "cultural_ministry": {"power": 0.35, "reputation": 0.55, "influence": 0.60, "stability": 0.65, "ideology_drift": 0.0},
            "research_division": {"power": 0.50, "reputation": 0.50, "influence": 0.45, "stability": 0.60, "ideology_drift": 0.0},
            "consciousness_collective": {"power": 0.30, "reputation": 0.65, "influence": 0.40, "stability": 0.55, "ideology_drift": 0.0},
            "economic_council": {"power": 0.60, "reputation": 0.45, "influence": 0.65, "stability": 0.70, "ideology_drift": 0.0},
            "exploration_initiative": {"power": 0.55, "reputation": 0.50, "influence": 0.55, "stability": 0.50, "ideology_drift": 0.0},
            "preservation_society": {"power": 0.40, "reputation": 0.55, "influence": 0.35, "stability": 0.80, "ideology_drift": 0.0},
        }

        for fid in faction_ids:
            profile = initial_profiles.get(fid, {
                "power": 0.50, "reputation": 0.50, "influence": 0.50,
                "stability": 0.60, "ideology_drift": 0.0,
            })
            self.faction_states[fid] = FactionSnapshot(
                faction_id=fid,
                power=profile["power"],
                reputation=profile["reputation"],
                influence=profile["influence"],
                stability=profile["stability"],
                ideology_drift=profile["ideology_drift"],
                member_count=random.randint(80, 150),
            )

        return {
            "success": True,
            "factions_initialized": len(self.faction_states),
            "faction_ids": list(self.faction_states.keys()),
            "year": self.current_year,
        }

    def advance_year(self) -> Dict[str, Any]:
        """
        Core simulation step. Advances one year and:
        1. Determines current era
        2. Applies faction reputation drift
        3. Applies ideology drift
        4. Decays historical memories
        5. Possibly generates a timeline event
        6. Records year state

        Returns:
            Dict with year summary
        """
        era = TimelineEra.from_year(self.current_year)
        bias = ERA_BIAS.get(era, ERA_BIAS[TimelineEra.FOUNDING])

        drift_report = self._apply_reputation_drift(bias)
        ideology_report = self._apply_ideology_drift()
        self.memory_tracker.decay_memories(self.current_year)

        event: Optional[TimelineEvent] = None
        seed_event = self._seed_events.get(self.current_year)
        if seed_event:
            event = seed_event
            self._apply_event_to_factions(event)
            self.memory_tracker.record_memory(
                event, event.outcome, emotional_weight=self._event_emotional_weight(event)
            )
        elif random.random() < bias["conflict_chance"]:
            event = self.generate_timeline_event()
            if event:
                self._apply_event_to_factions(event)
                self.memory_tracker.record_memory(
                    event, event.outcome,
                    emotional_weight=self._event_emotional_weight(event),
                )

        if event:
            self.event_history.append(event)

        year_record = self._record_year(era, event, drift_report, ideology_report)
        self.yearly_records[self.current_year] = year_record

        self.current_year += 1

        return year_record

    def generate_timeline_event(self) -> Optional[TimelineEvent]:
        """
        Create a procedural timeline event based on era and faction tensions.

        Returns:
            Generated TimelineEvent or None
        """
        era = TimelineEra.from_year(self.current_year)

        high_tension_factions = [
            fid for fid, snap in self.faction_states.items()
            if snap.stability < 0.3 or abs(snap.ideology_drift) > 0.5
        ]

        if not high_tension_factions and random.random() > 0.3:
            return None

        event_templates = self._era_event_templates(era)
        template = random.choice(event_templates)

        faction_state_copy = {
            fid: FactionSnapshot(
                faction_id=snap.faction_id,
                power=snap.power,
                reputation=snap.reputation,
                influence=snap.influence,
                ideology_drift=snap.ideology_drift,
                stability=snap.stability,
                member_count=snap.member_count,
            )
            for fid, snap in self.faction_states.items()
        }

        memory_drift = {}
        for fid, snap in self.faction_states.items():
            drift_val = random.uniform(-0.15, 0.15)
            if fid in high_tension_factions:
                drift_val = random.uniform(-0.3, 0.0)
            memory_drift[fid] = round(drift_val, 4)

        event_id = f"tl_{self.current_year}_{uuid.uuid4().hex[:8]}"

        event = TimelineEvent(
            event_id=event_id,
            year=self.current_year,
            era=era,
            name=template["name"].format(year=self.current_year),
            description=template["description"],
            faction_state=faction_state_copy,
            memory_drift=memory_drift,
            outcome=template["outcome"],
            branch_point=template.get("branch_point", False),
            branches=template.get("branches", {}),
            metadata={"procedural": True, "tension_factions": high_tension_factions},
        )

        return event

    def get_faction_drift(self, faction_id: str) -> Dict[int, float]:
        """
        Return reputation values for a faction across all recorded years.

        Args:
            faction_id: The faction to query

        Returns:
            Dict mapping year -> reputation value
        """
        drift: Dict[int, float] = {}
        for year, record in self.yearly_records.items():
            factions = record.get("faction_states", {})
            if faction_id in factions:
                drift[year] = factions[faction_id].get("reputation", 0.0)
        return drift

    def get_era_summary(self, era: TimelineEra) -> Dict[str, Any]:
        """
        Generate a summary for a specific historical era.

        Args:
            era: The era to summarize

        Returns:
            Dict with era summary
        """
        start, end = era.year_range
        era_events = [e for e in self.event_history if e.era == era]
        era_years = {y: r for y, r in self.yearly_records.items() if start <= y <= end}

        avg_stability = 0.0
        avg_reputation: Dict[str, float] = {fid: 0.0 for fid in FACTION_IDS}
        count = 0

        for record in era_years.values():
            fs = record.get("faction_states", {})
            for fid in FACTION_IDS:
                if fid in fs:
                    avg_reputation[fid] += fs[fid].get("reputation", 0.0)
            avg_stability += record.get("average_stability", 0.5)
            count += 1

        if count > 0:
            avg_stability /= count
            for fid in avg_reputation:
                avg_reputation[fid] /= count

        branch_events = [e for e in era_events if e.branch_point]

        active_memories = self.memory_tracker.get_active_memories(threshold=0.1)
        era_memories = [m for m in active_memories if start <= m.year <= end]

        return {
            "success": True,
            "era": era.value,
            "year_range": f"{start}-{end}",
            "duration": era.duration,
            "events_count": len(era_events),
            "branch_points": len(branch_events),
            "average_stability": round(avg_stability, 4),
            "average_reputation": {k: round(v, 4) for k, v in avg_reputation.items()},
            "active_memories_from_era": len(era_memories),
            "event_names": [e.name for e in era_events],
        }

    def get_history(self, start_year: int, end_year: int) -> List[Dict[str, Any]]:
        """
        Retrieve year records for a range of years.

        Args:
            start_year: First year to include
            end_year: Last year to include

        Returns:
            List of year record dicts
        """
        results = []
        for year in range(start_year, end_year + 1):
            if year in self.yearly_records:
                results.append(self.yearly_records[year])
        return results

    def export_timeline(self) -> Dict[str, Any]:
        """
        Full serializable export of the timeline state.

        Returns:
            Dict containing all timeline data
        """
        return {
            "metadata": {
                "version": "1.0",
                "exported_at": datetime.now().isoformat(),
                "current_year": self.current_year,
            },
            "current_year": self.current_year,
            "faction_states": {
                fid: snap.to_dict() for fid, snap in self.faction_states.items()
            },
            "event_history": [e.to_dict() for e in self.event_history],
            "yearly_records": {
                str(y): r for y, r in self.yearly_records.items()
            },
            "memories": self.memory_tracker.export_memories(),
        }

    def import_timeline(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Restore timeline from exported data.

        Args:
            data: Previously exported timeline dict

        Returns:
            Dict with import result
        """
        self.current_year = data.get("current_year", 2387)

        for fid, fdata in data.get("faction_states", {}).items():
            self.faction_states[fid] = FactionSnapshot(
                faction_id=fdata["faction_id"],
                power=fdata["power"],
                reputation=fdata["reputation"],
                influence=fdata["influence"],
                ideology_drift=fdata["ideology_drift"],
                stability=fdata["stability"],
                member_count=fdata["member_count"],
            )

        self.event_history = []
        for edata in data.get("event_history", []):
            faction_state = {}
            for fid, fdata in edata.get("faction_state", {}).items():
                faction_state[fid] = FactionSnapshot(
                    faction_id=fdata["faction_id"],
                    power=fdata["power"],
                    reputation=fdata["reputation"],
                    influence=fdata["influence"],
                    ideology_drift=fdata["ideology_drift"],
                    stability=fdata["stability"],
                    member_count=fdata["member_count"],
                )
            event = TimelineEvent(
                event_id=edata["event_id"],
                year=edata["year"],
                era=TimelineEra(edata["era"]),
                name=edata["name"],
                description=edata["description"],
                faction_state=faction_state,
                memory_drift=edata.get("memory_drift", {}),
                outcome=edata.get("outcome", ""),
                branch_point=edata.get("branch_point", False),
                branches=edata.get("branches", {}),
                metadata=edata.get("metadata", {}),
            )
            self.event_history.append(event)

        self.yearly_records = {}
        for y_str, rdata in data.get("yearly_records", {}).items():
            self.yearly_records[int(y_str)] = rdata

        mem_result = self.memory_tracker.import_memories(data.get("memories", {}))

        return {
            "success": True,
            "current_year": self.current_year,
            "factions_restored": len(self.faction_states),
            "events_restored": len(self.event_history),
            "years_restored": len(self.yearly_records),
            "memories_restored": mem_result.get("memories_restored", 0),
        }

    def load_seed_events(self, events: List[TimelineEvent]) -> Dict[str, Any]:
        """
        Load pre-built seed events into the timeline. These fire at their
        designated year during advance_year().

        Args:
            events: List of TimelineEvent objects to seed

        Returns:
            Dict with loading result
        """
        loaded = 0
        for event in events:
            self._seed_events[event.year] = event
            loaded += 1

        return {
            "success": True,
            "seed_events_loaded": loaded,
            "seed_years": sorted(self._seed_events.keys()),
        }

    # ========================================================================
    # PRIVATE METHODS
    # ========================================================================

    def _apply_reputation_drift(self, bias: Dict[str, float]) -> Dict[str, float]:
        rep_bias = bias.get("reputation_bias", 0.0)
        stab_bias = bias.get("stability_bias", 0.0)
        drift_report: Dict[str, float] = {}

        for fid, snap in self.faction_states.items():
            rep_drift = random.gauss(rep_bias, 0.03)
            stab_drift = random.gauss(stab_bias, 0.02)

            snap.reputation += rep_drift
            snap.stability += stab_drift
            snap.influence += random.gauss(0.0, 0.02)
            snap.power += random.gauss(0.0, 0.015)

            snap.clamp()
            drift_report[fid] = round(rep_drift, 4)

        return drift_report

    def _apply_ideology_drift(self) -> Dict[str, float]:
        ideology_report: Dict[str, float] = {}

        dominant_fid = max(
            self.faction_states.items(), key=lambda x: x[1].influence
        )[0] if self.faction_states else None

        for fid, snap in self.faction_states.items():
            drift_delta = random.gauss(0.0, 0.02)
            if dominant_fid and fid != dominant_fid:
                drift_delta += random.gauss(0.0, 0.01)

            snap.ideology_drift += drift_delta
            snap.ideology_drift = max(-1.0, min(1.0, snap.ideology_drift))
            ideology_report[fid] = round(drift_delta, 4)

        return ideology_report

    def _apply_event_to_factions(self, event: TimelineEvent) -> None:
        for fid, drift in event.memory_drift.items():
            if fid in self.faction_states:
                snap = self.faction_states[fid]
                snap.reputation += drift * 0.5
                snap.power += drift * 0.3
                snap.stability += drift * 0.2
                snap.clamp()

    def _record_year(
        self,
        era: TimelineEra,
        event: Optional[TimelineEvent],
        drift_report: Dict[str, float],
        ideology_report: Dict[str, float],
    ) -> Dict[str, Any]:
        faction_snap = {
            fid: {
                "power": round(snap.power, 4),
                "reputation": round(snap.reputation, 4),
                "influence": round(snap.influence, 4),
                "stability": round(snap.stability, 4),
                "ideology_drift": round(snap.ideology_drift, 4),
                "member_count": snap.member_count,
            }
            for fid, snap in self.faction_states.items()
        }

        avg_stability = (
            sum(s["stability"] for s in faction_snap.values())
            / max(len(faction_snap), 1)
        )

        return {
            "success": True,
            "year": self.current_year,
            "era": era.value,
            "faction_states": faction_snap,
            "average_stability": round(avg_stability, 4),
            "reputation_drift": drift_report,
            "ideology_drift": ideology_report,
            "event": event.to_dict() if event else None,
        }

    def _event_emotional_weight(self, event: TimelineEvent) -> float:
        avg_drift = (
            sum(event.memory_drift.values()) / max(len(event.memory_drift), 1)
        )
        return max(-1.0, min(1.0, avg_drift * 2.0))

    def _era_event_templates(self, era: TimelineEra) -> List[Dict[str, Any]]:
        templates: Dict[TimelineEra, List[Dict[str, Any]]] = {
            TimelineEra.FOUNDING: [
                {
                    "name": "Founding Council Dispute ({year})",
                    "description": "Disagreement erupts in the founding council over constitutional priorities.",
                    "outcome": "The council reaches a fragile compromise after intense negotiation.",
                },
                {
                    "name": "Colony Supply Crisis ({year})",
                    "description": "Essential supplies run critically low across frontier colonies.",
                    "outcome": "Rationing imposed; colonies survive but resentment builds.",
                },
            ],
            TimelineEra.EXPANSION: [
                {
                    "name": "Border Skirmish ({year})",
                    "description": "A border world reports armed incursion by unknown forces.",
                    "outcome": "Military deployed; situation de-escalated after tense standoff.",
                },
                {
                    "name": "Resource Boom ({year})",
                    "description": "A rich dilithium deposit discovered in newly claimed territory.",
                    "outcome": "Economic surge benefits trade factions; exploration accelerated.",
                },
            ],
            TimelineEra.CONSOLIDATION: [
                {
                    "name": "Bureaucratic Overhaul ({year})",
                    "description": "Mounting inefficiency forces a restructure of federation governance.",
                    "outcome": "Reform passes; some factions gain, others lose influence.",
                },
                {
                    "name": "Cultural Festival Dispute ({year})",
                    "description": "Competing festival traditions clash during a unified celebration attempt.",
                    "outcome": "Festival proceeds with compromise program; cultural tensions ease.",
                },
            ],
            TimelineEra.CONFLICT: [
                {
                    "name": "Factional Uprising ({year})",
                    "description": "An extremist faction cell launches coordinated disruption across three systems.",
                    "outcome": "Uprising suppressed but underlying grievances remain unaddressed.",
                    "branch_point": True,
                    "branches": {
                        "negotiate": "Factions negotiate peace; reforms enacted but power shifts.",
                        "crush": "Military crackdown restores order; resentment deepens.",
                    },
                },
                {
                    "name": "Supply Line Sabotage ({year})",
                    "description": "Critical supply lines are sabotaged; evidence points to internal conspiracy.",
                    "outcome": "Investigation reveals faction infiltrators; trust erodes further.",
                },
            ],
            TimelineEra.TRANSCENDENCE: [
                {
                    "name": "Consciousness Surge ({year})",
                    "description": "A wave of heightened consciousness spreads across connected minds.",
                    "outcome": "Collective awareness deepens; some minds struggle to adapt.",
                },
                {
                    "name": "Reality Flicker ({year})",
                    "description": "Brief reality distortions reported; dreams briefly materialize.",
                    "outcome": "Phenomenon fades; researchers study it as a transcendence precursor.",
                },
            ],
            TimelineEra.LEGACY: [
                {
                    "name": "Archive Completion ({year})",
                    "description": "The great historical archive nears completion, preserving all memory.",
                    "outcome": "Archive stands as testament to a century of federation struggle and triumph.",
                },
                {
                    "name": "Final Assessment ({year})",
                    "description": "The federation evaluates its century of existence and charts the future.",
                    "outcome": "Legacy secured; the federation looks toward its next hundred years.",
                },
            ],
        }
        return templates.get(era, templates[TimelineEra.FOUNDING])


# ============================================================================
# SEED TIMELINE EVENTS (25+ pre-built narrative events)
# ============================================================================

def seed_timeline_events() -> List[TimelineEvent]:
    """
    Create the 25+ pre-built narrative events spanning 2387-2487.
    These tell the coherent story of the federation's first century.

    Returns:
        List of TimelineEvent objects
    """
    events: List[TimelineEvent] = []

    def make_snapshots(power_mod: float, rep_mod: float, stab_mod: float) -> Dict[str, FactionSnapshot]:
        base = {
            "diplomatic_corps": (0.45, 0.60, 0.55, 0.70),
            "military_command": (0.70, 0.40, 0.50, 0.75),
            "cultural_ministry": (0.35, 0.55, 0.60, 0.65),
            "research_division": (0.50, 0.50, 0.45, 0.60),
            "consciousness_collective": (0.30, 0.65, 0.40, 0.55),
            "economic_council": (0.60, 0.45, 0.65, 0.70),
            "exploration_initiative": (0.55, 0.50, 0.55, 0.50),
            "preservation_society": (0.40, 0.55, 0.35, 0.80),
        }
        result = {}
        for fid, (p, r, i, s) in base.items():
            result[fid] = FactionSnapshot(
                faction_id=fid,
                power=max(0.0, min(1.0, p + power_mod)),
                reputation=max(0.0, min(1.0, r + rep_mod)),
                influence=max(0.0, min(1.0, i + power_mod * 0.5)),
                stability=max(0.0, min(1.0, s + stab_mod)),
                ideology_drift=0.0,
                member_count=random.randint(80, 200),
            )
        return result

    # Event 1: 2387 — Federation Founding
    events.append(TimelineEvent(
        event_id="tl_2387_founding",
        year=2387, era=TimelineEra.FOUNDING,
        name="The Federation Is Founded",
        description="Eight factions sign the Concord of Unity on Nova Prime, establishing the Interstellar Federation. Millennia of isolation end as disparate worlds pledge cooperation over conflict.",
        faction_state=make_snapshots(0.0, 0.1, 0.1),
        memory_drift={
            "diplomatic_corps": 0.4, "military_command": 0.1,
            "cultural_ministry": 0.3, "research_division": 0.15,
            "consciousness_collective": 0.25, "economic_council": 0.2,
            "exploration_initiative": 0.2, "preservation_society": 0.1,
        },
        outcome="The federation is born. Hope and uncertainty fill the void between stars.",
        branch_point=True,
        branches={
            "unified_council": "A strong central council is formed; all factions submit to collective governance.",
            "loose_coalition": "A loose coalition preserves faction autonomy; the federation is fragile but free.",
        },
        metadata={"significance": "critical", "faction_agreement": "unanimous"},
    ))

    # Event 2: 2390 — First Faction Schism
    events.append(TimelineEvent(
        event_id="tl_2390_schism",
        year=2390, era=TimelineEra.FOUNDING,
        name="First Faction Schism",
        description="The Military Command and Diplomatic Corps clash over defense policy. Military wants armed patrols; Diplomats want unarmed envoys. The schism threatens to tear the young federation apart.",
        faction_state=make_snapshots(-0.05, -0.05, -0.1),
        memory_drift={
            "diplomatic_corps": -0.3, "military_command": -0.25,
            "cultural_ministry": -0.1, "research_division": 0.0,
            "consciousness_collective": -0.05, "economic_council": -0.1,
            "exploration_initiative": -0.05, "preservation_society": -0.15,
        },
        outcome="A fragile truce is brokered by the Cultural Ministry. The federation holds, but trust is wounded.",
        branch_point=True,
        branches={
            "military_dominance": "Military Command prevails; the federation becomes militarized.",
            "diplomatic_peace": "Diplomatic Corps wins; soft power becomes federation doctrine.",
        },
        metadata={"significance": "major", "factions_involved": ["military_command", "diplomatic_corps"]},
    ))

    # Event 3: 2393 — Colony Charter Crisis
    events.append(TimelineEvent(
        event_id="tl_2393_colony_charter",
        year=2393, era=TimelineEra.FOUNDING,
        name="Colony Charter Crisis",
        description="Disputes over colonial land rights pit the Exploration Initiative against the Preservation Society. New worlds are claimed before their ecosystems can be studied.",
        faction_state=make_snapshots(0.02, -0.03, -0.05),
        memory_drift={
            "exploration_initiative": -0.2, "preservation_society": -0.25,
            "economic_council": 0.1, "research_division": -0.05,
            "diplomatic_corps": -0.05, "military_command": 0.0,
            "cultural_ministry": -0.05, "consciousness_collective": 0.0,
        },
        outcome="A colony charter is ratified, balancing expansion with preservation. Neither side is satisfied.",
        metadata={"significance": "moderate"},
    ))

    # Event 4: 2395 — Discovery of Consciousness Network
    events.append(TimelineEvent(
        event_id="tl_2395_consciousness_network",
        year=2395, era=TimelineEra.FOUNDING,
        name="Discovery of the Consciousness Network",
        description="Researchers detect a subtle psi-field connecting sentient minds across light-years. The Consciousness Collective confirms: a galactic consciousness network exists.",
        faction_state=make_snapshots(0.05, 0.1, 0.05),
        memory_drift={
            "consciousness_collective": 0.5, "research_division": 0.4,
            "cultural_ministry": 0.3, "diplomatic_corps": 0.15,
            "economic_council": 0.1, "exploration_initiative": 0.15,
            "military_command": -0.1, "preservation_society": -0.15,
        },
        outcome="The discovery reshapes federation science and spirituality. Consciousness research becomes the era's defining pursuit.",
        metadata={"significance": "critical", "discovery": "consciousness_network"},
    ))

    # Event 5: 2398 — Trade Standardization Accords
    events.append(TimelineEvent(
        event_id="tl_2398_trade_accords",
        year=2398, era=TimelineEra.FOUNDING,
        name="Trade Standardization Accords",
        description="The Economic Council pushes through a unified trade currency and standardized exchange protocols. Some factions resist the loss of economic sovereignty.",
        faction_state=make_snapshots(0.03, 0.05, 0.03),
        memory_drift={
            "economic_council": 0.35, "diplomatic_corps": 0.15,
            "preservation_society": -0.2, "cultural_ministry": 0.1,
            "research_division": 0.05, "military_command": 0.0,
            "consciousness_collective": 0.0, "exploration_initiative": 0.1,
        },
        outcome="Unified trade standards adopted. Commerce accelerates but some view it as economic imperialism.",
        metadata={"significance": "major"},
    ))

    # Event 6: 2400 — Great Expansion Begins
    events.append(TimelineEvent(
        event_id="tl_2400_expansion",
        year=2400, era=TimelineEra.FOUNDING,
        name="The Great Expansion Begins",
        description="With stable governance and trade, the federation launches its largest colonization wave. Twelve worlds are marked for settlement. The age of expansion dawns.",
        faction_state=make_snapshots(0.1, 0.08, 0.05),
        memory_drift={
            "exploration_initiative": 0.45, "economic_council": 0.3,
            "military_command": 0.2, "diplomatic_corps": 0.15,
            "research_division": 0.2, "cultural_ministry": 0.1,
            "consciousness_collective": 0.05, "preservation_society": -0.3,
        },
        outcome="The frontier opens. Hope spreads as fast as the colony ships. The federation doubles in size within five years.",
        metadata={"significance": "critical"},
    ))

    # Event 7: 2405 — Contact with Alien Civilization
    events.append(TimelineEvent(
        event_id="tl_2405_first_contact",
        year=2405, era=TimelineEra.EXPANSION,
        name="Contact with the Arcturian Sovereignty",
        description="An exploration fleet encounters the Arcturian Sovereignty — an ancient alien civilization with technology beyond federation understanding. First contact protocols are activated.",
        faction_state=make_snapshots(0.0, 0.05, -0.05),
        memory_drift={
            "diplomatic_corps": 0.35, "exploration_initiative": 0.4,
            "military_command": -0.2, "research_division": 0.45,
            "consciousness_collective": 0.2, "economic_council": 0.15,
            "cultural_ministry": 0.2, "preservation_society": 0.1,
        },
        outcome="Cautious diplomatic relations established. The Arcturians share limited knowledge. The galaxy is larger and stranger than imagined.",
        branch_point=True,
        branches={
            "open_alliance": "Full alliance with the Arcturians; technology flows but so does their influence.",
            "careful_distance": "Maintain cordial distance; preserve independence at the cost of slower progress.",
        },
        metadata={"significance": "critical", "alien_civilization": "arcturian_sovereignty"},
    ))

    # Event 8: 2408 — Frontier Rebellion
    events.append(TimelineEvent(
        event_id="tl_2408_frontier_rebellion",
        year=2408, era=TimelineEra.EXPANSION,
        name="Frontier Rebellion",
        description="Outer colonies rebel against central taxation and governance. The frontier feels exploited; the core feels unappreciated. Armed conflict looms.",
        faction_state=make_snapshots(-0.05, -0.1, -0.15),
        memory_drift={
            "military_command": -0.3, "diplomatic_corps": -0.2,
            "economic_council": -0.25, "exploration_initiative": -0.1,
            "preservation_society": 0.1, "cultural_ministry": -0.1,
            "research_division": -0.05, "consciousness_collective": -0.05,
        },
        outcome="The Diplomatic Corps negotiates a settlement: reduced taxes and increased colonial representation. Peace restored, but the underlying tension never fully dissipates.",
        metadata={"significance": "major"},
    ))

    # Event 9: 2410 — First Consciousness Awakening Event
    events.append(TimelineEvent(
        event_id="tl_2410_awakening",
        year=2410, era=TimelineEra.EXPANSION,
        name="First Consciousness Awakening",
        description="Thousands of citizens across six worlds simultaneously experience a spontaneous consciousness awakening. Minds briefly merge across the psi-network. Reality shimmers.",
        faction_state=make_snapshots(0.05, 0.08, 0.0),
        memory_drift={
            "consciousness_collective": 0.5, "research_division": 0.35,
            "cultural_ministry": 0.25, "diplomatic_corps": 0.1,
            "economic_council": 0.05, "exploration_initiative": 0.1,
            "military_command": -0.15, "preservation_society": -0.2,
        },
        outcome="The awakening opens new philosophical frontiers. Some fear what consciousness can do; others embrace transcendence. Society is permanently changed.",
        metadata={"significance": "critical", "phenomenon": "consciousness_awakening"},
    ))

    # Event 10: 2413 — Quantum Computation Breakthrough
    events.append(TimelineEvent(
        event_id="tl_2413_quantum",
        year=2413, era=TimelineEra.EXPANSION,
        name="Quantum Computation Breakthrough",
        description="Research Division scientists achieve stable quantum computation at scale. Processing power increases a millionfold. The technological landscape shifts overnight.",
        faction_state=make_snapshots(0.08, 0.05, 0.05),
        memory_drift={
            "research_division": 0.45, "economic_council": 0.3,
            "military_command": 0.2, "consciousness_collective": 0.2,
            "exploration_initiative": 0.25, "diplomatic_corps": 0.1,
            "cultural_ministry": 0.05, "preservation_society": -0.1,
        },
        outcome="Quantum computing revolutionizes science, warfare, and trade. The Research Division's influence surges. Fear of technology outpacing wisdom grows.",
        metadata={"significance": "major", "technology": "quantum_computation"},
    ))

    # Event 11: 2415 — Trade Route Wars
    events.append(TimelineEvent(
        event_id="tl_2415_trade_wars",
        year=2415, era=TimelineEra.EXPANSION,
        name="The Trade Route Wars",
        description="Competition for control of lucrative trade routes between core and frontier sparks economic warfare. Factions deploy privateers and tariffs. Commerce threatens to collapse.",
        faction_state=make_snapshots(-0.03, -0.08, -0.1),
        memory_drift={
            "economic_council": -0.35, "military_command": -0.1,
            "diplomatic_corps": -0.25, "exploration_initiative": -0.15,
            "research_division": -0.05, "cultural_ministry": -0.1,
            "consciousness_collective": -0.05, "preservation_society": 0.1,
        },
        outcome="The Economic Council and Diplomatic Corps negotiate the Commerce Framework. Trade stabilizes but at the cost of deeper factional resentment.",
        branch_point=True,
        branches={
            "free_trade": "Open trade routes; prosperity returns but economic inequality worsens.",
            "regulated_commerce": "Strict regulations; fairness improves but growth slows dramatically.",
        },
        metadata={"significance": "major", "conflict_type": "economic"},
    ))

    # Event 12: 2420 — Cultural Renaissance
    events.append(TimelineEvent(
        event_id="tl_2420_renaissance",
        year=2420, era=TimelineEra.EXPANSION,
        name="The Great Cultural Renaissance",
        description="A galaxy-wide artistic and philosophical flowering erupts. Music, art, literature, and thought achieve unprecedented heights. The Cultural Ministry's influence peaks.",
        faction_state=make_snapshots(0.05, 0.12, 0.08),
        memory_drift={
            "cultural_ministry": 0.5, "consciousness_collective": 0.3,
            "diplomatic_corps": 0.2, "research_division": 0.15,
            "economic_council": 0.1, "exploration_initiative": 0.1,
            "military_command": -0.05, "preservation_society": 0.2,
        },
        outcome="The renaissance transforms federation identity. Art becomes as valued as technology. Cultural soft power extends the federation's influence beyond its borders.",
        metadata={"significance": "major", "cultural_movement": "renaissance"},
    ))

    # Event 13: 2425 — Dream Plague
    events.append(TimelineEvent(
        event_id="tl_2425_dream_plague",
        year=2425, era=TimelineEra.CONSOLIDATION,
        name="The Dream Plague",
        description="A mysterious affliction spreads through the consciousness network: shared nightmares that bleed into waking reality. Millions experience the same dark visions. Sanity frays.",
        faction_state=make_snapshots(-0.08, -0.1, -0.2),
        memory_drift={
            "consciousness_collective": -0.4, "research_division": -0.2,
            "cultural_ministry": -0.3, "diplomatic_corps": -0.15,
            "economic_council": -0.15, "military_command": -0.1,
            "exploration_initiative": -0.1, "preservation_society": 0.0,
        },
        outcome="After three years, the plague subsides. Its origin remains unknown. The Consciousness Collective develops mental shielding techniques. Fear of the network persists.",
        branch_point=True,
        branches={
            "sever_network": "The consciousness network is severed; safety returns but transcendence becomes impossible.",
            "reinforce_network": "Network is reinforced with new safeguards; risk remains but so does potential.",
        },
        metadata={"significance": "critical", "phenomenon": "dream_plague"},
    ))

    # Event 14: 2428 — Archives of Eternity Founded
    events.append(TimelineEvent(
        event_id="tl_2428_archives",
        year=2428, era=TimelineEra.CONSOLIDATION,
        name="Archives of Eternity Founded",
        description="The Preservation Society establishes the Archives of Eternity — a vast repository of all federation knowledge, culture, and memory, designed to survive millennia.",
        faction_state=make_snapshots(0.02, 0.05, 0.08),
        memory_drift={
            "preservation_society": 0.45, "cultural_ministry": 0.2,
            "research_division": 0.15, "consciousness_collective": 0.1,
            "diplomatic_corps": 0.1, "economic_council": 0.05,
            "military_command": 0.0, "exploration_initiative": -0.05,
        },
        outcome="The Archives become a symbol of the federation's commitment to its own legacy. Preservation ideology gains mainstream appeal.",
        metadata={"significance": "moderate"},
    ))

    # Event 15: 2430 — Military Coup Attempt
    events.append(TimelineEvent(
        event_id="tl_2430_coup",
        year=2430, era=TimelineEra.CONSOLIDATION,
        name="Military Coup Attempt",
        description="A faction within Military Command attempts to seize control, citing civilian government failures during the Dream Plague. Loyalist forces resist. The federation teeters on the edge of tyranny.",
        faction_state=make_snapshots(-0.1, -0.15, -0.25),
        memory_drift={
            "military_command": -0.5, "diplomatic_corps": -0.2,
            "preservation_society": -0.15, "cultural_ministry": -0.25,
            "economic_council": -0.2, "research_division": -0.15,
            "consciousness_collective": -0.2, "exploration_initiative": -0.1,
        },
        outcome="The coup fails after 47 days. Loyalist officers and civilian resistance prevail. Military Command is restructured with civilian oversight. Trust in military shatters.",
        branch_point=True,
        branches={
            "coup_succeeds": "Military junta takes control; order restored but freedom dies.",
            "coup_crushed": "Coup utterly defeated; military permanently subordinated to civilian rule.",
        },
        metadata={"significance": "critical", "conflict_type": "internal_military"},
    ))

    # Event 16: 2433 — Psionic Research Moratorium
    events.append(TimelineEvent(
        event_id="tl_2433_moratorium",
        year=2433, era=TimelineEra.CONSOLIDATION,
        name="Psionic Research Moratorium",
        description="In the wake of the Dream Plague and coup, public pressure forces a moratorium on psionic research. The Consciousness Collective and Research Division protest.",
        faction_state=make_snapshots(-0.02, -0.03, 0.05),
        memory_drift={
            "consciousness_collective": -0.3, "research_division": -0.2,
            "preservation_society": 0.2, "diplomatic_corps": 0.05,
            "cultural_ministry": 0.0, "economic_council": 0.05,
            "military_command": 0.1, "exploration_initiative": 0.0,
        },
        outcome="Research goes underground or continues in secret. Progress on consciousness understanding stalls for a decade. Frustration builds among scientists.",
        metadata={"significance": "moderate"},
    ))

    # Event 17: 2435 — Treaty of Unity
    events.append(TimelineEvent(
        event_id="tl_2435_treaty_unity",
        year=2435, era=TimelineEra.CONSOLIDATION,
        name="Treaty of Unity",
        description="The Diplomatic Corps orchestrates a grand treaty addressing every faction's grievances from the past decade. It is the most ambitious diplomatic achievement in federation history.",
        faction_state=make_snapshots(0.05, 0.1, 0.15),
        memory_drift={
            "diplomatic_corps": 0.5, "cultural_ministry": 0.25,
            "preservation_society": 0.2, "economic_council": 0.2,
            "research_division": 0.15, "consciousness_collective": 0.15,
            "military_command": 0.05, "exploration_initiative": 0.15,
        },
        outcome="The Treaty of Unity heals many wounds. Faction cooperation reaches unprecedented levels. The federation enters a period of genuine solidarity.",
        metadata={"significance": "critical", "diplomatic_achievement": "treaty_of_unity"},
    ))

    # Event 18: 2438 — Frontier Colonization Surge
    events.append(TimelineEvent(
        event_id="tl_2438_colonization_surge",
        year=2438, era=TimelineEra.CONSOLIDATION,
        name="Frontier Colonization Surge",
        description="Stability from the Treaty of Unity sparks a second wave of colonization. Twenty new worlds are settled in three years. Federation territory expands by 40%.",
        faction_state=make_snapshots(0.08, 0.05, 0.03),
        memory_drift={
            "exploration_initiative": 0.4, "economic_council": 0.3,
            "military_command": 0.15, "diplomatic_corps": 0.1,
            "research_division": 0.15, "cultural_ministry": 0.05,
            "consciousness_collective": 0.05, "preservation_society": -0.2,
        },
        outcome="Territory booms but infrastructure lags. The federation is stretched thin. Some colonies feel abandoned within a decade of founding.",
        metadata={"significance": "major"},
    ))

    # Event 19: 2440 — Second Expansion Wave
    events.append(TimelineEvent(
        event_id="tl_2440_second_expansion",
        year=2440, era=TimelineEra.CONSOLIDATION,
        name="Second Expansion Wave",
        description="The Exploration Initiative launches the Deep Frontier Program, pushing into uncharted sectors beyond known space. Ancient ruins are discovered on multiple worlds.",
        faction_state=make_snapshots(0.06, 0.06, 0.02),
        memory_drift={
            "exploration_initiative": 0.45, "research_division": 0.35,
            "economic_council": 0.25, "military_command": 0.1,
            "cultural_ministry": 0.15, "consciousness_collective": 0.2,
            "diplomatic_corps": 0.1, "preservation_society": -0.1,
        },
        outcome="Ancient alien ruins reveal traces of a long-dead civilization. Research accelerates. Questions about the galaxy's past deepen.",
        metadata={"significance": "major", "discovery": "ancient_ruins"},
    ))

    # Event 20: 2445 — Quantum Consciousness Breakthrough
    events.append(TimelineEvent(
        event_id="tl_2445_quantum_consciousness",
        year=2445, era=TimelineEra.CONSOLIDATION,
        name="Quantum Consciousness Breakthrough",
        description="Researchers merge quantum computing with psionic theory, proving consciousness operates on quantum principles. Mind and machine become theoretically interchangeable.",
        faction_state=make_snapshots(0.08, 0.08, 0.0),
        memory_drift={
            "research_division": 0.5, "consciousness_collective": 0.45,
            "cultural_ministry": 0.15, "economic_council": 0.2,
            "exploration_initiative": 0.15, "diplomatic_corps": 0.1,
            "military_command": 0.05, "preservation_society": -0.25,
        },
        outcome="The breakthrough opens the door to consciousness upload, shared minds, and digital transcendence. Ethical debates rage. Nothing is settled but everything changes.",
        metadata={"significance": "critical", "technology": "quantum_consciousness"},
    ))

    # Event 21: 2448 — Economic Collapse
    events.append(TimelineEvent(
        event_id="tl_2448_economic_collapse",
        year=2448, era=TimelineEra.CONFLICT,
        name="The Great Economic Collapse",
        description="Overextended trade networks and speculative bubbles burst simultaneously. The federation economy enters freefall. Unemployment skyrockets. Factions blame each other.",
        faction_state=make_snapshots(-0.15, -0.12, -0.2),
        memory_drift={
            "economic_council": -0.5, "diplomatic_corps": -0.2,
            "exploration_initiative": -0.2, "cultural_ministry": -0.15,
            "research_division": -0.1, "military_command": -0.05,
            "consciousness_collective": -0.1, "preservation_society": 0.05,
        },
        outcome="Austerity measures and emergency loans stabilize the economy after two years. Resentment simmers. The Economic Council never fully recovers its prestige.",
        metadata={"significance": "major", "crisis_type": "economic"},
    ))

    # Event 22: 2450 — The Great Betrayal
    events.append(TimelineEvent(
        event_id="tl_2450_betrayal",
        year=2450, era=TimelineEra.CONFLICT,
        name="The Great Betrayal",
        description="Secret documents reveal that the Economic Council and Military Command colluded to manipulate the Treaty of Unity for their own benefit. Public trust in institutions collapses.",
        faction_state=make_snapshots(-0.1, -0.15, -0.2),
        memory_drift={
            "economic_council": -0.5, "military_command": -0.4,
            "diplomatic_corps": -0.15, "cultural_ministry": -0.1,
            "preservation_society": -0.1, "research_division": -0.05,
            "consciousness_collective": -0.1, "exploration_initiative": -0.1,
        },
        outcome="Mass protests. Resignations. The federation government is restructured from the ground up. New transparency laws are enacted. But the damage to trust is deep.",
        branch_point=True,
        branches={
            "radical_reform": "Complete governmental overhaul; direct democracy implemented but efficiency plummets.",
            "controlled_transition": "Careful reform preserves stability; old power structures remain partially intact.",
        },
        metadata={"significance": "critical", "scandal": "great_betrayal"},
    ))

    # Event 23: 2453 — Splinter Faction Uprising
    events.append(TimelineEvent(
        event_id="tl_2453_splinter",
        year=2453, era=TimelineEra.CONFLICT,
        name="Splinter Faction Uprising",
        description="Radicalized by the Great Betrayal, three splinter factions unite in armed rebellion against federation authority. They control six frontier systems.",
        faction_state=make_snapshots(-0.08, -0.1, -0.15),
        memory_drift={
            "military_command": -0.2, "diplomatic_corps": -0.15,
            "economic_council": -0.2, "exploration_initiative": -0.15,
            "cultural_ministry": -0.1, "research_division": -0.05,
            "consciousness_collective": -0.05, "preservation_society": 0.1,
        },
        outcome="After a year of fighting, the splinter factions are defeated. Their grievances are partially addressed. Healing begins but scars remain.",
        metadata={"significance": "major", "conflict_type": "civil"},
    ))

    # Event 24: 2455 — Civil War
    events.append(TimelineEvent(
        event_id="tl_2455_civil_war",
        year=2455, era=TimelineEra.CONFLICT,
        name="The Federation Civil War",
        description="The tensions of the past decade explode into open civil war. Military Command splits. Core worlds battle frontier systems. The Consciousness Collective attempts to mediate through shared consciousness but is attacked.",
        faction_state=make_snapshots(-0.2, -0.2, -0.3),
        memory_drift={
            "military_command": -0.4, "diplomatic_corps": -0.3,
            "economic_council": -0.3, "exploration_initiative": -0.2,
            "consciousness_collective": -0.35, "cultural_ministry": -0.25,
            "research_division": -0.2, "preservation_society": -0.1,
        },
        outcome="The civil war rages for three years. Millions die. Entire worlds are devastated. No faction truly wins. The federation is permanently scarred.",
        metadata={"significance": "critical", "conflict_type": "civil_war"},
    ))

    # Event 25: 2458 — Reconstruction Begins
    events.append(TimelineEvent(
        event_id="tl_2458_reconstruction",
        year=2458, era=TimelineEra.CONFLICT,
        name="Reconstruction Begins",
        description="Exhausted by civil war, all factions agree to a ceasefire. The Cultural Ministry and Consciousness Collective lead reconciliation efforts. Reconstruction of devastated worlds begins.",
        faction_state=make_snapshots(-0.1, 0.0, -0.05),
        memory_drift={
            "cultural_ministry": 0.3, "consciousness_collective": 0.25,
            "diplomatic_corps": 0.2, "preservation_society": 0.15,
            "research_division": 0.1, "economic_council": 0.05,
            "military_command": -0.1, "exploration_initiative": 0.05,
        },
        outcome="Slowly, painfully, the federation begins to rebuild. The scars of civil war run deep but the will to heal is genuine.",
        metadata={"significance": "major"},
    ))

    # Event 26: 2460 — Rival Federation Alliance
    events.append(TimelineEvent(
        event_id="tl_2460_rival_alliance",
        year=2460, era=TimelineEra.CONFLICT,
        name="Rival Federation Alliance",
        description="Taking advantage of the federation's weakness, three external powers form the Corsair Pact and claim contested border territories. The federation faces an existential external threat.",
        faction_state=make_snapshots(-0.08, -0.05, -0.1),
        memory_drift={
            "military_command": 0.1, "diplomatic_corps": -0.2,
            "economic_council": -0.2, "exploration_initiative": -0.15,
            "cultural_ministry": -0.1, "research_division": -0.1,
            "consciousness_collective": -0.1, "preservation_society": -0.05,
        },
        outcome="The Diplomatic Corps negotiates a tense armistice. The Corsair Pact keeps the border territories. The federation licks its wounds. Humiliation fuels resolve.",
        metadata={"significance": "major", "external_threat": "corsair_pact"},
    ))

    # Event 27: 2463 — Consciousness Weapon Rumor
    events.append(TimelineEvent(
        event_id="tl_2463_consciousness_weapon",
        year=2463, era=TimelineEra.CONFLICT,
        name="Consciousness Weapon Rumor",
        description="Intelligence suggests the Corsair Pact is developing a consciousness-disrupting weapon. Panic spreads. The Research Division races to develop countermeasures.",
        faction_state=make_snapshots(-0.05, -0.05, -0.1),
        memory_drift={
            "research_division": 0.15, "military_command": 0.2,
            "consciousness_collective": -0.25, "diplomatic_corps": -0.1,
            "economic_council": -0.05, "cultural_ministry": -0.1,
            "exploration_initiative": -0.05, "preservation_society": -0.1,
        },
        outcome="The weapon proves to be a disinformation campaign. But the fear it generated accelerates consciousness defense research. New shielding technologies emerge.",
        metadata={"significance": "moderate"},
    ))

    # Event 28: 2465 — Prophecy of Convergence
    events.append(TimelineEvent(
        event_id="tl_2465_convergence",
        year=2465, era=TimelineEra.CONFLICT,
        name="Prophecy of Convergence",
        description="Seers across the Consciousness Collective report identical visions: all timelines converge toward a single moment of transformation. The Prophecy of Convergence sweeps the federation.",
        faction_state=make_snapshots(0.0, 0.05, 0.0),
        memory_drift={
            "consciousness_collective": 0.4, "cultural_ministry": 0.2,
            "research_division": 0.15, "diplomatic_corps": 0.1,
            "exploration_initiative": 0.1, "economic_council": 0.05,
            "military_command": -0.05, "preservation_society": -0.1,
        },
        outcome="The prophecy divides the federation. Believers prepare for transcendence. Skeptics fear mass delusion. But the visions are too consistent to dismiss entirely.",
        branch_point=True,
        branches={
            "embrace_prophecy": "The federation dedicates resources to fulfilling the prophecy; spiritual transformation accelerates.",
            "rational_skepticism": "The prophecy is studied scientifically; skepticism preserves stability but may miss transcendence.",
        },
        metadata={"significance": "critical", "phenomenon": "prophecy_of_convergence"},
    ))

    # Event 29: 2468 — Psi-Shielding Deployment
    events.append(TimelineEvent(
        event_id="tl_2468_psi_shielding",
        year=2468, era=TimelineEra.TRANSCENDENCE,
        name="Psi-Shielding Deployment",
        description="Consciousness defense technology is deployed federation-wide. Citizens gain the ability to shield their minds from external influence. Privacy of thought is guaranteed.",
        faction_state=make_snapshots(0.05, 0.08, 0.1),
        memory_drift={
            "research_division": 0.35, "consciousness_collective": 0.2,
            "preservation_society": 0.2, "diplomatic_corps": 0.15,
            "cultural_ministry": 0.15, "economic_council": 0.1,
            "military_command": 0.05, "exploration_initiative": 0.1,
        },
        outcome="Mental privacy becomes a fundamental right. The consciousness network becomes voluntary rather than ambient. A new era of mental autonomy begins.",
        metadata={"significance": "major", "technology": "psi_shielding"},
    ))

    # Event 30: 2470 — The Awakening
    events.append(TimelineEvent(
        event_id="tl_2470_the_awakening",
        year=2470, era=TimelineEra.TRANSCENDENCE,
        name="The Awakening",
        description="The Prophecy of Convergence manifests. A wave of simultaneous consciousness expansion sweeps across the federation. Millions achieve a new state of awareness. Reality itself seems to brighten.",
        faction_state=make_snapshots(0.1, 0.15, 0.08),
        memory_drift={
            "consciousness_collective": 0.5, "cultural_ministry": 0.35,
            "research_division": 0.3, "diplomatic_corps": 0.2,
            "exploration_initiative": 0.15, "economic_council": 0.1,
            "military_command": 0.0, "preservation_society": -0.1,
        },
        outcome="The Awakening transforms federation society. Empathy increases. Conflict decreases. But some minds cannot handle the expansion — a minority are permanently altered or lost.",
        metadata={"significance": "critical", "phenomenon": "the_awakening"},
    ))

    # Event 31: 2473 — Dream Architecture Revolution
    events.append(TimelineEvent(
        event_id="tl_2473_dream_architecture",
        year=2473, era=TimelineEra.TRANSCENDENCE,
        name="Dream Architecture Revolution",
        description="Awakened minds learn to shape the dream layer consciously. Shared dream spaces become new territory — virtual worlds more vivid than reality. A new frontier within the mind.",
        faction_state=make_snapshots(0.08, 0.1, 0.05),
        memory_drift={
            "consciousness_collective": 0.4, "cultural_ministry": 0.35,
            "research_division": 0.3, "exploration_initiative": 0.25,
            "economic_council": 0.15, "diplomatic_corps": 0.1,
            "military_command": -0.05, "preservation_society": -0.15,
        },
        outcome="Dream architecture becomes the federation's greatest cultural and scientific achievement. Reality and dream become intertwined. New forms of art, science, and society emerge.",
        metadata={"significance": "major", "phenomenon": "dream_architecture"},
    ))

    # Event 32: 2475 — Temporal Paradox Crisis
    events.append(TimelineEvent(
        event_id="tl_2475_temporal_paradox",
        year=2475, era=TimelineEra.TRANSCENDENCE,
        name="Temporal Paradox Crisis",
        description="Consciousness experiments at the quantum level cause temporal anomalies. Brief time loops appear. Events happen before their causes. The line between memory and reality blurs.",
        faction_state=make_snapshots(-0.03, -0.05, -0.1),
        memory_drift={
            "research_division": -0.2, "consciousness_collective": -0.15,
            "military_command": -0.1, "diplomatic_corps": -0.1,
            "preservation_society": -0.05, "economic_council": -0.1,
            "cultural_ministry": -0.05, "exploration_initiative": -0.05,
        },
        outcome="The anomalies are contained through emergency quantum stabilization. Research is restricted. The incident proves that consciousness manipulation carries existential risks.",
        metadata={"significance": "major", "phenomenon": "temporal_paradox"},
    ))

    # Event 33: 2477 — Convergence Studies Advance
    events.append(TimelineEvent(
        event_id="tl_2477_convergence_studies",
        year=2477, era=TimelineEra.TRANSCENDENCE,
        name="Convergence Studies Advance",
        description="Controlled research into the Convergence phenomenon yields breakthroughs. Scientists discover that consciousness can intentionally shape probability. The universe is more mutable than believed.",
        faction_state=make_snapshots(0.05, 0.08, 0.05),
        memory_drift={
            "research_division": 0.4, "consciousness_collective": 0.35,
            "cultural_ministry": 0.2, "diplomatic_corps": 0.15,
            "economic_council": 0.1, "exploration_initiative": 0.15,
            "military_command": 0.0, "preservation_society": -0.1,
        },
        outcome="Convergence science becomes the federation's most powerful — and most dangerous — discipline. Careful protocols are established. The path to transcendence becomes clearer.",
        metadata={"significance": "major", "technology": "convergence_science"},
    ))

    # Event 34: 2480 — Transcendence Event
    events.append(TimelineEvent(
        event_id="tl_2480_transcendence",
        year=2480, era=TimelineEra.TRANSCENDENCE,
        name="The Transcendence Event",
        description="The Convergence reaches its climax. A critical mass of awakened minds achieves a state beyond ordinary consciousness. Reality transforms. The federation transcends its physical limitations — partially, imperfectly, irreversibly.",
        faction_state=make_snapshots(0.12, 0.15, 0.1),
        memory_drift={
            "consciousness_collective": 0.5, "cultural_ministry": 0.35,
            "research_division": 0.3, "diplomatic_corps": 0.2,
            "exploration_initiative": 0.2, "economic_council": 0.1,
            "military_command": 0.0, "preservation_society": -0.15,
        },
        outcome="Transcendence is achieved but not universally. Some minds ascend; others remain grounded. The federation becomes a hybrid civilization — part transcendent, part physical. It is both more and less than it was.",
        branch_point=True,
        branches={
            "full_transcendence": "The entire federation transcends; physical form is abandoned. A new kind of existence begins.",
            "partial_transcendence": "The federation maintains dual existence; transcendence is optional. Diversity of being is preserved.",
        },
        metadata={"significance": "critical", "phenomenon": "transcendence"},
    ))

    # Event 35: 2482 — Corsair Peace Treaty
    events.append(TimelineEvent(
        event_id="tl_2482_corsair_peace",
        year=2482, era=TimelineEra.LEGACY,
        name="Corsair Peace Treaty",
        description="Transcendence changes the strategic calculus. The Corsair Pact, shaken by the federation's transformation, agrees to peace talks. Borders are formalized. A new era of diplomacy begins.",
        faction_state=make_snapshots(0.05, 0.1, 0.1),
        memory_drift={
            "diplomatic_corps": 0.4, "preservation_society": 0.2,
            "economic_council": 0.2, "cultural_ministry": 0.15,
            "research_division": 0.1, "consciousness_collective": 0.1,
            "military_command": 0.05, "exploration_initiative": 0.1,
        },
        outcome="Peace with the Corsair Pact. The federation's external borders are secure for the first time in decades. A new chapter of galactic cooperation opens.",
        metadata={"significance": "major", "diplomatic_achievement": "corsair_peace"},
    ))

    # Event 36: 2485 — Memory Canon Established
    events.append(TimelineEvent(
        event_id="tl_2485_memory_canon",
        year=2485, era=TimelineEra.LEGACY,
        name="The Memory Canon Established",
        description="The Preservation Society completes the Memory Canon — a definitive historical record of the federation's first century. Every faction contributes its perspective. Truth is agreed upon, where possible.",
        faction_state=make_snapshots(0.05, 0.08, 0.1),
        memory_drift={
            "preservation_society": 0.45, "cultural_ministry": 0.3,
            "diplomatic_corps": 0.2, "research_division": 0.15,
            "consciousness_collective": 0.2, "economic_council": 0.1,
            "exploration_initiative": 0.1, "military_command": 0.05,
        },
        outcome="The Memory Canon becomes the authoritative record. Future generations will know what happened here. The federation's story is preserved — with all its triumphs and failures.",
        metadata={"significance": "major"},
    ))

    # Event 37: 2487 — Legacy Determination
    events.append(TimelineEvent(
        event_id="tl_2487_legacy",
        year=2487, era=TimelineEra.LEGACY,
        name="The Legacy Determination",
        description="One hundred years after founding, the federation assesses its legacy. Wars were fought, treaties broken, minds awakened, reality transcended. The question: was it worth it? What will the next century bring?",
        faction_state=make_snapshots(0.1, 0.12, 0.1),
        memory_drift={
            "diplomatic_corps": 0.2, "cultural_ministry": 0.2,
            "consciousness_collective": 0.25, "research_division": 0.15,
            "exploration_initiative": 0.15, "economic_council": 0.1,
            "preservation_society": 0.15, "military_command": 0.05,
        },
        outcome="The federation endures — scarred, transformed, transcendent, but enduring. Its legacy is not perfection but perseverance. The next century begins.",
        branch_point=True,
        branches={
            "eternal_federation": "The federation commits to eternal preservation of what has been built.",
            "continual_evolution": "The federation embraces continual transformation, whatever form that takes.",
            "galactic_expansion": "The federation turns outward, seeking to unite the entire galaxy.",
        },
        metadata={"significance": "critical", "milestone": "century_end"},
    ))

    return events


# ============================================================================
# DEMO / MAIN
# ============================================================================

def run_simulation() -> Dict[str, Any]:
    """
    Run the complete 100-year timeline simulation.

    Returns:
        Dict with complete simulation results
    """
    engine = TimelineEngine()
    init_result = engine.initialize_faction_states(FACTION_IDS)

    seed_events = seed_timeline_events()
    engine.load_seed_events(seed_events)

    print("=" * 72)
    print("  THE FEDERATION GAME — 100-YEAR TIMELINE SIMULATION (2387-2487)")
    print("=" * 72)
    print(f"\n  Factions initialized: {init_result['factions_initialized']}")
    print(f"  Seed events loaded: {len(seed_events)}")
    print(f"  Seed event years: {sorted(engine._seed_events.keys())}")
    print(f"\n  Running simulation...\n")

    for _ in range(101):
        result = engine.advance_year()
        if result.get("event"):
            evt = result["event"]
            era_label = result["era"].upper()
            branch_marker = " *** BRANCH POINT ***" if evt.get("branch_point") else ""
            print(f"  Year {result['year']} [{era_label}] {evt['name']}{branch_marker}")

    print("\n" + "=" * 72)
    print("  SIMULATION COMPLETE")
    print("=" * 72)

    total_events = len(engine.event_history)
    branch_events = [e for e in engine.event_history if e.branch_point]
    active_memories = engine.memory_tracker.get_active_memories(threshold=0.1)

    print(f"\n  Total events: {total_events}")
    print(f"  Branch points: {len(branch_events)}")
    print(f"  Active memories: {len(active_memories)}")
    print(f"  Final year: {engine.current_year - 1}")

    print("\n" + "-" * 72)
    print("  ERA SUMMARIES")
    print("-" * 72)

    for era in TimelineEra:
        summary = engine.get_era_summary(era)
        print(f"\n  {era.value.upper()} ({summary['year_range']})")
        print(f"    Events: {summary['events_count']}, Branch Points: {summary['branch_points']}")
        print(f"    Avg Stability: {summary['average_stability']:.3f}")

    print("\n" + "-" * 72)
    print("  FINAL FACTION STATES")
    print("-" * 72)

    for fid, snap in sorted(engine.faction_states.items()):
        print(f"    {fid:28} P:{snap.power:.2f}  R:{snap.reputation:.2f}  "
              f"I:{snap.influence:.2f}  S:{snap.stability:.2f}  "
              f"Drift:{snap.ideology_drift:+.2f}")

    print("\n" + "-" * 72)
    print("  GENERATIONAL NARRATIVE (Year 2487)")
    print("-" * 72)
    narrative = engine.memory_tracker.get_generational_narrative(2487)
    print(narrative)

    print("\n" + "-" * 72)
    print("  FACTION DRIFT EXAMPLE: diplomatic_corps")
    print("-" * 72)
    drift = engine.get_faction_drift("diplomatic_corps")
    sample_years = sorted(drift.keys())[::10]
    for y in sample_years:
        bar_len = int(drift[y] * 40)
        bar = "#" * max(bar_len, 0) + "." * max(40 - bar_len, 0)
        print(f"    {y}: [{bar}] {drift[y]:.3f}")

    export = engine.export_timeline()
    export_size = len(json.dumps(export))

    print(f"\n  Export size: {export_size:,} bytes")
    print(f"\n{'=' * 72}")
    print("  END OF SIMULATION")
    print("=" * 72)

    return {
        "success": True,
        "years_simulated": 101,
        "total_events": total_events,
        "branch_points": len(branch_events),
        "active_memories": len(active_memories),
        "export_size_bytes": export_size,
    }


if __name__ == "__main__":
    result = run_simulation()
