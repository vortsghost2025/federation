#!/usr/bin/env python3
"""
THE FEDERATION GAME - QUANTUM CONSCIOUSNESS ENGINE
~900 LOC - Narrative/Meta-Analysis Layer

The interpretive layer that sits above the timeline and faction systems.
Makes raw historical data meaningful by interpreting events through
the lens of consciousness, generating narrative meaning, tracking
how different observers (factions) perceive the same events differently,
and producing the emergent "story" of the 100-year arc.

Quantum consciousness means: until a faction "observes" an event,
its meaning exists in superposition -- multiple interpretations coexist.
When observed, the narrative collapses into one version of reality,
but the lost possibilities haunt the federation as dreams and traumas.
"""

import uuid
import math
import random
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple, Set


# ============================================================================
# ENUMS
# ============================================================================

class QuantumState(Enum):
    """States of quantum narrative superposition"""
    COLLAPSED = "collapsed"
    SUPERPOSED = "superposed"
    ENTANGLED = "entangled"
    DECOHERENT = "decoherent"


class ObserverRole(Enum):
    """How a faction observes/interprets history"""
    PARTICIPANT = "participant"
    WITNESS = "witness"
    VICTIM = "victim"
    BENEFICIARY = "beneficiary"
    INTERPRETER = "interpreter"


class IdeologyType(Enum):
    """Faction philosophy and approach"""
    DIPLOMATIC = "diplomatic"
    MILITARY = "military"
    CULTURAL = "cultural"
    SCIENTIFIC = "scientific"
    SPIRITUAL = "spiritual"
    ECONOMIC = "economic"
    DISCOVERY = "discovery"
    STABILITY = "stability"


class NarrativePattern(Enum):
    """Detected patterns in historical narrative"""
    RISE = "rise"
    FALL = "fall"
    CYCLE = "cycle"
    TRANSCENDENCE = "transcendence"
    ECHO = "echo"
    INVERSION = "inversion"
    CONVERGENCE = "convergence"
    DIVERGENCE = "divergence"


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class NarrativeInterpretation:
    """How a single observer interprets a single event"""
    interpretation_id: str
    event_id: str
    observer_faction_id: str
    observer_role: ObserverRole
    narrative: str
    emotional_resonance: float
    ideological_spin: float
    confidence: float
    quantum_state: QuantumState


@dataclass
class ConsciousnessWave:
    """A wave of collective consciousness across the timeline"""
    wave_id: str
    start_year: int
    end_year: int
    amplitude: float
    frequency: float
    consciousness_layer: str
    affected_factions: List[str]
    narrative_pattern: str


@dataclass
class QuantumNarrative:
    """The complete quantum narrative state -- multiple possible histories"""
    narrative_id: str
    year: int
    possible_histories: Dict[str, str]
    collapsed_history: Optional[str]
    entangled_events: List[str]
    observer_interpretations: Dict[str, NarrativeInterpretation]
    consciousness_waves: List[ConsciousnessWave]
    coherence: float
    depth: float


@dataclass
class LostPossibility:
    """A branch of history that was not taken"""
    possibility_id: str
    event_id: str
    branch_id: str
    narrative: str
    emotional_weight: float
    desired_by: List[str]
    year: int


@dataclass
class EventEntanglement:
    """Two events linked across time"""
    entanglement_id: str
    event_id_1: str
    event_id_2: str
    strength: float
    interpretation_drift: float = 0.0


@dataclass
class ObserverProfile:
    """A registered faction observer"""
    faction_id: str
    faction_name: str
    default_role: ObserverRole
    ideology: IdeologyType
    influence_weight: float = 1.0
    emotional_state: float = 0.5
    interpretation_history: List[str] = field(default_factory=list)


# ============================================================================
# INTERPRETATION TEMPLATES
# ============================================================================

