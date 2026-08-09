"""Computes the indicator set defined in crypto-ai-paper-trading-spec.md §4
(`indicators` table) and upserts it back into Supabase.

Indicators are computed directly with pandas (EMA/RSI/MACD/Bollinger/ATR)
rather than via pandas-ta: that library is unmaintained and breaks on
numpy>=2.0 (it still references the removed `numpy.NaN`).

Usage:
    python -m src.indicators.compute
    python -m src.indicators.compute --symbols BTCUSDT --timeframes 1h
"""

import argparse
import math
import sys

import pandas as pd

sys.path.insert(0, __file__.rsplit("/src/", 1)[0])

from src.data.supabase_client import run_sql

DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "BNBUSDT"]
DEFAULT_TIMEFRAMES = ["1h", "4h"]
INSERT_BATCH_SIZE = 1000

INDICATOR_COLUMNS = [
    "rsi14", "macd", "macd_signal", "macd_hist",
    "ema20", "ema50", "ema200",
    "bb_upper", "bb_mid", "bb_lower", "bb_width",
    "atr14", "vol_ma20",
]


def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return true_range.ewm(alpha=1 / length, adjust=False).mean()


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    out["rsi14"] = rsi(out["close"], length=14)

    macd_line, signal_line, hist = macd(out["close"], fast=12, slow=26, signal=9)
    out["macd"] = macd_line
    out["macd_signal"] = signal_line
    out["macd_hist"] = hist

    out["ema20"] = out["close"].ewm(span=20, adjust=False).mean()
    out["ema50"] = out["close"].ewm(span=50, adjust=False).mean()
    out["ema200"] = out["close"].ewm(span=200, adjust=False).mean()

    bb_mid = out["close"].rolling(20).mean()
    bb_std = out["close"].rolling(20).std()
    out["bb_upper"] = bb_mid + 2 * bb_std
    out["bb_mid"] = bb_mid
    out["bb_lower"] = bb_mid - 2 * bb_std
    out["bb_width"] = (out["bb_upper"] - out["bb_lower"]) / out["bb_mid"]

    out["atr14"] = atr(out["high"], out["low"], out["close"], length=14)
    out["vol_ma20"] = out["volume"].rolling(20).mean()

    return out


def fetch_ohlcv(symbol: str, timeframe: str, recent: int | None = None) -> pd.DataFrame:
    order = "DESC" if recent else "ASC"
    limit_sql = f"LIMIT {recent}" if recent else ""
    rows = run_sql(f"""
        SELECT open_time, open, high, low, close, volume
        FROM ohlcv
        WHERE symbol = '{symbol}' AND timeframe = '{timeframe}'
        ORDER BY open_time {order}
        {limit_sql};
    """)
    if recent:
        rows = list(reversed(rows))
    df = pd.DataFrame(rows)
    df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df


def sql_literal(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "NULL"
    return repr(float(value))


def build_upsert_sql(symbol: str, timeframe: str, rows: pd.DataFrame) -> str:
    values = []
    for _, row in rows.iterrows():
        open_time_iso = row["open_time"].isoformat()
        cols_sql = ", ".join(sql_literal(row[c]) for c in INDICATOR_COLUMNS)
        values.append(f"('{symbol}', '{timeframe}', '{open_time_iso}', {cols_sql})")
    values_sql = ",\n".join(values)
    set_sql = ", ".join(f"{c} = EXCLUDED.{c}" for c in INDICATOR_COLUMNS)
    columns_sql = ", ".join(INDICATOR_COLUMNS)
    return f"""
        INSERT INTO indicators (symbol, timeframe, open_time, {columns_sql})
        VALUES
        {values_sql}
        ON CONFLICT (symbol, timeframe, open_time) DO UPDATE SET {set_sql};
    """


def store_indicators(symbol: str, timeframe: str, enriched: pd.DataFrame) -> int:
    total = 0
    for start in range(0, len(enriched), INSERT_BATCH_SIZE):
        batch = enriched.iloc[start:start + INSERT_BATCH_SIZE]
        run_sql(build_upsert_sql(symbol, timeframe, batch))
        total += len(batch)
        print(f"  [{symbol} {timeframe}] upserted {total}/{len(enriched)} rows")
    return total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    parser.add_argument("--timeframes", nargs="+", default=DEFAULT_TIMEFRAMES)
    parser.add_argument("--recent", type=int, default=None,
                         help="Only recompute over the last N candles (EMA/RSI/ATR converge within ~500 bars) "
                              "instead of full history — for fast incremental scheduled runs.")
    args = parser.parse_args()

    grand_total = 0
    for symbol in args.symbols:
        for timeframe in args.timeframes:
            print(f"\n=== {symbol} {timeframe} ===")
            candles = fetch_ohlcv(symbol, timeframe, recent=args.recent)
            if candles.empty:
                print("  no ohlcv rows found, skipping")
                continue
            enriched = compute_indicators(candles)
            grand_total += store_indicators(symbol, timeframe, enriched)

    print(f"\nDone. Upserted {grand_total} indicator rows total.")


if __name__ == "__main__":
    main()
