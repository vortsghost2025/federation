"""
Phase 2 operator authentication dependency.

Provides a single reusable FastAPI dependency, `require_operator`, that
authorizes operator requests via the `X-Operator-Key` header against the
server-side runtime secret `FEDERATION_OPERATOR_API_KEY`.

Design rules (from PHASE2_OPERATOR_ROUTE_AUTH_CONTRACT.md, commit 563c7d3):

- The key is compared in constant time with `secrets.compare_digest`.
- A missing header, an empty header, or a whitespace-only header -> 401.
- A well-formed header carrying an incorrect key -> 403.
- A valid key lets the dependency succeed.
- A missing, empty, or malformed server configuration fails closed with a
  sanitized 503. No credential value is ever returned, logged, or raised.
- No Redis (or any other datastore) access happens here.
"""

import logging
import os
import secrets

from fastapi import Header, HTTPException, status

logger = logging.getLogger("federation.operator_auth")

OPERATOR_HEADER = "X-Operator-Key"
OPERATOR_ENV_VAR = "FEDERATION_OPERATOR_API_KEY"


def _load_configured_key() -> str:
    """Return the configured operator key.

    Raises HTTPException(503) when the server configuration is missing,
    empty, or malformed. The failure is sanitized: no key material is
    included in the detail or logs.
    """
    raw = os.environ.get(OPERATOR_ENV_VAR)
    if raw is None:
        logger.error("Operator authentication unavailable: server configuration missing")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Operator authentication is unavailable",
        )
    if not isinstance(raw, str) or raw.strip() == "":
        logger.error("Operator authentication unavailable: server configuration malformed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Operator authentication is unavailable",
        )
    return raw


async def require_operator(
    x_operator_key: str = Header(default=None, alias=OPERATOR_HEADER),
) -> None:
    """Authorize an operator request from the `X-Operator-Key` header.

    Returns nothing on success. Raises a sanitized HTTPException otherwise.
    No supplied or configured credential ever appears in the response,
    logs, or raised exception.
    """
    if x_operator_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Operator key required",
        )
    if not isinstance(x_operator_key, str) or x_operator_key.strip() == "":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Operator key required",
        )

    configured_key = _load_configured_key()

    if not secrets.compare_digest(x_operator_key, configured_key):
        logger.warning("Operator authentication failed: incorrect key")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operator key invalid",
        )

    # Success: no key material is logged.
    logger.debug("Operator authenticated")
