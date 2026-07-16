"""
Isolated tests for the Phase 2 councilor-exchange read-only helper (Gate B).

No Redis server, VPS, or real secret is used. A fake Redis client captures
which methods are invoked so we can prove:
- LRANGE is the only Redis method called
- no write method is invoked
- an injected client prevents construction of a real Redis client
- Redis failure surfaces only the sanitized StoreUnavailableError

The configured key is never touched here; authentication is Gate A's concern.
"""

import sys
from pathlib import Path

# Make the backend importable when pytest runs from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import pytest

import councilor_exchange
from councilor_exchange import (
    get_entries,
    CouncilorExchangeValidationError,
    StoreUnavailableError,
    SUPPORTED_VIEWS,
    SUPPORTED_COUNCILORS,
)


def make_fake_redis(store=None):
    """A fake Redis that records calls and only supports lrange.

    `store` maps a Redis key to a list of entries (str or bytes).
    Any write/scan method raises AssertionError to prove it is never used.
    """
    store = store or {}

    calls = []

    class FakeRedis:
        def lrange(self, key, start, end):
            calls.append(("lrange", key, start, end))
            data = list(store.get(key, []))
            # Mirror redis-py semantics so negative windows are honored.
            n = len(data)
            if n == 0:
                return []
            # Normalize negatives (redis: -1 == last element).
            s = start if start >= 0 else n + start
            e = end if end >= 0 else n + end
            s = max(0, s)
            e = min(n - 1, e)
            if s > e or s >= n:
                return []
            return data[s : e + 1]

        def __getattr__(self, name):
            # Any other attribute access is a forbidden Redis operation.
            def forbidden(*args, **kwargs):
                raise AssertionError(f"Forbidden Redis method invoked: {name}")

            return forbidden

    return FakeRedis(), calls


GOOD_ENTRY = '{"exchange_id":"cex_char_001_1","from":"char_001","to":"char_306","type":"question","body":"hi","ts":1}'
BAD_ENTRY = "not-json"


def test_empty_shared_list():
    client, _ = make_fake_redis({})
    result = get_entries("shared", limit=50, redis_client=client)
    assert result == {"entries": [], "count": 0, "invalid_count": 0, "partial": False}


def test_empty_valid_inbox():
    client, _ = make_fake_redis({})
    result = get_entries("inbox", char_id="char_001", limit=50, redis_client=client)
    assert result["entries"] == []
    assert result["count"] == 0
    assert result["partial"] is False


def test_empty_valid_outbox():
    client, _ = make_fake_redis({})
    result = get_entries("outbox", char_id="char_306", limit=50, redis_client=client)
    assert result["entries"] == []
    assert result["count"] == 0


def test_shared_key_selection():
    client, calls = make_fake_redis({"councilor_exchange:shared": [GOOD_ENTRY]})
    get_entries("shared", limit=50, redis_client=client)
    assert calls[0][1] == "councilor_exchange:shared"


def test_inbox_key_selection():
    client, calls = make_fake_redis(
        {"councilor_exchange:char_001:inbox": [GOOD_ENTRY]}
    )
    get_entries("inbox", char_id="char_001", limit=50, redis_client=client)
    assert calls[0][1] == "councilor_exchange:char_001:inbox"


def test_outbox_key_selection():
    client, calls = make_fake_redis(
        {"councilor_exchange:char_306:outbox": [GOOD_ENTRY]}
    )
    get_entries("outbox", char_id="char_306", limit=50, redis_client=client)
    assert calls[0][1] == "councilor_exchange:char_306:outbox"


def test_invalid_view():
    client, _ = make_fake_redis({})
    with pytest.raises(CouncilorExchangeValidationError):
        get_entries("dashboard", limit=50, redis_client=client)


def test_missing_char_id_for_inbox():
    client, _ = make_fake_redis({})
    with pytest.raises(CouncilorExchangeValidationError):
        get_entries("inbox", char_id=None, limit=50, redis_client=client)


def test_missing_char_id_for_outbox():
    client, _ = make_fake_redis({})
    with pytest.raises(CouncilorExchangeValidationError):
        get_entries("outbox", char_id=None, limit=50, redis_client=client)


def test_unknown_char_id():
    client, _ = make_fake_redis({})
    with pytest.raises(CouncilorExchangeValidationError):
        get_entries("inbox", char_id="char_999", limit=50, redis_client=client)


def test_limit_boundary_min():
    client, calls = make_fake_redis(
        {"councilor_exchange:shared": [GOOD_ENTRY, GOOD_ENTRY]}
    )
    get_entries("shared", limit=1, redis_client=client)
    assert calls[0][2] == -1  # start = -limit


def test_limit_boundary_max():
    client, calls = make_fake_redis(
        {"councilor_exchange:shared": [GOOD_ENTRY]}
    )
    get_entries("shared", limit=200, redis_client=client)
    assert calls[0][2] == -200


def test_limit_below_one():
    client, _ = make_fake_redis({})
    with pytest.raises(CouncilorExchangeValidationError):
        get_entries("shared", limit=0, redis_client=client)


