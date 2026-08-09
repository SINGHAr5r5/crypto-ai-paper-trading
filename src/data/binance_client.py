"""Thin client for Binance's public REST klines endpoint (no API key needed).

Uses data-api.binance.vision (Binance's public market-data mirror) instead of
api.binance.com: the main domain returns HTTP 451 for US-region IPs, which is
where GitHub Actions' hosted runners live — the vision mirror serves the same
market data without that geo-restriction.
"""

import time

import requests

BASE_URL = "https://data-api.binance.vision/api/v3/klines"
MAX_LIMIT = 1000

KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_asset_volume", "num_trades",
    "taker_buy_base", "taker_buy_quote", "ignore",
]


def fetch_klines_page(symbol: str, interval: str, start_time_ms: int, limit: int = MAX_LIMIT) -> list[list]:
    """Fetch one page (<=1000 candles) starting at start_time_ms (inclusive)."""
    resp = requests.get(
        BASE_URL,
        params={
            "symbol": symbol,
            "interval": interval,
            "startTime": start_time_ms,
            "limit": limit,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def iter_klines(symbol: str, interval: str, start_time_ms: int, end_time_ms: int, sleep_s: float = 0.4):
    """Yield raw Binance kline rows from start_time_ms up to end_time_ms, paginating transparently."""
    cursor = start_time_ms
    while cursor < end_time_ms:
        page = fetch_klines_page(symbol, interval, cursor)
        if not page:
            break
        for row in page:
            if row[0] > end_time_ms:
                return
            yield row
        last_open_time = page[-1][0]
        if last_open_time <= cursor:
            break  # safety: no forward progress, avoid infinite loop
        cursor = last_open_time + 1
        if len(page) < MAX_LIMIT:
            break  # short page means we've caught up to "now"
        time.sleep(sleep_s)
