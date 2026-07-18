"""Commit 2 — bounded operator acknowledgement-history tests.

These prove the optional forensic enhancement that keeps a capped LIST
(operator_ack_history:{cid}, max 20 entries via LPUSH + LTRIM 0 19) alongside
the single latest operator_ack:{cid} SET. Critical ordering guarantee:

  A successful exact acknowledgement writes BOTH records. A FAILED removal, a
  wrong target, a non-terminal response, or a send failure writes NEITHER —
  so a failed ack can never leave a false audit record.

No shared/global attribution state exists: the attribution object is passed
explicitly through _acknowledge_operator_directive(attribution=...). History
entries are lightweight (id, status, ts, requested/actual model) and NEVER
carry a directive body, prompt, response body, API key, or header.

No live Redis is used; fakeredis stands in.
"""

import json

import fakeredis
import pytest

import npc_redis_helpers as rh


ATTRIB = {
    "requested_model": "openrouter/free",
    "actual_model": "nvidia/nemotron-3-ultra-550b-a55b:free",
    "provider": "operator_openrouter",
    "error_category": "",
    "is_repair": False,
}


def _r():
    return fakeredis.FakeStrictRedis()


def _history(r, cid="char_306"):
    return r.lrange(f"operator_ack_history:{cid}", 0, -1)


def _latest(r, cid="char_306"):
    return r.get(f"operator_ack:{cid}")


# ---------------------------------------------------------------------------
# 1. Successful exact ZSET removal writes latest ack AND history.
# ---------------------------------------------------------------------------
def test_successful_zset_removal_writes_both():
    r = _r()
    r.zadd("msg:inbox:char_306", {"msg_dir_a": 1.0})
    ok = rh._acknowledge_operator_directive(r, "msg_dir_a", "char_306", "complete", attribution=ATTRIB)
    assert ok is True
    assert _latest(r) is not None
    hist = _history(r)
    assert len(hist) == 1
    assert json.loads(hist[0])["directive_id"] == "msg_dir_a"
    assert json.loads(hist[0])["actual_model"] == ATTRIB["actual_model"]


# ---------------------------------------------------------------------------
# 2. Failed ZSET removal writes neither.
# ---------------------------------------------------------------------------
def test_failed_zset_removal_writes_neither():
    r = _r()
    r.zadd("msg:inbox:char_306", {"msg_other": 1.0})  # does NOT contain msg_dir_a
    ok = rh._acknowledge_operator_directive(r, "msg_dir_a", "char_306", "complete", attribution=ATTRIB)
    assert ok is False
    assert _latest(r) is None
    assert _history(r) == []


# ---------------------------------------------------------------------------
# 3. Failed legacy LIST removal writes neither.
# ---------------------------------------------------------------------------
def test_failed_legacy_list_removal_writes_neither():
    r = _r()
    r.rpush("npc_messages:char_306:inbox", json.dumps({"id": "msg_other", "body": "x"}))
    ok = rh._acknowledge_operator_directive(r, "msg_dir_a", "char_306", "complete", attribution=ATTRIB)
    assert ok is False
    assert _latest(r) is None
    assert _history(r) == []


# ---------------------------------------------------------------------------
# 4. Send failure writes neither (simulated: inbox member missing).
# ---------------------------------------------------------------------------
def test_send_failure_writes_neither():
    r = _r()
    # No inbox entry at all => acknowledgement cannot remove anything.
    ok = rh._acknowledge_operator_directive(r, "msg_dir_a", "char_306", "failed", attribution=ATTRIB)
    assert ok is False
    assert _latest(r) is None
    assert _history(r) == []


# ---------------------------------------------------------------------------
# 5. Wrong target writes neither.
# ---------------------------------------------------------------------------
def test_wrong_target_writes_neither():
    r = _r()
    r.zadd("msg:inbox:char_306", {"msg_dir_a": 1.0})
    ok = rh._acknowledge_operator_directive(r, "msg_dir_WRONG", "char_306", "complete", attribution=ATTRIB)
    assert ok is False
    assert _latest(r) is None
    assert _history(r) == []
    # the real directive must remain untouched
    assert r.zscore("msg:inbox:char_306", "msg_dir_a") is not None


# ---------------------------------------------------------------------------
# 6. Non-terminal status writes neither when no member exists.
# ---------------------------------------------------------------------------
def test_non_terminal_status_writes_neither_when_no_member():
    r = _r()
    ok = rh._acknowledge_operator_directive(r, "msg_dir_a", "char_306", "pending", attribution=ATTRIB)
    assert ok is False
    assert _latest(r) is None
    assert _history(r) == []


