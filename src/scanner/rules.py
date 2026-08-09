"""Trigger rules A1-E3 from crypto-ai-paper-trading-spec.md §5.1.

Only rules computable from data we actually ingest (ohlcv + indicators) are
implemented. Not implemented, and why:
  - A4 (RSI divergence): needs swing-point detection, not built yet.
  - D2 (near support/resistance): needs swing-level detection, not built yet.
  - E1 (funding rate), E2 (Fear & Greed): market_context table is never
    populated — no fetch_context job exists yet (§8).

Each rule function takes `candles`, an ascending list of dicts with keys
open/high/low/close/volume/rsi14/macd_hist/ema20/ema50/ema200/bb_upper/
bb_mid/bb_lower/bb_width/atr14/vol_ma20 (i.e. an ohlcv+indicators join),
and returns a (matched: bool, description: str) tuple evaluated on the
last candle.
"""

RULES = []  # populated by @rule decorator below: (code, weight, group, fn)


def rule(code, weight, group):
    def deco(fn):
        RULES.append({"code": code, "weight": weight, "group": group, "fn": fn})
        return fn
    return deco


def _prev_curr(candles):
    return candles[-2], candles[-1]


@rule("A1", 2, "Momentum/Reversal")
def rsi_cross_up_30(candles):
    p, c = _prev_curr(candles)
    if p["rsi14"] is None or c["rsi14"] is None:
        return False, None
    if p["rsi14"] < 30 <= c["rsi14"]:
        return True, f"RSI ตัดขึ้นผ่าน 30 ({p['rsi14']:.1f} → {c['rsi14']:.1f})"
    return False, None


@rule("A2", 2, "Momentum/Reversal")
def rsi_cross_down_70(candles):
    p, c = _prev_curr(candles)
    if p["rsi14"] is None or c["rsi14"] is None:
        return False, None
    if p["rsi14"] >= 70 > c["rsi14"]:
        return True, f"RSI ตัดลงผ่าน 70 ({p['rsi14']:.1f} → {c['rsi14']:.1f})"
    return False, None


@rule("A3", 1, "Momentum/Reversal")
def macd_hist_sign_change(candles):
    p, c = _prev_curr(candles)
    if p["macd_hist"] is None or c["macd_hist"] is None:
        return False, None
    if p["macd_hist"] * c["macd_hist"] < 0:
        return True, f"MACD histogram เปลี่ยนเครื่องหมาย ({p['macd_hist']:.4f} → {c['macd_hist']:.4f})"
    return False, None


@rule("B1", 2, "Trend")
def price_cross_ema50(candles):
    p, c = _prev_curr(candles)
    if p["ema50"] is None or c["ema50"] is None:
        return False, None
    if (p["close"] - p["ema50"]) * (c["close"] - c["ema50"]) < 0:
        direction = "ขึ้น" if c["close"] > c["ema50"] else "ลง"
        return True, f"ราคาตัดผ่าน EMA50 ({direction})"
    return False, None


@rule("B2", 2, "Trend")
def ema20_cross_ema50(candles):
    p, c = _prev_curr(candles)
    if None in (p["ema20"], p["ema50"], c["ema20"], c["ema50"]):
        return False, None
    if (p["ema20"] - p["ema50"]) * (c["ema20"] - c["ema50"]) < 0:
        direction = "golden cross" if c["ema20"] > c["ema50"] else "death cross"
        return True, f"EMA20 ตัด EMA50 ({direction})"
    return False, None


@rule("B3", 3, "Trend")
def price_cross_ema200(candles):
    p, c = _prev_curr(candles)
    if p["ema200"] is None or c["ema200"] is None:
        return False, None
    if (p["close"] - p["ema200"]) * (c["close"] - c["ema200"]) < 0:
        direction = "ขึ้น" if c["close"] > c["ema200"] else "ลง"
        return True, f"ราคาตัดผ่าน EMA200 ({direction})"
    return False, None


@rule("C1", 2, "Volatility/Volume")
def volume_spike(candles):
    c = candles[-1]
    if not c.get("vol_ma20") or c["volume"] is None:
        return False, None
    if c["volume"] > 2 * c["vol_ma20"]:
        return True, f"Volume {c['volume'] / c['vol_ma20']:.1f}× MA20"
    return False, None


@rule("C2", 1, "Volatility/Volume")
def touches_bb_edge(candles):
    c = candles[-1]
    if c["bb_upper"] is None or c["bb_lower"] is None:
        return False, None
    if c["high"] >= c["bb_upper"]:
        return True, "ราคาแตะ BB upper"
    if c["low"] <= c["bb_lower"]:
        return True, "ราคาแตะ BB lower"
    return False, None


@rule("C3", 3, "Volatility/Volume")
def bb_squeeze_release(candles):
    if len(candles) < 100:
        return False, None
    widths = [x["bb_width"] for x in candles[-101:] if x["bb_width"] is not None]
    p, c = _prev_curr(candles)
    if p["bb_width"] is None or c["bb_width"] is None or len(widths) < 50:
        return False, None
    baseline = sorted(widths[:-1])
    rank = sum(1 for w in baseline if w <= p["bb_width"]) / len(baseline)
    if rank < 0.20 and c["bb_width"] > p["bb_width"] * 1.10:
        return True, f"BB squeeze คลายตัว (percentile {rank * 100:.0f}% → ขยาย)"
    return False, None


@rule("C4", 1, "Volatility/Volume")
def atr_spike(candles):
    if len(candles) < 21:
        return False, None
    c = candles[-1]
    prior = [x["atr14"] for x in candles[-21:-1] if x["atr14"] is not None]
    if not prior or c["atr14"] is None:
        return False, None
    avg = sum(prior) / len(prior)
    if c["atr14"] > 1.5 * avg:
        return True, f"ATR {c['atr14']:.4g} > 1.5× ค่าเฉลี่ย 20 แท่ง ({avg:.4g})"
    return False, None


@rule("D1", 3, "Structure")
def breakout_20bar(candles):
    if len(candles) < 21:
        return False, None
    c = candles[-1]
    prior = candles[-21:-1]
    hi = max(x["high"] for x in prior)
    lo = min(x["low"] for x in prior)
    if c["high"] > hi:
        return True, f"ราคาทะลุ high 20 แท่ง ({hi:.4g})"
    if c["low"] < lo:
        return True, f"ราคาทะลุ low 20 แท่ง ({lo:.4g})"
    return False, None


@rule("E3", 1, "Context")
def btc_big_move(candles, btc_change_4h=None):
    if btc_change_4h is None:
        return False, None
    if abs(btc_change_4h) > 3:
        return True, f"BTC เคลื่อนไหว {btc_change_4h:+.1f}% ใน 4 ชม."
    return False, None


def evaluate_rules(candles, btc_change_4h=None):
    """candles: ascending list of ohlcv+indicator dicts, most recent last.
    Returns list of {code, weight, group, description} for matched rules."""
    if len(candles) < 2:
        return []
    matched = []
    for r in RULES:
        fn = r["fn"]
        matched_flag, desc = fn(candles, btc_change_4h) if r["code"] == "E3" else fn(candles)
        if matched_flag:
            matched.append({"code": r["code"], "weight": r["weight"], "group": r["group"], "description": desc})
    return matched
