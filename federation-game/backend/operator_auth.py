"""
Phase 2 operator authorization dependency.

Provides a single reusable FastAPI dependency, `require_operator`, that
authorizes operator requests automatically based on **network trust**
instead of a shared secret.

Why network trust (not a key):
    The Federation deployment exposes the backend through Traefik on a
    personal Hostinger VPS that is also a Tailscale node. Operator callers
    (Sean's agents, the worker, and Sean's own machines) always originate
    from either the Tailscale mesh (100.64.0.0/10) or the internal Docker
    network (fed-net). A shared-secret model would force every agent to
    know a key Sean cannot conveniently distribute, so trust is derived
    from the source network instead. Defense in depth is provided by a
    Traefik IPAllowList middleware that restricts the operator route to the
    same ranges at the proxy layer.

Design rules:

- Trusted source = Tailscale range 100.64.0.0/10 OR loopback (127.0.0.0/8).
- The client address is taken ONLY from Uvicorn's proxy-validated
  `request.client.host`. Forwarded headers are never parsed here (spoofable).
- Any request from outside the trusted ranges fails closed with 401.
- No credential value is ever returned, logged, or raised.
- No Redis (or any other datastore) access happens here.
"""

import ipaddress
import logging

from fastapi import HTTPException, Request, status

logger = logging.getLogger("federation.operator_auth")

# Tailscale's assigned CGNAT range. Every device on Sean's tailnet lives here.
TAILSCALE_NETWORK = ipaddress.ip_network("100.64.0.0/10")

# Only Tailscale mesh + loopback are trusted. RFC1918 / Docker ranges are
# intentionally excluded: public visitors arrive via Traefik (proxy-validated
# client = their real public IP), so they must never match.
TRUSTED_NETWORKS = [
    TAILSCALE_NETWORK,
    ipaddress.ip_network("127.0.0.0/8"),
]


def _client_address(request: Request) -> str:
    """Proxy-validated client address (Uvicorn sets this from forwarded data

    only when the direct proxy IP is in `--forwarded-allow-ips`).
    """
    return request.client.host if request.client else ""


def _is_trusted(address: str) -> bool:
    if not address:
        return False
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in net for net in TRUSTED_NETWORKS)


async def require_operator(request: Request) -> None:
    """Authorize an operator request by source network trust.

    Returns nothing on success. Raises a sanitized HTTPException (401)
    otherwise. No network detail that could aid reconnaissance is returned.
    """
    address = _client_address(request)
    if not _is_trusted(address):
        logger.warning("Operator authorization denied: untrusted source")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Operator access denied",
        )
    logger.debug("Operator authorized by network trust")
