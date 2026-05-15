#!/usr/bin/env python3
"""
NPC System Adapter for Federation Game History Arc Simulation

Provides passive advisor bonuses from notable characters.
Assigns up to 3 NPCs per faction based on trait suitability.
Each year, NPCs contribute small morale/identity boosts.

Integration: In HistoryArcOrchestrator.initialize():
    if ENABLE_NPC_SYSTEM:
        self.npc_engine = NPCSystemAdapter(FACTION_IDS)
        self.npc_engine.initialize()
In advance_year() after _sync_game_state():
    if self.npc_engine:
        modifiers = self.npc_engine.process_year(self.game_state)
        self.game_state.federation.morale = max(0.0, min(1.0,
            self.game_state.federation.morale + modifiers.get('morale_delta', 0.0)
        ))
        self.game_state.federation.identity_strength = max(0.0, min(1.0,
            self.game_state.federation.identity_strength + modifiers.get('identity_delta', 0.0)
        ))
Default: disabled (opt-in).
"""

from typing import Dict, List, Any, Optional
from federation_game_npcs import build_npc_system, Character

class NPCSystemAdapter:
    """Advisor NPC system that applies passive bonuses."""
    
    def __init__(self, faction_ids: List[str]):
        self.npc_system = None
        self.faction_ids = faction_ids
        self.faction_advisors: Dict[str, List[Character]] = {}
        self.summary_data: Dict[str, Any] = {}
        self.enabled = True
        
    def initialize(self):
        """Build NPC system and assign advisors to factions."""
        try:
            self.npc_system = build_npc_system()
        except Exception:
            self.enabled = False
            return
        
        # For each faction, pick up to 3 characters with suitable affiliation/traits
        for fid in self.faction_ids:
            candidates = []
            for char in self.npc_system.characters.values():
                # Match by explicit affiliation
                if char.affiliation == fid:
                    candidates.append(char)
                # Also allow if char's name hints at faction? Keep simple.
            # If not enough, pick any high-loyalty characters regardless
            if len(candidates) < 3:
                extra = [
                    c for c in self.npc_system.characters.values()
                    if c not in candidates and c.loyalty >= 0.6 and c.charisma >= 0.6
                ]
                candidates.extend(extra[:3 - len(candidates)])
            # Take top 3 by combined traits (loyalty+charisma)
            candidates.sort(key=lambda c: (c.loyalty + c.charisma + c.wisdom)/3, reverse=True)
            advisors = candidates[:3]
            self.faction_advisors[fid] = advisors
        
        # Compute per-faction annual morale delta from advisors
        # Each advisor contributes: (loyalty + charisma)/2 * 0.005 (max +0.0075 per advisor)
        self.faction_morale_delta: Dict[str, float] = {}
        for fid, advisors in self.faction_advisors.items():
            delta = 0.0
            for adv in advisors:
                delta += ((adv.loyalty + adv.charisma) / 2) * 0.005
            self.faction_morale_delta[fid] = delta
        
        # Compute identity strength contribution (from wisdom)
        self.faction_identity_delta: Dict[str, float] = {}
        for fid, advisors in self.faction_advisors.items():
            delta = 0.0
            for adv in advisors:
                delta += adv.wisdom * 0.003
            self.faction_identity_delta[fid] = delta
        
        self.summary_data = {
            'enabled': True,
            'total_advisors': sum(len(v) for v in self.faction_advisors.values()),
            'faction_counts': {fid: len(adv) for fid, adv in self.faction_advisors.items()},
        }
    
    def process_year(self, year: int, game_state) -> Dict[str, float]:
        """Compute modifiers for the given year. Returns dict with keys:
           'morale_delta', 'identity_delta' (to add to federation state)."""
        if not self.enabled or not self.faction_advisors:
            return {}
        # Aggregate across factions: take average of per-faction deltas
        # (since federation is average of factions)
        total_morale = sum(self.faction_morale_delta.values())
        total_identity = sum(self.faction_identity_delta.values())
        count = len(self.faction_ids)
        return {
            'morale_delta': total_morale / count if count else 0.0,
            'identity_delta': total_identity / count if count else 0.0,
        }
    
    @property
    def summary(self) -> Dict[str, Any]:
        return self.summary_data
