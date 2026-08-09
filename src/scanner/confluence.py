"""Confluence gate — spec §5.2."""

from src.scanner.rules import evaluate_rules


def score_candles(candles, btc_change_4h=None):
    matched = evaluate_rules(candles, btc_change_4h=btc_change_4h)
    confluence_score = sum(r["weight"] for r in matched)
    return confluence_score, matched


def confluence_gate(confluence_score: int, has_open_position: bool = False):
    """Returns (passed: bool, reason: str)."""
    if confluence_score >= 4:
        return True, f"confluence_score={confluence_score} >= 4"
    if confluence_score >= 3 and has_open_position:
        return True, f"confluence_score={confluence_score} >= 3 และมี position เปิดอยู่"
    return False, f"confluence_score={confluence_score} ต่ำกว่าเกณฑ์"
