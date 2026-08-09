-- Placeholder portfolio row so ai_score (portfolio_id FK, NOT NULL) has something to
-- attach to before the real paper-trading executor (§9 week 6) exists. Only the
-- scoring system uses it for now — no real trades are booked against it.
INSERT INTO portfolios (name, mode, cash_thb, equity_thb)
SELECT 'ai-scoring', 'paper', 100000, 100000
WHERE NOT EXISTS (SELECT 1 FROM portfolios WHERE name = 'ai-scoring');