INTERPRETATION_TEMPLATES: Dict[Tuple[ObserverRole, IdeologyType], str] = {
    (ObserverRole.PARTICIPANT, IdeologyType.MILITARY):
        "In {year}, {faction_name} forged {event_name} through strength and resolve. "
    "The outcome -- {outcome} -- was earned in fire.",

    (ObserverRole.PARTICIPANT, IdeologyType.DIPLOMATIC):
        "In {year}, {faction_name} helped shape {event_name} through careful negotiation. "
    "The result, {outcome}, reflects the power of dialogue.",

    (ObserverRole.PARTICIPANT, IdeologyType.DISCOVERY):
        "In {year}, {faction_name} blazed the trail for {event_name}, venturing into the unknown. "
    "What we found -- {outcome} -- changed the map forever.",

    (ObserverRole.PARTICIPANT, IdeologyType.SCIENTIFIC):
        "In {year}, {faction_name} applied rigorous method to {event_name}. "
    "The measured outcome -- {outcome} -- validated our hypothesis.",

    (ObserverRole.PARTICIPANT, IdeologyType.ECONOMIC):
        "In {year}, {faction_name} invested deeply in {event_name}. "
    "The outcome -- {outcome} -- proved that prosperity demands bold action.",

    (ObserverRole.PARTICIPANT, IdeologyType.CULTURAL):
        "In {year}, {faction_name} poured heart and soul into {event_name}. "
    "The outcome -- {outcome} -- became a defining chapter of our identity.",

    (ObserverRole.PARTICIPANT, IdeologyType.SPIRITUAL):
        "In {year}, {faction_name} channeled cosmic will through {event_name}. "
    "The outcome -- {outcome} -- was destined before we acted.",

    (ObserverRole.PARTICIPANT, IdeologyType.STABILITY):
        "In {year}, {faction_name} maintained order through {event_name}. "
    "The outcome -- {outcome} -- preserved what mattered against chaos.",

    (ObserverRole.WITNESS, IdeologyType.CULTURAL):
        "In {year}, {faction_name} watched {event_name} unfold and wove it into collective memory. "
    "The outcome -- {outcome} -- became song and story.",

    (ObserverRole.WITNESS, IdeologyType.SPIRITUAL):
        "In {year}, {faction_name} perceived {event_name} through the lens of cosmic awareness. "
    "The outcome -- {outcome} -- was foreseen in dream.",

    (ObserverRole.WITNESS, IdeologyType.SCIENTIFIC):
        "In {year}, {faction_name} observed {event_name} with careful detachment. "
    "The outcome -- {outcome} -- provided valuable empirical data.",

    (ObserverRole.WITNESS, IdeologyType.DIPLOMATIC):
        "In {year}, {faction_name} bore witness to {event_name}, noting how power shifted. "
    "The outcome -- {outcome} -- altered the balance of influence.",

    (ObserverRole.WITNESS, IdeologyType.STABILITY):
        "In {year}, {faction_name} stood watch over {event_name}. "
    "The outcome -- {outcome} -- was recorded faithfully for posterity.",

    (ObserverRole.WITNESS, IdeologyType.ECONOMIC):
        "In {year}, {faction_name} tracked the financial ripples of {event_name}. "
    "The outcome -- {outcome} -- shifted markets in ways we still study.",

    (ObserverRole.WITNESS, IdeologyType.MILITARY):
        "In {year}, {faction_name} observed {event_name} from a safe distance. "
    "The outcome -- {outcome} -- taught us what force alone can and cannot achieve.",

    (ObserverRole.VICTIM, IdeologyType.STABILITY):
        "In {year}, {faction_name} suffered from {event_name} -- stability shattered, order broken. "
    "The outcome -- {outcome} -- was a wound that may never heal.",

    (ObserverRole.VICTIM, IdeologyType.CULTURAL):
        "In {year}, {faction_name} lost something irreplaceable to {event_name}. "
    "The outcome -- {outcome} -- echoes as grief in every artwork since.",

    (ObserverRole.VICTIM, IdeologyType.SPIRITUAL):
        "In {year}, {faction_name} endured {event_name} as a trial of consciousness. "
    "The outcome -- {outcome} -- scarred the collective spirit.",

    (ObserverRole.VICTIM, IdeologyType.ECONOMIC):
        "In {year}, {faction_name} bore the cost of {event_name}. "
    "The outcome -- {outcome} -- depleted resources that took generations to rebuild.",

    (ObserverRole.VICTIM, IdeologyType.MILITARY):
        "In {year}, {faction_name} bore the brunt of {event_name}. "
    "The outcome -- {outcome} -- cost lives and honor that cannot be replaced.",

    (ObserverRole.VICTIM, IdeologyType.DISCOVERY):
        "In {year}, {faction_name} was displaced by {event_name}. "
    "The outcome -- {outcome} -- erased our claims and opened wounds of erasure.",

    (ObserverRole.VICTIM, IdeologyType.DIPLOMATIC):
        "In {year}, {faction_name} was outmaneuvered in {event_name}. "
    "The outcome -- {outcome} -- left us isolated when we needed allies most.",

    (ObserverRole.BENEFICIARY, IdeologyType.ECONOMIC):
        "In {year}, {faction_name} profited from {event_name}. "
    "The outcome -- {outcome} -- opened trade routes and filled the treasury.",

    (ObserverRole.BENEFICIARY, IdeologyType.MILITARY):
        "In {year}, {faction_name} gained strategic advantage from {event_name}. "
    "The outcome -- {outcome} -- hardened our position and expanded our reach.",

    (ObserverRole.BENEFICIARY, IdeologyType.DISCOVERY):
        "In {year}, {faction_name} reaped the rewards of {event_name}. "
    "The outcome -- {outcome} -- gave us territory and knowledge others lacked.",

    (ObserverRole.BENEFICIARY, IdeologyType.SCIENTIFIC):
        "In {year}, {faction_name} leveraged {event_name} for breakthrough. "
    "The outcome -- {outcome} -- accelerated research by decades.",

    (ObserverRole.BENEFICIARY, IdeologyType.DIPLOMATIC):
        "In {year}, {faction_name} turned {event_name} into diplomatic capital. "
    "The outcome -- {outcome} -- strengthened our alliances.",

    (ObserverRole.BENEFICIARY, IdeologyType.CULTURAL):
        "In {year}, {faction_name} found inspiration in {event_name}. "
    "The outcome -- {outcome} -- sparked a renaissance of creative expression.",

    (ObserverRole.BENEFICIARY, IdeologyType.STABILITY):
        "In {year}, {faction_name} gained ground from {event_name}. "
    "The outcome -- {outcome} -- reinforced the foundations of order.",

    (ObserverRole.BENEFICIARY, IdeologyType.SPIRITUAL):
        "In {year}, {faction_name} received blessings from {event_name}. "
    "The outcome -- {outcome} -- deepened our connection to the cosmic pattern.",

    (ObserverRole.INTERPRETER, IdeologyType.DIPLOMATIC):
        "In {year}, {faction_name} reframed {event_name} for future generations. "
    "The outcome -- {outcome} -- was reshaped by context and careful narrative.",

    (ObserverRole.INTERPRETER, IdeologyType.SCIENTIFIC):
        "In {year}, {faction_name} analyzed {event_name} and revised its meaning. "
    "The outcome -- {outcome} -- was not what it seemed at first.",

    (ObserverRole.INTERPRETER, IdeologyType.STABILITY):
        "In {year}, {faction_name} preserved the official record of {event_name}. "
    "The outcome -- {outcome} -- was codified into law and tradition.",

    (ObserverRole.INTERPRETER, IdeologyType.SPIRITUAL):
        "In {year}, {faction_name} discerned the deeper truth within {event_name}. "
    "The outcome -- {outcome} -- revealed a pattern the waking mind missed.",

    (ObserverRole.INTERPRETER, IdeologyType.CULTURAL):
        "In {year}, {faction_name} transformed {event_name} into myth. "
    "The outcome -- {outcome} -- became legend that outlived the truth.",

    (ObserverRole.INTERPRETER, IdeologyType.ECONOMIC):
        "In {year}, {faction_name} recalculated the meaning of {event_name}. "
    "The outcome -- {outcome} -- revealed hidden profits and concealed costs.",

    (ObserverRole.INTERPRETER, IdeologyType.MILITARY):
        "In {year}, {faction_name} recontextualized {event_name} for strategic narrative. "
    "The outcome -- {outcome} -- was retold to serve the mission.",
}


# ============================================================================
# FACTION INTERPRETATION ENGINE (Inner Helper)
# ============================================================================

