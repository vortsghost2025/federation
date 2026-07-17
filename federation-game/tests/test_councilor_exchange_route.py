"""
Isolated tests for the Phase2 councilor-exchange operator route (Gate C).

Test-first: this file is created and run before main.py is wired.

The isolated app mounts ONLY the new router plus one ordinary public route,
so we can prove:
- operator auth outcomes (401) are owned by require_operator (network trust)
- contract inputs never produce 422
- authorization completes before get_entries / Redis
- get_entries is invoked exactly once for a valid request
- the public route remains accessible without operator trust
- the router explicitly carries require_operator as a dependency

No live Redis, VPS, or real secret is used. get_entries is patched at the
route module so the handler never touches a store.
"""

import sys
import importlib.util
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

import pytest
from fastapi import FastAPI, APIRouter
from fastapi.testclient import TestClient as _RealTestClient

import councilor_exchange
from councilor_exchange import (
    CouncilorExchangeValidationError,
    StoreUnavailableError,
)

# The route file is named councilor_exchange.py, which clashes with the
# backend helper module of the same name. Load it under a distinct module
# name via its file path so the bare helper import stays unambiguous.
_route_path = BACKEND / "routes" / "councilor_exchange.py"
_spec = importlib.util.spec_from_file_location(
    "federation_route_councilor_exchange", str(_route_path)
)
route_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(route_module)
exchange_router = route_module.router


# --- Proxy-validated client-address injection -------------------------------
# The operator guard trusts ONLY request.client.host (populated by Uvicorn
# from forwarded headers only when the direct proxy IP is trusted via
# --forwarded-allow-ips). We simulate that validated address by injecting
# scope["client"] in an ASGI wrapper. No X-Forwarded-For header is used;
# that header is explicitly NOT trusted by the corrected guard.
_TRUSTED_ADDR = ("100.64.0.1", 54321)


def _client_injector(app, addr):
    async def wrapper(scope, receive, send):
        if scope["type"] == "http":
            # Override whatever address the test transport set (e.g.
            # ("testclient", 123)) with the proxy-validated address the
            # guard actually trusts.
            scope["client"] = addr
        await app(scope, receive, send)

    return wrapper


class TestClient(_RealTestClient):
    """TestClient that injects a proxy-validated client address."""

    def __init__(self, app, addr=_TRUSTED_ADDR):
        super().__init__(_client_injector(app, addr))


def untrusted_client(app):
    """Client whose injected address is a public (untrusted) IP."""
    return TestClient(app, addr=("203.0.113.5", 54321))


@pytest.fixture
def app_with_public():
    """Isolated app with the operator router + one public route."""

    public = APIRouter()

    @public.get("/public/ping")
    def ping():
        return {"ok": True}

    app = FastAPI()
    app.include_router(exchange_router)
    app.include_router(public)
    return app


def make_call_counter(monkeypatch, payload):
    """Patch route-module get_entries to count calls and return payload."""
    calls = []

    def fake_get_entries(view, char_id=None, limit=50, redis_client=None):
        calls.append(
            {
                "view": view,
                "char_id": char_id,
                "limit": limit,
                "redis_client": redis_client,
            }
        )
        return payload

    monkeypatch.setattr(route_module, "get_entries", fake_get_entries)
    return calls


GOOD_PAYLOAD = {
    "entries": [{"exchange_id": "x", "body": "hi"}],
    "count": 1,
    "invalid_count": 0,
    "partial": False,
}

EMPTY_PAYLOAD = {
    "entries": [],
    "count": 0,
    "invalid_count": 0,
    "partial": False,
}


# --- 1-4: authorization outcomes owned by require_operator (network trust) ---

def test_untrusted_source_401(app_with_public):
    client = untrusted_client(app_with_public)
    resp = client.get("/simulation/operator/councilor-exchange")
    assert resp.status_code == 401


