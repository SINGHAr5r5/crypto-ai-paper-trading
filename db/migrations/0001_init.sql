-- Initial schema for Crypto AI Paper Trading System
-- Source: crypto-ai-paper-trading-spec.md §4

-- ราคาย้อนหลัง
CREATE TABLE IF NOT EXISTS ohlcv (
  symbol      TEXT NOT NULL,
  timeframe   TEXT NOT NULL,
  open_time   TIMESTAMPTZ NOT NULL,
  open        NUMERIC NOT NULL,
  high        NUMERIC NOT NULL,
  low         NUMERIC NOT NULL,
  close       NUMERIC NOT NULL,
  volume      NUMERIC NOT NULL,
  PRIMARY KEY (symbol, timeframe, open_time)
);
CREATE INDEX IF NOT EXISTS idx_ohlcv_lookup ON ohlcv (symbol, timeframe, open_time DESC);

-- ตัวชี้วัดที่คำนวณล่วงหน้า
CREATE TABLE IF NOT EXISTS indicators (
  symbol      TEXT NOT NULL,
  timeframe   TEXT NOT NULL,
  open_time   TIMESTAMPTZ NOT NULL,
  rsi14       NUMERIC,
  macd        NUMERIC,
  macd_signal NUMERIC,
  macd_hist   NUMERIC,
  ema20       NUMERIC,
  ema50       NUMERIC,
  ema200      NUMERIC,
  bb_upper    NUMERIC,
  bb_mid      NUMERIC,
  bb_lower    NUMERIC,
  bb_width    NUMERIC,
  atr14       NUMERIC,
  vol_ma20    NUMERIC,
  PRIMARY KEY (symbol, timeframe, open_time)
);

-- บริบทตลาด
CREATE TABLE IF NOT EXISTS market_context (
  ts             TIMESTAMPTZ PRIMARY KEY,
  fear_greed     INT,
  btc_dominance  NUMERIC,
  funding_rates  JSONB
);

-- trigger ที่ scanner ยิง (เก็บทั้งที่ผ่านและไม่ผ่าน gate)
CREATE TABLE IF NOT EXISTS triggers (
  id                BIGSERIAL PRIMARY KEY,
  symbol            TEXT NOT NULL,
  triggered_at      TIMESTAMPTZ NOT NULL,
  confluence_score  INT NOT NULL,
  matched_rules     JSONB NOT NULL,
  passed_gate       BOOLEAN NOT NULL,
  gate_reason       TEXT,
  called_ai         BOOLEAN DEFAULT FALSE
);

-- การทำนายของ AI
CREATE TABLE IF NOT EXISTS predictions (
  id             BIGSERIAL PRIMARY KEY,
  trigger_id     BIGINT REFERENCES triggers(id),
  symbol         TEXT NOT NULL,
  ts             TIMESTAMPTZ NOT NULL,
  direction      TEXT NOT NULL CHECK (direction IN ('UP','DOWN','HOLD')),
  confidence     NUMERIC CHECK (confidence BETWEEN 0 AND 1),
  entry_price    NUMERIC,
  stop_loss      NUMERIC,
  take_profit    NUMERIC,
  horizon_hours  INT NOT NULL DEFAULT 24,
  reasoning      TEXT,
  snapshot_json  JSONB NOT NULL,   -- input ทั้งหมดที่ AI เห็นตอนนั้น
  model_version  TEXT
);

-- ผลการประเมินหลังครบ horizon
CREATE TABLE IF NOT EXISTS prediction_results (
  prediction_id     BIGINT PRIMARY KEY REFERENCES predictions(id),
  actual_price      NUMERIC NOT NULL,
  actual_change_pct NUMERIC NOT NULL,
  is_correct        BOOLEAN NOT NULL,
  score_delta       INT NOT NULL,
  evaluated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- พอร์ต
CREATE TABLE IF NOT EXISTS portfolios (
  id          BIGSERIAL PRIMARY KEY,
  name        TEXT NOT NULL,
  mode        TEXT NOT NULL CHECK (mode IN ('paper','backtest')),
  cash_thb    NUMERIC NOT NULL,
  equity_thb  NUMERIC NOT NULL,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS positions (
  id             BIGSERIAL PRIMARY KEY,
  portfolio_id   BIGINT REFERENCES portfolios(id),
  symbol         TEXT NOT NULL,
  qty            NUMERIC NOT NULL,
  avg_price      NUMERIC NOT NULL,
  stop_loss      NUMERIC,
  take_profit    NUMERIC,
  opened_at      TIMESTAMPTZ NOT NULL,
  UNIQUE (portfolio_id, symbol)
);

CREATE TABLE IF NOT EXISTS trades (
  id            BIGSERIAL PRIMARY KEY,
  portfolio_id  BIGINT REFERENCES portfolios(id),
  prediction_id BIGINT REFERENCES predictions(id),
  symbol        TEXT NOT NULL,
  side          TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
  qty           NUMERIC NOT NULL,
  price         NUMERIC NOT NULL,
  fee           NUMERIC NOT NULL,
  executed_at   TIMESTAMPTZ NOT NULL,
  pnl           NUMERIC,          -- เฉพาะขาปิด
  exit_reason   TEXT              -- AI_SIGNAL / STOP_LOSS / TAKE_PROFIT / MANUAL
);

-- snapshot มูลค่าพอร์ตรายวัน (ไว้วาด equity curve)
CREATE TABLE IF NOT EXISTS equity_snapshots (
  portfolio_id  BIGINT REFERENCES portfolios(id),
  ts            TIMESTAMPTZ NOT NULL,
  equity_thb    NUMERIC NOT NULL,
  cash_thb      NUMERIC NOT NULL,
  PRIMARY KEY (portfolio_id, ts)
);

-- คะแนน AI
CREATE TABLE IF NOT EXISTS ai_score (
  id              BIGSERIAL PRIMARY KEY,
  portfolio_id    BIGINT REFERENCES portfolios(id),
  date            DATE NOT NULL,
  score           INT NOT NULL,
  wrong_streak    INT NOT NULL DEFAULT 0,
  total_correct   INT NOT NULL DEFAULT 0,
  total_wrong     INT NOT NULL DEFAULT 0,
  UNIQUE (portfolio_id, date)
);