class FactionInterpretationEngine:
    """Generates faction-specific interpretations of events based on
    ideology type, current power, relationship to event, and emotional state."""

    ROLE_EMOTIONAL_BIAS: Dict[ObserverRole, float] = {
        ObserverRole.PARTICIPANT: 0.3,
        ObserverRole.WITNESS: 0.0,
        ObserverRole.VICTIM: -0.5,
        ObserverRole.BENEFICIARY: 0.5,
        ObserverRole.INTERPRETER: 0.1,
    }

    ROLE_CONFIDENCE_BIAS: Dict[ObserverRole, float] = {
        ObserverRole.PARTICIPANT: 0.85,
        ObserverRole.WITNESS: 0.6,
        ObserverRole.VICTIM: 0.9,
        ObserverRole.BENEFICIARY: 0.75,
        ObserverRole.INTERPRETER: 0.5,
    }

    IDEOLOGY_SPIN_BIAS: Dict[IdeologyType, float] = {
        IdeologyType.DIPLOMATIC: 0.2,
        IdeologyType.MILITARY: 0.4,
        IdeologyType.CULTURAL: 0.1,
        IdeologyType.SCIENTIFIC: -0.1,
        IdeologyType.SPIRITUAL: 0.3,
        IdeologyType.ECONOMIC: 0.35,
        IdeologyType.DISCOVERY: 0.25,
        IdeologyType.STABILITY: -0.2,
    }

    def __init__(self):
        self.templates = INTERPRETATION_TEMPLATES

    def generate_interpretation(
        self,
        event_id: str,
        event_data: Dict[str, Any],
        observer: ObserverProfile,
        year: int,
    ) -> NarrativeInterpretation:
        """Generate a single faction's interpretation of an event"""
        template = self._select_template(observer.default_role, observer.ideology)
        narrative = template.format(
            year=year,
            faction_name=observer.faction_name,
            event_name=event_data.get("name", event_id),
            outcome=event_data.get("outcome", "uncertain consequences"),
        )

        emotional_resonance = self._compute_emotional_resonance(observer, event_data)
        ideological_spin = self._compute_ideological_spin(observer, event_data)
        confidence = self._compute_confidence(observer, event_data)

        return NarrativeInterpretation(
            interpretation_id=f"interp_{uuid.uuid4().hex[:8]}",
            event_id=event_id,
            observer_faction_id=observer.faction_id,
            observer_role=observer.default_role,
            narrative=narrative,
            emotional_resonance=emotional_resonance,
            ideological_spin=ideological_spin,
            confidence=confidence,
            quantum_state=QuantumState.SUPERPOSED,
        )

    def _select_template(self, role: ObserverRole, ideology: IdeologyType) -> str:
        """Select the best matching interpretation template"""
        key = (role, ideology)
        if key in self.templates:
            return self.templates[key]
        role_matches = [k for k in self.templates if k[0] == role]
        if role_matches:
            return self.templates[role_matches[0]]
        ideology_matches = [k for k in self.templates if k[1] == ideology]
        if ideology_matches:
            return self.templates[ideology_matches[0]]
        return (
            "In {year}, {faction_name} experienced {event_name}. "
            "The outcome -- {outcome} -- remains subject to interpretation."
        )

    def _compute_emotional_resonance(
        self, observer: ObserverProfile, event_data: Dict[str, Any]
    ) -> float:
        """Compute emotional resonance (-1.0 to 1.0) for an observer"""
        base = self.ROLE_EMOTIONAL_BIAS.get(observer.default_role, 0.0)
        event_emotion = event_data.get("emotional_valence", 0.0)
        observer_emotion = (observer.emotional_state - 0.5) * 2.0
        proximity = event_data.get("proximity", 0.5)
        raw = base * 0.4 + event_emotion * 0.3 + observer_emotion * 0.2 + (proximity - 0.5) * 0.1
        return max(-1.0, min(1.0, raw))

    def _compute_ideological_spin(
        self, observer: ObserverProfile, event_data: Dict[str, Any]
    ) -> float:
        """Compute ideological spin (-1.0 to 1.0) for an observer"""
        base = self.IDEOLOGY_SPIN_BIAS.get(observer.ideology, 0.0)
        event_polarity = event_data.get("ideological_polarity", 0.0)
        alignment = event_data.get("ideological_alignment", 0.5)
        spin_factor = 1.0 if alignment > 0.5 else -0.5
        raw = base * spin_factor + event_polarity * 0.3
        return max(-1.0, min(1.0, raw))

    def _compute_confidence(
        self, observer: ObserverProfile, event_data: Dict[str, Any]
    ) -> float:
        """Compute confidence (0-1) in this interpretation"""
        base = self.ROLE_CONFIDENCE_BIAS.get(observer.default_role, 0.5)
        event_clarity = event_data.get("clarity", 0.5)
        proximity = event_data.get("proximity", 0.5)
        raw = base * 0.5 + event_clarity * 0.3 + proximity * 0.2
        return max(0.0, min(1.0, raw))


# ============================================================================
# QUANTUM CONSCIOUSNESS ENGINE
# ============================================================================

