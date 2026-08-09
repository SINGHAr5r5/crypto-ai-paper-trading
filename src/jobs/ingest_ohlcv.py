"""Incremental OHLCV ingestion — spec §8 `ingest_ohlcv` job.

Fetches only new candles since the last stored one per (symbol, timeframe),
re-fetching the last stored candle too so an in-progress bar gets its final
values once it closes. Reuses the backfill machinery since "backfill the gap
since X" is the same operation as the original 3-year backfill, just with a
different start point.

Usage:
    python -m src.jobs.ingest_ohlcv
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.data.backfill import DEFAULT_SYMBOLS, TIMEFRAMES, backfill_symbol_timeframe
from src.data.supabase_client import run_sql

FALLBACK_LOOKBACK_MS = 5 * 24 * 60 * 60 * 1000  # 5 days, only used if a symbol/tf has no rows yet


def last_open_time_ms(symbol: str, timeframe: str):
    rows = run_sql(f"""
        select max(open_time) mx from ohlcv where symbol = '{symbol}' and timeframe = '{timeframe}';
    """)
    mx = rows[0]["mx"] if rows else None
    if mx is None:
        return None
    dt = datetime.fromisoformat(mx.replace("Z", "+00:00")) if isinstance(mx, str) else mx
    return int(dt.timestamp() * 1000)


def ingest_all(symbols=DEFAULT_SYMBOLS, timeframes=TIMEFRAMES):
    end_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    grand_total = 0
    for symbol in symbols:
        for timeframe in timeframes:
            start_ms = last_open_time_ms(symbol, timeframe)
            if start_ms is None:
                start_ms = end_ms - FALLBACK_LOOKBACK_MS
            if start_ms >= end_ms:
                continue
            count = backfill_symbol_timeframe(symbol, timeframe, start_ms, end_ms)
            grand_total += count
            print(f"[{symbol} {timeframe}] ingested/updated {count} candles")
    return grand_total


if __name__ == "__main__":
    total = ingest_all()
    print(f"Done. {total} candles ingested/updated.")
