#!/usr/bin/env python3
"""
Quest Engine Adapter for Federation Game History Arc Simulation

Wraps federation_game_quests.QuestSystem to provide automated quest
processing during the 100-year simulation. Quests are auto-accepted and
auto-completed based on current federation state (objectives are considered
achieved by fast-forwarding progress). Rewards are applied to federation metrics.

Integration: In HistoryArcOrchestrator.initialize():
    if ENABLE_QUEST_SYSTEM:
        self.quest_engine = QuestEngine()
        self.quest_engine.initialize()
In advance_year() after _sync_game_state():
    if self.quest_engine:
        rewards_list = self.quest_engine.process_year(year, self.game_state)
        if rewards_list:
            for reward_info in rewards_list:
                apply rewards to federation state
Note: Default disabled; enable explicitly for testing.
"""

from typing import Dict, List, Any, Optional
from federation_game_quests import create_quest_library, QuestSystem
import logging

logger = logging.getLogger(__name__)


class QuestEngine:
    """Manages quest lifecycle during simulation."""

    def __init__(self):
        self.quest_system: Optional[QuestSystem] = None
        self.player_id: str = "federation"
        self.max_quests_per_year: int = 1
        self.quest_completion_chance: float = (
            0.3  # 30% chance per year to attempt a quest
        )
        self.reward_scale: float = (
            0.2  # Scale down resource rewards to prevent inflation
        )
        self.quests_this_run: List[str] = []

    def initialize(self):
        """Create and populate quest system."""
        self.quest_system = create_quest_library()

    def process_year(self, year: int, game_state) -> List[Dict[str, Any]]:
        """
        Process quests for the given year.

        Returns list of reward dicts for quests completed this year.
        """
        if self.quest_system is None:
            return []

        rewards_list = []
        try:
            # Random check if we attempt any quest this year
            import random

            if random.random() > self.quest_completion_chance:
                return []

            available = self.quest_system.get_available_quests(self.player_id)
            if not available:
                return []

            # Pick one random quest
            quest = random.choice(available)

            # Accept quest
            success, msg = self.quest_system.accept_quest(
                self.player_id, quest.quest_id, current_turn=year
            )
            if not success:
                return []

            # Auto-advance all objectives to completion
            for obj in quest.objectives:
                if not obj.is_complete():
                    needed = obj.target - obj.current_progress
                    if needed > 0:
                        prog_success, prog_msg = self.quest_system.progress_objective(
                            self.player_id,
                            quest.quest_id,
                            obj.objective_id,
                            amount=needed,
                        )
                        if not prog_success:
                            # Direct set
                            obj.current_progress = obj.target
                            obj.completed = True

            # Complete quest
            comp_success, comp_msg, reward = self.quest_system.complete_quest(
                self.player_id, quest.quest_id, current_turn=year
            )
            if comp_success and reward:
                self.quests_this_run.append(quest.quest_id)
                reward_dict = reward.to_dict()
                # Scale down resource rewards to keep economy balanced
                if "resources" in reward_dict:
                    reward_dict["resources"] = int(
                        reward_dict["resources"] * self.reward_scale
                    )
                rewards_list.append(
                    {
                        "quest_id": quest.quest_id,
                        "quest_title": quest.title,
                        "year": year,
                        "rewards": reward_dict,
                    }
                )
        except Exception as e:
            logger.debug(f"Quest reward claim failed: {e}; continuing simulation")

        return rewards_list

    @property
    def summary(self) -> Dict[str, Any]:
        """Summary of quest activity."""
        if self.quest_system is None:
            return {"enabled": False}
        player_stats = self.quest_system.player_stats.get(self.player_id, {})
        return {
            "enabled": True,
            "quests_completed": len(self.quests_this_run),
            "completed_ids": self.quests_this_run,
            "total_quests_available": len(self.quest_system.quests),
            "player_stats": player_stats,
        }

    def apply_rewards(self, rewards_list, federation):
        """Apply quest rewards to the federation state."""
        for reward_info in rewards_list:
            reward = reward_info.get("rewards", {})
            if "resources" in reward:
                federation.treasury += reward["resources"]
            if "reputation" in reward:
                federation.morale = max(
                    0.0, min(1.0, federation.morale + reward["reputation"] * 0.5)
                )
            if "morale_boost" in reward:
                federation.morale = max(
                    0.0, min(1.0, federation.morale + reward["morale_boost"])
                )
            if "stability_boost" in reward:
                federation.stability = max(
                    0.0, min(1.0, federation.stability + reward["stability_boost"])
                )
            if "tech_points" in reward:
                bump = reward["tech_points"] / 1000.0
                federation.technological_level = max(
                    0.0, min(1.0, federation.technological_level + bump)
                )