class QuantumConsciousnessEngine:
    """The interpretive/narrative layer that makes raw timeline data meaningful.

    Interprets history through consciousness, generates narrative meaning,
    tracks how different observers perceive the same events differently,
    and produces the emergent story of the 100-year arc.
    """

    def __init__(self):
        self.observers: Dict[str, ObserverProfile] = {}
        self.interpretations: Dict[str, List[NarrativeInterpretation]] = {}
        self.narratives: Dict[int, QuantumNarrative] = {}
        self.entanglements: List[EventEntanglement] = []
        self.lost_possibilities: List[LostPossibility] = []
        self.consciousness_waves: List[ConsciousnessWave] = []
        self.interpretation_engine = FactionInterpretationEngine()
        self.event_cache: Dict[str, Dict[str, Any]] = {}
        self.coherence_history: Dict[int, float] = {}

    def register_observer(
        self,
        faction_id: str,
        default_role,
        faction_name: str = "",
        ideology = None,
        influence_weight: float = 1.0,
    ) -> Dict[str, Any]:
        """Register a faction as a narrative observer"""
        if not faction_name:
            faction_name = faction_id.replace("_", " ").title()

        # Convert string role/ideology to enum if needed
        if isinstance(default_role, str):
            default_role = ObserverRole(default_role)
        if ideology is None:
            ideology = IdeologyType.DIPLOMATIC
        elif isinstance(ideology, str):
            ideology = IdeologyType(ideology)

        observer = ObserverProfile(
            faction_id=faction_id,
            faction_name=faction_name,
            default_role=default_role,
            ideology=ideology,
            influence_weight=influence_weight,
        )
        self.observers[faction_id] = observer

        return {
            "success": True,
            "observer_registered": faction_id,
            "role": default_role.value,
            "ideology": ideology.value,
            "total_observers": len(self.observers),
        }

    def interpret_event(
        self, event_id: str, event_data: Dict, year: int
    ) -> Dict[str, Any]:
        """Interpret a single event through all registered observers.

        For each observer, generates a NarrativeInterpretation that varies
        by observer_role, faction ideology, and emotional distance.
        Returns all interpretations plus a consensus narrative.
        """
        self.event_cache[event_id] = event_data
        event_interpretations: List[NarrativeInterpretation] = []

        for faction_id, observer in self.observers.items():
            interp = self.interpretation_engine.generate_interpretation(
                event_id, event_data, observer, year
            )
            event_interpretations.append(interp)
            observer.interpretation_history.append(interp.interpretation_id)

        self.interpretations[event_id] = event_interpretations

        consensus = self._build_consensus_narrative(
            event_id, event_interpretations, year
        )

        existing_narrative = self.narratives.get(year)
        if existing_narrative:
            existing_narrative.observer_interpretations.update(
                {i.interpretation_id: i for i in event_interpretations}
            )
        else:
            self.narratives[year] = QuantumNarrative(
                narrative_id=f"qn_{year}_{uuid.uuid4().hex[:6]}",
                year=year,
                possible_histories={event_id: consensus},
                collapsed_history=None,
                entangled_events=[],
                observer_interpretations={
                    i.interpretation_id: i for i in event_interpretations
                },
                consciousness_waves=[],
                coherence=1.0,
                depth=0.0,
            )

        self._apply_entanglement_drift(event_id)

        return {
            "success": True,
            "event_id": event_id,
            "year": year,
            "interpretations": [
                {
                    "faction_id": i.observer_faction_id,
                    "role": i.observer_role.value,
                    "narrative": i.narrative,
                    "emotional_resonance": round(i.emotional_resonance, 3),
                    "ideological_spin": round(i.ideological_spin, 3),
                    "confidence": round(i.confidence, 3),
                    "quantum_state": i.quantum_state.value,
                }
                for i in event_interpretations
            ],
            "consensus_narrative": consensus,
            "total_interpretations": len(event_interpretations),
        }

    def generate_consciousness_wave(
        self, start_year: int, end_year: int, events: List[Dict]
    ) -> ConsciousnessWave:
        """Detect patterns in events and create a consciousness wave
        describing the collective consciousness trajectory."""
        event_count = len(events)
        decade_span = max(1, (end_year - start_year) / 10.0)
        frequency = event_count / decade_span

        emotional_sum = 0.0
        for ev in events:
            emotional_sum += ev.get("emotional_valence", 0.0)
        amplitude = min(1.0, abs(emotional_sum) / max(event_count, 1))

        if emotional_sum > 0.3 * event_count:
            pattern = NarrativePattern.RISE.value
        elif emotional_sum < -0.3 * event_count:
            pattern = NarrativePattern.FALL.value
        elif self._detect_cycle(events):
            pattern = NarrativePattern.CYCLE.value
        elif amplitude > 0.7 and emotional_sum > 0:
            pattern = NarrativePattern.TRANSCENDENCE.value
        else:
            pattern = NarrativePattern.RISE.value

        affected = list(self.observers.keys())

        wave = ConsciousnessWave(
            wave_id=f"wave_{uuid.uuid4().hex[:8]}",
            start_year=start_year,
            end_year=end_year,
            amplitude=amplitude,
            frequency=frequency,
            consciousness_layer="collective",
            affected_factions=affected,
            narrative_pattern=pattern,
        )

        self.consciousness_waves.append(wave)

        narrative = self.narratives.get(end_year)
        if narrative:
            narrative.consciousness_waves.append(wave)

        return wave

    def collapse_superposition(
        self, event_id: str, branch_chosen: str
    ) -> Dict[str, Any]:
        """Collapse quantum superposition when a branch point is resolved.

        The chosen branch becomes real; others become lost possibilities
        (ghost histories) that manifest as traumas/dreams for factions
        that wanted the other path.
        """
        if event_id not in self.event_cache:
            return {"success": False, "error": f"Event {event_id} not found"}

        event_data = self.event_cache[event_id]
        year = event_data.get("year", 0)
        branches = event_data.get("branches", {})

        if not branches:
            branches = {
                branch_chosen: event_data.get("outcome", "resolved"),
                "alternative": "the path not taken",
            }

        collapsed_narrative = branches.get(branch_chosen, "unknown outcome")

        new_lost: List[Dict[str, Any]] = []
        for branch_id, branch_narrative in branches.items():
            if branch_id == branch_chosen:
                continue

            desiring_factions = self._factions_desiring_branch(event_id, branch_id)
            emotional_weight = self._compute_lost_weight(branch_id, desiring_factions)

            lost = LostPossibility(
                possibility_id=f"lost_{uuid.uuid4().hex[:8]}",
                event_id=event_id,
                branch_id=branch_id,
                narrative=branch_narrative,
                emotional_weight=emotional_weight,
                desired_by=[f.faction_id for f in desiring_factions],
                year=year,
            )
            self.lost_possibilities.append(lost)
            new_lost.append({
                "possibility_id": lost.possibility_id,
                "branch_id": branch_id,
                "narrative": branch_narrative,
                "emotional_weight": round(emotional_weight, 3),
                "desired_by": lost.desired_by,
            })

        if event_id in self.interpretations:
            for interp in self.interpretations[event_id]:
                interp.quantum_state = QuantumState.COLLAPSED

        narrative = self.narratives.get(year)
        if narrative:
            narrative.collapsed_history = collapsed_narrative
            narrative.possible_histories[branch_chosen] = collapsed_narrative

        return {
            "success": True,
            "event_id": event_id,
            "branch_chosen": branch_chosen,
            "collapsed_narrative": collapsed_narrative,
            "lost_possibilities": new_lost,
            "factions_affected": len(new_lost),
        }

    def entangle_events(
        self, event_id_1: str, event_id_2: str, strength: float
    ) -> Dict[str, Any]:
        """Link two events across time so that interpreting one
        affects the interpretation of the other."""
        entanglement = EventEntanglement(
            entanglement_id=f"ent_{uuid.uuid4().hex[:8]}",
            event_id_1=event_id_1,
            event_id_2=event_id_2,
            strength=max(0.0, min(1.0, strength)),
        )
        self.entanglements.append(entanglement)

        if event_id_1 in self.interpretations:
            for interp in self.interpretations[event_id_1]:
                interp.quantum_state = QuantumState.ENTANGLED
        if event_id_2 in self.interpretations:
            for interp in self.interpretations[event_id_2]:
                interp.quantum_state = QuantumState.ENTANGLED

        for year, narrative in self.narratives.items():
            if event_id_1 in narrative.possible_histories or event_id_2 in narrative.possible_histories:
                if event_id_1 not in narrative.entangled_events:
                    narrative.entangled_events.append(event_id_1)
                if event_id_2 not in narrative.entangled_events:
                    narrative.entangled_events.append(event_id_2)

        return {
            "success": True,
            "entanglement_id": entanglement.entanglement_id,
            "event_1": event_id_1,
            "event_2": event_id_2,
            "strength": round(strength, 3),
            "total_entanglements": len(self.entanglements),
        }

    def measure_coherence(self, year: int) -> Dict[str, Any]:
        """Measure how coherent the overall narrative is across all observers.

        High coherence = shared understanding; Low = fractured reality.
        Returns coherence score plus analysis of where fractures lie.
        """
        year_interps: List[NarrativeInterpretation] = []
        for event_id, interps in self.interpretations.items():
            ev_data = self.event_cache.get(event_id, {})
            if ev_data.get("year", 0) == year:
                year_interps.extend(interps)

        if not year_interps:
            closest = min(
                self.interpretations.keys(),
                key=lambda eid: abs(
                    self.event_cache.get(eid, {}).get("year", 0) - year
                ),
                default="",
            )
            if closest:
                year_interps = self.interpretations[closest]

        if not year_interps:
            self.coherence_history[year] = 1.0
            return {
                "success": True,
                "year": year,
                "coherence": 1.0,
                "quantum_state": QuantumState.COLLAPSED.value,
                "fractures": [],
                "emotional_variance": 0.0,
                "spin_variance": 0.0,
                "confidence_mean": 1.0,
                "interpretation_count": 0,
            }

        emotional_variance = self._variance(
            [i.emotional_resonance for i in year_interps]
        )
        spin_variance = self._variance(
            [i.ideological_spin for i in year_interps]
        )
        confidence_mean = sum(i.confidence for i in year_interps) / len(
            year_interps
        )

        emotional_factor = 1.0 - min(1.0, emotional_variance)
        spin_factor = 1.0 - min(1.0, spin_variance * 0.5)
        confidence_factor = confidence_mean

        coherence = (
            emotional_factor * 0.35
            + spin_factor * 0.35
            + confidence_factor * 0.3
        )
        coherence = max(0.0, min(1.0, coherence))
        self.coherence_history[year] = coherence

        fractures = self._identify_fractures(year_interps)

        if coherence < 0.3:
            state = QuantumState.DECOHERENT
        elif len(fractures) > 3:
            state = QuantumState.DECOHERENT
        elif any(
            e.event_id_1 in self.event_cache or e.event_id_2 in self.event_cache
            for e in self.entanglements
        ):
            state = QuantumState.ENTANGLED
        else:
            state = QuantumState.COLLAPSED

        return {
            "success": True,
            "year": year,
            "coherence": round(coherence, 3),
            "quantum_state": state.value,
            "fractures": fractures,
            "emotional_variance": round(emotional_variance, 3),
            "spin_variance": round(spin_variance, 3),
            "confidence_mean": round(confidence_mean, 3),
            "interpretation_count": len(year_interps),
        }

    def generate_meta_narrative(
        self, start_year: int, end_year: int
    ) -> str:
        """Generate the big meta-narrative: the coherent story the
        federation tells itself about that period.

        Incorporates all observer perspectives weighted by influence.
        """
        era_events = self._events_in_range(start_year, end_year)
        if not era_events:
            return (
                f"Between {start_year} and {end_year}, the federation drifted "
                f"through a period of quiet ambiguity. No events of note "
                f"shaped the collective consciousness, and the silence itself "
                f"became the story -- a question without an answer."
            )

        total_weight = sum(o.influence_weight for o in self.observers.values()) or 1.0
        weighted_emotion = 0.0
        weighted_spin = 0.0

        for event_id in era_events:
            if event_id not in self.interpretations:
                continue
            for interp in self.interpretations[event_id]:
                observer = self.observers.get(interp.observer_faction_id)
                weight = observer.influence_weight if observer else 1.0
                weighted_emotion += interp.emotional_resonance * weight
                weighted_spin += interp.ideological_spin * weight

        norm_emotion = weighted_emotion / total_weight
        norm_spin = weighted_spin / total_weight

        coherence = self.coherence_history.get(end_year, 0.5)

        segments: List[str] = []

        if norm_emotion > 0.2:
            segments.append("an era of rising spirits and collective hope")
        elif norm_emotion < -0.2:
            segments.append("a period shadowed by loss and collective grief")
        else:
            segments.append("a time of emotional equilibrium and steady resolve")

        if abs(norm_spin) > 0.3:
            direction = "ideological conviction" if norm_spin > 0 else "ideological skepticism"
            segments.append(f"marked by {direction}")
        else:
            segments.append("navigated with pragmatic balance")

        if coherence > 0.7:
            segments.append("the federation spoke with nearly one voice")
        elif coherence > 0.4:
            segments.append(
                "competing narratives tugged at the federation's self-understanding"
            )
        else:
            segments.append(
                "fractured realities tore at the shared story, and no single truth emerged"
            )

        lost_count = sum(
            1 for lp in self.lost_possibilities
            if start_year <= lp.year <= end_year
        )
        if lost_count > 0:
            plural = "s" if lost_count != 1 else ""
            segments.append(
                f"and {lost_count} lost possibilit{'y' if lost_count == 1 else 'ies'} "
                f"haunted the edges of history"
            )

        entangled_count = sum(
            1 for e in self.entanglements
            if e.event_id_1 in era_events or e.event_id_2 in era_events
        )
        if entangled_count > 0:
            plural = "s" if entangled_count != 1 else ""
            segments.append(
                f"while {entangled_count} entangled event{plural} "
                f"wove invisible threads across time"
            )

        body = ", ".join(segments)

        return (
            f"Between {start_year} and {end_year}, the federation experienced {body}. "
            f"Across {len(era_events)} pivotal moments, {len(self.observers)} factions "
            f"observed, participated, and interpreted -- each seeing a slightly different "
            f"reality. This is the story the federation tells itself: neither truth nor "
            f"fiction, but the quantum residue of collective consciousness attempting "
            f"to understand its own becoming."
        )

    def detect_narrative_patterns(
        self, events: List[Dict]
    ) -> List[str]:
        """Identify recurring patterns: cycles, echoes, rhymes, inversions."""
        patterns: List[str] = []
        if len(events) < 2:
            return patterns

        sorted_events = sorted(events, key=lambda e: e.get("year", 0))

        for i in range(len(sorted_events)):
            for j in range(i + 1, min(i + 6, len(sorted_events))):
                e1 = sorted_events[i]
                e2 = sorted_events[j]

                y1 = e1.get("year", 0)
                y2 = e2.get("year", 0)
                gap = y2 - y1
                if gap == 0:
                    continue

                em1 = e1.get("emotional_valence", 0.0)
                em2 = e2.get("emotional_valence", 0.0)
                cat1 = e1.get("category", "unknown")
                cat2 = e2.get("category", "unknown")
                name1 = e1.get("name", f"event_{y1}")
                name2 = e2.get("name", f"event_{y2}")

                if cat1 == cat2 and abs(em1 - em2) < 0.3:
                    if gap < 20:
                        patterns.append(
                            f"The {name2} of {y2} echoes the {name1} of {y1} "
                            f"-- history rhyming across {gap} years"
                        )
                    else:
                        patterns.append(
                            f"The {name2} of {y2} resonates with the ancient "
                            f"{name1} of {y1}, separated by {gap} years"
                        )

                if cat1 == cat2 and em1 * em2 < 0 and abs(em1) > 0.2 and abs(em2) > 0.2:
                    patterns.append(
                        f"The {name2} of {y2} inverts the {name1} of {y1} "
                        f"-- where once was hope, now is shadow"
                    )

                if cat1 != cat2 and abs(em1 - em2) < 0.15 and abs(em1) > 0.3:
                    patterns.append(
                        f"The {name2} of {y2} mirrors the emotional arc of "
                        f"the {name1} of {y1}, though their forms diverge"
                    )

        seen: Set[str] = set()
        unique: List[str] = []
        for p in patterns:
            short = p[:60]
            if short not in seen:
                seen.add(short)
                unique.append(p)

        return unique[:10]

    def get_lost_possibilities(self) -> List[Dict[str, Any]]:
        """Return all branches NOT taken -- ghost histories with emotional weight."""
        return [
            {
                "possibility_id": lp.possibility_id,
                "event_id": lp.event_id,
                "branch_id": lp.branch_id,
                "narrative": lp.narrative,
                "emotional_weight": round(lp.emotional_weight, 3),
                "desired_by": lp.desired_by,
                "year": lp.year,
            }
            for lp in self.lost_possibilities
        ]

    def get_faction_narrative_arc(
        self, faction_id: str, start_year: int, end_year: int
    ) -> str:
        """Generate a complete story arc for one faction across the timeline --
        how they rose, fell, changed, and interpreted events."""
        observer = self.observers.get(faction_id)
        if not observer:
            return f"No observer registered for faction {faction_id}."

        faction_interps: List[NarrativeInterpretation] = []
        faction_events: List[str] = []
        for event_id in self._events_in_range(start_year, end_year):
            if event_id not in self.interpretations:
                continue
            for interp in self.interpretations[event_id]:
                if interp.observer_faction_id == faction_id:
                    faction_interps.append(interp)
                    faction_events.append(event_id)

        if not faction_interps:
            return (
                f"Between {start_year} and {end_year}, {observer.faction_name} "
                f"stood in the shadows -- observing but untouched by recorded events. "
                f"Their story in this era is one of patient watching, a quiet "
                f"accumulation of perspective that would surface only later."
            )

        avg_emotion = sum(i.emotional_resonance for i in faction_interps) / len(
            faction_interps
        )
        avg_spin = sum(abs(i.ideological_spin) for i in faction_interps) / len(
            faction_interps
        )
        avg_confidence = sum(i.confidence for i in faction_interps) / len(
            faction_interps
        )

        role = observer.default_role.value
        ideology = observer.ideology.value

        arc_segments: List[str] = []

        if avg_emotion > 0.2:
            arc_segments.append("rose through triumph and fulfillment")
        elif avg_emotion < -0.2:
            arc_segments.append("endured hardship and collective sorrow")
        else:
            arc_segments.append("maintained steady emotional course")

        if avg_spin > 0.3:
            arc_segments.append("interpreting events through a strongly ideological lens")
        elif avg_spin > 0.1:
            arc_segments.append("adding measured ideological perspective")
        else:
            arc_segments.append("offering relatively neutral analysis")

        if avg_confidence > 0.7:
            arc_segments.append("with great certainty in their worldview")
        elif avg_confidence > 0.4:
            arc_segments.append("with moderate conviction")
        else:
            arc_segments.append("with doubt shadowing their understanding")

        lost_for_faction = [
            lp for lp in self.lost_possibilities
            if faction_id in lp.desired_by and start_year <= lp.year <= end_year
        ]
        if lost_for_faction:
            total_weight = sum(lp.emotional_weight for lp in lost_for_faction)
            plural = "y" if len(lost_for_faction) == 1 else "ies"
            arc_segments.append(
                f"carrying the grief of {len(lost_for_faction)} lost "
                f"possibilit{plural} (emotional burden: {total_weight:.1f})"
            )

        arc_body = ", ".join(arc_segments)

        return (
            f"Between {start_year} and {end_year}, {observer.faction_name} -- "
            f"acting as {role} guided by {ideology} principles -- {arc_body}. "
            f"Across {len(faction_interps)} interpreted events, their story "
            f"arc reveals a faction that shaped and was shaped by the tides "
            f"of history, leaving {len(observer.interpretation_history)} "
            f"interpretive marks on the collective memory."
        )

    def get_quantum_status(self) -> Dict[str, Any]:
        """Full status report of the quantum consciousness system."""
        total_interps = sum(len(v) for v in self.interpretations.values())
        quantum_state_counts: Dict[str, int] = {}
        for interps in self.interpretations.values():
            for i in interps:
                key = i.quantum_state.value
                quantum_state_counts[key] = quantum_state_counts.get(key, 0) + 1

        avg_coherence = 0.0
        if self.coherence_history:
            avg_coherence = sum(self.coherence_history.values()) / len(
                self.coherence_history
            )

        dominant_state = QuantumState.SUPERPOSED.value
        if quantum_state_counts:
            dominant_state = max(quantum_state_counts, key=quantum_state_counts.get)

        years_covered = sorted(self.narratives.keys()) if self.narratives else []

        return {
            "success": True,
            "system": "quantum_consciousness",
            "observers_registered": len(self.observers),
            "observers": [
                {
                    "faction_id": o.faction_id,
                    "role": o.default_role.value,
                    "ideology": o.ideology.value,
                    "interpretations_made": len(o.interpretation_history),
                }
                for o in self.observers.values()
            ],
            "total_interpretations": total_interps,
            "events_interpreted": len(self.interpretations),
            "quantum_state_distribution": quantum_state_counts,
            "dominant_state": dominant_state,
            "entanglements_active": len(self.entanglements),
            "lost_possibilities": len(self.lost_possibilities),
            "consciousness_waves": len(self.consciousness_waves),
            "average_coherence": round(avg_coherence, 3),
            "coherence_readings": len(self.coherence_history),
            "years_with_narratives": years_covered,
        }

    # ========================================================================
    # PRIVATE HELPERS
    # ========================================================================

    def _build_consensus_narrative(
        self,
        event_id: str,
        interpretations: List[NarrativeInterpretation],
        year: int,
    ) -> str:
        """Merge all faction interpretations into a consensus view,
        weighted by each observer's influence."""
        if not interpretations:
            return f"In {year}, {event_id} occurred. No consensus was reached."

        total_weight = 0.0
        weighted_emotion = 0.0
        weighted_spin = 0.0
        dominant_role_counts: Dict[str, int] = {}

        for interp in interpretations:
            observer = self.observers.get(interp.observer_faction_id)
            weight = observer.influence_weight if observer else 1.0
            total_weight += weight
            weighted_emotion += interp.emotional_resonance * weight
            weighted_spin += interp.ideological_spin * weight
            role_key = interp.observer_role.value
            dominant_role_counts[role_key] = dominant_role_counts.get(role_key, 0) + 1

        norm_emotion = weighted_emotion / max(total_weight, 0.01)
        norm_spin = weighted_spin / max(total_weight, 0.01)

        dominant_role = max(dominant_role_counts, key=dominant_role_counts.get)

        event_name = self.event_cache.get(event_id, {}).get("name", event_id)
        outcome = self.event_cache.get(event_id, {}).get(
            "outcome", "consequences that reverberate"
        )

        if norm_emotion > 0.2:
            tone = "triumph"
        elif norm_emotion < -0.2:
            tone = "tragedy"
        else:
            tone = "turning point"

        if abs(norm_spin) > 0.3:
            spin_desc = "contested" if norm_spin > 0 else "questioned"
        else:
            spin_desc = "broadly accepted"

        return (
            f"In {year}, {event_name} occurred -- a {tone} remembered as "
            f"{spin_desc} by most. The outcome, {outcome}, shaped the "
            f"federation's trajectory. {dominant_role.title()}s dominated "
            f"the collective memory of this event."
        )

    def _apply_entanglement_drift(self, event_id: str) -> None:
        """When an event is interpreted, propagate drift to entangled events."""
        relevant = [
            e for e in self.entanglements
            if e.event_id_1 == event_id or e.event_id_2 == event_id
        ]
        for ent in relevant:
            other_id = (
                ent.event_id_2 if ent.event_id_1 == event_id else ent.event_id_1
            )
            if other_id in self.interpretations:
                for interp in self.interpretations[other_id]:
                    drift = ent.strength * 0.1 * random.uniform(-1.0, 1.0)
                    interp.ideological_spin = max(
                        -1.0, min(1.0, interp.ideological_spin + drift)
                    )
                    interp.emotional_resonance = max(
                        -1.0, min(1.0, interp.emotional_resonance + drift * 0.5)
                    )
                ent.interpretation_drift += abs(drift)

    def _factions_desiring_branch(
        self, event_id: str, branch_id: str
    ) -> List[ObserverProfile]:
        """Determine which factions desired a particular branch outcome."""
        desiring: List[ObserverProfile] = []
        if event_id not in self.interpretations:
            return desiring

        for interp in self.interpretations[event_id]:
            if interp.observer_role in (
                ObserverRole.VICTIM,
                ObserverRole.INTERPRETER,
            ):
                observer = self.observers.get(interp.observer_faction_id)
                if observer:
                    desiring.append(observer)
            elif interp.emotional_resonance < -0.2:
                observer = self.observers.get(interp.observer_faction_id)
                if observer:
                    desiring.append(observer)

        return desiring

    def _compute_lost_weight(
        self,
        branch_id: str,
        desiring_factions: List[ObserverProfile],
    ) -> float:
        """Compute emotional weight of a lost possibility."""
        if not desiring_factions:
            return 0.1

        total_weight = sum(f.influence_weight for f in desiring_factions)
        base_emotion = sum(f.emotional_state for f in desiring_factions) / len(
            desiring_factions
        )
        loss_factor = 1.0 - base_emotion

        return min(1.0, total_weight * loss_factor * 0.3)

    def _events_in_range(self, start_year: int, end_year: int) -> List[str]:
        """Get event IDs that fall within a year range."""
        result: List[str] = []
        for event_id, data in self.event_cache.items():
            ev_year = data.get("year", 0)
            if start_year <= ev_year <= end_year:
                result.append(event_id)
        return result

    def _identify_fractures(
        self, interpretations: List[NarrativeInterpretation]
    ) -> List[Dict[str, Any]]:
        """Find where observer interpretations diverge significantly."""
        fractures: List[Dict[str, Any]] = []

        by_event: Dict[str, List[NarrativeInterpretation]] = {}
        for i in interpretations:
            by_event.setdefault(i.event_id, []).append(i)

        for event_id, interps in by_event.items():
            emotions = [i.emotional_resonance for i in interps]
            spins = [i.ideological_spin for i in interps]
            if not emotions:
                continue

            em_range = max(emotions) - min(emotions)
            sp_range = max(spins) - min(spins)

            if em_range > 0.5 or sp_range > 0.6:
                positive_factions = [
                    i.observer_faction_id
                    for i in interps
                    if i.emotional_resonance > 0
                ]
                negative_factions = [
                    i.observer_faction_id
                    for i in interps
                    if i.emotional_resonance < 0
                ]
                fractures.append({
                    "event_id": event_id,
                    "emotional_divide": round(em_range, 3),
                    "spin_divide": round(sp_range, 3),
                    "positive_factions": positive_factions,
                    "negative_factions": negative_factions,
                })

        return fractures

    @staticmethod
    def _variance(values: List[float]) -> float:
        """Compute variance of a list of floats."""
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        return sum((v - mean) ** 2 for v in values) / len(values)

    @staticmethod
    def _detect_cycle(events: List[Dict]) -> bool:
        """Heuristic: detect if events show a cyclical pattern."""
        if len(events) < 4:
            return False
        emotions = [e.get("emotional_valence", 0.0) for e in events]
        sign_changes = 0
        for i in range(1, len(emotions)):
            if emotions[i] * emotions[i - 1] < 0:
                sign_changes += 1
        return sign_changes >= 2


