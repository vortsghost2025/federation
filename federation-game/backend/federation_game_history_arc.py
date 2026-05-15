#!/usr/bin/env python3
"""
THE FEDERATION GAME - HISTORY ARC ORCHESTRATOR
~900 LOC - Integration Module

Wires together the Timeline Engine, Quantum Consciousness Engine,
Faction System, and Game State into a unified HistoryArcOrchestrator
that drives the 100-year simulation (2387-2487).

This is the master conductor: timeline provides the raw history,
consciousness provides the interpretive layer, factions provide
the ideological scaffolding, and game state provides the persistent
backbone. Together they produce the emergent story of a federation
across a century of triumph, tragedy, and transcendence.
"""

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

from federation_game_timeline import (
    TimelineEngine,
    TimelineEra,
    TimelineEvent,
    FactionSnapshot,
    HistoricalMemory,
    NarrativeMemoryTracker,
    seed_timeline_events,
)
from federation_game_quantum_consciousness import (
    QuantumConsciousnessEngine,
    ObserverRole,
    QuantumState,
    NarrativeInterpretation,
    FactionInterpretationEngine,
    IdeologyType as QCIdeologyType,
    ObserverProfile,
    ConsciousnessWave,
    LostPossibility,
    EventEntanglement,
    QuantumNarrative,
    NarrativePattern,
)
from federation_game_factions import (
    FactionSystem,
    Faction,
    IdeologyType as FactionIdeologyType,
    build_faction_system,
    get_faction_report,
    BonusType,
    QuestType,
)
from federation_game_state import (
    GameState as FederationGameState,
    FederationCoreState,
    SubsystemState,
    GamePhase as StateGamePhase,
    VictoryType,
    GameStatistics,
)
from federation_game_events import (
    EventType as EventEngineType,
    EventSeverity,
    GameEvent,
    GameEffect,
    EffectType,
    GameChoice,
)

from federation_game_technology_integration import TechnologyEngine
from federation_game_quest_integration import QuestEngine
from federation_game_political_integration import PoliticalEngine
from federation_game_npc_integration import NPCSystemAdapter


# ============================================================================
# MODULE-LEVEL CONSTANTS
# ============================================================================

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

ENABLE_TECHNOLOGY_TREE = True
ENABLE_QUEST_SYSTEM = True
ENABLE_POLITICAL_SYSTEM = True
ENABLE_NPC_SYSTEM = True

FACTION_IDEOLOGY_MAP = {
    "diplomatic_corps": "diplomatic",
    "military_command": "military",
    "cultural_ministry": "cultural",
    "research_division": "scientific",
    "consciousness_collective": "spiritual",
    "economic_council": "economic",
    "exploration_initiative": "discovery",
    "preservation_society": "stability",
}

_FACTION_IDEOLOGY_TO_QC: Dict[str, QCIdeologyType] = {
    "diplomatic": QCIdeologyType.DIPLOMATIC,
    "military": QCIdeologyType.MILITARY,
    "cultural": QCIdeologyType.CULTURAL,
    "scientific": QCIdeologyType.SCIENTIFIC,
    "spiritual": QCIdeologyType.SPIRITUAL,
    "economic": QCIdeologyType.ECONOMIC,
    "discovery": QCIdeologyType.DISCOVERY,
    "stability": QCIdeologyType.STABILITY,
}

_FACTION_IDEOLOGY_TO_FACTION: Dict[str, FactionIdeologyType] = {
    "diplomatic": FactionIdeologyType.DIPLOMATIC,
    "military": FactionIdeologyType.MILITARY,
    "cultural": FactionIdeologyType.CULTURAL,
    "scientific": FactionIdeologyType.SCIENTIFIC,
    "spiritual": FactionIdeologyType.SPIRITUAL,
    "economic": FactionIdeologyType.ECONOMIC,
    "discovery": FactionIdeologyType.DISCOVERY,
    "stability": FactionIdeologyType.STABILITY,
}

OBSERVER_FACTION_MAP: Dict[str, Tuple[ObserverRole, QCIdeologyType]] = {
    "diplomatic_corps": (ObserverRole.INTERPRETER, QCIdeologyType.DIPLOMATIC),
    "military_command": (ObserverRole.PARTICIPANT, QCIdeologyType.MILITARY),
    "cultural_ministry": (ObserverRole.WITNESS, QCIdeologyType.CULTURAL),
    "research_division": (ObserverRole.INTERPRETER, QCIdeologyType.SCIENTIFIC),
    "consciousness_collective": (ObserverRole.WITNESS, QCIdeologyType.SPIRITUAL),
    "economic_council": (ObserverRole.BENEFICIARY, QCIdeologyType.ECONOMIC),
    "exploration_initiative": (ObserverRole.PARTICIPANT, QCIdeologyType.DISCOVERY),
    "preservation_society": (ObserverRole.VICTIM, QCIdeologyType.STABILITY),
}


# ============================================================================
# HISTORY ARC REPORT DATACLASS
# ============================================================================

