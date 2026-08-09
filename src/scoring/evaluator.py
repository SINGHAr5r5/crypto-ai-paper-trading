"""Evaluates matured predictions and updates the running AI score — spec §7.

Correctness (§7.1): direction UP/DOWN needs >=0.5% move in that direction by
T+horizon_hours; HOLD is correct if price stayed within +/-0.5%.

Scoring (§7.2): correct = +2 (confidence>=0.7) or +1, resets wrong_streak;
wrong = -wrong_streak (so consecutive misses cost more), score capped at 100,
unbounded below. State is carried via the most recent `ai_score` row and
written to a per-day row (upsert) — the schema keys ai_score on (portfolio_id, date).

Usage:
    python -m src.scoring.evaluator
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.data.supabase_client import run_sql

CORRECT_THRESHOLD_PCT = 0.5
SYSTEM_PORTFOLIO_ID = 1  # seeded in db/migrations/0002_seed_system_portfolio.sql


def get_state():
    rows = run_sql(f"""
        select score, wrong_streak, total_correct, total_wrong
        from ai_score where portfolio_id = {SYSTEM_PORTFOLIO_ID}
        order by date desc limit 1;
    """)
    if rows:
        return dict(rows[0])
    return {"score": 0, "wrong_streak": 0, "total_correct": 0, "total_wrong": 0}


def is_correct(direction, actual_change_pct):
    if direction == "UP":
        return actual_change_pct >= CORRECT_THRESHOLD_PCT
    if direction == "DOWN":
        return actual_change_pct <= -CORRECT_THRESHOLD_PCT
    return -CORRECT_THRESHOLD_PCT <= actual_change_pct <= CORRECT_THRESHOLD_PCT


def fetch_maturable_predictions():
    return run_sql("""
        select p.id, p.symbol, p.ts, p.direction, p.confidence, p.entry_price, p.horizon_hours
        from predictions p
        left join prediction_results pr on pr.prediction_id = p.id
        where pr.prediction_id is null
          and p.ts + (p.horizon_hours || ' hours')::interval <= now()
        order by p.ts;
    """)


def actual_price_at_horizon(symbol, ts_iso, horizon_hours):
    rows = run_sql(f"""
        select close from ohlcv
        where symbol = '{symbol}' and timeframe = '1h'
          and open_time <= '{ts_iso}'::timestamptz + interval '{horizon_hours} hours'
        order by open_time desc limit 1;
    """)
    return float(rows[0]["close"]) if rows else None


def basis_price(symbol, ts_iso, entry_price):
    if entry_price is not None:
        return float(entry_price)
    rows = run_sql(f"""
        select close from ohlcv
        where symbol = '{symbol}' and timeframe = '4h' and open_time <= '{ts_iso}'::timestamptz
        order by open_time desc limit 1;
    """)
    return float(rows[0]["close"]) if rows else None


def save_result(prediction_id, actual_price, actual_change_pct, correct, score_delta):
    run_sql(f"""
        insert into prediction_results (prediction_id, actual_price, actual_change_pct, is_correct, score_delta)
        values ({prediction_id}, {actual_price}, {actual_change_pct}, {str(correct).lower()}, {score_delta});
    """)


def upsert_today_score(state):
    today = date.today().isoformat()
    run_sql(f"""
        insert into ai_score (portfolio_id, date, score, wrong_streak, total_correct, total_wrong)
        values ({SYSTEM_PORTFOLIO_ID}, '{today}', {state['score']}, {state['wrong_streak']},
                {state['total_correct']}, {state['total_wrong']})
        on conflict (portfolio_id, date) do update set
          score = excluded.score, wrong_streak = excluded.wrong_streak,
          total_correct = excluded.total_correct, total_wrong = excluded.total_wrong;
    """)


def run():
    predictions = fetch_maturable_predictions()
    if not predictions:
        print("No predictions ready to evaluate.")
        return

    state = get_state()
    for p in predictions:
        actual = actual_price_at_horizon(p["symbol"], p["ts"], p["horizon_hours"])
        basis = basis_price(p["symbol"], p["ts"], p["entry_price"])
        if actual is None or basis is None:
            print(f"  prediction {p['id']} ({p['symbol']}): no price data at horizon yet, skipping")
            continue

        change_pct = (actual - basis) / basis * 100
        correct = is_correct(p["direction"], change_pct)

        if correct:
            delta = 2 if float(p["confidence"]) >= 0.7 else 1
            state["wrong_streak"] = 0
            state["total_correct"] += 1
        else:
            state["wrong_streak"] += 1
            delta = -state["wrong_streak"]
            state["total_wrong"] += 1
        state["score"] = min(100, state["score"] + delta)

        save_result(p["id"], actual, round(change_pct, 4), correct, delta)
        print(f"  prediction {p['id']} ({p['symbol']} {p['direction']}): "
              f"actual {change_pct:+.2f}% -> {'CORRECT' if correct else 'WRONG'}, "
              f"delta={delta:+d}, score={state['score']}")

    upsert_today_score(state)
    print(f"\nDone. score={state['score']} wrong_streak={state['wrong_streak']} "
          f"total_correct={state['total_correct']} total_wrong={state['total_wrong']}")


if __name__ == "__main__":
    run()