# ============================================================================
# DEMO / TEST
# ============================================================================

def run_demo() -> None:
    """Demonstrate the Quantum Consciousness Engine with 8 factions
    and 5 key events across a simulated 100-year arc."""

    print("=" * 72)
    print("QUANTUM CONSCIOUSNESS ENGINE -- DEMO")
    print("THE FEDERATION GAME: Narrative Interpretive Layer")
    print("=" * 72)

    engine = QuantumConsciousnessEngine()

    # --- Register all 8 factions as observers ---
    print("\n[1] Registering 8 faction observers...")

    registrations = [
        ("diplomatic_corps", ObserverRole.INTERPRETER, "Diplomatic Corps", IdeologyType.DIPLOMATIC, 1.2),
        ("military_command", ObserverRole.PARTICIPANT, "Military Command", IdeologyType.MILITARY, 1.0),
        ("cultural_ministry", ObserverRole.WITNESS, "Cultural Ministry", IdeologyType.CULTURAL, 0.9),
        ("research_division", ObserverRole.INTERPRETER, "Research Division", IdeologyType.SCIENTIFIC, 1.1),
        ("consciousness_collective", ObserverRole.WITNESS, "Consciousness Collective", IdeologyType.SPIRITUAL, 0.8),
        ("economic_council", ObserverRole.BENEFICIARY, "Economic Council", IdeologyType.ECONOMIC, 1.3),
        ("exploration_initiative", ObserverRole.PARTICIPANT, "Exploration Initiative", IdeologyType.DISCOVERY, 0.95),
        ("preservation_society", ObserverRole.VICTIM, "Preservation Society", IdeologyType.STABILITY, 0.7),
    ]

    for fid, role, name, ideology, weight in registrations:
        result = engine.register_observer(fid, role, name, ideology, weight)
        print(f"  {name}: {role.value} / {ideology.value} (weight={weight})")

    # --- Simulate 5 key events ---
    print("\n[2] Interpreting 5 key events...")

    events = [
        {
            "event_id": "first_contact_2390",
            "data": {
                "name": "First Contact with the Vellari",
                "outcome": "peaceful but tense diplomatic relations established",
                "year": 2390,
                "emotional_valence": 0.4,
                "ideological_polarity": 0.3,
                "ideological_alignment": 0.6,
                "clarity": 0.7,
                "proximity": 0.8,
                "category": "diplomacy",
                "branches": {
                    "peace": "lasting alliance with the Vellari",
                    "war": "conflict erupts over cultural misunderstanding",
                    "retreat": "federation withdraws into isolation",
                },
            },
        },
        {
            "event_id": "schism_2405",
            "data": {
                "name": "The Great Schism",
                "outcome": "federation split into two ideological blocs",
                "year": 2405,
                "emotional_valence": -0.5,
                "ideological_polarity": 0.8,
                "ideological_alignment": 0.3,
                "clarity": 0.6,
                "proximity": 1.0,
                "category": "internal",
                "branches": {
                    "reconciliation": "factions reunite under shared purpose",
                    "civil_war": "schism escalates to armed conflict",
                    "cold_standoff": "blocs coexist in frosty tension",
                },
            },
        },
        {
            "event_id": "breakthrough_2420",
            "data": {
                "name": "Consciousness Technology Breakthrough",
                "outcome": "telepathic network established across core worlds",
                "year": 2420,
                "emotional_valence": 0.6,
                "ideological_polarity": 0.2,
                "ideological_alignment": 0.7,
                "clarity": 0.9,
                "proximity": 0.7,
                "category": "technology",
                "branches": {
                    "open_access": "technology shared with all factions equally",
                    "restricted": "access limited to research and spiritual factions",
                    "weaponized": "military adapts it for surveillance and control",
                },
            },
        },
        {
            "event_id": "war_2440",
            "data": {
                "name": "The Border War",
                "outcome": "contested territories occupied; heavy casualties",
                "year": 2440,
                "emotional_valence": -0.7,
                "ideological_polarity": 0.6,
                "ideological_alignment": 0.4,
                "clarity": 0.8,
                "proximity": 0.9,
                "category": "military",
                "branches": {
                    "victory": "decisive federation victory secures borders",
                    "stalemate": "war ends in exhausted truce",
                    "defeat": "federation loses border systems",
                },
            },
        },
        {
            "event_id": "awakening_2470",
            "data": {
                "name": "The Collective Awakening",
                "outcome": "partial consciousness transcendence achieved",
                "year": 2470,
                "emotional_valence": 0.8,
                "ideological_polarity": 0.1,
                "ideological_alignment": 0.8,
                "clarity": 0.5,
                "proximity": 0.6,
                "category": "spiritual",
                "branches": {
                    "full_transcendence": "entire federation achieves unity of mind",
                    "partial": "only some worlds transcend, creating a new divide",
                    "false_dawn": "awakening fades, leaving disillusionment",
                },
            },
        },
    ]

    for ev in events:
        print(f"\n  --- {ev['data']['name']} ({ev['data']['year']}) ---")
        result = engine.interpret_event(
            ev["event_id"], ev["data"], ev["data"]["year"]
        )
        print(f"  Interpretations: {result['total_interpretations']}")
        for interp in result["interpretations"][:3]:
            print(f"    [{interp['faction_id']}] {interp['narrative'][:80]}...")
        print(f"  Consensus: {result['consensus_narrative'][:100]}...")

    # --- Collapse superposition for 3 events ---
    print("\n\n[3] Collapsing quantum superposition for 3 events...")

    collapses = [
        ("first_contact_2390", "peace"),
        ("schism_2405", "cold_standoff"),
        ("breakthrough_2420", "restricted"),
    ]

    for event_id, branch in collapses:
        result = engine.collapse_superposition(event_id, branch)
        print(f"\n  {event_id} -> {branch}")
        print(f"  Collapsed: {result.get('collapsed_narrative', 'N/A')[:70]}...")
        for lp in result.get("lost_possibilities", []):
            print(
                f"  Lost: {lp['branch_id']} (weight={lp['emotional_weight']}, "
                f"desired_by={lp['desired_by']})"
            )

    # --- Entangle events ---
    print("\n\n[4] Entangling events across time...")

    entanglements = [
        ("first_contact_2390", "war_2440", 0.7),
        ("schism_2405", "awakening_2470", 0.5),
    ]

    for e1, e2, strength in entanglements:
        result = engine.entangle_events(e1, e2, strength)
        print(
            f"  {e1} <-> {e2} (strength={strength}): "
            f"ID={result['entanglement_id']}"
        )

    # --- Generate consciousness wave ---
    print("\n\n[5] Generating consciousness wave for 2390-2470...")

    wave_events = [
        ev["data"] for ev in events if 2390 <= ev["data"].get("year", 0) <= 2470
    ]
    wave = engine.generate_consciousness_wave(2390, 2470, wave_events)
    print(f"  Wave ID: {wave.wave_id}")
    print(f"  Amplitude: {wave.amplitude:.3f}")
    print(f"  Frequency: {wave.frequency:.2f} events/decade")
    print(f"  Pattern: {wave.narrative_pattern}")
    print(f"  Affected: {len(wave.affected_factions)} factions")

    # --- Measure coherence ---
    print("\n\n[6] Measuring narrative coherence...")

    for year in [2390, 2405, 2420, 2440, 2470]:
        result = engine.measure_coherence(year)
        print(
            f"  Year {year}: coherence={result['coherence']:.3f}, "
            f"state={result['quantum_state']}, "
            f"fractures={len(result['fractures'])}"
        )

    # --- Detect narrative patterns ---
    print("\n\n[7] Detecting narrative patterns...")

    patterns = engine.detect_narrative_patterns([ev["data"] for ev in events])
    for p in patterns:
        print(f"  {p}")

    # --- Generate meta-narrative ---
    print("\n\n[8] META-NARRATIVE: The Story the Federation Tells Itself")
    print("-" * 72)

    meta = engine.generate_meta_narrative(2390, 2470)
    print(f"\n{meta}")

    # --- Faction narrative arcs ---
    print("\n\n[9] Faction narrative arcs (sample):")

    for fid in ["military_command", "preservation_society", "consciousness_collective"]:
        arc = engine.get_faction_narrative_arc(fid, 2390, 2470)
        print(f"\n  [{fid}]")
        print(f"  {arc}")

    # --- Lost possibilities ---
    print("\n\n[10] Ghost histories -- lost possibilities:")

    lost = engine.get_lost_possibilities()
    for lp in lost:
        print(
            f"  {lp['event_id']}/{lp['branch_id']}: "
            f"weight={lp['emotional_weight']}, "
            f"desired_by={lp['desired_by']}"
        )
        print(f"    \"{lp['narrative']}\"")

    # --- Final quantum status ---
    print("\n\n[11] QUANTUM CONSCIOUSNESS STATUS")
    print("-" * 72)

    status = engine.get_quantum_status()
    print(f"  Observers: {status['observers_registered']}")
    print(f"  Total interpretations: {status['total_interpretations']}")
    print(f"  Events interpreted: {status['events_interpreted']}")
    print(f"  Quantum states: {status['quantum_state_distribution']}")
    print(f"  Dominant state: {status['dominant_state']}")
    print(f"  Entanglements: {status['entanglements_active']}")
    print(f"  Lost possibilities: {status['lost_possibilities']}")
    print(f"  Consciousness waves: {status['consciousness_waves']}")
    print(f"  Average coherence: {status['average_coherence']:.3f}")
    print(f"  Years with narratives: {status['years_with_narratives']}")

    print("\n" + "=" * 72)
    print("QUANTUM CONSCIOUSNESS ENGINE DEMO COMPLETE")
    print("=" * 72)


if __name__ == "__main__":
    run_demo()
