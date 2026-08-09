"""Builds docs/index.html — a static snapshot dashboard of the paper-trading
pipeline's current state (pipeline status, per-symbol price/indicators, BTCUSDT
chart). Pulls fresh data from Supabase every run; fonts are pre-baked into
web/template.html as base64 (see web/fonts/*.b64, sourced from Google Fonts).

Usage:
    python web/build.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.supabase_client import run_sql

WEB_DIR = Path(__file__).resolve().parent
REPO_ROOT = WEB_DIR.parent
SYMBOLS_ORDER = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
MAIN_CHART_SYMBOL = "BTCUSDT"
MAIN_CHART_CANDLES = 90
SPARKLINE_DAYS = 10


def fetch_latest_snapshot():
    rows = run_sql("""
        select distinct on (o.symbol) o.symbol, o.open_time, o.close,
          i.rsi14, i.macd_hist, i.ema20, i.ema50, i.ema200, i.atr14, i.bb_width
        from ohlcv o
        left join indicators i on i.symbol=o.symbol and i.timeframe=o.timeframe and i.open_time=o.open_time
        where o.timeframe = '4h'
        order by o.symbol, o.open_time desc;
    """)
    return {r["symbol"]: r for r in rows}


def fetch_24h_ago_closes():
    rows = run_sql("""
        select symbol, close as close_24h_ago from ohlcv
        where timeframe='1h' and open_time <= now() - interval '24 hours'
        and (symbol, open_time) in (
          select symbol, max(open_time) from ohlcv
          where timeframe='1h' and open_time <= now() - interval '24 hours'
          group by symbol
        );
    """)
    return {r["symbol"]: float(r["close_24h_ago"]) for r in rows}


def fetch_main_chart_candles(symbol: str, limit: int):
    rows = run_sql(f"""
        select o.open_time, o.open, o.high, o.low, o.close, i.ema20, i.ema50, i.rsi14
        from ohlcv o
        left join indicators i on i.symbol=o.symbol and i.timeframe=o.timeframe and i.open_time=o.open_time
        where o.symbol = '{symbol}' and o.timeframe = '4h'
        order by o.open_time desc
        limit {limit};
    """)
    return list(reversed(rows))


def fetch_sparklines(symbols: list[str], days: int):
    symbols_sql = ", ".join(f"'{s}'" for s in symbols)
    rows = run_sql(f"""
        select symbol, open_time, close from ohlcv
        where symbol in ({symbols_sql}) and timeframe='4h'
        and open_time > now() - interval '{days} days'
        order by symbol, open_time;
    """)
    out: dict[str, list[float]] = {}
    for r in rows:
        out.setdefault(r["symbol"], []).append(float(r["close"]))
    return out


def fetch_pipeline_status():
    rows = run_sql("""
        select 'ohlcv' as t, count(*) c, min(open_time) mn, max(open_time) mx from ohlcv
        union all
        select 'indicators', count(*), min(open_time), max(open_time) from indicators;
    """)
    return {r["t"]: r for r in rows}


def build_data():
    latest = fetch_latest_snapshot()
    prev_closes = fetch_24h_ago_closes()

    symbols_out = []
    for sym in SYMBOLS_ORDER:
        row = latest.get(sym)
        if row is None:
            continue
        close = float(row["close"])
        prev = prev_closes.get(sym)
        change_pct = round((close - prev) / prev * 100, 2) if prev else None
        symbols_out.append({
            "symbol": sym,
            "close": close,
            "change_pct": change_pct,
            "rsi14": float(row["rsi14"]) if row["rsi14"] is not None else None,
            "macd_hist": float(row["macd_hist"]) if row["macd_hist"] is not None else None,
            "ema20": float(row["ema20"]) if row["ema20"] is not None else None,
            "ema50": float(row["ema50"]) if row["ema50"] is not None else None,
            "ema200": float(row["ema200"]) if row["ema200"] is not None else None,
            "atr14": float(row["atr14"]) if row["atr14"] is not None else None,
            "bb_width": float(row["bb_width"]) if row["bb_width"] is not None else None,
        })

    main_rows = fetch_main_chart_candles(MAIN_CHART_SYMBOL, MAIN_CHART_CANDLES)
    btc_candles = [{
        "t": r["open_time"],
        "o": float(r["open"]), "h": float(r["high"]), "l": float(r["low"]), "c": float(r["close"]),
        "ema20": float(r["ema20"]) if r["ema20"] is not None else None,
        "ema50": float(r["ema50"]) if r["ema50"] is not None else None,
        "rsi14": float(r["rsi14"]) if r["rsi14"] is not None else None,
    } for r in main_rows]

    other_symbols = [s for s in SYMBOLS_ORDER if s != MAIN_CHART_SYMBOL]
    sparklines = fetch_sparklines(other_symbols, SPARKLINE_DAYS)

    status = fetch_pipeline_status()
    from datetime import datetime, timezone
    pipeline = {
        "ohlcv_rows": status["ohlcv"]["c"],
        "indicator_rows": status["indicators"]["c"],
        "range_start": status["ohlcv"]["mn"][:10],
        "range_end": status["ohlcv"]["mx"][:10],
        "symbols_count": len(SYMBOLS_ORDER),
        "timeframes": ["1h", "4h"],
    }

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "symbols": symbols_out,
        "btc_candles": btc_candles,
        "sparklines": sparklines,
        "pipeline": pipeline,
    }


def render_candle_table_rows(candles: list[dict]) -> str:
    rows = []
    for c in candles[-20:]:
        def fp(v):
            if v is None:
                return "—"
            dp = 4 if v < 10 else 2
            return f"{v:,.{dp}f}"
        rsi = f"{c['rsi14']:.1f}" if c["rsi14"] is not None else "—"
        rows.append(
            f"<tr><td>{c['t'][:16].replace('T', ' ')}</td>"
            f"<td class='mono'>{fp(c['o'])}</td><td class='mono'>{fp(c['h'])}</td>"
            f"<td class='mono'>{fp(c['l'])}</td><td class='mono'>{fp(c['c'])}</td>"
            f"<td class='mono'>{fp(c['ema20'])}</td><td class='mono'>{fp(c['ema50'])}</td>"
            f"<td class='mono'>{rsi}</td></tr>"
        )
    return "\n".join(reversed(rows))


def main():
    data = build_data()

    template = (WEB_DIR / "template.html").read_text()
    fonts = {}
    for name in ["mono400", "mono500", "mono600", "sanscond400", "sanscond500", "sanscond600", "sanscond700"]:
        fonts[name] = (WEB_DIR / "fonts" / f"{name}.b64").read_text().strip()

    html = template
    html = html.replace("__FONT_MONO_400__", fonts["mono400"])
    html = html.replace("__FONT_MONO_500__", fonts["mono500"])
    html = html.replace("__FONT_MONO_600__", fonts["mono600"])
    html = html.replace("__FONT_SANSCOND_400__", fonts["sanscond400"])
    html = html.replace("__FONT_SANSCOND_500__", fonts["sanscond500"])
    html = html.replace("__FONT_SANSCOND_600__", fonts["sanscond600"])
    html = html.replace("__FONT_SANSCOND_700__", fonts["sanscond700"])
    html = html.replace("__GENERATED_AT__", data["generated_at"])
    html = html.replace("__CANDLE_TABLE_ROWS__", render_candle_table_rows(data["btc_candles"]))
    html = html.replace("__DASHBOARD_DATA__", json.dumps(data))

    docs_dir = REPO_ROOT / "docs"
    docs_dir.mkdir(exist_ok=True)
    out_path = docs_dir / "index.html"
    out_path.write_text(html)
    print(f"Wrote {out_path} ({out_path.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