def test_public_source_xff_401(app_with_public):
    # Even with a spoofed X-Forwarded-For, the guard must reject: it does
    # NOT read that header. The injected (public) client address is untrusted.
    client = untrusted_client(app_with_public)
    resp = client.get(
        "/simulation/operator/councilor-exchange",
        headers={"X-Forwarded-For": "203.0.113.5"},
    )
    assert resp.status_code == 401


def test_trusted_source_reaches_handler(app_with_public, monkeypatch):
    calls = make_call_counter(monkeypatch, GOOD_PAYLOAD)
    client = TestClient(app_with_public)
    resp = client.get(
        "/simulation/operator/councilor-exchange",

    )
    assert resp.status_code == 200
    assert len(calls) == 1


def test_unauthorized_invokes_get_entries_zero_times(app_with_public, monkeypatch):
    calls = make_call_counter(monkeypatch, GOOD_PAYLOAD)
    client = untrusted_client(app_with_public)
    resp = client.get("/simulation/operator/councilor-exchange")
    assert resp.status_code == 401
    assert calls == []


def test_unauthorized_with_invalid_view_still_401(app_with_public, monkeypatch):
    make_call_counter(monkeypatch, GOOD_PAYLOAD)
    client = untrusted_client(app_with_public)
    resp = client.get(
        "/simulation/operator/councilor-exchange?view=dashboard",
    )
    assert resp.status_code == 401


def test_trusted_source_passes_before_limit_validation(app_with_public, monkeypatch):
    # With a trusted source, the (invalid) limit is validated by the handler
    # and returns 400 -- proving auth passed and validation ran, not a 401.
    make_call_counter(monkeypatch, GOOD_PAYLOAD)
    client = TestClient(app_with_public)
    resp = client.get(
        "/simulation/operator/councilor-exchange?limit=abc",

    )
    assert resp.status_code == 400
    assert resp.status_code != 401


def test_default_view_is_shared(app_with_public, monkeypatch):
    calls = make_call_counter(monkeypatch, GOOD_PAYLOAD)
    client = TestClient(app_with_public)
    client.get(
        "/simulation/operator/councilor-exchange",

    )
    assert calls[0]["view"] == "shared"


def test_default_limit_is_50(app_with_public, monkeypatch):
    calls = make_call_counter(monkeypatch, GOOD_PAYLOAD)
    client = TestClient(app_with_public)
    client.get(
        "/simulation/operator/councilor-exchange",

    )
    assert calls[0]["limit"] == 50


def test_shared_view_allows_absent_char_id(app_with_public, monkeypatch):
    calls = make_call_counter(monkeypatch, GOOD_PAYLOAD)
    client = TestClient(app_with_public)
    resp = client.get(
        "/simulation/operator/councilor-exchange?view=shared",

    )
    assert resp.status_code == 200
    assert calls[0]["char_id"] is None


def test_inbox_without_char_id_400(app_with_public):
    client = TestClient(app_with_public)
    resp = client.get(
        "/simulation/operator/councilor-exchange?view=inbox",

    )
    assert resp.status_code == 400


def test_outbox_without_char_id_400(app_with_public):
    client = TestClient(app_with_public)
    resp = client.get(
        "/simulation/operator/councilor-exchange?view=outbox",

    )
    assert resp.status_code == 400


def test_unknown_char_id_400(app_with_public):
    client = TestClient(app_with_public)
    resp = client.get(
        "/simulation/operator/councilor-exchange?view=inbox&char_id=char_999",

    )
    assert resp.status_code == 400


def test_invalid_view_400(app_with_public):
    client = TestClient(app_with_public)
    resp = client.get(
        "/simulation/operator/councilor-exchange?view=dashboard",

    )
    assert resp.status_code == 400


