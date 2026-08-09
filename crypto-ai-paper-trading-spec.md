# Crypto AI Paper Trading System — Specification

> เอกสารนี้ใช้เป็น context ให้ Claude Code สร้างระบบ
> สถานะ: ยังไม่เริ่มเขียนโค้ด — เอกสารออกแบบอย่างเดียว

---

## 1. เป้าหมายของโปรเจกต์

สร้างระบบ **จำลองการเทรดคริปโต (paper trading)** ที่ให้ AI เป็นคนตัดสินใจซื้อ/ขาย
โดยเทียบกับราคาจริงแบบ real-time เก็บประวัติการทำนายทั้งหมด และมีระบบให้คะแนนความแม่นยำ

**สิ่งที่ระบบนี้เป็น:** เครื่องมือวัดผลว่ากลยุทธ์ไหนใช้ได้จริง ก่อนเอาเงินจริงไปเสี่ยง
**สิ่งที่ระบบนี้ไม่ใช่:** ระบบที่การันตีกำไร — ห้ามใช้เงินจริงจนกว่าจะ paper trade ครบอย่างน้อย 3 เดือนและผ่านเกณฑ์ใน §9

### คำศัพท์
| คำ | ความหมาย |
|---|---|
| Paper Trading | จำลองซื้อขายด้วยเงินปลอม เทียบราคาจริง |
| Backtesting | ทดสอบกลยุทธ์ย้อนหลังกับข้อมูลเก่า |
| Look-ahead bias | ข้อผิดพลาดที่ระบบแอบเห็นข้อมูลอนาคตตอน backtest |
| Confluence | การที่หลายสัญญาณเกิดพร้อมกัน |
| Drawdown | ขาดทุนจากจุดสูงสุดของพอร์ต |

---

## 2. Tech Stack

| ส่วน | เทคโนโลยี |
|---|---|
| Database | Supabase (self-hosted: supabase.gramick.dev) — PostgreSQL |
| Backend / Worker | Python 3.11+ |
| Scheduler | APScheduler |
| Indicators | pandas-ta (หรือ TA-Lib) |
| Price data | Binance REST API `/api/v3/klines` (ฟรี ไม่ต้องใช้ key) |
| AI Decision | Claude API (Anthropic) |
| Deploy | Raspberry Pi |
| Dashboard | Flutter (มี stack อยู่แล้ว) หรือ Next.js |

---

## 3. กติกาหลัก (Configuration)

```yaml
symbols:        [BTCUSDT, ETHUSDT, XRPUSDT, SOLUSDT, BNBUSDT]
base_timeframe: 1h          # timeframe ที่เก็บข้อมูล
decision_tf:    4h          # timeframe ที่ใช้ตัดสินใจ
initial_capital: 100000     # THB (virtual)

fees:
  taker_fee_pct:  0.10      # ต่อครั้ง (เข้า+ออก = 0.20%)
  slippage_pct:   0.05      # จำลอง slippage

risk:
  max_position_pct:   20    # % ของพอร์ตต่อ 1 เหรียญ
  max_open_positions: 3
  stop_loss_pct:      3.0
  take_profit_pct:    6.0
  # หรือใช้ ATR-based: SL = entry - 1.5×ATR, TP = entry + 3×ATR

prediction:
  horizon_hours:   24
  correct_threshold_pct: 0.5   # ต้องขยับเกิน 0.5% ถึงนับว่าทายถูก
```

**หมายเหตุสำคัญ:** ค่าฟีและ slippage ต้องหักทุกครั้งที่จำลองเทรด ถ้าไม่หัก ผลลัพธ์จะสวยเกินจริงมาก

---

## 4. Database Schema (Supabase / PostgreSQL)

