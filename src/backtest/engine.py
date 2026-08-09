"""Rule-based backtest engine — spec §9 week 3 ("Backtest engine (rule-based
ล้วน ยังไม่ใช้ AI)") and §10.1/§10.3/§10.7.

Strategy (no AI, no manual tuning beyond what's already in the spec's own
config): go long when confluence_score >= 4 and the matched rules' net
direction (see src/scanner/confluence.py::net_direction) is UP; exit on
stop-loss, take-profit, or a >=4-confluence DOWN signal. Long-only — no
shorting, to avoid modeling margin/borrow mechanics the schema doesn't cover.

Look-ahead bias guard (§10.1): the full historical series is fetched once
per symbol for efficiency, but the simulation loop at step i only ever
passes `candles[symbol][:i+1]` into the rule engine — never a future row.
This is safe specifically because RSI/MACD/EMA/BB/ATR are strictly causal
(backward-only) rolling/EWM calculations: a precomputed value at time T
never depends on data after T, so slicing the precomputed series is
equivalent to recomputing it fresh at each step with `WHERE open_time <=
sim_time`.

Fees + slippage (§3, §10.4) are deducted on every simulated fill via an
"effective price" — the same technique used in web/template.html's sandbox
and documented there.

Usage:
    python -m src.backtest.engine --timeframe 4h
    python -m src.backtest.engine --timeframe 4h --start 2024-08-10 --end 2025-08-10
    python -m src.backtest.engine --compare-timeframes
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, pstdev

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.data.backfill import DEFAULT_SYMBOLS
from src.data.supabase_client import run_sql
from src.scanner.confluence import net_direction, score_candles

INITIAL_CAPITAL = 100_000  # spec §3 initial_capital; treated as USD here (Binance prices are USD, spec doesn't
                           # specify a THB/USD rate) — same simplification as web/template.html's sandbox.
TAKER_FEE_PCT = 0.10
SLIPPAGE_PCT = 0.05
FEE_FRAC = (TAKER_FEE_PCT + SLIPPAGE_PCT) / 100
MAX_POSITION_PCT = 20
MAX_OPEN_POSITIONS = 3
STOP_LOSS_PCT = 3.0
TAKE_PROFIT_PCT = 6.0
CONFLUENCE_ENTRY_THRESHOLD = 4
WARMUP_BARS = 250  # let EMA200 / BB-percentile (C3 needs 100 bars) stabilize before trusting signals


def fetch_series(symbol, timeframe, start=None, end=None):
    clauses = [f"o.symbol = '{symbol}'", f"o.timeframe = '{timeframe}'"]
    if start:
        clauses.append(f"o.open_time >= '{start}'")
    if end:
        clauses.append(f"o.open_time <= '{end}'")
    where = " AND ".join(clauses)
    rows = run_sql(f"""
        SELECT o.open_time, o.open, o.high, o.low, o.close, o.volume,
               i.rsi14, i.macd_hist, i.ema20, i.ema50, i.ema200,
               i.bb_upper, i.bb_mid, i.bb_lower, i.bb_width, i.atr14, i.vol_ma20
        FROM ohlcv o
        JOIN indicators i ON i.symbol = o.symbol AND i.timeframe = o.timeframe AND i.open_time = o.open_time
        WHERE {where}
        ORDER BY o.open_time ASC;
    """)

    def f(v):
        return float(v) if v is not None else None

    return [{
        "t": r["open_time"],
        "open": f(r["open"]), "high": f(r["high"]), "low": f(r["low"]), "close": f(r["close"]), "volume": f(r["volume"]),
        "rsi14": f(r["rsi14"]), "macd_hist": f(r["macd_hist"]),
        "ema20": f(r["ema20"]), "ema50": f(r["ema50"]), "ema200": f(r["ema200"]),
        "bb_upper": f(r["bb_upper"]), "bb_mid": f(r["bb_mid"]), "bb_lower": f(r["bb_lower"]), "bb_width": f(r["bb_width"]),
        "atr14": f(r["atr14"]), "vol_ma20": f(r["vol_ma20"]),
    } for r in rows]


class Position:
    def __init__(self, symbol, qty, entry_price, stop_loss, take_profit, opened_at):
        self.symbol = symbol
        self.qty = qty
        self.entry_price = entry_price
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.opened_at = opened_at


class BacktestState:
    def __init__(self, capital):
        self.cash = capital
        self.positions: dict[str, Position] = {}
        self.trades: list[dict] = []
        self.equity_curve: list[tuple] = []  # (timestamp, equity)

    def equity(self, price_at: dict):
        value = self.cash
        for sym, pos in self.positions.items():
            price = price_at.get(sym, pos.entry_price)
            value += pos.qty * price
        return value


def open_position(state: BacktestState, symbol, price, t):
    equity = state.cash + sum(p.qty * p.entry_price for p in state.positions.values())
    target_value = min(equity * MAX_POSITION_PCT / 100, state.cash)
    if target_value < 10:
        return
    effective_entry = price * (1 + FEE_FRAC)
    qty = target_value / effective_entry
    state.cash -= target_value
    state.positions[symbol] = Position(
        symbol, qty, effective_entry,
        stop_loss=price * (1 - STOP_LOSS_PCT / 100),
        take_profit=price * (1 + TAKE_PROFIT_PCT / 100),
        opened_at=t,
    )
    state.trades.append({"symbol": symbol, "side": "BUY", "qty": qty, "price": effective_entry,
                          "fee": target_value * FEE_FRAC, "executed_at": t, "pnl": None, "exit_reason": None})


def close_position(state: BacktestState, symbol, price, reason, t):
    pos = state.positions.pop(symbol)
    effective_exit = price * (1 - FEE_FRAC)
    proceeds = pos.qty * effective_exit
    cost_basis = pos.qty * pos.entry_price
    pnl = proceeds - cost_basis
    state.cash += proceeds
    state.trades.append({"symbol": symbol, "side": "SELL", "qty": pos.qty, "price": effective_exit,
                          "fee": proceeds * FEE_FRAC, "executed_at": t, "pnl": pnl, "exit_reason": reason})


def run_simulation(symbols, timeframe, start=None, end=None, capital=INITIAL_CAPITAL):
    print(f"Loading {symbols} {timeframe} candles" + (f" [{start} .. {end}]" if start or end else "") + "...")
    series = {sym: fetch_series(sym, timeframe, start, end) for sym in symbols}
    if "BTCUSDT" not in series:
        series["BTCUSDT"] = fetch_series("BTCUSDT", timeframe, start, end)
    lengths = {sym: len(c) for sym, c in series.items()}
    n = min(lengths.values())
    if n <= WARMUP_BARS:
        raise ValueError(f"not enough data: shortest series has {n} candles, need > {WARMUP_BARS}")

    btc = series["BTCUSDT"]
    state = BacktestState(capital)
    last_day = None

    for i in range(WARMUP_BARS, n):
        t = series[symbols[0]][i]["t"]
        btc_change_4h = None
        if i >= 1 and len(btc) > i:
            btc_change_4h = (btc[i]["close"] - btc[i - 1]["close"]) / btc[i - 1]["close"] * 100

        price_at = {sym: series[sym][i]["close"] for sym in symbols}

        # exits first
        for sym in list(state.positions.keys()):
            pos = state.positions[sym]
            c = series[sym][i]
            if c["low"] <= pos.stop_loss:
                close_position(state, sym, pos.stop_loss, "STOP_LOSS", t)
                continue
            if c["high"] >= pos.take_profit:
                close_position(state, sym, pos.take_profit, "TAKE_PROFIT", t)
                continue
            score, matched = score_candles(series[sym][max(0, i - 149):i + 1], btc_change_4h=btc_change_4h)
            if score >= CONFLUENCE_ENTRY_THRESHOLD and net_direction(matched) == "DOWN":
                close_position(state, sym, c["close"], "SIGNAL", t)

        # then entries, respecting the open-position cap
        for sym in symbols:
            if len(state.positions) >= MAX_OPEN_POSITIONS:
                break
            if sym in state.positions:
                continue
            c = series[sym][i]
            score, matched = score_candles(series[sym][max(0, i - 149):i + 1], btc_change_4h=btc_change_4h)
            if score >= CONFLUENCE_ENTRY_THRESHOLD and net_direction(matched) == "UP":
                open_position(state, sym, c["close"], t)

        day = t[:10]
        if day != last_day:
            state.equity_curve.append((t, state.equity(price_at)))
            last_day = day

    # close anything still open at the final candle
    final_t = series[symbols[0]][n - 1]["t"]
    for sym in list(state.positions.keys()):
        close_position(state, sym, series[sym][n - 1]["close"], "BACKTEST_END", final_t)
    state.equity_curve.append((final_t, state.cash))

    return state


def compute_metrics(state: BacktestState, capital):
    closed = [t for t in state.trades if t["side"] == "SELL"]
    wins = [t for t in closed if t["pnl"] > 0]
    losses = [t for t in closed if t["pnl"] <= 0]

    win_rate = len(wins) / len(closed) if closed else None
    gross_win = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else None)
    avg_win = mean(t["pnl"] for t in wins) if wins else None
    avg_loss = mean(abs(t["pnl"]) for t in losses) if losses else None

    equities = [e for _, e in state.equity_curve]
    peak = equities[0] if equities else capital
    max_dd = 0.0
    for e in equities:
        peak = max(peak, e)
        max_dd = max(max_dd, (peak - e) / peak) if peak > 0 else max_dd
    daily_returns = []
    for j in range(1, len(equities)):
        if equities[j - 1] > 0:
            daily_returns.append((equities[j] - equities[j - 1]) / equities[j - 1])
    sharpe = None
    if len(daily_returns) > 1 and pstdev(daily_returns) > 0:
        sharpe = mean(daily_returns) / pstdev(daily_returns) * (365 ** 0.5)

    final_equity = equities[-1] if equities else capital
    return {
        "total_trades": len(closed),
        "win_rate": round(win_rate, 4) if win_rate is not None else None,
        "profit_factor": round(profit_factor, 3) if isinstance(profit_factor, float) and profit_factor != float("inf") else profit_factor,
        "max_drawdown_pct": round(max_dd * 100, 2),
        "sharpe_ratio": round(sharpe, 3) if sharpe is not None else None,
        "avg_win": round(avg_win, 2) if avg_win is not None else None,
        "avg_loss": round(avg_loss, 2) if avg_loss is not None else None,
        "final_equity": round(final_equity, 2),
        "total_return_pct": round((final_equity - capital) / capital * 100, 2),
    }


def print_report(label, metrics):
    print(f"\n=== {label} ===")
    for k, v in metrics.items():
        print(f"  {k:20s} {v}")


def sql_str(v):
    return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"


def persist_results(label, timeframe, state: BacktestState, metrics, capital):
    rows = run_sql(f"""
        insert into portfolios (name, mode, cash_thb, equity_thb)
        values ({sql_str(label)}, 'backtest', {state.cash}, {metrics['final_equity']})
        returning id;
    """)
    portfolio_id = rows[0]["id"]

    for start_i in range(0, len(state.trades), 500):
        batch = state.trades[start_i:start_i + 500]
        values = []
        for tr in batch:
            values.append(
                f"({portfolio_id}, '{tr['symbol']}', '{tr['side']}', {tr['qty']}, {tr['price']}, "
                f"{tr['fee']}, {sql_str(tr['executed_at'])}, "
                f"{'NULL' if tr['pnl'] is None else tr['pnl']}, {sql_str(tr['exit_reason'])})"
            )
        run_sql(f"""
            insert into trades (portfolio_id, symbol, side, qty, price, fee, executed_at, pnl, exit_reason)
            values {','.join(values)};
        """)

    for start_i in range(0, len(state.equity_curve), 500):
        batch = state.equity_curve[start_i:start_i + 500]
        values = [f"({portfolio_id}, {sql_str(t)}, {eq}, {eq})" for t, eq in batch]
        run_sql(f"""
            insert into equity_snapshots (portfolio_id, ts, equity_thb, cash_thb)
            values {','.join(values)}
            on conflict (portfolio_id, ts) do nothing;
        """)

    print(f"\nPersisted to Supabase: portfolio_id={portfolio_id}, {len(state.trades)} trades, {len(state.equity_curve)} equity snapshots")
    return portfolio_id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    parser.add_argument("--timeframe", default="4h", choices=["1h", "4h"])
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--capital", type=float, default=INITIAL_CAPITAL)
    parser.add_argument("--compare-timeframes", action="store_true", help="Run on both 1h and 4h and print both (spec §10.7)")
    parser.add_argument("--persist", action="store_true", help="Write results to Supabase (portfolios/trades/equity_snapshots)")
    args = parser.parse_args()

    timeframes = ["1h", "4h"] if args.compare_timeframes else [args.timeframe]
    results = {}
    for tf in timeframes:
        state = run_simulation(args.symbols, tf, args.start, args.end, args.capital)
        metrics = compute_metrics(state, args.capital)
        results[tf] = (state, metrics)
        print_report(f"{tf} — {len(state.trades)} fills, {sum(1 for t in state.trades if t['side'] == 'SELL')} closed trades", metrics)
        if args.persist:
            run_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            label = f"backtest-{tf}-{run_ts}"
            persist_results(label, tf, state, metrics, args.capital)

    if len(results) > 1:
        print("\n=== Timeframe comparison (after fees, §10.7) ===")
        header = f"{'metric':20s}" + "".join(f"{tf:>14s}" for tf in results)
        print(header)
        for key in ["total_trades", "win_rate", "profit_factor", "max_drawdown_pct", "sharpe_ratio", "total_return_pct"]:
            row = f"{key:20s}" + "".join(f"{str(results[tf][1][key]):>14s}" for tf in results)
            print(row)


if __name__ == "__main__":
    main()
