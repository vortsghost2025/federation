"""Phase 2 councilor-exchange read-only operator route (Gate C).

Exposes a single authenticated, read-only endpoint:

    GET /simulation/operator/councilor-exchange

Authentication is owned entirely by the `require_operator` dependency
(Gate A). This router never validates or reads any operator secret; it only
receives the authorization result. `require_operator` grants access by
source-network trust (Tailscale + internal Docker), not by a shared key, so
callers need no credential. Request validation (view / char_id / limit) is
performed manually so FastAPI never emits a 422 for contract inputs — the
contract requires 400/401/503 instead.

No Redis connection is created by this router; the helper builds or accepts
a client internally, and only after authorization succeeds.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status

from operator_auth import require_operator
from councilor_exchange import (
    get_entries,
    CouncilorExchangeValidationError,
    StoreUnavailableError,
)

router = APIRouter(
    prefix="/simulation/operator",
    tags=["councilor-exchange"],
    dependencies=[Depends(require_operator)],
)

DEFAULT_VIEW = "shared"
DEFAULT_LIMIT = 50
VALID_LIMIT_MIN = 1
VALID_LIMIT_MAX = 200


def _parse_limit(raw_limit: Optional[str]) -> int:
    """Parse and clamp the limit value manually (no 422)."""
    if raw_limit is None or raw_limit.strip() == "":
        return DEFAULT_LIMIT
    try:
        value = int(raw_limit.strip())
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="limit must be an integer",
        )
    if value < VALID_LIMIT_MIN or value > VALID_LIMIT_MAX:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"limit must be between {VALID_LIMIT_MIN} and {VALID_LIMIT_MAX}",
        )
    return value


def _normalize_view(raw_view: Optional[str]) -> str:
    if raw_view is None or raw_view.strip() == "":
        return DEFAULT_VIEW
    return raw_view.strip()


@router.get("/councilor-exchange")
def councilor_exchange(
    view: Optional[str] = None,
    char_id: Optional[str] = None,
    limit: Optional[str] = None,
):
    """Return councilor-exchange ledger entries (read-only).

    Authorization has already completed via `require_operator` before this
    handler runs. Validation failures become sanitized 400s; store failures
    become sanitized 503s. No raw exception text is returned.
    """
    normalized_view = _normalize_view(view)
    parsed_limit = _parse_limit(limit)

    try:
        result = get_entries(
            view=normalized_view,
            char_id=char_id,
            limit=parsed_limit,
        )
    except CouncilorExchangeValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid councilor exchange request",
        ) from exc
    except StoreUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Councilor exchange store is unavailable",
        ) from exc

    return result