```sql
-- ราคาย้อนหลัง
CREATE TABLE ohlcv (
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
CREATE INDEX idx_ohlcv_lookup ON ohlcv (symbol, timeframe, open_time DESC);

-- ตัวชี้วัดที่คำนวณล่วงหน้า
CREATE TABLE indicators (
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
CREATE TABLE market_context (
  ts             TIMESTAMPTZ PRIMARY KEY,
  fear_greed     INT,
  btc_dominance  NUMERIC,
  funding_rates  JSONB
);

-- trigger ที่ scanner ยิง (เก็บทั้งที่ผ่านและไม่ผ่าน gate)
CREATE TABLE triggers (
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
CREATE TABLE predictions (
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
CREATE TABLE prediction_results (
  prediction_id     BIGINT PRIMARY KEY REFERENCES predictions(id),
  actual_price      NUMERIC NOT NULL,
  actual_change_pct NUMERIC NOT NULL,
  is_correct        BOOLEAN NOT NULL,
  score_delta       INT NOT NULL,
  evaluated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- พอร์ต
CREATE TABLE portfolios (
  id          BIGSERIAL PRIMARY KEY,
  name        TEXT NOT NULL,
  mode        TEXT NOT NULL CHECK (mode IN ('paper','backtest')),
  cash_thb    NUMERIC NOT NULL,
  equity_thb  NUMERIC NOT NULL,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE positions (
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

CREATE TABLE trades (
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
  exit_reason   TEXT              -- AI_SIGNAL / STOP_LOSS / TAKE_PROTIT / MANUAL
);

-- snapshot มูลค่าพอร์ตรายวัน (ไว้วาด equity curve)
CREATE TABLE equity_snapshots (
  portfolio_id  BIGINT REFERENCES portfolios(id),
  ts            TIMESTAMPTZ NOT NULL,
  equity_thb    NUMERIC NOT NULL,
  cash_thb      NUMERIC NOT NULL,
  PRIMARY KEY (portfolio_id, ts)
);

-- คะแนน AI
CREATE TABLE ai_score (
  id              BIGSERIAL PRIMARY KEY,
  portfolio_id    BIGINT REFERENCES portfolios(id),
  date            DATE NOT NULL,
  score           INT NOT NULL,
  wrong_streak    INT NOT NULL DEFAULT 0,
  total_correct   INT NOT NULL DEFAULT 0,
  total_wrong     INT NOT NULL DEFAULT 0,
  UNIQUE (portfolio_id, date)
);
```

**สำคัญ:** `snapshot_json` ต้องเก็บ input ทั้งหมดที่ AI เห็นตอนตัดสินใจ ไม่งั้นจะย้อนวิเคราะห์ไม่ได้ว่าทำไมทายผิด

---

## 5. Rule Scanner — เงื่อนไขปลุก AI

Scanner ทำหน้าที่ **กรอง** ไม่ใช่ตัดสินใจ รันทุก 15 นาที เช็คบน 4H candle ที่ปิดแล้ว

### 5.1 Trigger Rules

**กลุ่ม A — Momentum / Reversal**
| รหัส | เงื่อนไข | น้ำหนัก |
|---|---|---|
| A1 | RSI(14) ตัดขึ้นผ่าน 30 | 2 |
| A2 | RSI(14) ตัดลงผ่าน 70 | 2 |
| A3 | MACD histogram เปลี่ยนเครื่องหมาย | 1 |
| A4 | RSI divergence (ราคา new low แต่ RSI ไม่ new low) | 2 |

**กลุ่ม B — Trend**
| รหัส | เงื่อนไข | น้ำหนัก |
|---|---|---|
| B1 | ราคาตัดผ่าน EMA50 | 2 |
| B2 | EMA20 ตัด EMA50 | 2 |
| B3 | ราคาตัดผ่าน EMA200 | 3 |

**กลุ่ม C — Volatility / Volume**
| รหัส | เงื่อนไข | น้ำหนัก |
|---|---|---|
| C1 | Volume > 2× MA20 ของ volume | 2 |
| C2 | ราคาแตะขอบ Bollinger Band | 1 |
| C3 | BB squeeze คลายตัว (bb_width จาก percentile ต่ำ → ขยาย) | 3 |
| C4 | ATR > 1.5× ค่าเฉลี่ย 20 แท่ง | 1 |

**กลุ่ม D — Structure**
| รหัส | เงื่อนไข | น้ำหนัก |
|---|---|---|
| D1 | ราคาทะลุ high/low ของ 20 แท่งล่าสุด | 3 |
| D2 | ราคาเข้าใกล้แนวรับ/ต้าน ±0.5% | 1 |

**กลุ่ม E — Context (เช็คทุก 1 ชม.)**
| รหัส | เงื่อนไข | น้ำหนัก |
|---|---|---|
| E1 | Funding rate > +0.05% หรือ < -0.05% | 1 |
| E2 | Fear & Greed < 20 หรือ > 80 | 1 |
| E3 | BTC เคลื่อนไหว > 3% ใน 4 ชม. → ปลุกทุกเหรียญ | 1 |

### 5.2 Confluence Gate

```
confluence_score ≥ 4                        → เรียก AI
confluence_score ≥ 3 และมี position เปิดอยู่ → เรียก AI (ถามว่าควรปิดไหม)
ต่ำกว่านั้น                                  → log ลง triggers เฉย ๆ
```

### 5.3 Rate Gate (บล็อกไม่ให้ยิงถี่เกิน)

```
cooldown        : เหรียญเดิม ห้ามเรียกซ้ำภายใน 4 ชม. (ยกเว้น score ≥ 7)
daily cap       : สูงสุด 10 ครั้ง/วัน ทั้งระบบ
position limit  : ถือพร้อมกันไม่เกิน 3 เหรียญ
no-trade window : ห้ามเปิดไม้ใหม่ก่อนข่าวใหญ่ (CPI, FOMC) 2 ชม.
kill switch     : drawdown > 10% ใน 1 สัปดาห์ → หยุดเปิดไม้ใหม่ รอ review
```

