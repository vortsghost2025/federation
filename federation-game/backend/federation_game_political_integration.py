#!/usr/bin/env python3
"""
Political Engine Adapter for Federation Game History Arc Simulation.

Wraps political_system.PoliticalSystem to provide yearly law/policy generation
that influences federation metrics (treasury, stability, morale, identity).

Integration: In HistoryArcOrchestrator.initialize():
    if ENABLE_POLITICAL_SYSTEM:
        self.political_engine = PoliticalEngine(faction_ids, self.game_state.federation)
In advance_year(): after state sync
    if self.political_engine:
        self.political_engine.process_year(year, self.game_state.federation)
        self.game_state.political_data = self.political_engine.summary
Default: disabled.
"""

from typing import Dict, List, Any, Optional
import random

class PoliticalEngine:
    """Simplified political overlay: generates laws that affect federation metrics."""
    
    def __init__(self, faction_ids: List[str], initial_federation_state):
        self.faction_ids = faction_ids
        self.federation = initial_federation_state
        self.laws_passed: List[Dict[str, Any]] = []
        self.cabinet: Dict[str, str] = {}  # faction_id -> leader name (stub)
        self.enabled = True
        # Predefined small law set with effects
        self.law_library = [
            {
                "id": "research_funding",
                "name": "Incremental Research Funding",
                "description": "Allocate extra resources to R&D.",
                "treasury_delta": -200,
                "stability_delta": 0.02,
                "coherence_bonus": 0.01,
                "min_year": 2400,
            },
            {
                "id": "deficit_spending",
                "name": "Deficit Spending Initiative",
                "description": "Spend beyond means to boost morale.",
                "treasury_delta": +300,
                "stability_delta": -0.03,
                "min_year": 2387,
            },
            {
                "id": "cultural_grants",
                "name": "Cultural Heritage Grants",
                "description": "Fund arts and traditions.",
                "treasury_delta": -150,
                "morale_delta": 0.05,
                "identity_delta": 0.03,
                "min_year": 2420,
            },
            {
                "id": "military_draft",
                "name": "Conscription Mandate",
                "description": "Draft citizens to strengthen defense.",
                "treasury_delta": +100,
                "stability_delta": -0.02,
                "morale_delta": -0.04,
                "min_year": 2430,
            },
        ]
    
    def initialize(self):
        """Assign a simple cabinet (one leader per faction, just a placeholder)."""
        surnames = ["Vex", "Krag", "Axiom", "Lore", "Mira", "Tor", "Sage", "Rook"]
        for idx, fid in enumerate(self.faction_ids):
            self.cabinet[fid] = f"{surnames[idx % len(surnames)]}"
    
    def process_year(self, year: int, federation) -> List[Dict[str, Any]]:
        """Attempt to pass at most one law this year."""
        if not self.enabled:
            return []
        # Filter laws available this year
        available = [law for law in self.law_library if year >= law.get("min_year", 2387)]
        if not available:
            return []
        # Random chance to propose a law (30%)
        if random.random() < 0.3:
            law = random.choice(available)
            # Apply effects
            effects = {}
            if "treasury_delta" in law:
                self.federation.treasury = max(0, self.federation.treasury + law["treasury_delta"])
                effects["treasury"] = law["treasury_delta"]
            if "stability_delta" in law:
                self.federation.stability = max(0.0, min(1.0, self.federation.stability + law["stability_delta"]))
                effects["stability"] = law["stability_delta"]
            if "morale_delta" in law:
                self.federation.morale = max(0.0, min(1.0, self.federation.morale + law["morale_delta"]))
                effects["morale"] = law["morale_delta"]
            if "identity_delta" in law:
                self.federation.identity_strength = max(0.0, min(1.0, self.federation.identity_strength + law["identity_delta"]))
                effects["identity_strength"] = law["identity_delta"]
            if "coherence_bonus" in law:
                # coherence not directly on federation, but we can indirectly influence via later sync
                pass
            # Record
            law_record = {
                "year": year,
                "law_id": law["id"],
                "law_name": law["name"],
                "description": law["description"],
                "effects": effects,
            }
            self.laws_passed.append(law_record)
            return [law_record]
        return []
    
    @property
    def summary(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "laws_passed_count": len(self.laws_passed),
            "recent_laws": self.laws_passed[-5:] if self.laws_passed else [],
            "cabinet_size": len(self.cabinet),
        }