@dataclass
class HistoryArcReport:
    """Summary report of the 100-year history arc simulation."""

    total_years_simulated: int
    events_generated: int
    branch_points_encountered: int
    lost_possibilities_created: int
    final_faction_states: Dict[str, Dict[str, Any]]
    coherence_trajectory: Dict[int, float]
    era_summaries: Dict[str, str]
    dominant_quantum_state: str
    simulation_complete: bool
    narrative_patterns: List[str]
    technology_summary: Dict[str, Any] = field(default_factory=dict)
    quest_summary: Dict[str, Any] = field(default_factory=dict)
    political_summary: Dict[str, Any] = field(default_factory=dict)
    npc_summary: Dict[str, Any] = field(default_factory=dict)
    rival_summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_years_simulated": self.total_years_simulated,
            "events_generated": self.events_generated,
            "branch_points_encountered": self.branch_points_encountered,
            "lost_possibilities_created": self.lost_possibilities_created,
            "final_faction_states": self.final_faction_states,
            "coherence_trajectory": {
                str(k): round(v, 4) for k, v in self.coherence_trajectory.items()
            },
            "era_summaries": self.era_summaries,
            "dominant_quantum_state": self.dominant_quantum_state,
            "simulation_complete": self.simulation_complete,
            "narrative_patterns": self.consciousness.detect_narrative_patterns(self._collect_event_data_for_patterns()) if hasattr(self.consciousness, "detect_narrative_patterns") else [],
        "technology_summary": self.technology_summary,
        "quest_summary": self.quest_summary,
            "political_summary": self.political_summary,
        "npc_summary": self.npc_summary,
        "rival_summary": self.rival_summary,
        }

    def display(self) -> str:
        lines = [
            "=" * 72,
            "  HISTORY ARC SIMULATION REPORT",
            "=" * 72,
            "",
            f"  Years Simulated:       {self.total_years_simulated}",
            f"  Events Generated:      {self.events_generated}",
            f"  Branch Points:         {self.branch_points_encountered}",
            f"  Lost Possibilities:    {self.lost_possibilities_created}",
            f"  Dominant Quantum State: {self.dominant_quantum_state}",
            f"  Simulation Complete:   {self.simulation_complete}",
            "",
            "-" * 72,
            "  ERA SUMMARIES",
            "-" * 72,
        ]

        for era_name, narrative in self.era_summaries.items():
            lines.append(f"\n  [{era_name.upper()}]")
            wrapped = self._wrap_text(narrative, width=68, indent=4)
            lines.append(wrapped)

        lines.append("")
        lines.append("-" * 72)
        lines.append("  FINAL FACTION STATES")
        lines.append("-" * 72)

        for fid, fstate in self.final_faction_states.items():
            power = fstate.get("power", 0.0)
            rep = fstate.get("reputation", 0.0)
            stab = fstate.get("stability", 0.0)
            inf = fstate.get("influence", 0.0)
            drift = fstate.get("ideology_drift", 0.0)
            lines.append(
                f"  {fid:28} P:{power:.2f} R:{rep:.2f} "
                f"I:{inf:.2f} S:{stab:.2f} Drift:{drift:+.2f}"
            )

        if self.narrative_patterns:
            lines.append("")
            lines.append("-" * 72)
            lines.append("  NARRATIVE PATTERNS DETECTED")
            lines.append("-" * 72)
            for pattern in self.narrative_patterns[:8]:
                lines.append(f"  - {pattern}")

        # Technology summary
        if self.technology_summary:
            lines.append("")
            lines.append("-" * 72)
            lines.append("  TECHNOLOGY PROGRESSION")
            lines.append("-" * 72)
            summary = self.technology_summary
            lines.append(f"  Techs Completed:       {summary.get('techs_completed', 0)}")
            lines.append(f"  Max Tier Reached:      Tier {summary.get('max_tier_reached', 0)}")
            if summary.get('eras'):
                lines.append(f"  Eras Covered:          {', '.join(summary['eras'])}")
            if summary.get('philosophies_explored'):
                lines.append(f"  Philosophies:          {', '.join(summary['philosophies_explored'])}")
            lines.append(f"  Current Tech Level:    {summary.get('tech_level', 0.2):.3f} / 1.0")
            research_points = summary.get('research_points_available', 0)
            lines.append(f"  Research Points Bank:  {research_points:,.0f}")
        # Quests summary
        if self.quest_summary:
            lines.append("")
            lines.append("-" * 72)
            lines.append("  QUEST ACTIVITY")
            lines.append("-" * 72)
            qsummary = self.quest_summary
            lines.append(f"  Quests Completed:      {qsummary.get('quests_completed', 0)}")
            if qsummary.get('completed_ids'):
                lines.append(f"  Completed Quest IDs:   {', '.join(qsummary['completed_ids'][:5])}")
            total_avail = qsummary.get('total_quests_available', 0)
            lines.append(f"  Total Quests Available: {total_avail}")
        # NPC advisor summary
        if self.npc_summary:
            lines.append("")
            lines.append("-" * 72)
            lines.append("  NPC ADVISORS")
            lines.append("-" * 72)
            nsummary = self.npc_summary
            lines.append(f"  Total Advisors:        {nsummary.get('total_advisors', 0)}")
            # Show per-faction counts
            faction_counts = nsummary.get('faction_counts', {})
            if faction_counts:
                for fid, cnt in sorted(faction_counts.items()):
                    lines.append(f"    {fid}: {cnt} advisor(s)")

        coherence_vals = list(self.coherence_trajectory.values())

        # Political summary
        if self.political_summary:
            lines.append("")
            lines.append("-" * 72)
            lines.append(" POLITICAL CLIMATE")
            lines.append("-" * 72)
            psum = self.political_summary
            lines.append(f" Laws Passed: {psum.get('laws_passed_count', 0)}")
            if psum.get('recent_laws'):
                lines.append(" Recent Enactments:")
                for law in psum['recent_laws'][:3]:
                    lines.append(f" - {law['law_name']} ({law['law_id']}): {law['description']}")
                    for k, v in law.get('effects', {}).items():
                        lines.append(f" {k}: {v:+.2f}")
        if coherence_vals:
            avg_coh = sum(coherence_vals) / len(coherence_vals)
            min_coh = min(coherence_vals)
            max_coh = max(coherence_vals)
            lines.append("")
            lines.append("-" * 72)
            lines.append("  COHERENCE TRAJECTORY")
            lines.append("-" * 72)
            lines.append(f"  Average: {avg_coh:.3f}  Min: {min_coh:.3f}  Max: {max_coh:.3f}")

        lines.append("")
        lines.append("=" * 72)
        return "\n".join(lines)

    @staticmethod
    def _wrap_text(text: str, width: int = 68, indent: int = 4) -> str:
        prefix = " " * indent
        words = text.split()
        current_line = prefix
        result_lines: List[str] = []
        for word in words:
            if len(current_line) + 1 + len(word) > width + indent:
                result_lines.append(current_line)
                current_line = prefix + word
            else:
                if current_line == prefix:
                    current_line += word
                else:
                    current_line += " " + word
        if current_line.strip():
            result_lines.append(current_line)
        return "\n".join(result_lines)


# ============================================================================
# HISTORY ARC ORCHESTRATOR
# ============================================================================