def test_limit_above_max():
    client, _ = make_fake_redis({})
    with pytest.raises(CouncilorExchangeValidationError):
        get_entries("shared", limit=201, redis_client=client)


def test_rpush_order_a_b_c_limit_2_returns_c_b():
    # Stored oldest->newest: A, B, C. Newest 2 window = [B, C];
    # returned newest-first = [C, B].
    store = {
        "councilor_exchange:shared": [
            '{"exchange_id":"a","from":"char_001","to":"world","type":"note","body":"A","ts":1}',
            '{"exchange_id":"b","from":"char_001","to":"world","type":"note","body":"B","ts":2}',
            '{"exchange_id":"c","from":"char_001","to":"world","type":"note","body":"C","ts":3}',
        ]
    }
    client, _ = make_fake_redis(store)
    result = get_entries("shared", limit=2, redis_client=client)
    bodies = [e["body"] for e in result["entries"]]
    assert bodies == ["C", "B"]
    assert result["count"] == 2


def test_malformed_entry_counts_toward_window():
    store = {
        "councilor_exchange:shared": [
            '{"exchange_id":"a","from":"char_001","to":"world","type":"note","body":"A","ts":1}',
            BAD_ENTRY,
        ]
    }
    client, _ = make_fake_redis(store)
    result = get_entries("shared", limit=2, redis_client=client)
    assert result["invalid_count"] == 1
    assert result["count"] == 1


def test_malformed_entry_sets_partial_true():
    store = {"councilor_exchange:shared": [BAD_ENTRY, GOOD_ENTRY]}
    client, _ = make_fake_redis(store)
    result = get_entries("shared", limit=2, redis_client=client)
    assert result["partial"] is True


def test_no_older_entry_backfill():
    # Window of 2 selects only [B, BAD]; the older valid A is NOT fetched to
    # replace the malformed entry.
    store = {
        "councilor_exchange:shared": [
            '{"exchange_id":"a","from":"char_001","to":"world","type":"note","body":"A","ts":1}',
            '{"exchange_id":"b","from":"char_001","to":"world","type":"note","body":"B","ts":2}',
            BAD_ENTRY,
        ]
    }
    client, calls = make_fake_redis(store)
    result = get_entries("shared", limit=2, redis_client=client)
    # Only the newest 2 entries were read.
    assert calls[0][2] == -2
    assert calls[0][3] == -1
    assert result["count"] == 1  # only B valid
    assert result["invalid_count"] == 1  # the malformed entry
    bodies = [e["body"] for e in result["entries"]]
    assert bodies == ["B"]
    assert all(e["body"] != "A" for e in result["entries"])


def test_bytes_and_string_values_decode():
    store = {
        "councilor_exchange:shared": [
            GOOD_ENTRY.encode("utf-8"),  # bytes
            '{"exchange_id":"x2","from":"char_306","to":"char_001","type":"note","body":"S","ts":2}',
        ]
    }
    client, _ = make_fake_redis(store)
    result = get_entries("shared", limit=50, redis_client=client)
    assert result["count"] == 2
    bodies = {e["body"] for e in result["entries"]}
    assert bodies == {"hi", "S"}


def test_redis_failure_sanitized_only():
    class FailingRedis:
        def lrange(self, key, start, end):
            raise RuntimeError("REDIS_DOWN: connection refused at redis://u:p@host:6379")

    result = None
    with pytest.raises(StoreUnavailableError) as excinfo:
        get_entries("shared", limit=50, redis_client=FailingRedis())
    msg = str(excinfo.value)
    assert "REDIS_DOWN" not in msg
    assert "redis://" not in msg
    assert "connection refused" not in msg
    assert "unavailable" in msg.lower()


def test_injected_client_no_real_construction(monkeypatch):
    """When a client is injected, no real Redis client is built."""
    built = []

    import redis as real_redis

    def fake_redis_constructor(*args, **kwargs):
        built.append(True)
        return object()

    monkeypatch.setattr(real_redis, "Redis", fake_redis_constructor)

    client, _ = make_fake_redis({"councilor_exchange:shared": [GOOD_ENTRY]})
    get_entries("shared", limit=50, redis_client=client)
    assert built == [], "Real Redis client was constructed despite injection"


def test_lrange_only_redis_method():
    client, calls = make_fake_redis({"councilor_exchange:shared": [GOOD_ENTRY]})
    get_entries("shared", limit=50, redis_client=client)
    methods = [c[0] for c in calls]
    assert methods == ["lrange"]


