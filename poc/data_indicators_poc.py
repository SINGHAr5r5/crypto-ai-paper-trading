"""
Proof-of-concept: pull real OHLCV candles from Binance and compute the exact
indicator set defined in crypto-ai-paper-trading-spec.md §4 (indicators table).

No DB, no scheduler, no AI call — just proves the data + indicators leg of the
pipeline is programmable with the chosen stack (Python + pandas + Binance REST).

Indicators are computed directly with pandas (EMA/RSI/MACD/Bollinger/ATR) instead
of via pandas-ta: that library is unmaintained and breaks on numpy>=2.0 (it still
references the removed `numpy.NaN`), so implementing the formulas directly avoids
a dependency-version fight for no real benefit.

Usage:
    python poc/data_indicators_poc.py [SYMBOL] [INTERVAL] [LIMIT]
    python poc/data_indicators_poc.py BTCUSDT 4h 300
"""

import sys

import pandas as pd
import requests

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"

KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_asset_volume", "num_trades",
    "taker_buy_base", "taker_buy_quote", "ignore",
]


def fetch_klines(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    resp = requests.get(
        BINANCE_KLINES_URL,
        params={"symbol": symbol, "interval": interval, "limit": limit},
        timeout=10,
    )
    resp.raise_for_status()
    raw = resp.json()

    df = pd.DataFrame(raw, columns=KLINE_COLUMNS)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df[["open_time", "open", "high", "low", "close", "volume"]]


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


def main():
    symbol = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    interval = sys.argv[2] if len(sys.argv) > 2 else "4h"
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 300

    print(f"Fetching {limit} x {interval} candles for {symbol} from Binance...")
    candles = fetch_klines(symbol, interval, limit)
    print(f"Got {len(candles)} candles, {candles['open_time'].min()} -> {candles['open_time'].max()}")

    enriched = compute_indicators(candles)

    latest = enriched.iloc[-1]
    print("\nLatest closed candle + indicators (matches `indicators` table schema):")
    for col in [
        "open_time", "close", "rsi14", "macd", "macd_signal", "macd_hist",
        "ema20", "ema50", "ema200", "bb_upper", "bb_mid", "bb_lower",
        "bb_width", "atr14", "vol_ma20",
    ]:
        print(f"  {col:15s} {latest[col]}")

    print("\nLast 5 rows:")
    print(enriched.tail(5).to_string(index=False))


if __name__ == "__main__":
    main()
