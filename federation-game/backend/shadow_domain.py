"""Read-only Shadow Domain lore registry loader.

This module is intentionally DORMANT. It exposes ``load_shadow_domain_lore()``,
which reads ``backend/data/lore/shadow_domain.json`` and returns it as a dict.

It performs NO writes, fires NO events, registers NO routes, and is NOT invoked
by any runtime path. Runtime activation (SHADOW_INCURSION events, Rival 13
behavior, incursion firing) is deferred to a separate approved plan and must
respect the 4 critical backend constraints (single-process game_state,
``/choose`` always returns ``outcome``, ``gs.current_event = None`` after a
successful choice, no ``--workers`` in docker-compose).

Canon source of truth: ``.horizon/SHADOW_DOMAIN_STATE.md``.
"""

from __future__ import annotations

import json
import os

_LORE_PATH = os.path.join(os.path.dirname(__file__), "data", "lore", "shadow_domain.json")


def load_shadow_domain_lore() -> dict:
    """Load the Shadow Domain lore registry as a read-only dict.

    The returned dict must be treated as immutable by callers. This function
    performs no side effects and does not mutate shared state.
    """
    with open(_LORE_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def is_integration_enabled() -> bool:
    """Shadow Domain runtime integration is disabled by default.

    Mirrors the phase boundary in ``.horizon/SHADOW_DOMAIN_STATE.md``: lore
    only, no runtime behavior yet. Callers must not activate Shadow Domain
    features unless this returns ``True`` behind an approved plan.
    """
    return bool(load_shadow_domain_lore().get("integration_enabled", False))