def test_no_write_method_invoked():
    client, _ = make_fake_redis({"councilor_exchange:shared": [GOOD_ENTRY]})
    get_entries("shared", limit=50, redis_client=client)
    # If any write/scan method were used, the fake would have raised.
    # get_entries returned normally, so no forbidden method ran.

    # Explicitly assert the helper never calls known write methods by
    # making those methods raise and confirming the call still succeeds.
    class WriteCapturingRedis:
        def lrange(self, key, start, end):
            return []

        def rpush(self, *a, **k):
            raise AssertionError("rpush invoked")

        def set(self, *a, **k):
            raise AssertionError("set invoked")

        def expire(self, *a, **k):
            raise AssertionError("expire invoked")

        def delete(self, *a, **k):
            raise AssertionError("delete invoked")

        def scan(self, *a, **k):
            raise AssertionError("scan invoked")

        def keys(self, *a, **k):
            raise AssertionError("keys invoked")

    get_entries("shared", limit=50, redis_client=WriteCapturingRedis())


# ---------------------------------------------------------------------------
# GATE B CORRECTIONS — proof-hardening (test-first)
# ---------------------------------------------------------------------------

INVALID_CASES = [
    ("invalid_view", dict(view="dashboard")),
    ("inbox_without_char_id", dict(view="inbox", char_id=None)),
    ("outbox_without_char_id", dict(view="outbox", char_id=None)),
    ("unknown_char_id", dict(view="inbox", char_id="char_999")),
    ("limit_below_1", dict(view="shared", limit=0)),
    ("limit_above_200", dict(view="shared", limit=201)),
]


@pytest.mark.parametrize("case_name,kwargs", INVALID_CASES)
def test_validation_before_redis_zero_calls(case_name, kwargs):
    client, calls = make_fake_redis({})
    with pytest.raises(CouncilorExchangeValidationError):
        get_entries(redis_client=client, **kwargs)
    # Redis must never be touched when inputs are invalid.
    assert calls == [], f"Redis was called for invalid case {case_name}: {calls}"


def test_lazy_accessor_bypassed_when_injected(monkeypatch):
    """Patching _get_redis_client proves the lazy *construction* path is
    skipped when a client is injected: the accessor must never attempt to
    build a real Redis client."""
    called = []

    original = councilor_exchange._get_redis_client

    def patched(injected=None):
        called.append(True)
        if injected is None:
            # The lazy path would build a real client here; that must never
            # happen for an injected request.
            raise AssertionError("Lazy Redis construction attempted on inject")
        return injected

    monkeypatch.setattr(councilor_exchange, "_get_redis_client", patched)

    client, calls = make_fake_redis({"councilor_exchange:shared": [GOOD_ENTRY]})
    result = get_entries("shared", limit=50, redis_client=client)
    assert called == [True], "Accessor was not invoked as expected"
    assert result["count"] == 1
    # Exactly one LRANGE call occurred.
    assert len(calls) == 1


def test_exactly_one_lrange_call_shared():
    client, calls = make_fake_redis({"councilor_exchange:shared": [GOOD_ENTRY]})
    get_entries("shared", limit=50, redis_client=client)
    assert calls == [("lrange", "councilor_exchange:shared", -50, -1)]


def test_malformed_utf8_bytes_count_as_invalid():
    # One valid entry + one bytes value with invalid UTF-8.
    bad_bytes = b"{\"exchange_id\":\"x\",\"body\":\"\xff\xfe broken\""
    store = {
        "councilor_exchange:shared": [
            GOOD_ENTRY.encode("utf-8"),
            bad_bytes,
        ]
    }
    client, _ = make_fake_redis(store)
    result = get_entries("shared", limit=50, redis_client=client)
    assert result["count"] == 1
    assert result["invalid_count"] == 1
    assert result["partial"] is True
    # No exception escaped; valid entries newest-first.
    bodies = [e["body"] for e in result["entries"]]
    assert bodies == ["hi"]


@pytest.mark.parametrize(
    "non_object_json",
    [
        "null",
        '"a string scalar"',
        "42",
        "true",
        "[1, 2, 3]",
    ],
)
def test_non_object_json_counts_as_malformed(non_object_json):
    store = {
        "councilor_exchange:shared": [
            GOOD_ENTRY,
            non_object_json,
        ]
    }
    client, _ = make_fake_redis(store)
    result = get_entries("shared", limit=50, redis_client=client)
    assert result["count"] == 1
    assert result["invalid_count"] == 1
    assert result["partial"] is True
    # The non-object value is not returned in entries.
    bodies = [e.get("body") for e in result["entries"]]
    assert bodies == ["hi"]
    assert all(not isinstance(e, (list, int, bool, str)) or e == "hi" for e in result["entries"])


def test_sanitized_exception_chaining():
    class FailingRedis:
        def lrange(self, key, start, end):
            raise RuntimeError(
                "REDIS_DOWN: connection refused at ******secret123@host:6379"
            )

    with pytest.raises(StoreUnavailableError) as excinfo:
        get_entries("shared", limit=50, redis_client=FailingRedis())
    outer = excinfo.value
    assert str(outer) == "Exchange ledger store is unavailable"
    assert "REDIS_DOWN" not in str(outer)
    assert "******" not in str(outer)
    assert "secret123" not in str(outer)
    assert isinstance(outer.__cause__, RuntimeError)
    assert "REDIS_DOWN" in str(outer.__cause__)
