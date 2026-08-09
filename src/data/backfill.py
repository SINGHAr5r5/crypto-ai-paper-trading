"""Backfill 3 years of OHLCV history from Binance into the `ohlcv` table.

Covers both timeframes the spec actually needs data for: base_timeframe (1h,
stored candles) and decision_tf (4h, what the rule scanner evaluates) — both
are native Binance intervals, so we pull each directly rather than resampling.

Usage:
    python -m src.data.backfill
    python -m src.data.backfill --symbols BTCUSDT ETHUSDT --years 1
"""

import argparse
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, __file__.rsplit("/src/", 1)[0])

from src.data.binance_client import KLINE_COLUMNS, iter_klines
from src.data.supabase_client import run_sql

DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "BNBUSDT"]
TIMEFRAMES = ["1h", "4h"]
INSERT_BATCH_SIZE = 1000


def sql_literal(value) -> str:
    return "NULL" if value is None else str(value)


def build_upsert_sql(symbol: str, timeframe: str, rows: list[list]) -> str:
    values = []
    for row in rows:
        open_time_iso = datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc).isoformat()
        o, h, l, c, v = row[1], row[2], row[3], row[4], row[5]
        values.append(
            f"('{symbol}', '{timeframe}', '{open_time_iso}', "
            f"{sql_literal(o)}, {sql_literal(h)}, {sql_literal(l)}, {sql_literal(c)}, {sql_literal(v)})"
        )
    values_sql = ",\n".join(values)
    return f"""
        INSERT INTO ohlcv (symbol, timeframe, open_time, open, high, low, close, volume)
        VALUES
        {values_sql}
        ON CONFLICT (symbol, timeframe, open_time) DO UPDATE SET
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume;
    """


def backfill_symbol_timeframe(symbol: str, timeframe: str, start_ms: int, end_ms: int) -> int:
    total = 0
    batch: list[list] = []

    def flush():
        nonlocal total
        if not batch:
            return
        run_sql(build_upsert_sql(symbol, timeframe, batch))
        total += len(batch)
        print(f"  [{symbol} {timeframe}] upserted {total} rows so far "
              f"(latest: {datetime.fromtimestamp(batch[-1][0] / 1000, tz=timezone.utc).date()})")
        batch.clear()

    for row in iter_klines(symbol, timeframe, start_ms, end_ms):
        batch.append(row)
        if len(batch) >= INSERT_BATCH_SIZE:
            flush()
    flush()
    return total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    parser.add_argument("--timeframes", nargs="+", default=TIMEFRAMES)
    parser.add_argument("--years", type=float, default=3.0)
    args = parser.parse_args()

    end = datetime.now(tz=timezone.utc)
    start = end - timedelta(days=365 * args.years)
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)

    print(f"Backfilling {args.symbols} x {args.timeframes} from {start.date()} to {end.date()}")

    grand_total = 0
    t0 = time.time()
    for symbol in args.symbols:
        for timeframe in args.timeframes:
            print(f"\n=== {symbol} {timeframe} ===")
            count = backfill_symbol_timeframe(symbol, timeframe, start_ms, end_ms)
            grand_total += count

    elapsed = time.time() - t0
    print(f"\nDone. Upserted {grand_total} candles total in {elapsed:.1f}s.")


if __name__ == "__main__":
    main()
