"""
FEDERATION GAME - 100-Year Timeline System (2387-2487)
Manages era progression, decade gates, faction drift, narrative memory,
branching history, and quantum consciousness evolution over a century.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any, Set, Tuple
from datetime import datetime
import math
import random


class Era(Enum):
    EARLY_EXPLORATION = "early_exploration"
    CONSOLIDATION = "consolidation"
    EXPANSION = "expansion"
    CRISES_AND_CONFLICTS = "crises_and_conflicts"
    MATURITY = "maturity"
    TRANSCENDENCE = "transcendence"


ERA_RANGES = {
    Era.EARLY_EXPLORATION: (2387, 2397),
    Era.CONSOLIDATION: (2397, 2407),
    Era.EXPANSION: (2407, 2427),
    Era.CRISES_AND_CONFLICTS: (2427, 2447),
    Era.MATURITY: (2447, 2467),
    Era.TRANSCENDENCE: (2467, 2487),
}

ERA_DESCRIPTIONS = {
    Era.EARLY_EXPLORATION: "The Federation pushes beyond known borders. Every sector is a first contact, every discovery a risk.",
    Era.CONSOLIDATION: "New territories must be governed. The Council writes the rules that will shape the next century.",
    Era.EXPANSION: "The Federation stretches across sectors. Trade routes, alliances, and rivalries define the era.",
    Era.CRISES_AND_CONFLICTS: "Old fractures become chasms. Rivals test borders, factions clash, and the Constitution bends.",
    Era.MATURITY: "The Federation finds equilibrium or collapses under its weight. Wisdom or entropy.",
    Era.TRANSCENDENCE: "Consciousness technology reshapes identity itself. The Federation becomes something new or falls into the old.",
}

TURNS_PER_DECADE = 10


@dataclass
class DecadeGate:
    decade: int
    year_start: int
    year_end: int
    era: Era
    triggered: bool = False
    major_events: List[str] = field(default_factory=list)
    divergence_applied: bool = False


@dataclass
class NarrativeMemory:
    memory_id: str
    turn: int
    year: int
    event_id: str
    event_title: str
    choice_id: str
    outcome: str
    emotional_valence: float
    factions_affected: Dict[str, float] = field(default_factory=dict)
    constitutional_impact: float = 0.0
    tags: List[str] = field(default_factory=list)


@dataclass
class DivergencePoint:
    divergence_id: str
    turn: int
    year: int
    description: str
    condition_type: str
    condition_value: float
    locked_event_pools: List[str] = field(default_factory=list)
    unlocked_event_pools: List[str] = field(default_factory=list)
    triggered: bool = False


@dataclass
class ConsciousnessState:
    coherence: float = 50.0
    stability: float = 50.0
    complexity: float = 50.0
    awakeness: float = 0.0
    memories_recorded: int = 0
    traumas_processed: float = 0.0
    dream_integration_rate: float = 0.0
    last_measurement: Optional[str] = None


class TimelineSystem:
    def __init__(self, start_year: int = 2387, end_year: int = 2487):
        self.start_year = start_year
        self.end_year = end_year
        self.current_year = start_year
        self.current_era = Era.EARLY_EXPLORATION
        self.turn = 0
        self.decade_gates: Dict[int, DecadeGate] = {}
        self.narrative_memory: List[NarrativeMemory] = []
        self.divergence_points: List[DivergencePoint] = []
        self.consciousness = ConsciousnessState()
        self._memory_counter = 0
        self._divergence_counter = 0
        self.era_history: List[Dict[str, Any]] = []
        self._initialize_decade_gates()
        self._initialize_divergence_points()

    def _initialize_decade_gates(self):
        for decade_start in range(self.start_year, self.end_year, 10):
            decade_num = (decade_start - self.start_year) // 10
            era = self._era_for_year(decade_start)
            self.decade_gates[decade_num] = DecadeGate(
                decade=decade_num,
                year_start=decade_start,
                year_end=min(decade_start + 10, self.end_year),
                era=era,
            )

    def _era_for_year(self, year: int) -> Era:
        for era, (start, end) in ERA_RANGES.items():
            if start <= year < end:
                return era
        return Era.TRANSCENDENCE

    def _initialize_divergence_points(self):
        divergence_defs = [
            ("first_contact_policy", 10, 2397, "First contact policy sets the tone for the century",
             "public_trust", 60.0, ["expansion_events"], ["isolationist_events"]),
            ("constitutional_fork", 25, 2412, "The Constitution faces its first real test",
             "constitutional_integrity", 50.0, ["rights_expansion_events"], ["authoritarian_drift_events"]),
            ("consciousness_awakening", 50, 2437, "Consciousness technology changes what it means to be Federation",
             "consciousness_complexity", 60.0, ["transcendence_events"], ["stability_lock_events"]),
            ("the_great_schism", 70, 2457, "Factions split on the fundamental question of identity",
             "faction_polarization", 0.3, ["unity_events"], ["civil_war_events"]),
            ("final_arbitration", 90, 2477, "The Federation chooses its final form",
             "federation_stability", 65.0, ["ascension_events"], ["dissolution_events"]),
        ]
        for div_id, turn, year, desc, cond_type, cond_val, locked, unlocked in divergence_defs:
            self._divergence_counter += 1
            self.divergence_points.append(DivergencePoint(
                divergence_id=div_id,
                turn=turn,
                year=year,
                description=desc,
                condition_type=cond_type,
                condition_value=cond_val,
                locked_event_pools=locked,
                unlocked_event_pools=unlocked,
            ))

    def advance_year(self) -> Dict[str, Any]:
        self.turn += 1
        years_per_turn = (self.end_year - self.start_year) / 100.0
        self.current_year = min(
            self.end_year,
            self.start_year + int(self.turn * years_per_turn),
        )
        new_era = self._era_for_year(self.current_year)
        era_changed = new_era != self.current_era
        if era_changed:
            self.era_history.append({
                "from_era": self.current_era.value,
                "to_era": new_era.value,
                "year": self.current_year,
                "turn": self.turn,
            })
            self.current_era = new_era

        decade_num = (self.current_year - self.start_year) // 10
        decade_gate = self.decade_gates.get(decade_num)
        gate_triggered = False
        if decade_gate and not decade_gate.triggered and self.turn > 0 and self.turn % TURNS_PER_DECADE == 0:
            decade_gate.triggered = True
            gate_triggered = True

        return {
            "turn": self.turn,
            "year": self.current_year,
            "era": self.current_era.value,
            "era_changed": era_changed,
            "decade_gate": gate_triggered,
            "decade_number": decade_num,
        }

    def apply_faction_drift(self, faction_reputations: Dict[str, float],
                            faction_allies: Dict[str, List[str]],
                            faction_enemies: Dict[str, List[str]]) -> Dict[str, float]:
        drift_rate = 0.005
        updated = dict(faction_reputations)
        for fid, rep in faction_reputations.items():
            drift = random.gauss(0, drift_rate)
            for ally_id in faction_allies.get(fid, []):
                if ally_id in faction_reputations:
                    ally_rep = faction_reputations[ally_id]
                    drift += (ally_rep - rep) * 0.002
            for enemy_id in faction_enemies.get(fid, []):
                if enemy_id in faction_reputations:
                    enemy_rep = faction_reputations[enemy_id]
                    drift -= abs(enemy_rep - rep) * 0.001
            updated[fid] = max(0.0, min(1.0, rep + drift))
        return updated

    def record_narrative(self, event_id: str, event_title: str,
                         choice_id: str, outcome: str,
                         emotional_valence: float,
                         factions_affected: Dict[str, float],
                         constitutional_impact: float = 0.0,
                         tags: Optional[List[str]] = None) -> NarrativeMemory:
        self._memory_counter += 1
        mem = NarrativeMemory(
            memory_id=f"narr_{self._memory_counter:06d}",
            turn=self.turn,
            year=self.current_year,
            event_id=event_id,
            event_title=event_title,
            choice_id=choice_id,
            outcome=outcome,
            emotional_valence=max(-1.0, min(1.0, emotional_valence)),
            factions_affected=factions_affected,
            constitutional_impact=constitutional_impact,
            tags=tags or [],
        )
        self.narrative_memory.append(mem)
        return mem

    def check_divergence(self, metrics: Dict[str, float]) -> List[DivergencePoint]:
        triggered = []
        for dp in self.divergence_points:
            if dp.triggered:
                continue
            if self.turn < dp.turn:
                continue
            metric_val = metrics.get(dp.condition_type, 0.0)
            if metric_val >= dp.condition_value:
                dp.triggered = True
                triggered.append(dp)
        return triggered

    def update_consciousness(self, emotional_valence: float = 0.0,
                             trauma: bool = False,
                             breakthrough: bool = False) -> ConsciousnessState:
        c = self.consciousness
        c.memories_recorded += 1
        c.last_measurement = datetime.now().isoformat()

        if abs(emotional_valence) > 0.5:
            c.complexity = min(100.0, c.complexity + 1.5)
        if emotional_valence > 0.3:
            c.coherence = min(100.0, c.coherence + 0.8)
            c.stability = min(100.0, c.stability + 0.5)
        elif emotional_valence < -0.3:
            c.coherence = max(0.0, c.coherence - 1.2)
            c.stability = max(0.0, c.stability - 0.8)

        if trauma:
            c.stability = max(0.0, c.stability - 3.0)
            c.complexity = min(100.0, c.complexity + 2.0)
            c.traumas_processed += 1

        if breakthrough:
            c.coherence = min(100.0, c.coherence + 5.0)
            c.complexity = min(100.0, c.complexity + 4.0)
            c.awakeness = min(1.0, c.awakeness + 0.1)

        memory_factor = min(1.0, c.memories_recorded / 50.0)
        trauma_factor = min(1.0, c.traumas_processed / 10.0) * 0.3
        c.awakeness = min(1.0, memory_factor * 0.4 + trauma_factor + c.awakeness * 0.3)

        return c

    def get_timeline_status(self) -> Dict[str, Any]:
        return {
            "current_year": self.current_year,
            "current_era": self.current_era.value,
            "era_description": ERA_DESCRIPTIONS.get(self.current_era, ""),
            "turn": self.turn,
            "years_remaining": self.end_year - self.current_year,
            "decade_gates_triggered": sum(1 for g in self.decade_gates.values() if g.triggered),
            "total_decade_gates": len(self.decade_gates),
            "narrative_memories": len(self.narrative_memory),
            "divergence_points_triggered": sum(1 for d in self.divergence_points if d.triggered),
            "total_divergence_points": len(self.divergence_points),
            "consciousness": {
                "coherence": self.consciousness.coherence,
                "stability": self.consciousness.stability,
                "complexity": self.consciousness.complexity,
                "awakeness": self.consciousness.awakeness,
                "memories_recorded": self.consciousness.memories_recorded,
                "description": self._describe_consciousness(),
            },
            "era_history": self.era_history[-5:],
        }

    def get_narrative_arc(self, limit: int = 20) -> List[Dict[str, Any]]:
        return [
            {
                "memory_id": m.memory_id,
                "year": m.year,
                "turn": m.turn,
                "event": m.event_title,
                "choice": m.choice_id,
                "outcome": m.outcome,
                "emotional_valence": m.emotional_valence,
                "factions_affected": m.factions_affected,
                "tags": m.tags,
            }
            for m in self.narrative_memory[-limit:]
        ]

    def get_divergence_status(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": d.divergence_id,
                "year": d.year,
                "description": d.description,
                "condition_type": d.condition_type,
                "threshold": d.condition_value,
                "triggered": d.triggered,
                "unlocked_pools": d.unlocked_event_pools if d.triggered else [],
                "locked_pools": d.locked_event_pools if d.triggered else [],
            }
            for d in self.divergence_points
        ]

    def _describe_consciousness(self) -> str:
        level = self.consciousness.awakeness
        if level < 0.1:
            return "Deeply unconscious, barely aware"
        elif level < 0.25:
            return "Fragmentary awareness, dream-like"
        elif level < 0.4:
            return "Emerging consciousness, awakening"
        elif level < 0.6:
            return "Conscious and self-aware, present"
        elif level < 0.75:
            return "Highly conscious, deeply reflective"
        elif level < 0.9:
            return "Transcendent awareness, unified self"
        else:
            return "Infinite consciousness, pure being"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_year": self.start_year,
            "end_year": self.end_year,
            "current_year": self.current_year,
            "current_era": self.current_era.value,
            "turn": self.turn,
            "consciousness": {
                "coherence": self.consciousness.coherence,
                "stability": self.consciousness.stability,
                "complexity": self.consciousness.complexity,
                "awakeness": self.consciousness.awakeness,
            },
        }
