"""
Isolated tests for the Phase 2 operator authorization dependency.

These tests prove Gate A behavior without touching Redis, the VPS, or any
real secret. Authorization is by **source-network trust** (only the Tailscale
range 100.64.0.0/10 and loopback 127.0.0.0/8), not by a shared key, so no
credential is involved.

CRITICAL SECURITY MODEL (2026-07-17 fix):
    Trust is derived ONLY from Uvicorn's proxy-validated `request.client.host`.
    Uvicorn sets that value from forwarded headers *only when the direct proxy
    IP is in `--forwarded-allow-ips`* (the Traefik container 172.16.2.7). The
    operator_auth module never parses X-Forwarded-For / X-Real-IP, so a public
    visitor cannot spoof a trusted address. In Starlette's TestClient the
    validated client address is supplied via the `client=` parameter, which is
    the correct analog of Uvicorn's proxy-validated `request.client`.

No secret value ever appears in response bodies, captured logs, or
assertions.
"""

import logging
import sys
from pathlib import Path

# Make the backend package importable when pytest runs from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import pytest
from fastapi import FastAPI, Depends, Request
from fastapi.testclient import TestClient

import operator_auth
from operator_auth import require_operator


def _client_injector(app, addr):
    """ASGI wrapper that injects the proxy-validated client address into the
    scope the same way Uvicorn does once the direct proxy is trusted. This
    exercises the real require_operator / request.client.host path."""
    from starlette.types import Receive, Scope, Send

    async def wrapped(scope: Scope, receive: Receive, send: Send):
        if addr is not None:
            scope["client"] = addr
        await app(scope, receive, send)

    return wrapped


def build_app():
    """Build a minimal app that mounts only the operator dependency."""
    app = FastAPI()

    @app.get("/operator/protected")
    async def protected(_: None = Depends(require_operator)):
        return {"ok": True}

    return app


def client_with_app(addr=None):
    return TestClient(_client_injector(build_app(), addr))



def test_trusted_tailscale_source_succeeds():
    client = client_with_app(addr=("100.75.95.23", 54321))
    resp = client.get("/operator/protected")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_trusted_loopback_source_succeeds():
    client = client_with_app(addr=("127.0.0.1", 54321))
    resp = client.get("/operator/protected")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_untrusted_public_source_returns_401():
    client = client_with_app(addr=("203.0.113.5", 54321))
    resp = client.get("/operator/protected")
    assert resp.status_code == 401
    assert "denied" in resp.json()["detail"].lower()


def test_rfc1918_docker_source_now_untrusted_returns_401():
    # The old design trusted all RFC1918 ranges; after the fix only Tailscale
    # and loopback are trusted, so a Docker bridge address must be rejected.
    for untrusted in ("10.0.0.5", "172.18.0.4", "192.168.1.10", "169.254.1.1"):
        client = client_with_app(addr=(untrusted, 54321))
        resp = client.get("/operator/protected")
        assert resp.status_code == 401, f"expected denial for {untrusted}"


def test_spoofed_x_forwarded_for_cannot_bypass_guard():
    # X-Forwarded-For is attacker-controlled and must be ignored by the guard.
    client = client_with_app(addr=("203.0.113.9", 54321))
    resp = client.get(
        "/operator/protected",
        headers={"X-Forwarded-For": "100.75.95.23"},
    )
    assert resp.status_code == 401


def test_spoofed_first_hop_xff_chain_cannot_bypass_guard():
    client = client_with_app(addr=("198.51.100.7", 54321))
    resp = client.get(
        "/operator/protected",
        headers={"X-Forwarded-For": "203.0.113.9, 100.64.1.1"},
    )
    assert resp.status_code == 401


def test_untrusted_direct_peer_without_client_returns_401():
    client = client_with_app(addr=None)
    resp = client.get("/operator/protected")
    assert resp.status_code == 401


def test_no_redis_access(monkeypatch):
    """Gate A must not import or touch any Redis client."""
    redis_touched = []

    class _RedisBlocker:
        def __getattr__(self, name):
            redis_touched.append(name)
            raise AssertionError("Redis accessed during Gate A auth test")

    # Only block attribute access; restore the real modules afterward so the
    # monkeypatch cannot leak Redis-blocking state into later test imports.
    saved = {}
    for mod in list(sys.modules):
        if mod == "redis" or mod.startswith("redis."):
            saved[mod] = sys.modules[mod]
            sys.modules[mod] = _RedisBlocker()

    try:
        client = client_with_app(addr=("100.64.0.1", 54321))
        resp = client.get("/operator/protected")
        assert resp.status_code == 200
        assert redis_touched == []
    finally:
        for mod, real in saved.items():
            sys.modules[mod] = real


def test_public_routes_unaffected_in_isolated_app():
    """In the isolated test app, only the operator route requires trust."""
    app = FastAPI()

    @app.get("/public")
    async def public():
        return {"public": True}

    @app.get("/operator/protected")
    async def protected(_: None = Depends(require_operator)):
        return {"ok": True}

    client = TestClient(_client_injector(app, ("198.51.100.7", 54321)))

    public_resp = client.get("/public")
    assert public_resp.status_code == 200
    assert public_resp.json() == {"public": True}

    protected_resp = client.get("/operator/protected")
    assert protected_resp.status_code == 401
