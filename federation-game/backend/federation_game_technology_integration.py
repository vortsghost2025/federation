#!/usr/bin/env python3
"""
Technology Engine Adapter for Federation Game History Arc Simulation

Thin wrapper around federation_game_technology.TechTree that provides
automatic yearly progression based on federation treasury.

Integration: Add to HistoryArcOrchestrator.initialize():
    self.technology = TechnologyEngine(treasury=self.game_state.federation.treasury)
Then in advance_year() after _sync_game_state():
    if self.technology:
        completed = self.technology.process_year(year, self.game_state.federation.treasury)
        if completed:
            for t in completed: self.choice_ledger.append({...})
        self.game_state.federation.technological_level = self.technology.technological_level
"""

from typing import Dict, List, Any, Optional
from federation_game_technology import create_technology_tree, Technology

class TechnologyEngine:
    """Manages technology progression for the simulation."""
    
    def __init__(self, treasury: float = 0.0):
        self.tree = create_technology_tree()
        self.research_points: float = treasury * 0.01  # initial from treasury
        self.completed_techs: Dict[str, Technology] = {}
        self.research_history: List[Dict[str, Any]] = []
        self._tech_level: float = 0.2
        self.research_rate: float = 0.01   # 1% of treasury per year
        self.max_completions_per_year: int = 1

    def process_year(self, year: int, treasury: float) -> List[str]:
        """Process one year of research. Returns list of completed tech IDs."""
        self.research_points += treasury * self.research_rate
        completed = []
        for _ in range(self.max_completions_per_year):
            available = [
                t for t in self.tree.get_available_techs("federation")
                if t.research_cost <= self.research_points
            ]
            if not available:
                break
            tech = min(available, key=lambda t: t.research_cost)
            self.research_points -= tech.research_cost
            self.completed_techs[tech.tech_id] = tech
            self.research_history.append({
                'year': year,
                'tech_id': tech.tech_id,
                'name': tech.name,
                'cost': tech.research_cost,
                'tier': tech.tier,
                'era': tech.era.value,
            })
            completed.append(tech.tech_id)
        self._recompute_level()
        return completed

    def _recompute_level(self) -> None:
        base = 0.2
        if not self.completed_techs:
            self._tech_level = base
            return
        max_tier = max(t.tier for t in self.completed_techs.values())
        tiers_covered = len(set(t.tier for t in self.completed_techs.values()))
        tier_bonus = min(0.15 * max_tier, 0.75)
        breadth_bonus = min(0.05 * tiers_covered, 0.20)
        self._tech_level = min(1.0, base + tier_bonus + breadth_bonus)

    @property
    def technological_level(self) -> float:
        return self._tech_level

    @property
    def summary(self) -> Dict[str, Any]:
        techs = list(self.completed_techs.values()) if self.completed_techs else []
        return {
            'research_points_available': self.research_points,
            'techs_completed': len(self.completed_techs),
            'completed_tech_ids': list(self.completed_techs.keys()),
            'tech_level': self.technological_level,
            'max_tier_reached': max((t.tier for t in techs), default=0),
            'eras': list(set(t.era.value for t in techs)),
            'philosophies_explored': list(set(t.philosophy.value for t in techs
                                              if hasattr(t, 'philosophy'))) if techs else [],
        }
