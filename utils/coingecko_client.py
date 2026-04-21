"""Centralized CoinGecko client with rate limiting and backoff."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, Iterable, Optional

import requests

logger = logging.getLogger(__name__)

COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"
MIN_INTERVAL_SECONDS = 6.0  # ~10 calls/minute
MAX_RETRIES = 3
TIMEOUT_SECONDS = 10

# Read API key from environment variable
API_KEY = os.getenv("COINGECKO_API_KEY")

_lock = threading.Lock()
_last_call_ts = 0.0


def _rate_limited_get(url: str, params: Optional[Dict[str, Any]] = None) -> requests.Response:
    """Make HTTP GET with rate limiting (MIN_INTERVAL_SECONDS between calls)."""
    global _last_call_ts

    # Build headers with API key if available
    headers = {}
    if API_KEY:
        headers["x-cg-demo-api-key"] = API_KEY

    with _lock:
        now = time.time()
        wait = MIN_INTERVAL_SECONDS - (now - _last_call_ts)
        if wait > 0:
            logger.debug(f"[COINGECKO] Rate limit: sleeping {wait:.2f}s")
            time.sleep(wait)
        response = requests.get(url, params=params, headers=headers, timeout=TIMEOUT_SECONDS)
        _last_call_ts = time.time()

    return response


def _safe_get_with_backoff(url: str, params: Optional[Dict[str, Any]] = None) -> requests.Response:
    """Make request with exponential backoff on 429 (rate limit) errors."""
    last_exc: Optional[Exception] = None

    for attempt in range(MAX_RETRIES):
        try:
            response = _rate_limited_get(url, params=params)
            
            # Handle 429 with backoff
            if response.status_code == 429:
                sleep_time = (attempt + 1) * 5
                logger.warning(f"[COINGECKO] 429 received on attempt {attempt + 1}, backing off {sleep_time}s")
                time.sleep(sleep_time)
                continue
            
            response.raise_for_status()
            return response
            
        except requests.HTTPError as exc:
            # Special handling for 429 in exception form
            if exc.response is not None and exc.response.status_code == 429:
                sleep_time = (attempt + 1) * 5
                logger.warning(f"[COINGECKO] 429 (HTTPError) on attempt {attempt + 1}, backing off {sleep_time}s")
                time.sleep(sleep_time)
                last_exc = exc
                if attempt < (MAX_RETRIES - 1):
                    continue
                else:
                    raise
            else:
                last_exc = exc
                if attempt < (MAX_RETRIES - 1):
                    time.sleep((attempt + 1) * 2)
                    continue
                raise
                
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < (MAX_RETRIES - 1):
                time.sleep((attempt + 1) * 2)
                continue
            raise

    if last_exc:
        raise last_exc
    raise RuntimeError("CoinGecko request failed without response")


def fetch_simple_price(
    ids: Iterable[str],
    vs_currency: str = "usd",
    include_market_cap: bool = True,
    include_24hr_vol: bool = True,
    include_24hr_change: bool = True,
    include_last_updated_at: bool = True,
) -> Dict[str, Any]:
    """Fetch simple price data for given cryptocurrency IDs."""
    ids_list = [i for i in ids if i]
    if not ids_list:
        return {}

    endpoint = f"{COINGECKO_BASE_URL}/simple/price"
    params = {
        "ids": ",".join(ids_list),
        "vs_currencies": vs_currency,
        "include_market_cap": "true" if include_market_cap else "false",
        "include_24hr_vol": "true" if include_24hr_vol else "false",
        "include_24hr_change": "true" if include_24hr_change else "false",
        "include_last_updated_at": "true" if include_last_updated_at else "false",
    }

    response = _safe_get_with_backoff(endpoint, params=params)
    data = response.json()
    if isinstance(data, dict):
        return data
    return {}
