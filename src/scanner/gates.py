"""Rate gate — spec §5.3. Only cooldown + daily cap are implemented (both are
computable from the `triggers` table). Not implemented, and why:
  - position limit: no real portfolio/positions system exists yet.
  - no-trade window before CPI/FOMC: no news calendar ingested.
  - kill switch on drawdown: no real portfolio equity to measure.
"""

from src.data.supabase_client import run_sql

DAILY_CAP = 10
COOLDOWN_HOURS = 4
COOLDOWN_BYPASS_SCORE = 7


def rate_gate(symbol: str, confluence_score: int):
    """Returns (passed: bool, reason: str)."""
    daily_count = run_sql("""
        select count(*) c from triggers
        where called_ai = true and triggered_at >= date_trunc('day', now());
    """)[0]["c"]
    if daily_count >= DAILY_CAP:
        return False, f"daily cap reached ({daily_count}/{DAILY_CAP})"

    if confluence_score < COOLDOWN_BYPASS_SCORE:
        recent = run_sql(f"""
            select count(*) c from triggers
            where symbol = '{symbol}' and called_ai = true
            and triggered_at >= now() - interval '{COOLDOWN_HOURS} hours';
        """)[0]["c"]
        if recent > 0:
            return False, f"cooldown active ({COOLDOWN_HOURS}h) for {symbol}"

    return True, "rate gate passed"