---

## 6. AI Decision Layer

### 6.1 สถาปัตยกรรม 2 ชั้น

1. **Rule engine (Python)** — คำนวณ indicator + confluence score (LLM คำนวณเลขไม่เก่ง)
2. **Claude API** — ตีความบริบท ตัดสินใจ ตอบเป็น JSON

### 6.2 Input ที่ส่งให้ AI

```json
{
  "symbol": "XRPUSDT",
  "triggered_at": "2026-08-09T12:00:00Z",
  "confluence_score": 6,
  "triggers": [
    "A1: RSI ตัดขึ้นผ่าน 30 (28.4 → 31.2)",
    "C2: แตะ BB lower",
    "C1: volume 2.3× MA20"
  ],
  "indicators": {
    "rsi14": 31.2, "macd_hist": -0.0021,
    "ema20": 2.84, "ema50": 2.91, "ema200": 2.62,
    "atr14": 0.087, "bb_upper": 3.02, "bb_lower": 2.78,
    "price": 2.79
  },
  "recent_candles": "[ 20 แท่ง 4H ล่าสุด: o/h/l/c/v ]",
  "btc_context": { "change_4h": -1.2, "trend": "sideways" },
  "market_context": { "fear_greed": 34, "funding_rate": -0.012 },
  "portfolio": {
    "cash_thb": 72000,
    "open_positions": [{"symbol":"BTCUSDT","unrealized_pnl_pct":1.8}],
    "current_score": 47,
    "recent_win_rate": 0.54,
    "last_5_predictions": ["correct","wrong","correct","correct","wrong"]
  }
}
```

ใส่ `current_score` และ `recent_win_rate` เข้าไปด้วย เพื่อให้ AI ปรับความระมัดระวังตามฟอร์มตัวเอง

### 6.3 Output ที่ต้องการ (JSON เท่านั้น)

```json
{
  "symbol": "XRPUSDT",
  "action": "BUY",
  "direction": "UP",
  "confidence": 0.72,
  "entry_price": 2.79,
  "stop_loss": 2.70,
  "take_profit": 2.97,
  "position_size_pct": 15,
  "reasoning": "RSI oversold bounce ที่ BB lower พร้อม volume confirm ...",
  "risk_level": "medium",
  "invalidation": "ถ้าหลุด 2.70 แสดงว่าโครงสร้างเสีย"
}
```

`action` ที่เป็นไปได้: `BUY` / `SELL` / `CLOSE` / `HOLD`

---

## 7. ระบบให้คะแนน (Scoring)

### 7.1 นิยาม "ทายถูก"

```
direction = UP   → ถูก ถ้าราคาปิด T+24h สูงกว่าตอนทำนาย ≥ 0.5%
direction = DOWN → ถูก ถ้าราคาปิด T+24h ต่ำกว่าตอนทำนาย ≥ 0.5%
direction = HOLD → ถูก ถ้าราคาขยับอยู่ในช่วง ±0.5%
```

### 7.2 สูตรคะแนน

```python
if is_correct:
    delta = 2 if confidence >= 0.7 else 1
    wrong_streak = 0
else:
    wrong_streak += 1
    delta = -wrong_streak      # ผิด 1 ครั้ง = -1, ผิด 2 ติด = -2, ...

score = min(100, score + delta)   # เพดาน 100, พื้นไม่จำกัด (ติดลบได้)
```

### 7.3 Metrics ที่ต้องเก็บควบคู่

**อย่าดูคะแนนตัวเดียว** — ทายถูก 90% แต่ตอนผิดขาดทุนหนักก็เจ๊งได้

| Metric | สูตร | เกณฑ์ที่ยอมรับได้ |
|---|---|---|
| Win Rate | ถูก / ทั้งหมด | > 50% |
| Profit Factor | กำไรรวม ÷ ขาดทุนรวม | > 1.5 |
| Max Drawdown | ขาดทุนสูงสุดจากจุดพีค | < 20% |
| Sharpe Ratio | ผลตอบแทน ÷ ความผันผวน | > 1.0 |
| Avg Win / Avg Loss | | > 1.5 |

---

## 8. Jobs / Workers

| Job | ความถี่ | หน้าที่ |
|---|---|---|
| `ingest_ohlcv` | ทุก 5 นาที | ดึงราคาจาก Binance → ตาราง ohlcv |
| `compute_indicators` | หลัง ingest | คำนวณ indicator → ตาราง indicators |
| `fetch_context` | ทุก 1 ชม. | Fear & Greed, funding rate, BTC dominance |
| `rule_scanner` | ทุก 15 นาที | เช็ค trigger + confluence + gate |
| `ai_decision` | เมื่อ scanner สั่ง | เรียก Claude API → บันทึก prediction → execute |
| `risk_monitor` | **ทุก 1 นาที** | เช็ค SL/TP ของทุก position |
| `evaluate_predictions` | ทุก 1 ชม. | หา prediction ที่ครบ horizon → คิดคะแนน |
| `daily_snapshot` | วันละ 1 ครั้ง | บันทึก equity + สรุปคะแนนรายวัน |

