"""Main scheduled job — spec §8 `rule_scanner` + `ai_decision`, run every 15 min.

For each symbol, on the latest closed 4H candle (skipped if already scanned):
  1. compute confluence score from the trigger rules (§5.1)
  2. log a row in `triggers` regardless of outcome (§10.5: log everything)
  3. if confluence gate (§5.2) and rate gate (§5.3) both pass, call the AI
     decision layer (§6) and store the result in `predictions`

Usage:
    python -m src.jobs.scan_and_decide
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.ai.claude_client import ClaudeCallFailed, get_decision
from src.ai.prompt_builder import build_input, build_messages
from src.data.backfill import DEFAULT_SYMBOLS
from src.data.supabase_client import run_sql
from src.indicators.compute import compute_indicators, fetch_ohlcv, store_indicators
from src.jobs.ingest_ohlcv import ingest_all
from src.scanner.confluence import confluence_gate, score_candles
from src.scanner.gates import rate_gate

RECENT_WINDOW = 500
DECISION_TF = "4h"


def df_to_candles(df):
    records = df.to_dict("records")
    for r in records:
        r["t"] = r["open_time"].isoformat()
    return records


def sql_str(v):
    return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"


def already_scanned(symbol: str, triggered_at_iso: str) -> bool:
    rows = run_sql(f"""
        select 1 from triggers where symbol = '{symbol}' and triggered_at = {sql_str(triggered_at_iso)};
    """)
    return len(rows) > 0


def log_trigger(symbol, triggered_at_iso, confluence_score, matched_rules, passed_gate, gate_reason):
    matched_json = json.dumps(matched_rules, ensure_ascii=False).replace("'", "''")
    rows = run_sql(f"""
        insert into triggers (symbol, triggered_at, confluence_score, matched_rules, passed_gate, gate_reason, called_ai)
        values ('{symbol}', {sql_str(triggered_at_iso)}, {confluence_score}, '{matched_json}'::jsonb, {passed_gate}, {sql_str(gate_reason)}, false)
        returning id;
    """)
    return rows[0]["id"]


def mark_called_ai(trigger_id: int):
    run_sql(f"update triggers set called_ai = true where id = {trigger_id};")


def save_prediction(trigger_id, symbol, ts_iso, decision, snapshot):
    snapshot_json = json.dumps(snapshot, ensure_ascii=False).replace("'", "''")
    reasoning = (decision.get("reasoning") or "").replace("'", "''")
    model_version = decision.get("_model_version", "unknown").replace("'", "''")

    def num(v):
        return "NULL" if v is None else str(v)

    run_sql(f"""
        insert into predictions
          (trigger_id, symbol, ts, direction, confidence, entry_price, stop_loss, take_profit,
           horizon_hours, reasoning, snapshot_json, model_version)
        values
          ({trigger_id}, '{symbol}', {sql_str(ts_iso)}, '{decision['direction']}', {decision['confidence']},
           {num(decision.get('entry_price'))}, {num(decision.get('stop_loss'))}, {num(decision.get('take_profit'))},
           24, '{reasoning}', '{snapshot_json}'::jsonb, '{model_version}');
    """)


def run():
    print("== ingest_ohlcv ==")
    ingest_all()

    print("\n== compute_indicators (recent window) ==")
    for symbol in DEFAULT_SYMBOLS:
        for tf in ["1h", "4h"]:
            candles = fetch_ohlcv(symbol, tf, recent=RECENT_WINDOW)
            if candles.empty:
                continue
            enriched = compute_indicators(candles)
            store_indicators(symbol, tf, enriched.tail(50))  # only the tail actually needs writing back

    print("\n== rule scanner + confluence + gates ==")
    btc_df = fetch_ohlcv("BTCUSDT", DECISION_TF, recent=RECENT_WINDOW)
    btc_candles = df_to_candles(compute_indicators(btc_df))
    btc_change_4h = None
    if len(btc_candles) >= 2:
        p, c = btc_candles[-2], btc_candles[-1]
        btc_change_4h = (c["close"] - p["close"]) / p["close"] * 100

    for symbol in DEFAULT_SYMBOLS:
        df = fetch_ohlcv(symbol, DECISION_TF, recent=RECENT_WINDOW)
        if df.empty or len(df) < 2:
            print(f"[{symbol}] not enough data, skipping")
            continue
        candles = df_to_candles(compute_indicators(df))
        latest = candles[-1]
        triggered_at_iso = latest["t"]

        if already_scanned(symbol, triggered_at_iso):
            print(f"[{symbol}] candle {triggered_at_iso} already scanned, skipping")
            continue

        confluence_score, matched_rules = score_candles(candles, btc_change_4h=btc_change_4h)
        passed, gate_reason = confluence_gate(confluence_score)
        print(f"[{symbol}] confluence_score={confluence_score} passed={passed} rules={[r['code'] for r in matched_rules]}")

        trigger_id = log_trigger(symbol, triggered_at_iso, confluence_score, matched_rules, passed, gate_reason)

        if not passed:
            continue

        rate_ok, rate_reason = rate_gate(symbol, confluence_score)
        if not rate_ok:
            print(f"[{symbol}] rate gate blocked: {rate_reason}")
            continue

        input_payload = build_input(symbol, triggered_at_iso, confluence_score, matched_rules, latest, candles, btc_change_4h)
        system_prompt, user_content = build_messages(input_payload)
        try:
            decision = get_decision(system_prompt, user_content)
        except ClaudeCallFailed as e:
            print(f"[{symbol}] AI call failed (skipping prediction): {e}")
            continue

        save_prediction(trigger_id, symbol, triggered_at_iso, decision, input_payload)
        mark_called_ai(trigger_id)
        print(f"[{symbol}] AI decision: {decision['action']} / {decision['direction']} (confidence={decision['confidence']})")


if __name__ == "__main__":
    run()
