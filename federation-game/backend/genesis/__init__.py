"""
genesis — WE4FREE 4-layer scaffold for Federation NPC autonomy.

This package is OPT-IN. Nothing in the running simulation imports it unless
GENESIS_LAYERS_ENABLED is True (see genesis_config). It does NOT modify
npc_autonomy.py or game_state. Each layer closes specific Named Failure Modes
(NFM) from the WE4FREE framework (Papers A–F).

Layers:
  L1 genesis_constitution  — Symmetry Preservation (snapshot + functorial recover)
  L2 genesis_constraints   — Selection Under Constraint (lattice, not random.choices)
  L3 genesis_phenotype     — Phenotype / CPS attractor ("universe in their image")
  L4 genesis_drift         — Stability Under Transformation (drift detect + recovery)

Reference: S:\\Genesis Kernel World Sim\\world-sim\\backend\\
Theory:    docs/handoffs/FEDERATION_WE4FREE_THEORY_MAP.md
Audit:     docs/handoffs/FEDERATION_NPC_AUTONOMY_AUDIT.md
Sketch:    docs/handoffs/FEDERATION_GENESIS_SCAFFOLD_SKETCH.md
"""

from .genesis_config import GENESIS_LAYERS_ENABLED, GenesisConfig

__all__ = ["GENESIS_LAYERS_ENABLED", "GenesisConfig"]