def test_non_integer_limit_400_not_422(app_with_public, monkeypatch):
    make_call_counter(monkeypatch, GOOD_PAYLOAD)
    client = TestClient(app_with_public)
    resp = client.get(
        "/simulation/operator/councilor-exchange?limit=abc",

    )
    assert resp.status_code == 400
    assert resp.status_code != 422


def test_limit_zero_400(app_with_public, monkeypatch):
    make_call_counter(monkeypatch, GOOD_PAYLOAD)
    client = TestClient(app_with_public)
    resp = client.get(
        "/simulation/operator/councilor-exchange?limit=0",

    )
    assert resp.status_code == 400


def test_limit_201_400(app_with_public, monkeypatch):
    make_call_counter(monkeypatch, GOOD_PAYLOAD)
    client = TestClient(app_with_public)
    resp = client.get(
        "/simulation/operator/councilor-exchange?limit=201",

    )
    assert resp.status_code == 400


def test_limit_1_succeeds(app_with_public, monkeypatch):
    calls = make_call_counter(monkeypatch, GOOD_PAYLOAD)
    client = TestClient(app_with_public)
    resp = client.get(
        "/simulation/operator/councilor-exchange?limit=1",

    )
    assert resp.status_code == 200
    assert calls[0]["limit"] == 1


def test_limit_200_succeeds(app_with_public, monkeypatch):
    calls = make_call_counter(monkeypatch, GOOD_PAYLOAD)
    client = TestClient(app_with_public)
    resp = client.get(
        "/simulation/operator/councilor-exchange?limit=200",

    )
    assert resp.status_code == 200
    assert calls[0]["limit"] == 200


def test_empty_ledger_exact_shape(app_with_public, monkeypatch):
    make_call_counter(monkeypatch, EMPTY_PAYLOAD)
    client = TestClient(app_with_public)
    resp = client.get(
        "/simulation/operator/councilor-exchange",

    )
    assert resp.status_code == 200
    assert resp.json() == EMPTY_PAYLOAD


def test_populated_result_returned_unchanged(app_with_public, monkeypatch):
    make_call_counter(monkeypatch, GOOD_PAYLOAD)
    client = TestClient(app_with_public)
    resp = client.get(
        "/simulation/operator/councilor-exchange",

    )
    assert resp.json() == GOOD_PAYLOAD


def test_store_unavailable_503(app_with_public, monkeypatch):
    def fake_get_entries(**kwargs):
        raise StoreUnavailableError("Exchange ledger store is unavailable")

    monkeypatch.setattr(route_module, "get_entries", fake_get_entries)
    client = TestClient(app_with_public)
    resp = client.get(
        "/simulation/operator/councilor-exchange",

    )
    assert resp.status_code == 503
    assert "unavailable" in resp.json()["detail"].lower()


def test_store_error_text_absent_from_response(app_with_public, monkeypatch):
    def fake_get_entries(**kwargs):
        raise StoreUnavailableError("Exchange ledger store is unavailable")

    monkeypatch.setattr(route_module, "get_entries", fake_get_entries)
    client = TestClient(app_with_public)
    resp = client.get(
        "/simulation/operator/councilor-exchange",

    )
    body = resp.text
    assert "REDIS_DOWN" not in body
    assert "connection refused" not in body
    assert "redis://" not in body


def test_get_entries_invoked_once(app_with_public, monkeypatch):
    calls = make_call_counter(monkeypatch, GOOD_PAYLOAD)
    client = TestClient(app_with_public)
    client.get(
        "/simulation/operator/councilor-exchange",

    )
    assert len(calls) == 1


def test_router_explicitly_requires_operator():
    # The router declares require_operator as a dependency.
    dep_functions = []
    for routes in exchange_router.routes:
        for dep in getattr(routes, "dependencies", []):
            dep_functions.append(dep.dependency)
    assert require_operator_ref() in dep_functions


def require_operator_ref():
    from operator_auth import require_operator

    return require_operator


