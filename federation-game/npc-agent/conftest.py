"""Pytest configuration for npc-agent tests."""
import os
import sys

# Add the shared package root (S:/federation/federation-game/shared) so that
# 'federation_work_loop' is importable when running from the repo without the
# runtime PYTHONPATH=/opt/federation_shared.
_shared_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared")
if os.path.isdir(_shared_root) and _shared_root not in sys.path:
    sys.path.insert(0, _shared_root)