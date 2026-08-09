"""Builds the AI input payload (§6.2) and the prompt sent to Claude (§6.3)."""

import json

from src.data.supabase_client import run_sql

INITIAL_CAPITAL_THB = 100000


def get_portfolio_context():
    score_row = run_sql("""
        select score, wrong_streak, total_correct, total_wrong
        from ai_score order by date desc limit 1;
    """)
    score_row = score_row[0] if score_row else {"score": 0, "wrong_streak": 0, "total_correct": 0, "total_wrong": 0}

    recent = run_sql("""
        select is_correct from prediction_results order by evaluated_at desc limit 20;
    """)
    win_rate = round(sum(1 for r in recent if r["is_correct"]) / len(recent), 3) if recent else None

    last5 = run_sql("""
        select is_correct from prediction_results order by evaluated_at desc limit 5;
    """)
    last5_labels = ["correct" if r["is_correct"] else "wrong" for r in last5]

    return {
        "cash_thb": INITIAL_CAPITAL_THB,
        "open_positions": [],
        "current_score": score_row["score"],
        "recent_win_rate": win_rate,
        "last_5_predictions": last5_labels,
    }


def build_input(symbol, triggered_at_iso, confluence_score, matched_rules, latest_candle, recent_candles, btc_change_4h):
    return {
        "symbol": symbol,
        "triggered_at": triggered_at_iso,
        "confluence_score": confluence_score,
        "triggers": [f"{r['code']}: {r['description']}" for r in matched_rules],
        "indicators": {
            "rsi14": latest_candle["rsi14"],
            "macd_hist": latest_candle["macd_hist"],
            "ema20": latest_candle["ema20"],
            "ema50": latest_candle["ema50"],
            "ema200": latest_candle["ema200"],
            "atr14": latest_candle["atr14"],
            "bb_upper": latest_candle["bb_upper"],
            "bb_lower": latest_candle["bb_lower"],
            "price": latest_candle["close"],
        },
        "recent_candles": [
            {"t": c["t"], "o": c["open"], "h": c["high"], "l": c["low"], "c": c["close"], "v": c["volume"]}
            for c in recent_candles[-20:]
        ],
        "btc_context": {"change_4h": round(btc_change_4h, 2) if btc_change_4h is not None else None},
        "market_context": {"fear_greed": None, "funding_rate": None},  # not ingested yet, see §8 fetch_context (not built)
        "portfolio": get_portfolio_context(),
    }


SYSTEM_PROMPT = """คุณเป็นผู้ช่วยวิเคราะห์การเทรดคริปโตสำหรับระบบ paper trading (เงินสมมติเท่านั้น ไม่ใช่เงินจริง)
กฎ:
- ตอบเป็น JSON เท่านั้น ห้ามมีข้อความอื่นนอก JSON
- action ต้องเป็นหนึ่งใน: BUY, SELL, CLOSE, HOLD
- direction ต้องเป็นหนึ่งใน: UP, DOWN, HOLD
- confidence เป็นตัวเลข 0-1
- ใช้ current_score และ recent_win_rate ในการปรับความระมัดระวัง ถ้าฟอร์มไม่ดี (win rate ต่ำ, wrong streak สูง) ให้ระมัดระวังมากขึ้น
- นี่คือการทดลอง/วัดผลกลยุทธ์ ไม่ใช่คำแนะนำการลงทุนจริง

รูปแบบ JSON ที่ต้องการ:
{"symbol": "...", "action": "BUY|SELL|CLOSE|HOLD", "direction": "UP|DOWN|HOLD", "confidence": 0.0-1.0,
 "entry_price": number|null, "stop_loss": number|null, "take_profit": number|null,
 "position_size_pct": number|null, "reasoning": "...", "risk_level": "low|medium|high", "invalidation": "..."}
"""


def build_messages(input_payload: dict):
    user_content = "ข้อมูลตลาดปัจจุบัน:\n" + json.dumps(input_payload, ensure_ascii=False, indent=2)
    return SYSTEM_PROMPT, user_content
