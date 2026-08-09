"""Confluence gate — spec §5.2."""

from src.scanner.rules import evaluate_rules


def score_candles(candles, btc_change_4h=None):
    matched = evaluate_rules(candles, btc_change_4h=btc_change_4h)
    confluence_score = sum(r["weight"] for r in matched)
    return confluence_score, matched


def net_direction(matched_rules):
    """Aggregate matched rules' directions into a single UP/DOWN/NEUTRAL read.
    Used by the rule-based backtest engine (§9 week 3) to pick long vs. short —
    the live AI decision layer (§6) doesn't use this, it reasons over the raw
    trigger list itself."""
    up = sum(r["weight"] for r in matched_rules if r["direction"] == "UP")
    down = sum(r["weight"] for r in matched_rules if r["direction"] == "DOWN")
    if up > down:
        return "UP"
    if down > up:
        return "DOWN"
    return "NEUTRAL"


def confluence_gate(confluence_score: int, has_open_position: bool = False):
    """Returns (passed: bool, reason: str)."""
    if confluence_score >= 4:
        return True, f"confluence_score={confluence_score} >= 4"
    if confluence_score >= 3 and has_open_position:
        return True, f"confluence_score={confluence_score} >= 3 และมี position เปิดอยู่"
    return False, f"confluence_score={confluence_score} ต่ำกว่าเกณฑ์"