class HistoryArcOrchestrator:
    """Master orchestrator that wires together Timeline, Consciousness,
    Factions, and Game State to drive the 100-year history arc simulation.

    Each year:
      1. Timeline advances (faction drift, events, memory decay)
      2. Events are interpreted through quantum consciousness
      3. Branch points collapse into a single history (lost possibilities recorded)
      4. Game state syncs with the evolving federation
      5. Coherence is measured across all observers
    """

    OBSERVER_FACTION_MAP = OBSERVER_FACTION_MAP  # Reference module-level constant

    def __init__(self):
        self.timeline: TimelineEngine = TimelineEngine()
        self.consciousness: QuantumConsciousnessEngine = QuantumConsciousnessEngine()
        self.faction_system: FactionSystem = build_faction_system()
        self.game_state: FederationGameState = FederationGameState()
        self.current_era: Optional[TimelineEra] = None
        self.choice_ledger: List[Dict[str, Any]] = []
        self._initialized: bool = False
        self.technology: Optional[TechnologyEngine] = None
        self.quest_engine: Optional[QuestEngine] = None
        self.npc_engine: Optional[NPCSystemAdapter] = None
        self.political_engine: Optional[PoliticalEngine] = None
        self.rival_simulator = None
        self.chaosbringer = None

    # ====================================================================
    # INITIALIZE
    # ====================================================================

    def initialize(self) -> Dict[str, Any]:
        """Initialize all subsystems and prepare the 100-year simulation.

        Steps:
          1. Initialize faction states in timeline
          2. Register all 8 observers in quantum consciousness
          3. Load seed events into timeline
          4. Mark orchestrator as initialized

        Returns:
            Dict with initialization summary
        """
        if self._initialized:
            return {
                "success": True,
                "already_initialized": True,
                "faction_ids": FACTION_IDS,
                "observers_registered": len(self.consciousness.observers),
            }

        # Step 1: Initialize faction states in timeline
        timeline_init = self.timeline.initialize_faction_states(FACTION_IDS)

        # Step 2: Register all 8 observers in quantum consciousness
        observers_registered = 0
        for faction_id, (role, qc_ideology) in self.OBSERVER_FACTION_MAP.items():
            faction_obj = self.faction_system.factions.get(faction_id)
            faction_name = faction_obj.name if faction_obj else faction_id.replace("_", " ").title()
            reg_result = self.consciousness.register_observer(
                faction_id=faction_id,
                default_role=role,
                faction_name=faction_name,
                ideology=qc_ideology,
                influence_weight=1.0,
            )
            if reg_result.get("success"):
                observers_registered += 1

        # Step 3: Load seed events
        seed_events = seed_timeline_events()
        seed_result = self.timeline.load_seed_events(seed_events)

        # Step 4: Set initialized
        self._initialized = True
        # Initialize technology engine
        if ENABLE_TECHNOLOGY_TREE:
            self.technology = TechnologyEngine(treasury=self.game_state.federation.treasury)
        # Initialize quest engine
        if ENABLE_QUEST_SYSTEM:
            self.quest_engine = QuestEngine()
            self.quest_engine.initialize()
        # Initialize NPC system
        if ENABLE_NPC_SYSTEM:
            self.npc_engine = NPCSystemAdapter(FACTION_IDS)
            self.npc_engine.initialize()
        # Initialize political engine
        if ENABLE_POLITICAL_SYSTEM:
            self.political_engine = PoliticalEngine(FACTION_IDS, self.game_state.federation)
            self.political_engine.initialize()
        # Initialize rival simulator
        try:
            from federation_game_rival_simulator import RivalFederationSimulator
            self.rival_simulator = RivalFederationSimulator()
            init_result = self.rival_simulator.initialize_rivals()
            if self.consciousness and init_result.get("success"):
                for obs in self.rival_simulator.get_rival_observers():
                    try:
                        self.consciousness.register_observer(**obs)
                    except Exception:
                        pass
        except ImportError:
            self.rival_simulator = None
        # Initialize Chaosbringer consciousness
        try:
            from uss_chaosbringer_consciousness import FederationConsciousnessEngine
            self.chaosbringer = FederationConsciousnessEngine(
                qc_engine=self.consciousness,
                rival_simulator=self.rival_simulator,
            )
            self.chaosbringer.initialize_bridge()
        except ImportError:
            self.chaosbringer = None
        self.current_era = TimelineEra.from_year(self.timeline.current_year)

        return {
            "success": True,
            "already_initialized": False,
            "timeline_factions": timeline_init.get("factions_initialized", 0),
            "observers_registered": observers_registered,
            "seed_events_loaded": seed_result.get("seed_events_loaded", 0),
            "seed_years": seed_result.get("seed_years", []),
            "faction_ids": FACTION_IDS,
            "current_year": self.timeline.current_year,
            "current_era": self.current_era.value if self.current_era else None,
        }

    # ====================================================================
    # ADVANCE YEAR (Core Simulation Step)
    # ====================================================================

    def advance_year(self) -> Dict[str, Any]:
        """Advance one year of the simulation.

        Steps:
          1. Advance the timeline engine
          2. Detect era transitions
          3. If an event occurred this year:
             a. Build event_data and interpret through consciousness
             b. If branch point, auto-collapse to first branch
          4. Measure coherence
          5. Sync game state from timeline faction averages

        Returns:
            Dict with year summary augmented with quantum data
        """
        if not self._initialized:
            return {
                "success": False,
                "error": "Orchestrator not initialized. Call initialize() first.",
            }

        # Step 1: Advance timeline
        year_record = self.timeline.advance_year()
        year = year_record.get("year", self.timeline.current_year - 1)

        # Step 2: Detect era transition
        new_era = TimelineEra.from_year(year)
        era_changed = False
        if self.current_era is None or new_era != self.current_era:
            era_changed = True
            self.current_era = new_era

        # Step 3: Process event if one occurred
        quantum_interpretation = None
        coherence_result = None
        event_data_out = None

        event_dict = year_record.get("event")
        if event_dict is not None:
            event_id = event_dict.get("event_id", f"ev_{year}")
            event_data = self._build_event_data(event_dict, year)

            # 3a: Interpret event through consciousness
            interp_result = self.consciousness.interpret_event(
                event_id, event_data, year
            )
            quantum_interpretation = {
                "event_id": event_id,
                "total_interpretations": interp_result.get("total_interpretations", 0),
                "consensus_narrative": interp_result.get("consensus_narrative", ""),
                "interpretation_summary": [
                    {
                        "faction_id": i.get("faction_id"),
                        "role": i.get("role"),
                        "emotional_resonance": i.get("emotional_resonance"),
                        "ideological_spin": i.get("ideological_spin"),
                    }
                    for i in interp_result.get("interpretations", [])
                ],
            }

            # 3b: If branch point, auto-collapse to first branch
            branches = event_data.get("branches")
            if branches and isinstance(branches, dict) and len(branches) > 0:
                primary_branch_key = next(iter(branches.keys()))
                collapse_result = self.consciousness.collapse_superposition(
                    event_id, primary_branch_key
                )
                self.choice_ledger.append({
                    "event_id": event_id,
                    "year": year,
                    "branch_chosen": primary_branch_key,
                    "collapsed_narrative": collapse_result.get("collapsed_narrative", ""),
                    "lost_possibilities": collapse_result.get("lost_possibilities", []),
                    "auto_collapsed": True,
                    "timestamp": datetime.now().isoformat(),
                })

            event_data_out = {
                "event_id": event_id,
                "name": event_data.get("name", ""),
                "outcome": event_data.get("outcome", ""),
                "year": year,
                "branch_point": event_dict.get("branch_point", False),
                "branches": event_dict.get("branches", {}),
            }

        # Step 4: Measure coherence
        coherence_result = self.consciousness.measure_coherence(year)

        # Step 5: Sync game state from timeline faction averages
        self._sync_game_state(year_record)

        # Process technology research
        if self.technology:
            completed = self.technology.process_year(year, self.game_state.federation.treasury)
            if completed:
                for tech_id in completed:
                    self.choice_ledger.append({"year": year, "type": "technology_completion", "tech_id": tech_id})
            # Apply technology level to federation state
            self.game_state.federation.technological_level = self.technology.technological_level

        # Process quest system for this year
        if self.quest_engine:
            rewards_list = self.quest_engine.process_year(year, self.game_state)
            if rewards_list:
                self.quest_engine.apply_rewards(rewards_list, self.game_state.federation)
                for reward_info in rewards_list:
                    self.choice_ledger.append({
                        "year": year,
                        "type": "quest_completion",
                        "quest_id": reward_info.get('quest_id'),
                        "quest_title": reward_info.get('quest_title'),
                        "rewards_applied": reward_info.get('rewards')
                    })
        # Process NPC system for this year
        if self.npc_engine:
            modifiers = self.npc_engine.process_year(year, self.game_state)
            if modifiers:
                if 'morale_delta' in modifiers:
                    self.game_state.federation.morale = max(0.0, min(1.0,
                        self.game_state.federation.morale + modifiers['morale_delta']
                    ))
            if 'identity_delta' in modifiers:
                self.game_state.federation.identity_strength = max(0.0, min(1.0,
                    self.game_state.federation.identity_strength + modifiers['identity_delta']
                ))

        # Rival simulator
        rival_actions = {}
        if self.rival_simulator:
            rival_actions = self.rival_simulator.act_all_rivals(year)
            self.rival_simulator.advance_year()

        # Chaosbringer consciousness overlay
        chaosbringer_report = {}
        if self.chaosbringer:
            chaosbringer_report = self.chaosbringer.process_year(year)


        # Process political system
        if self.political_engine:
            laws = self.political_engine.process_year(year, self.game_state.federation)
            if laws:
                self.game_state.political_data = self.political_engine.summary
                for law in laws:
                    self.choice_ledger.append({
                        "year": year,
                        "type": "law_passed",
                        "law_id": law["law_id"],
                        "law_name": law["law_name"],
                        "effects": law["effects"]
                    })
        return {
            "success": True,
            "year": year,
            "era": new_era.value,
            "era_changed": era_changed,
            "event": event_data_out,
            "quantum_interpretation": quantum_interpretation,
            "coherence": coherence_result.get("coherence", 1.0) if coherence_result else 1.0,
            "quantum_state": coherence_result.get("quantum_state", "collapsed") if coherence_result else "collapsed",
            "average_stability": year_record.get("average_stability", 0.5),
            "rival_actions": rival_actions,
            "chaosbringer_report": chaosbringer_report,
        }

    # ====================================================================
    # RUN SIMULATION
    # ====================================================================

    def run_simulation(
        self, start_year: int = 2387, end_year: int = 2487
    ) -> HistoryArcReport:
        """Run the full 100-year history arc simulation.

        Args:
            start_year: First year of simulation (default 2387)
            end_year: Final year of simulation (exclusive, default 2487)

        Returns:
            HistoryArcReport with complete simulation results
        """
        if not self._initialized:
            self.initialize()

        current_year = self.timeline.current_year

        # Run year-by-year simulation
        events_count = 0
        branch_count = 0
        for _ in range(end_year - current_year):
            result = self.advance_year()
            if not result.get("success"):
                break
            if result.get("event"):
                events_count += 1
            event = result.get("event")
            if event and event.get("branch_point"):
                branch_count += 1

        # Generate consciousness waves for each era
        self._generate_era_consciousness_waves()

        # Build era summaries
        era_summaries: Dict[str, str] = {}
        for era in TimelineEra:
            era_start, era_end = era.year_range
            meta_narrative = self.consciousness.generate_meta_narrative(
                era_start, era_end
            )
            era_summaries[era.value] = meta_narrative

        # Build final faction states
        final_faction_states: Dict[str, Dict[str, Any]] = {}
        for fid, snap in self.timeline.faction_states.items():
            final_faction_states[fid] = snap.to_dict()

        # Coherence trajectory
        coherence_trajectory: Dict[int, float] = dict(
            self.consciousness.coherence_history
        )

        # Dominant quantum state
        quantum_status = self.consciousness.get_quantum_status()
        dominant_quantum_state = quantum_status.get("dominant_state", "collapsed")

        # Narrative patterns from all events
        all_events_for_patterns = self._collect_event_data_for_patterns()
        narrative_patterns = self.consciousness.detect_narrative_patterns(
            all_events_for_patterns
        )

        # Count lost possibilities
        lost_possibilities_count = len(self.consciousness.lost_possibilities)

        # Total events includes both seed and procedural
        total_events = len(self.timeline.event_history)

        technology_summary = {}
        if self.technology:
            technology_summary = self.technology.summary

        quest_summary = {}
        if self.quest_engine:
            quest_summary = self.quest_engine.summary

        political_summary = {}
        if self.political_engine:
            political_summary = self.political_engine.summary

        npc_summary = {}
        if self.npc_engine:
            npc_summary = self.npc_engine.summary

        rival_summary = {}
        if self.rival_simulator:
            rival_summary = self.rival_simulator.get_threat_assessment()

        return HistoryArcReport(
            total_years_simulated=end_year - start_year,
            events_generated=total_events,
            branch_points_encountered=branch_count,
            lost_possibilities_created=lost_possibilities_count,
            final_faction_states=final_faction_states,
            coherence_trajectory=coherence_trajectory,
            era_summaries=era_summaries,
            dominant_quantum_state=dominant_quantum_state,
            simulation_complete=True,
            narrative_patterns=narrative_patterns,
            technology_summary=technology_summary,
            quest_summary=quest_summary,
            political_summary=political_summary,
            npc_summary=npc_summary,
            rival_summary=rival_summary,
        )

    # ====================================================================
    # GET STATUS
    # ====================================================================

    def get_status(self) -> Dict[str, Any]:
        """Return comprehensive status combining all subsystem states.

        Returns:
            Dict with timeline, consciousness, game state, and choice ledger info
        """
        timeline_status = {
            "current_year": self.timeline.current_year,
            "era": self.current_era.value if self.current_era else None,
            "event_count": len(self.timeline.event_history),
            "faction_count": len(self.timeline.faction_states),
        }

        quantum_status = self.consciousness.get_quantum_status()
        consciousness_summary = {
            "observer_count": quantum_status.get("observers_registered", 0),
            "total_interpretations": quantum_status.get("total_interpretations", 0),
            "coherence": quantum_status.get("average_coherence", 0.0),
            "lost_possibilities_count": quantum_status.get("lost_possibilities", 0),
        }

        game_summary = self.game_state.get_game_summary()
        game_core = game_summary.get("game_summary", {}).get("federation_core", {})
        game_status = {
            "turn": self.game_state.statistics.current_turn,
            "phase": self.game_state.game_phase.value,
            "morale": game_core.get("morale", 0.5),
            "stability": game_core.get("stability", 0.5),
        }

        return {
            "success": True,
            "timeline": timeline_status,
            "consciousness": consciousness_summary,
            "game_state": game_status,
            "choice_ledger_count": len(self.choice_ledger),
            "technology": self.technology.summary if self.technology else None,
            "quest_engine": self.quest_engine.summary if self.quest_engine else None,
            "npc_engine": self.npc_engine.summary if self.npc_engine else None,
            "political_engine": self.political_engine.summary if self.political_engine else None,
            "rival_summary": self.rival_simulator.get_threat_assessment() if self.rival_simulator else None,
            "chaosbringer_status": self.chaosbringer.get_bridge_status() if self.chaosbringer else None,
        }

    # ====================================================================
    # RESOLVE BRANCH POINT (Manual)
    # ====================================================================

    def resolve_branch_point(
        self, event_id: str, branch_key: str
    ) -> Dict[str, Any]:
        """Manually resolve a branch-point event instead of auto-collapse.

        Args:
            event_id: The event to resolve
            branch_key: The branch to choose

        Returns:
            Dict with collapse result and ledger recording
        """
        collapse_result = self.consciousness.collapse_superposition(
            event_id, branch_key
        )

        if not collapse_result.get("success"):
            return {
                "success": False,
                "error": collapse_result.get("error", f"Failed to collapse {event_id}"),
            }

        event_data = self.consciousness.event_cache.get(event_id, {})
        year = event_data.get("year", 0)

        ledger_entry = {
            "event_id": event_id,
            "year": year,
            "branch_chosen": branch_key,
            "collapsed_narrative": collapse_result.get("collapsed_narrative", ""),
            "lost_possibilities": collapse_result.get("lost_possibilities", []),
            "auto_collapsed": False,
            "timestamp": datetime.now().isoformat(),
        }
        self.choice_ledger.append(ledger_entry)

        return {
            "success": True,
            "event_id": event_id,
            "branch_chosen": branch_key,
            "collapsed_narrative": collapse_result.get("collapsed_narrative", ""),
            "lost_possibilities_created": len(collapse_result.get("lost_possibilities", [])),
            "ledger_entry": ledger_entry,
        }

    # ====================================================================
    # EXPORT / IMPORT FULL STATE
    # ====================================================================

    def export_full_state(self) -> Dict[str, Any]:
        state = {
            "timeline": self.timeline.export_timeline(),
            "consciousness": self.consciousness.get_quantum_status(),
            "faction_states": {fid: self.faction_system.get_faction_status(fid) for fid in FACTION_IDS},
            "narrative_patterns": self.consciousness.detect_narrative_patterns(self._collect_event_data_for_patterns()) if hasattr(self.consciousness, "detect_narrative_patterns") else [],
            "statistics": asdict(self.game_state.statistics) if self.game_state.statistics else {},
            "current_era": self.current_era.value if self.current_era else None,
        "choice_ledger": self.choice_ledger,
            "coherence_trajectory": dict(self.consciousness.coherence_history),
            "game_state": self.game_state.get_game_summary() if self.game_state else {},
        }
        # Adapter state snapshots
        try:
            state["technology"] = self.technology.summary if self.technology else {}
        except Exception:
            state["technology"] = {}
        try:
            state["quest_engine"] = self.quest_engine.summary if self.quest_engine else {}
        except Exception:
            state["quest_engine"] = {}
        try:
            state["npc_engine"] = self.npc_engine.summary if self.npc_engine else {}
        except Exception:
            state["npc_engine"] = {}
        try:
            state["political_engine"] = self.political_engine.summary if self.political_engine else {}
        except Exception:
            state["political_engine"] = {}
        return state

    def import_full_state(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Restore orchestrator from a previously exported state.

        Args:
            data: Previously exported orchestrator state dict

        Returns:
            Dict with import results for each subsystem
        """
        results: Dict[str, Any] = {"success": True}

        # Restore timeline
        timeline_data = data.get("timeline", {})
        timeline_result = self.timeline.import_timeline(timeline_data)
        results["timeline_restored"] = timeline_result

        # Restore era
        era_str = data.get("current_era") or data.get("metadata", {}).get("current_era")
        if era_str:
            try:
                self.current_era = TimelineEra(era_str)
            except ValueError:
                self.current_era = TimelineEra.from_year(self.timeline.current_year)
        else:
            self.current_era = TimelineEra.from_year(self.timeline.current_year)

        # Restore consciousness observers
        raw_observers = data.get("consciousness", {}).get("observers", {})
        restored_observers = 0
        self.consciousness.observers = {}
        # Export format is a list of dicts; convert to dict keyed by faction_id
        if isinstance(raw_observers, list):
            for obs_data in raw_observers:
                fid = obs_data.get("faction_id", "")
                if not fid:
                    continue
                role = ObserverRole(obs_data.get("role", obs_data.get("default_role", "interpreter")))
                ideology_str = obs_data.get("ideology", "diplomatic")
                ideology = _FACTION_IDEOLOGY_TO_QC.get(ideology_str, QCIdeologyType.DIPLOMATIC)
                observer = ObserverProfile(
                    faction_id=fid,
                    faction_name=obs_data.get("faction_name", fid),
                    default_role=role,
                    ideology=ideology,
                    influence_weight=obs_data.get("influence_weight", 1.0),
                    emotional_state=obs_data.get("emotional_state", 0.5),
                    interpretation_history=obs_data.get("interpretation_history", []),
                )
                self.consciousness.observers[fid] = observer
                restored_observers += 1
        elif isinstance(raw_observers, dict):
            for fid, obs_data in raw_observers.items():
                role = ObserverRole(obs_data.get("default_role", obs_data.get("role", "interpreter")))
                ideology_str = obs_data.get("ideology", "diplomatic")
                ideology = _FACTION_IDEOLOGY_TO_QC.get(ideology_str, QCIdeologyType.DIPLOMATIC)
                observer = ObserverProfile(
                    faction_id=obs_data.get("faction_id", fid),
                    faction_name=obs_data.get("faction_name", fid),
                    default_role=role,
                    ideology=ideology,
                    influence_weight=obs_data.get("influence_weight", 1.0),
                    emotional_state=obs_data.get("emotional_state", 0.5),
                    interpretation_history=obs_data.get("interpretation_history", []),
                )
                self.consciousness.observers[fid] = observer
                restored_observers += 1
        results["observers_restored"] = restored_observers

        # Restore consciousness interpretations
        interpretations_data = data.get("consciousness", {}).get("interpretations", {})
        restored_interpretations = 0
        self.consciousness.interpretations = {}
        for event_id, interp_list in interpretations_data.items():
            parsed_interps: List[NarrativeInterpretation] = []
            for i_data in interp_list:
                interp = NarrativeInterpretation(
                    interpretation_id=i_data.get("interpretation_id", ""),
                    event_id=i_data.get("event_id", event_id),
                    observer_faction_id=i_data.get("observer_faction_id", ""),
                    observer_role=ObserverRole(i_data.get("observer_role", "interpreter")),
                    narrative=i_data.get("narrative", ""),
                    emotional_resonance=i_data.get("emotional_resonance", 0.0),
                    ideological_spin=i_data.get("ideological_spin", 0.0),
                    confidence=i_data.get("confidence", 0.5),
                    quantum_state=QuantumState(i_data.get("quantum_state", "collapsed")),
                )
                parsed_interps.append(interp)
                restored_interpretations += 1
            self.consciousness.interpretations[event_id] = parsed_interps
        results["interpretations_restored"] = restored_interpretations

        # Restore lost possibilities
        lost_raw = data.get("consciousness", {}).get("lost_possibilities", [])
        self.consciousness.lost_possibilities = []
        if isinstance(lost_raw, list) and lost_raw and isinstance(lost_raw[0], dict):
            # Full format: list of LostPossibility dicts
            for lp_data in lost_raw:
                lp = LostPossibility(
                    possibility_id=lp_data.get("possibility_id", ""),
                    event_id=lp_data.get("event_id", ""),
                    branch_id=lp_data.get("branch_id", ""),
                    narrative=lp_data.get("narrative", ""),
                    emotional_weight=lp_data.get("emotional_weight", 0.0),
                    desired_by=lp_data.get("desired_by", []),
                    year=lp_data.get("year", 0),
                )
                self.consciousness.lost_possibilities.append(lp)
        # If lost_raw is an integer count or empty list, we keep the existing
        # lost_possibilities (already cleared above) — no action needed
        results["lost_possibilities_restored"] = len(self.consciousness.lost_possibilities)

        # Restore coherence history (export uses top-level "coherence_trajectory" key)
        coh_data = data.get("coherence_trajectory") or data.get("consciousness", {}).get("coherence_history", {})
        self.consciousness.coherence_history = {
            int(y): float(c) for y, c in coh_data.items()
        }
        results["coherence_readings_restored"] = len(self.consciousness.coherence_history)

        # Restore event cache
        cache_data = data.get("consciousness", {}).get("event_cache", {})
        self.consciousness.event_cache = dict(cache_data)
        results["event_cache_restored"] = len(self.consciousness.event_cache)

        # Restore choice ledger
        self.choice_ledger = data.get("choice_ledger", [])
        results["choice_ledger_restored"] = len(self.choice_ledger)

        # Restore narrative patterns
        if "narrative_patterns" in data:
            # narrative_patterns are computed on-demand, not stored
            results["narrative_patterns_restored"] = True

        # Restore initialized flag
        self._initialized = data.get("metadata", {}).get("initialized", True)

        # Rival simulator state
        if "rival_simulator" in data and self.rival_simulator:
            try:
                self.rival_simulator.import_state(data["rival_simulator"])
            except Exception:
                pass
        # Chaosbringer state
        if "chaosbringer" in data and self.chaosbringer:
            try:
                self.chaosbringer.import_state(data["chaosbringer"])
            except Exception:
                pass
        # Restore game state core metrics from export
        gs_data = data.get("game_state", {}).get("game_summary", {}).get("federation_core", {})
        if gs_data:
            try:
                self.game_state.federation.morale = gs_data.get("morale", self.game_state.federation.morale)
                self.game_state.federation.identity_strength = gs_data.get("identity_strength", self.game_state.federation.identity_strength)
                self.game_state.federation.stability = gs_data.get("stability", self.game_state.federation.stability)
                self.game_state.federation.technological_level = gs_data.get("technological_level", self.game_state.federation.technological_level)
                self.game_state.federation.military_power = gs_data.get("military_power", self.game_state.federation.military_power)
                self.game_state.federation.treasury = gs_data.get("treasury", self.game_state.federation.treasury)
                self.game_state.federation.population = gs_data.get("population", self.game_state.federation.population)
                self.game_state.federation.territory_size = gs_data.get("territory_size", self.game_state.federation.territory_size)
                results["game_state_restored"] = True
            except Exception:
                results["game_state_restored"] = False
        # Restore adapter state summaries (best-effort: log state, re-init adapters if needed)
        if "technology" in data and self.technology:
            try:
                tech_data = data["technology"]
                self.game_state.technology_data = tech_data
                results["technology_state_restored"] = True
            except Exception:
                results["technology_state_restored"] = False
        if "quest_engine" in data and self.quest_engine:
            try:
                quest_data = data["quest_engine"]
                self.game_state.quest_data = quest_data
                results["quest_state_restored"] = True
            except Exception:
                results["quest_state_restored"] = False
        if "npc_engine" in data and self.npc_engine:
            try:
                npc_data = data["npc_engine"]
                self.game_state.npc_data = npc_data
                results["npc_state_restored"] = True
            except Exception:
                results["npc_state_restored"] = False
        # Political engine state
        if "political_engine" in data and self.political_engine:
            try:
                political_data = data["political_engine"]
                self.game_state.political_data = political_data
                results["political_state_restored"] = True
            except Exception:
                results["political_state_restored"] = False

        return results

    # ====================================================================
    # PRIVATE HELPERS
    # ====================================================================

    def _build_event_data(
        self, event_dict: Dict[str, Any], year: int
    ) -> Dict[str, Any]:
        """Build the event_data dict expected by QuantumConsciousnessEngine.

        Maps timeline event fields into the format consumed by
        interpret_event(), including emotional valence derived from
        memory drift and ideological alignment from faction ideology.
        """
        faction_id = self._identify_primary_faction(event_dict)
        ideology_str = FACTION_IDEOLOGY_MAP.get(faction_id, "diplomatic")
        qc_ideology = _FACTION_IDEOLOGY_TO_QC.get(ideology_str, QCIdeologyType.DIPLOMATIC)

        # Determine ideological alignment from observer ideology match
        ideology_alignment = 0.5
        if faction_id in self.OBSERVER_FACTION_MAP:
            _, faction_qc_ideology = self.OBSERVER_FACTION_MAP[faction_id]
            if faction_qc_ideology == qc_ideology:
                ideology_alignment = 0.8

        emotional_valence = self._compute_emotional_valence(event_dict)
        ideological_polarity = self._compute_ideological_polarity(event_dict)

        proximity = self._compute_proximity(event_dict)
        clarity = self._compute_clarity(event_dict)

        return {
            "name": event_dict.get("name", "Unknown Event"),
            "outcome": event_dict.get("outcome", "Consequences unfolded."),
            "year": year,
            "category": self._infer_event_category(event_dict),
            "emotional_valence": emotional_valence,
            "ideological_polarity": ideological_polarity,
            "ideological_alignment": ideology_alignment,
            "proximity": proximity,
            "clarity": clarity,
            "branches": event_dict.get("branches", {}),
        }

    def _compute_emotional_valence(self, event_dict: Dict[str, Any]) -> float:
        """Compute emotional valence from memory drift: positive = good, negative = bad."""
        memory_drift = event_dict.get("memory_drift", {})
        if not memory_drift:
            return 0.0
        avg_drift = sum(memory_drift.values()) / len(memory_drift)
        return max(-1.0, min(1.0, avg_drift * 2.0))

    def _compute_ideological_polarity(self, event_dict: Dict[str, Any]) -> float:
        """Compute how ideologically charged an event is based on drift variance."""
        memory_drift = event_dict.get("memory_drift", {})
        if not memory_drift:
            return 0.0
        values = list(memory_drift.values())
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        return min(1.0, variance * 10.0)

    def _compute_proximity(self, event_dict: Dict[str, Any]) -> float:
        """Estimate how close/proximate the event is to federation core."""
        metadata = event_dict.get("metadata", {})
        significance = metadata.get("significance", "moderate")
        proximity_map = {"critical": 0.9, "major": 0.7, "moderate": 0.5, "minor": 0.3}
        return proximity_map.get(significance, 0.5)

    def _compute_clarity(self, event_dict: Dict[str, Any]) -> float:
        """Estimate how clear/unambiguous the event outcome is."""
        has_branches = bool(event_dict.get("branches"))
        has_outcome = bool(event_dict.get("outcome"))
        if has_branches:
            return 0.4
        if has_outcome:
            return 0.8
        return 0.3

    def _identify_primary_faction(
        self, event_dict: Dict[str, Any]
    ) -> str:
        """Identify the faction most affected by this event (highest memory drift)."""
        memory_drift = event_dict.get("memory_drift", {})
        if not memory_drift:
            return FACTION_IDS[0]
        max_fid = max(memory_drift, key=lambda k: abs(memory_drift[k]))
        return max_fid

    def _infer_event_category(self, event_dict: Dict[str, Any]) -> str:
        """Infer an event category from metadata and memory drift."""
        metadata = event_dict.get("metadata", {})
        if "conflict_type" in metadata:
            return "conflict"
        if "discovery" in metadata:
            return "discovery"
        if "technology" in metadata:
            return "technology"
        if "phenomenon" in metadata:
            return "consciousness"
        if "diplomatic_achievement" in metadata:
            return "diplomacy"
        if "cultural_movement" in metadata:
            return "culture"
        if "scandal" in metadata:
            return "politics"
        if "crisis_type" in metadata:
            return metadata["crisis_type"]
        if "external_threat" in metadata:
            return "external_threat"
        if "milestone" in metadata:
            return "milestone"

        memory_drift = event_dict.get("memory_drift", {})
        if memory_drift:
            most_affected = max(memory_drift, key=lambda k: abs(memory_drift[k]))
            ideology = FACTION_IDEOLOGY_MAP.get(most_affected, "diplomatic")
            return ideology

        return "general"

    def _sync_game_state(self, year_record: Dict[str, Any]) -> None:
        """Update FederationCoreState from timeline faction averages."""
        faction_states = year_record.get("faction_states", {})
        if not faction_states:
            return

        avg_power = 0.0
        avg_reputation = 0.0
        avg_stability = 0.0
        avg_influence = 0.0
        count = 0

        for fid, fstate in faction_states.items():
            avg_power += fstate.get("power", 0.5)
            avg_reputation += fstate.get("reputation", 0.5)
            avg_stability += fstate.get("stability", 0.5)
            avg_influence += fstate.get("influence", 0.5)
            count += 1

        if count > 0:
            avg_power /= count
            avg_reputation /= count
            avg_stability /= count
            avg_influence /= count

        # Blend current game state with new averages (gradual sync)
        blend = 0.1
        self.game_state.federation.stability = max(
            0.0, min(1.0, self.game_state.federation.stability * (1 - blend) + avg_stability * blend)
        )
        self.game_state.federation.morale = max(
            0.0, min(1.0, self.game_state.federation.morale * (1 - blend) + avg_reputation * blend)
        )
        self.game_state.federation.military_power = max(
            0.0, min(1.0, self.game_state.federation.military_power * (1 - blend) + avg_power * blend)
        )
        self.game_state.federation.identity_strength = max(
            0.0, min(1.0, self.game_state.federation.identity_strength * (1 - blend) + avg_influence * blend)
        )

        # Update game phase based on timeline year
        year = year_record.get("year", 2387)
        if year <= 2400:
            self.game_state.game_phase = StateGamePhase.GENESIS
        elif year <= 2420:
            self.game_state.game_phase = StateGamePhase.EARLY_EXPANSION
        elif year <= 2445:
            self.game_state.game_phase = StateGamePhase.MID_GAME
        elif year <= 2465:
            self.game_state.game_phase = StateGamePhase.LATE_GAME
        elif year <= 2480:
            self.game_state.game_phase = StateGamePhase.ENDGAME
        else:
            self.game_state.game_phase = StateGamePhase.ENDGAME

        # Update consciousness subsystem level from coherence
        coherence_history = self.consciousness.coherence_history
        if coherence_history:
            latest_coherence = list(coherence_history.values())[-1]
            self.game_state.subsystems.consciousness_level = max(
                0.0, min(1.0, latest_coherence)
            )

        # Update treasury based on economic council state
        econ_state = faction_states.get("economic_council", {})
        econ_rep = econ_state.get("reputation", 0.5)
        treasury_delta = int((econ_rep - 0.5) * 200)
        self.game_state.federation.treasury = max(
            0, self.game_state.federation.treasury + treasury_delta
        )

        # Population growth
        pop_state = faction_states.get("exploration_initiative", {})
        pop_rep = pop_state.get("reputation", 0.5)
        if pop_rep > 0.4:
            growth = int(pop_rep * 500)
            self.game_state.federation.population += growth

        # Territory grows with exploration reputation
        if pop_rep > 0.5:
            self.game_state.federation.territory_size += pop_rep * 5.0

    def _generate_era_consciousness_waves(self) -> None:
        """Generate consciousness waves for each completed era."""
        for era in TimelineEra:
            era_start, era_end = era.year_range
            era_events = self._collect_era_events_for_wave(era_start, era_end)
            if era_events:
                self.consciousness.generate_consciousness_wave(
                    era_start, era_end, era_events
                )

    def _collect_era_events_for_wave(
        self, start_year: int, end_year: int
    ) -> List[Dict[str, Any]]:
        """Collect event data dicts for consciousness wave generation in an era range."""
        events: List[Dict[str, Any]] = []
        for event_id, event_data in self.consciousness.event_cache.items():
            ev_year = event_data.get("year", 0)
            if start_year <= ev_year <= end_year:
                events.append(event_data)
        return events

    def _collect_event_data_for_patterns(self) -> List[Dict[str, Any]]:
        """Collect all event data dicts for narrative pattern detection."""
        events: List[Dict[str, Any]] = []
        for event_id, event_data in self.consciousness.event_cache.items():
            events.append(event_data)
        return sorted(events, key=lambda e: e.get("year", 0))


# ============================================================================
# CONVENIENCE / DEMO
# ============================================================================

def run_history_arc_simulation(
    start_year: int = 2387, end_year: int = 2487
) -> HistoryArcReport:
    """Run the full 100-year history arc simulation and return the report.

    Args:
        start_year: First year of simulation
        end_year: Final year (exclusive)

    Returns:
        HistoryArcReport with complete results
    """
    orchestrator = HistoryArcOrchestrator()
    report = orchestrator.run_simulation(start_year, end_year)
    return report


def run_history_arc_demo() -> None:
    """Demonstrate the History Arc Orchestrator with a full 100-year run."""
    print("=" * 72)
    print("  HISTORY ARC ORCHESTRATOR - 100-YEAR SIMULATION")
    print("  THE FEDERATION GAME: Integration Layer")
    print("=" * 72)

    orchestrator = HistoryArcOrchestrator()

    # Initialize
    print("\n[1] Initializing orchestrator...")
    init_result = orchestrator.initialize()
    print(f"  Factions: {init_result.get('timeline_factions', 0)}")
    print(f"  Observers: {init_result.get('observers_registered', 0)}")
    print(f"  Seed Events: {init_result.get('seed_events_loaded', 0)}")

    # Run simulation
    print(f"\n[2] Running 100-year simulation (2387-2487)...")
    report = orchestrator.run_simulation(2387, 2487)

    # Display results
    print(f"\n[3] Simulation complete.")
    print(f"  Years: {report.total_years_simulated}")
    print(f"  Events: {report.events_generated}")
    print(f"  Branch Points: {report.branch_points_encountered}")
    print(f"  Lost Possibilities: {report.lost_possibilities_created}")
    print(f"  Dominant Quantum State: {report.dominant_quantum_state}")

    # Status
    print(f"\n[4] Final status:")
    status = orchestrator.get_status()
    print(f"  Timeline year: {status['timeline']['current_year']}")
    print(f"  Total interpretations: {status['consciousness']['total_interpretations']}")
    print(f"  Avg coherence: {status['consciousness']['coherence']:.3f}")
    print(f"  Choice ledger entries: {status['choice_ledger_count']}")

    # Full report display
    print("\n" + report.display())

    # Export test
    print("\n[5] Export/import test...")
    exported = orchestrator.export_full_state()
    print(f"  Export keys: {list(exported.keys())}")
    print(f"  Timeline events in export: {len(exported.get('timeline', {}).get('event_history', []))}")
    print(f"  Consciousness observers in export: {len(exported.get('consciousness', {}).get('observers', {}))}")

    orchestrator2 = HistoryArcOrchestrator()
    import_result = orchestrator2.import_full_state(exported)
    print(f"  Import result: {import_result}")

    print(f"\n{'=' * 72}")
    print("  END OF HISTORY ARC DEMO")
    print("=" * 72)


if __name__ == "__main__":
    run_history_arc_demo()
