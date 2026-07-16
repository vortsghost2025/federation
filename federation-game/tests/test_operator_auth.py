"""
Isolated tests for the Phase 2 operator authentication dependency.

These tests prove Gate A behavior without touching Redis, the VPS, or any
real secret. The configured key is injected through a patched environment
variable. No supplied or configured credential ever appears in response
bodies, captured logs, or assertions.
"""

import logging
import os
import sys
from pathlib import Path

# Make the backend package importable when pytest runs from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import pytest
from fastapi import FastAPI, HTTPException, Depends
from fastapi.testclient import TestClient

import operator_auth
from operator_auth import require_operator, OPERATOR_HEADER, OPERATOR_ENV_VAR


TEST_KEY = "test-operator-key-do-not-use-in-production"


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    """Ensure a clean, controlled operator-key environment per test."""
    monkeypatch.delenv(OPERATOR_ENV_VAR, raising=False)
    monkeypatch.setenv(OPERATOR_ENV_VAR, TEST_KEY)
    yield
    monkeypatch.delenv(OPERATOR_ENV_VAR, raising=False)


def build_app():
    """Build a minimal app that mounts only the operator dependency."""
    app = FastAPI()

    @app.get("/operator/protected")
    async def protected(_: None = Depends(require_operator)):
        return {"ok": True}

    return app


def client_with_app():
    app = build_app()
    return TestClient(app)


def test_missing_header_returns_401():
    client = client_with_app()
    resp = client.get("/operator/protected")
    assert resp.status_code == 401
    assert "required" in resp.json()["detail"].lower()


def test_whitespace_only_header_returns_401():
    client = client_with_app()
    resp = client.get("/operator/protected", headers={OPERATOR_HEADER: "   "})
    assert resp.status_code == 401
    assert "required" in resp.json()["detail"].lower()


def test_empty_header_returns_401():
    client = client_with_app()
    resp = client.get("/operator/protected", headers={OPERATOR_HEADER: ""})
    assert resp.status_code == 401


def test_incorrect_key_returns_403():
    client = client_with_app()
    resp = client.get(
        "/operator/protected",
        headers={OPERATOR_HEADER: "wrong-key"},
    )
    assert resp.status_code == 403
    assert "invalid" in resp.json()["detail"].lower()


def test_correct_key_succeeds():
    client = client_with_app()
    resp = client.get(
        "/operator/protected",
        headers={OPERATOR_HEADER: TEST_KEY},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_missing_server_configuration_returns_503(monkeypatch):
    monkeypatch.delenv(OPERATOR_ENV_VAR, raising=False)
    client = client_with_app()
    resp = client.get(
        "/operator/protected",
        headers={OPERATOR_HEADER: TEST_KEY},
    )
    assert resp.status_code == 503
    assert "unavailable" in resp.json()["detail"].lower()


def test_empty_server_configuration_returns_503(monkeypatch):
    monkeypatch.setenv(OPERATOR_ENV_VAR, "")
    client = client_with_app()
    resp = client.get(
        "/operator/protected",
        headers={OPERATOR_HEADER: TEST_KEY},
    )
    assert resp.status_code == 503


def test_whitespace_server_configuration_returns_503(monkeypatch):
    monkeypatch.setenv(OPERATOR_ENV_VAR, "   ")
    client = client_with_app()
    resp = client.get(
        "/operator/protected",
        headers={OPERATOR_HEADER: TEST_KEY},
    )
    assert resp.status_code == 503


def test_credentials_not_in_response_body():
    client = client_with_app()
    # Both a wrong key and the correct key must never echo the secret.
    for key in ("wrong-key", TEST_KEY):
        resp = client.get(
            "/operator/protected",
            headers={OPERATOR_HEADER: key},
        )
        body = resp.text
        assert TEST_KEY not in body
        assert "wrong-key" not in body


def test_credentials_not_in_captured_logs(caplog):
    client = client_with_app()
    with caplog.at_level(logging.DEBUG, logger="federation.operator_auth"):
        client.get(
            "/operator/protected",
            headers={OPERATOR_HEADER: "wrong-key"},
        )
        client.get(
            "/operator/protected",
            headers={OPERATOR_HEADER: TEST_KEY},
        )
    for record in caplog.records:
        assert TEST_KEY not in record.getMessage()
        assert "wrong-key" not in record.getMessage()


def test_compare_digest_is_used(monkeypatch):
    """Confirm constant-time comparison is the path taken."""
    calls = []

    original = secrets_compare_digest_target()

    def spy(a, b):
        calls.append((a, b))
        return original(a, b)

    monkeypatch.setattr(operator_auth.secrets, "compare_digest", spy)
    client = client_with_app()
    resp = client.get(
        "/operator/protected",
        headers={OPERATOR_HEADER: TEST_KEY},
    )
    assert resp.status_code == 200
    assert len(calls) == 1
    # Neither argument should be the literal configured key in plaintext logs,
    # but functionally compare_digest received two strings.
    assert calls[0][0] == TEST_KEY


def secrets_compare_digest_target():
    import secrets as _secrets

    return _secrets.compare_digest


def test_no_redis_access(monkeypatch):
    """Gate A must not import or touch any Redis client."""
    import sys

    redis_touched = []

    class _RedisBlocker:
        def __getattr__(self, name):
            redis_touched.append(name)
            raise AssertionError("Redis accessed during Gate A auth test")

    for mod in list(sys.modules):
        if mod == "redis" or mod.startswith("redis."):
            monkeypatch.setattr(sys.modules, mod, _RedisBlocker())

    client = client_with_app()
    resp = client.get(
        "/operator/protected",
        headers={OPERATOR_HEADER: TEST_KEY},
    )
    assert resp.status_code == 200
    assert redis_touched == []


def test_public_routes_unaffected_in_isolated_app():
    """In the isolated test app, only the operator route requires auth."""

    app = FastAPI()

    @app.get("/public")
    async def public():
        return {"public": True}

    @app.get("/operator/protected")
    async def protected(_: None = Depends(require_operator)):
        return {"ok": True}

    client = TestClient(app)

    public_resp = client.get("/public")
    assert public_resp.status_code == 200
    assert public_resp.json() == {"public": True}

    # Operator route without key is still rejected.
    protected_resp = client.get("/operator/protected")
    assert protected_resp.status_code == 401
