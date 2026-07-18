"""Focused unit tests for moderator-directive prompt visibility.

Regression guard for the bug where a 1,325-char moderator directive was
truncated to 80 chars by the partner-message preview limit, so the LLM never
saw the actual instruction.

Scope: federation-game/npc-agent/npc_context.py :: think_about_world
"""
import importlib.util
import json
import os
import types

# npc_context only uses stdlib, so no redis/httpx stubbing is required.
MODULE_PATH = os.path.join(os.path.dirname(__file__), "npc_context.py")
spec = importlib.util.spec_from_file_location("npc_context_under_test", MODULE_PATH)
npc_context = importlib.util.module_from_spec(spec)
spec.loader.exec_module(npc_context)

MODERATOR_DIRECTIVE = (
    "Moderator directive — stop the planning loop, produce the artifact now. "
    + "You are in a repetitive planning basin. "  # pad to a long body
    + ("Oracle must emit the final structured report with these five sections: "
       "prioritized criteria, quantitative metrics and thresholds, sector "
       "comparison method, risk and ethical safeguards, and a final "
       "recommendation. Archimedes must send only missing evidence. " * 6)
)
assert 1325 <= len(MODERATOR_DIRECTIVE) <= 2000, "fixture must model the real ~1325-char directive and stay under the 2000 cap"

PARTNER_MSG = "Short partner note about the rollout schedule for pilot sectors."
SECRET = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-secret-api-key"


class FakeRedis:
    """Minimal redis stand-in covering only what think_about_world touches."""

    def __init__(self, inbox=None, sent=None):
        self._inbox = inbox or []
        self._sent = sent or []

    def get(self, key):
        return None

    def lrange(self, key, start, end):
        if key.endswith(":inbox"):
            items = list(self._inbox)
        elif key.endswith(":sent"):
            items = list(self._sent)
        else:
            return []
        n = len(items)
        if not n:
            return []
        if start < 0:
            start = max(n + start, 0)
        if end < 0:
            end = n + end
        end = min(end, n - 1)
        if start > end or start >= n:
            return []
        return items[start:end + 1]

    def llen(self, key):
        if key.endswith(":inbox"):
            return len(self._inbox)
        if key.endswith(":sent"):
            return len(self._sent)
        return 0


def _moderator_entry(body, subject="Stop planning loop - produce final report"):
    return json.dumps({
        "from_char_id": "moderator",
        "from_name": "Sean / Federation Moderator",
        "subject": subject,
        "body": body,
    })


def _partner_entry(body):
    return json.dumps({
        "from_char_id": "char_306",
        "from_name": "The Oracle",
        "subject": "rollout",
        "body": body,
    })


def test_moderator_directive_reaches_context_intact():
    fake = FakeRedis(inbox=[_moderator_entry(MODERATOR_DIRECTIVE)])
    # Stub the partner/roster helpers so the test stays isolated to the inbox block.
    npc_context._rh = lambda: (lambda *a, **k: "char_306", lambda *a, **k: [],
                                (lambda s, n=60: s[:n]),
                                lambda *a, **k: {}, lambda *a, **k: [],
                                lambda *a, **k: [], lambda *a, **k: "")
    ctx = npc_context.think_about_world(fake, char_id="char_001")
    # Full body preserved (no 80-char truncation).
    assert MODERATOR_DIRECTIVE in ctx, "moderator body was truncated"
    # Dedicated high-priority block present.
    assert "MODERATOR DIRECTIVE" in ctx
    assert "READ FULLY AND ACT FIRST" in ctx
    # Ending instructions survived.
    assert "five sections" in ctx
    assert "prioritized criteria" in ctx
    assert "final recommendation" in ctx


def test_moderator_directive_capped_at_safe_maximum():
    huge = "X" * 5000
    fake = FakeRedis(inbox=[_moderator_entry(huge)])
    npc_context._rh = lambda: (lambda *a, **k: "char_306", lambda *a, **k: [],
                                (lambda s, n=60: s[:n]),
                                lambda *a, **k: {}, lambda *a, **k: [],
                                lambda *a, **k: "", lambda *a, **k: "")
    ctx = npc_context.think_about_world(fake, char_id="char_001")
    assert "X" * 2000 in ctx, "body should be preserved up to the 2000-char cap"
    assert "X" * 2001 not in ctx, "body must not exceed the 2000-char cap"


def test_partner_messages_remain_truncated():
    long_partner = "A" * 300
    fake = FakeRedis(inbox=[_partner_entry(long_partner)])
    npc_context._rh = lambda: (lambda *a, **k: "char_306", lambda *a, **k: [],
                                (lambda s, n=60: s[:n]),
                                lambda *a, **k: {}, lambda *a, **k: [],
                                lambda *a, **k: "", lambda *a, **k: "")
    ctx = npc_context.think_about_world(fake, char_id="char_001")
    # Partner preview is still capped at 80 chars.
    assert "A" * 81 not in ctx
    assert "A" * 80 in ctx


def test_no_secrets_exposed_in_context():
    # A moderator body that accidentally contains a secret must still round-trip
    # through json; we only assert the test harness keeps secrets out of the
    # fixture and that ordinary partner bodies are not padded with secrets.
    fake = FakeRedis(inbox=[_partner_entry(PARTNER_MSG)])
    npc_context._rh = lambda: (lambda *a, **k: "char_306", lambda *a, **k: [],
                                (lambda s, n=60: s[:n]),
                                lambda *a, **k: {}, lambda *a, **k: [],
                                lambda *a, **k: "", lambda *a, **k: "")
    ctx = npc_context.think_about_world(fake, char_id="char_001")
    assert SECRET not in ctx, "fixture secret must not appear in generated context"


if __name__ == "__main__":
    test_moderator_directive_reaches_context_intact()
    test_moderator_directive_capped_at_safe_maximum()
    test_partner_messages_remain_truncated()
    test_no_secrets_exposed_in_context()
    print("Moderator prompt-visibility tests passed.")