# ---------------------------------------------------------------------------
# 7. Complete status records the correct attribution.
# ---------------------------------------------------------------------------
def test_complete_records_correct_attribution():
    r = _r()
    r.zadd("msg:inbox:char_306", {"msg_dir_a": 1.0})
    rh._acknowledge_operator_directive(r, "msg_dir_a", "char_306", "complete", attribution=ATTRIB)
    entry = json.loads(_history(r)[0])
    assert entry["status"] == "complete"
    assert entry["requested_model"] == "openrouter/free"
    assert entry["actual_model"] == "nvidia/nemotron-3-ultra-550b-a55b:free"
    latest = json.loads(_latest(r))
    assert latest["status"] == "complete"
    assert latest["directive_id"] == "msg_dir_a"


# ---------------------------------------------------------------------------
# 8. Failed status records correct attribution only after removal.
# ---------------------------------------------------------------------------
def test_failed_records_attribution_after_removal():
    r = _r()
    r.zadd("msg:inbox:char_306", {"msg_dir_a": 1.0})
    ok = rh._acknowledge_operator_directive(r, "msg_dir_a", "char_306", "failed", attribution=ATTRIB)
    assert ok is True
    entry = json.loads(_history(r)[0])
    assert entry["status"] == "failed"
    assert entry["actual_model"] == ATTRIB["actual_model"]
    assert json.loads(_latest(r))["status"] == "failed"


# ---------------------------------------------------------------------------
# 9/10. Sequential / interleaved decisions cannot exchange attribution.
# ---------------------------------------------------------------------------
def test_sequential_decisions_cannot_exchange_attribution():
    r = _r()
    r.zadd("msg:inbox:char_306", {"msg_a": 1.0})
    r.zadd("msg:inbox:char_306", {"msg_b": 1.0})
    a1 = dict(ATTRIB, actual_model="model-A")
    a2 = dict(ATTRIB, actual_model="model-B")
    rh._acknowledge_operator_directive(r, "msg_a", "char_306", "complete", attribution=a1)
    rh._acknowledge_operator_directive(r, "msg_b", "char_306", "complete", attribution=a2)
    hist = [json.loads(x) for x in _history(r)]
    assert {h["directive_id"] for h in hist} == {"msg_a", "msg_b"}
    by_id = {h["directive_id"]: h["actual_model"] for h in hist}
    assert by_id["msg_a"] == "model-A"
    assert by_id["msg_b"] == "model-B"


def test_interleaved_decisions_cannot_exchange_attribution():
    r = _r()
    r.zadd("msg:inbox:char_306", {"msg_a": 1.0})
    r.zadd("msg:inbox:char_001", {"msg_b": 1.0})
    a1 = dict(ATTRIB, actual_model="model-A")
    a2 = dict(ATTRIB, actual_model="model-B")
    rh._acknowledge_operator_directive(r, "msg_a", "char_306", "complete", attribution=a1)
    rh._acknowledge_operator_directive(r, "msg_b", "char_001", "complete", attribution=a2)
    assert json.loads(_history(r, "char_306")[0])["actual_model"] == "model-A"
    assert json.loads(_history(r, "char_001")[0])["actual_model"] == "model-B"


# ---------------------------------------------------------------------------
# 11. History and latest acknowledgement identify the same directive.
# ---------------------------------------------------------------------------
def test_history_and_latest_same_directive():
    r = _r()
    r.zadd("msg:inbox:char_306", {"msg_dir_a": 1.0})
    rh._acknowledge_operator_directive(r, "msg_dir_a", "char_306", "complete", attribution=ATTRIB)
    assert json.loads(_history(r)[0])["directive_id"] == json.loads(_latest(r))["directive_id"]


# ---------------------------------------------------------------------------
# 12. History remains capped at 20.
# ---------------------------------------------------------------------------
def test_history_capped_at_20():
    r = _r()
    r.zadd("msg:inbox:char_306", {f"msg_dir_{i}": float(i) for i in range(25)})
    for i in range(25):
        rh._acknowledge_operator_directive(r, f"msg_dir_{i}", "char_306", "complete", attribution=ATTRIB)
    entries = _history(r)
    assert len(entries) == 20
    head = json.loads(entries[0])
    assert head["directive_id"] == "msg_dir_24"
    tail = json.loads(entries[-1])
    assert tail["directive_id"] == "msg_dir_5"


# ---------------------------------------------------------------------------
# 13. No attribution globals exist in npc_actions or npc_redis_helpers.
# ---------------------------------------------------------------------------
def test_no_attribution_globals():
    import npc_actions as na
    for name in ("_last_operator_requested_model", "_last_operator_actual_model",
                 "_last_operator_cid", "_set_operator_ack_attribution"):
        assert not hasattr(rh, name), f"npc_redis_helpers still has {name}"
        assert not hasattr(na, name), f"npc_actions still has {name}"


def test_history_entry_never_carries_body():
    r = _r()
    r.zadd("msg:inbox:char_306", {"msg_dir_a": 1.0})
    rh._acknowledge_operator_directive(r, "msg_dir_a", "char_306", "complete", attribution=ATTRIB)
    entry = json.loads(_history(r)[0])
    assert set(entry.keys()) == {"directive_id", "status", "ts", "requested_model", "actual_model"}
    assert "body" not in json.dumps(entry)