**Stop loss / Take profit ห้ามรอ AI** — ต้องเป็นโค้ดเช็คทุกนาที ถ้าราคาชน SL ตอนตี 3 แล้วรอ AI ตัดสินใจตอนเช้า พอร์ตพังไปแล้ว

---

## 9. ลำดับการพัฒนา

| สัปดาห์ | งาน |
|---|---|
| 1 | Schema Supabase + backfill ราคาย้อนหลัง 3 ปี |
| 2 | คำนวณ indicator ทั้งหมด + validate ตัวเลขถูกต้อง |
| 3 | Backtest engine (rule-based ล้วน ยังไม่ใช้ AI) |
| 4 | ต่อ Claude API เข้าชั้นตัดสินใจ + backtest ใหม่ |
| 5 | ระบบให้คะแนน + ตาราง metrics |
| 6 | Deploy paper trading บน Pi + dashboard |
| 7–18 | ปล่อยรันเก็บข้อมูล **อย่าแก้กลยุทธ์บ่อย** |

### เกณฑ์ก่อนพิจารณาใช้เงินจริง
- Paper trade ต่อเนื่อง ≥ 3 เดือน
- จำนวนเทรด ≥ 50 ครั้ง
- Profit Factor > 1.5
- Max Drawdown < 20%

---

## 10. ข้อควรระวังทางเทคนิค

1. **Look-ahead bias** — ตอน backtest ทุก query ต้องมี `WHERE open_time <= sim_time` เด็ดขาด ถ้าพลาดข้อนี้ผล backtest จะสวยมากแต่ใช้จริงไม่ได้เลย
2. **Overfitting** — ถ้าปรับ RSI จาก 30 เป็น 31 แล้วกำไรเพิ่มเท่าตัว แปลว่ากำลัง fit noise ไม่ใช่เจอ edge
3. **Walk-forward validation** — จูนพารามิเตอร์จากข้อมูลปี A แล้วทดสอบกับปี B ที่ไม่เคยเห็น
4. **ค่าฟีและ slippage** — ต้องหักทุกครั้ง ไม่งั้นผลลัพธ์หลอกตัวเอง
5. **Log ทุก trigger** รวมทั้งที่ไม่ผ่าน gate เพื่อดูว่ากรองแรงไป/หลวมไป
6. **Threshold ทั้งหมดในเอกสารนี้เป็นจุดตั้งต้น** ต้องเอาไป backtest แล้วจูน
7. **Timeframe** — backtest เทียบ 1H / 4H / 1D พร้อมกัน ดูว่าอันไหนดีสุด **หลังหักค่าฟี**
8. **Idempotency** — ทุก job ต้องรันซ้ำได้โดยไม่สร้างข้อมูลซ้ำ (ใช้ PK / UPSERT)

---

## 11. โครงสร้างโปรเจกต์ที่เสนอ

```
crypto-ai-trader/
├── config/
│   ├── settings.yaml          # กติกาใน §3
│   └── rules.yaml             # trigger rules + น้ำหนัก
├── src/
│   ├── data/
│   │   ├── binance_client.py
│   │   ├── backfill.py
│   │   └── context_fetcher.py
│   ├── indicators/
│   │   └── compute.py
│   ├── scanner/
│   │   ├── rules.py           # A1–E3
│   │   ├── confluence.py
│   │   └── gates.py
│   ├── ai/
│   │   ├── prompt_builder.py
│   │   ├── claude_client.py
│   │   └── schema.py          # validate JSON output
│   ├── portfolio/
│   │   ├── executor.py        # จำลองซื้อขาย + หักค่าฟี
│   │   ├── risk_monitor.py    # SL/TP
│   │   └── accounting.py
│   ├── scoring/
│   │   ├── evaluator.py
│   │   └── metrics.py
│   ├── backtest/
│   │   └── engine.py          # ต้องกัน look-ahead
│   └── jobs/
│       └── scheduler.py
├── db/
│   └── migrations/
└── tests/
```

---

## 12. หมายเหตุ

เอกสารนี้เป็นการออกแบบเชิงวิศวกรรม ไม่ใช่คำแนะนำการลงทุน
การทำนายทิศทางราคาคริปโตระยะสั้นให้แม่นสม่ำเสมอเป็นเรื่องยากมาก
คุณค่าหลักของระบบนี้คือการ **พิสูจน์ว่ากลยุทธ์ใช้ไม่ได้** ก่อนจะเสียเงินจริง
