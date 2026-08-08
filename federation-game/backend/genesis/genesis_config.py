"""
genesis_config — opt-in gating for the WE4FREE Genesis layers.

Per the standing agreement, the scaffold is OFF by default. Flip
GENESIS_LAYERS_ENABLED only after unit tests pass and Sean approves wiring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class GenesisConfig:
    """Runtime configuration for the Genesis layers.

    enabled        — master switch. False = layers are no-ops.
    snapshot_store — "redis" (default, matches Federation infra) or "json".
    snapshot_ttl   — seconds a snapshot stays authoritative (NFM-009 freshness guard).
    drift_tolerance— max phenotype drift before L4 recovery triggers.
    seed_from_decrees — if True, phenotype attractors seed from decree alignment.
    """

    enabled: bool = False
    snapshot_store: str = "redis"
    snapshot_ttl: int = 3600
    drift_tolerance: float = 0.15
    seed_from_decrees: bool = True
    # Layer-specific debug flags
    log_l1: bool = False
    log_l2: bool = False
    log_l3: bool = False
    log_l4: bool = False


# Single process-wide config instance.
config = GenesisConfig()

# Convenience module-level flag mirroring config.enabled.
GENESIS_LAYERS_ENABLED = False


def enable() -> None:
    """Enable the Genesis layers (no-op until explicitly called by wiring code)."""
    global GENESIS_LAYERS_ENABLED
    config.enabled = True
    GENESIS_LAYERS_ENABLED = True


def disable() -> None:
    """Disable the Genesis layers."""
    global GENESIS_LAYERS_ENABLED
    config.enabled = False
    GENESIS_LAYERS_ENABLED = False


def is_enabled() -> bool:
    return GENESIS_LAYERS_ENABLED and config.enabled