def test_public_route_accessible_without_key(app_with_public, monkeypatch):
    client = TestClient(app_with_public)
    resp = client.get("/public/ping")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_no_contract_input_returns_422(app_with_public):
    # Exercise every contract-input failure path with a trusted source and
    # assert the route returns 400 (never 422) from the real helper.
    client = TestClient(app_with_public)
    cases = [
        "?view=dashboard",
        "?view=inbox",
        "?view=outbox",
        "?view=inbox&char_id=char_999",
        "?limit=abc",
        "?limit=0",
        "?limit=201",
    ]
    for q in cases:
        resp = client.get(
            f"/simulation/operator/councilor-exchange{q}",

        )
        assert resp.status_code != 422, f"422 for {q}"
        assert resp.status_code == 400, f"expected 400 for {q}, got {resp.status_code}"


def test_empty_view_query_normalizes_to_shared(app_with_public, monkeypatch):
    calls = make_call_counter(monkeypatch, GOOD_PAYLOAD)
    client = TestClient(app_with_public)
    resp = client.get(
        "/simulation/operator/councilor-exchange?view=",

    )
    assert resp.status_code == 200
    assert resp.status_code != 422
    assert len(calls) == 1
    assert calls[0]["view"] == "shared"
    assert calls[0]["limit"] == 50


def test_empty_limit_query_normalizes_to_50(app_with_public, monkeypatch):
    calls = make_call_counter(monkeypatch, GOOD_PAYLOAD)
    client = TestClient(app_with_public)
    resp = client.get(
        "/simulation/operator/councilor-exchange?limit=",

    )
    assert resp.status_code == 200
    assert resp.status_code != 422
    assert len(calls) == 1
    assert calls[0]["limit"] == 50
    assert calls[0]["view"] == "shared"


# ---------------------------------------------------------------------------
# Wiring proofs added after isolated route tests pass.
# ---------------------------------------------------------------------------

def test_import_main_app_no_redis(monkeypatch):
    """Importing main.app must not contact Redis (no get_entries call)."""
    calls = []

    def fake_get_entries(**kwargs):
        calls.append(True)
        return EMPTY_PAYLOAD

    monkeypatch.setattr(councilor_exchange, "get_entries", fake_get_entries)

    import main  # noqa: F401

    assert calls == [], "main.app import triggered get_entries"


def test_main_has_exact_operator_route(monkeypatch):
    import main

    paths = [
        (getattr(r, "path", None), sorted(d.dependency.__name__ for d in getattr(r, "dependencies", [])))
        for r in main.app.routes
    ]
    target = "/simulation/operator/councilor-exchange"
    matches = [p for p in paths if p[0] == target]
    assert len(matches) == 1, f"expected exactly one {target}, found {len(matches)}"


def test_main_route_retains_operator_dep(monkeypatch):
    import main
    from operator_auth import require_operator

    for r in main.app.routes:
        if getattr(r, "path", None) == "/simulation/operator/councilor-exchange":
            dep_names = [d.dependency for d in getattr(r, "dependencies", [])]
            assert require_operator in dep_names
            return
    raise AssertionError("operator route not found in main.app")


def test_main_import_does_not_call_get_entries(monkeypatch):
    calls = []

    def fake_get_entries(**kwargs):
        calls.append(True)
        return EMPTY_PAYLOAD

    monkeypatch.setattr(councilor_exchange, "get_entries", fake_get_entries)
    import main  # noqa: F401

    assert calls == []


def test_main_public_routes_remain_mounted(monkeypatch):
    import main

    mounted = {getattr(r, "path", None) for r in main.app.routes}
    assert "/metrics" in mounted or any(
        p and p.startswith("/councilor/needs") for p in mounted
    )


def test_no_duplicate_route_registration(monkeypatch):
    import main

    target = "/simulation/operator/councilor-exchange"
    count = sum(
        1 for r in main.app.routes if getattr(r, "path", None) == target
    )
    assert count == 1
