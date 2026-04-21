"""Multi-provider market data client (Binance -> Kraken -> CoinGecko)."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Iterable, Optional

import requests

from utils.coingecko_client import fetch_simple_price as coingecko_fetch_simple_price

logger = logging.getLogger(__name__)

BINANCE_BASE_URL = "https://api.binance.com"
KRAKEN_BASE_URL = "https://api.kraken.com"

MIN_INTERVAL_SECONDS = 1.0
MAX_RETRIES = 3
TIMEOUT_SECONDS = 10

_lock = threading.Lock()
_last_call_ts = 0.0


COINGECKO_ID_TO_BASE = {
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "solana": "SOL",
    "usd-coin": "USDC",
    "tether": "USDT",
    "raydium": "RAY",
    "orca": "ORCA",
}

BINANCE_SYMBOLS = {
    "bitcoin": "BTCUSDT",
    "ethereum": "ETHUSDT",
    "solana": "SOLUSDT",
    "usd-coin": "USDCUSDT",
    "tether": "USDTUSDT",
    "raydium": "RAYUSDT",
    "orca": "ORCAUSDT",
}

KRAKEN_SYMBOLS = {
    "bitcoin": "XBTUSD",
    "ethereum": "ETHUSD",
    "solana": "SOLUSD",
    "usd-coin": "USDCUSD",
    "tether": "USDTUSD",
}


def _rate_limited_get(url: str, params: Optional[Dict[str, Any]] = None) -> requests.Response:
    global _last_call_ts

    with _lock:
        now = time.time()
        wait = MIN_INTERVAL_SECONDS - (now - _last_call_ts)
        if wait > 0:
            time.sleep(wait)
        response = requests.get(url, params=params, timeout=TIMEOUT_SECONDS)
        _last_call_ts = time.time()

    return response


def _safe_get(url: str, params: Optional[Dict[str, Any]] = None) -> requests.Response:
    last_exc: Optional[Exception] = None

    for attempt in range(MAX_RETRIES):
        try:
            response = _rate_limited_get(url, params=params)
            if response.status_code in {418, 429}:
                sleep_time = (attempt + 1) * 2
                time.sleep(sleep_time)
                continue
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < (MAX_RETRIES - 1):
                time.sleep((attempt + 1) * 2)
                continue
            raise

    if last_exc:
        raise last_exc
    raise RuntimeError("Market data request failed without response")


def _to_coin_gecko_shape(
    coingecko_id: str,
    price: float,
    volume_24h: float = 0.0,
    price_change_24h: float = 0.0,
) -> Dict[str, Any]:
    return {
        coingecko_id: {
            "usd": price,
            "usd_24h_vol": volume_24h,
            "usd_24h_change": price_change_24h,
            "market_cap": {"usd": 0},
        }
    }


def _fetch_binance(coingecko_id: str) -> Optional[Dict[str, Any]]:
    symbol = BINANCE_SYMBOLS.get(coingecko_id)
    if not symbol:
        return None

    url = f"{BINANCE_BASE_URL}/api/v3/ticker/24hr"
    params = {"symbol": symbol}
    response = _safe_get(url, params=params)
    data = response.json()

    try:
        price = float(data.get("lastPrice", 0))
        volume = float(data.get("quoteVolume", 0))
        change = float(data.get("priceChange", 0))
    except (TypeError, ValueError):
        return None

    return _to_coin_gecko_shape(coingecko_id, price, volume, change)


def _fetch_kraken(coingecko_id: str) -> Optional[Dict[str, Any]]:
    pair = KRAKEN_SYMBOLS.get(coingecko_id)
    if not pair:
        return None

    url = f"{KRAKEN_BASE_URL}/0/public/Ticker"
    params = {"pair": pair}
    response = _safe_get(url, params=params)
    payload = response.json()
    result = payload.get("result", {})
    if not result:
        return None

    key = next(iter(result.keys()), None)
    if not key:
        return None
    ticker = result.get(key, {})

    try:
        price = float(ticker.get("c", [0])[0])
        open_price = float(ticker.get("o", 0))
        volume = float(ticker.get("v", [0])[1])
        change = price - open_price
    except (TypeError, ValueError, IndexError):
        return None

    return _to_coin_gecko_shape(coingecko_id, price, volume, change)


def fetch_simple_price(
    ids: Iterable[str],
    vs_currency: str = "usd",
    include_market_cap: bool = True,
    include_24hr_vol: bool = True,
    include_24hr_change: bool = True,
    include_last_updated_at: bool = True,
) -> Dict[str, Any]:
    ids_list = [i for i in ids if i]
    if not ids_list:
        return {}

    results: Dict[str, Any] = {}
    for coingecko_id in ids_list:
        try:
            data = _fetch_binance(coingecko_id)
            if not data:
                data = _fetch_kraken(coingecko_id)
            if not data:
                data = coingecko_fetch_simple_price(
                    ids=[coingecko_id],
                    vs_currency=vs_currency,
                    include_market_cap=include_market_cap,
                    include_24hr_vol=include_24hr_vol,
                    include_24hr_change=include_24hr_change,
                    include_last_updated_at=include_last_updated_at,
                )
            if data and coingecko_id in data:
                results[coingecko_id] = data[coingecko_id]
        except Exception as exc:
            logger.warning("Market data fetch failed for %s: %s", coingecko_id, exc)

    return results