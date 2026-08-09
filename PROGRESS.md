# สถานะโปรเจกต์ — Crypto AI Paper Trading

อัปเดตล่าสุด: 2026-08-09

Repo: https://github.com/SINGHAr5r5/crypto-ai-paper-trading (public)
Dashboard: https://singhar5r5.github.io/crypto-ai-paper-trading/
Supabase project: `fanjxckcjfghvxsubwey`

---

## ทำไปแล้ว

### สัปดาห์ 3 — Backtest Engine (rule-based, ไม่ใช้ AI)
- `src/backtest/engine.py` — จำลองเทรดย้อนหลังด้วย rule-based strategy ล้วน (ไม่มี AI) ตาม §9 สัปดาห์ 3
- กันชี้ look-ahead bias ตาม §10.1: ที่ step i ใช้ข้อมูลแค่ `candles[:i+1]` เท่านั้น (ปลอดภัยเพราะ indicator ทุกตัวเป็น backward-looking rolling/EWM คำนวณครั้งเดียวพอ)
- หักค่าฟี+slippage ทุกไม้ตาม §3/§10.4 (0.15% ต่อขา ผ่าน "effective price" เหมือนที่ sandbox ใช้)
- Risk management ตาม §3: max 3 positions พร้อมกัน, 20% ของ equity ต่อไม้, SL 3%, TP 6%
- Direction ต่อกฎ: เพิ่ม field `direction` (UP/DOWN) ให้ทุกกฎใน `src/scanner/rules.py`, รวมเป็น net direction ใน `src/scanner/confluence.py::net_direction()` — ใช้เฉพาะ backtest (AI decision layer ตัดสินใจเองจาก trigger list ไม่ยุ่งกับ field นี้)
- คำนวณ metrics ครบตาม §7.3: Win Rate, Profit Factor, Max Drawdown, Sharpe Ratio, Avg Win/Loss
- เปรียบเทียบ timeframe 1H vs 4H หลังหักค่าฟีตาม §10.7 (`--compare-timeframes`)
- บันทึกผลลง Supabase จริง (`portfolios` mode=`backtest`, `trades`, `equity_snapshots`) ด้วย `--persist`
- **ผลรันจริง (BTC+ETH+XRP+SOL+BNB, 3 ปี):** กลยุทธ์นี้ **ขาดทุน** ทั้งคู่ — 4H: -20.9% (win rate 34.9%, Sharpe -0.34), 1H: -71.8% (win rate 30.7%, Sharpe -1.76) เห็นชัดว่า 1H เทรดถี่เกินจนค่าฟีกินหมด ตรงกับคำเตือนใน §10.4 พอดี — **นี่คือผลลัพธ์ที่ถูกต้องของเครื่องมือนี้**: มันพิสูจน์ว่ากลยุทธ์พื้นฐานตามกฎ A1-E3 เฉยๆ (ยังไม่ผ่าน AI, ยังไม่ tune) ใช้ไม่ได้ ตรงตาม §12 "คุณค่าหลักคือการพิสูจน์ว่ากลยุทธ์ใช้ไม่ได้"

### สัปดาห์ 1 — Schema + Backfill
- สร้างตาราง Supabase ครบ 11 ตารางตาม §4 (`db/migrations/0001_init.sql`)
- Backfill ราคาย้อนหลัง 3 ปี: BTC/ETH/XRP/SOL/BNB × timeframe 1h + 4h = 164,250 แท่งเทียน (`src/data/backfill.py`)

### สัปดาห์ 2 — Indicators
- คำนวณ 13 indicators (RSI14, MACD, EMA20/50/200, Bollinger Bands, ATR14, vol_ma20) ด้วย pandas ล้วน — ไม่ใช้ `pandas-ta` เพราะไลบรารีเลิกดูแลแล้วและพังกับ numpy รุ่นใหม่ (`src/indicators/compute.py`)
- โหมด `--recent N` สำหรับคำนวณเฉพาะช่วงล่าสุด (เร็วกว่ามาก ใช้ในงานอัตโนมัติ)

### สัปดาห์ 3-4 — Rule Scanner + AI Decision (ยังไม่ตรงสเปกร้อยเปอร์เซ็นต์ ดูช่องว่างด้านล่าง)
- Trigger rules 12 จาก 16 ข้อใน §5.1: A1, A2, A3, B1, B2, B3, C1, C2, C3, C4, D1, E3 (`src/scanner/rules.py`)
- Confluence gate (§5.2) + Rate gate บางส่วน: cooldown 4 ชม./เหรียญ, cap 10 ครั้ง/วัน (`src/scanner/confluence.py`, `src/scanner/gates.py`)
- AI decision layer (§6): เรียก Claude ผ่าน **OpenRouter** (ไม่ใช่ Anthropic API ตรงเพราะ credit หมด) ตอน confluence ≥ 4 (`src/ai/`)
- บันทึกทุก trigger ลง `triggers` table (ผ่าน gate หรือไม่ก็บันทึก ตาม §10.5)

### สัปดาห์ 5 — Scoring
- Evaluator job: ประเมิน prediction หลังครบ 24 ชม., คำนวณ score/wrong_streak ตามสูตร §7.2, อัปเดต `ai_score` (`src/scoring/evaluator.py`)
- Portfolio หลอก (`id=1`, name=`ai-scoring`) ไว้ผูกกับ `ai_score` เพราะยังไม่มีระบบพอร์ตจริง

### สัปดาห์ 6 (บางส่วน) — Dashboard
- **ไม่ได้ทำเป็น Flutter/Next.js ตามสเปก** — ทำเป็น static HTML dashboard เดียว (`web/template.html` + `web/build.py`) เพราะเร็วกว่าและ deploy ฟรีผ่าน GitHub Pages ได้ทันที
- เลือกเหรียญ/timeframe ได้, toggle EMA/Bollinger/Volume, กราฟแท่งเทียน+RSI พร้อม tooltip
- แผง "AI Decision & Scoring": win rate, score, wrong streak, ประวัติ prediction, trigger log
- ตัวนับถอยหลังอัปเดตรอบถัดไป
- **โหมดจำลองการเทรด (Sandbox)**: ซื้อ/ขายด้วยเงินสมมติ เก็บใน `localStorage` ของเบราว์เซอร์ตัวเอง **ไม่ใช่ระบบ paper trading จริงตาม §6-8** — เป็นแค่ของเล่นให้ลองกดดู ไม่เชื่อมกับ Supabase

### Automation
- GitHub Actions (`.github/workflows/rebuild-dashboard.yml`) รันทุก 15 นาที: ingest → indicators → scan+AI → evaluate → build dashboard → commit ถ้าข้อมูลเปลี่ยน
- แก้ปัญหา Binance บล็อก IP ของ GitHub Actions (HTTP 451) โดยเปลี่ยนไปใช้ `data-api.binance.vision`
- Secrets ที่ตั้งไว้ใน GitHub: `SUPABASE_ACCESS_TOKEN`, `OPENROUTER_API_KEY`

---

## ยังไม่ได้ทำ / ช่องว่างที่รู้อยู่

### Rules ที่ยังไม่ implement (4 จาก 16 ข้อใน §5.1)
- **A4** RSI divergence — ต้องมี swing-point detection
- **D2** ราคาใกล้แนวรับ/ต้าน — ต้องมี support/resistance level detection
- **E1** Funding rate, **E2** Fear & Greed — ยังไม่มี job ดึงข้อมูลบริบทตลาด (`fetch_context` ใน §8 ไม่เคยสร้าง, ตาราง `market_context` ว่างเปล่า)

### Rate gate ที่ยังไม่ implement (§5.3)
- Position limit (ถือพร้อมกันไม่เกิน 3 เหรียญ) — ไม่มีความหมายเพราะยังไม่มีระบบพอร์ตจริง
- No-trade window ก่อนข่าวใหญ่ (CPI/FOMC) — ไม่มีปฏิทินข่าว
- Kill switch เมื่อ drawdown > 10%/สัปดาห์ — ไม่มี equity จริงให้วัด

### ระบบที่ยังไม่มีเลย
- **Portfolio/Position/Trade execution จริง** (§9 สัปดาห์ 6) — ตาราง `portfolios`, `positions`, `trades`, `equity_snapshots` มีแต่ยังไม่ถูกใช้งานจริง (มีแค่ portfolio หลอกสำหรับผูก ai_score)
- **risk_monitor job** (เช็ค SL/TP ทุก 1 นาที, §8) — ไม่มีความหมายถ้าไม่มี position จริง (backtest engine มี SL/TP ในตัวอยู่แล้ว แต่นั่นคือจำลอง ไม่ใช่ live)
- **daily_snapshot job** — ไม่มีความหมายถ้าไม่มี portfolio จริง (backtest engine เขียน equity_snapshots ของตัวเองตอนรันเสร็จ ไม่ใช่ job ที่รันทุกวันจริง)
- **Walk-forward validation แบบเป็นระบบ** (§10.3) — เครื่องมือรองรับแล้ว (`--start`/`--end`) แต่ยังไม่ได้ลองแบ่งช่วง train/test จริงจัง หรือ tune น้ำหนักกฎ/threshold ตามผล
- **1D timeframe comparison** (§10.7 อยากได้ 1H/4H/1D) — ตอนนี้เทียบแค่ 1H/4H เพราะเก็บแค่ 2 timeframe นี้ใน DB จริง

### ความเบี่ยงเบนจากสเปกที่ควรรู้ไว้
- ใช้ **OpenRouter** แทน Anthropic API ตรง (Anthropic key ที่ให้มามี credit ไม่พอ) — ถ้าจะเปลี่ยนกลับ แก้ที่ `src/ai/claude_client.py`
- Deploy บน **GitHub Actions + Pages** แทน Raspberry Pi ตามสเปก §2 — เพราะเซ็ตอัปเร็วกว่ามากและฟรี ถ้าต้องการรันบน Pi จริงๆ ทีหลังค่อยย้าย
- Dashboard เป็น static site ไม่ใช่ Flutter/Next.js — ข้อมูลอัปเดตทุก 15 นาทีผ่านการ rebuild ไม่ใช่ live connection

---

## ลำดับที่แนะนำถ้าจะทำต่อ

1. **แก้กลยุทธ์แล้ว backtest ใหม่** — ผลตอนนี้ขาดทุนทั้ง 1H/4H (ดูด้านบน) อย่าปล่อยให้ AI ตัดสินใจ live ต่อจนกว่าจะเจอชุดกฎ/threshold ที่ backtest แล้วกำไรจริง (นี่คือเงื่อนไขก่อนใช้เงินจริงตาม §9 อยู่แล้ว)
2. **fetch_context job** (funding rate + Fear & Greed) — ปลดล็อก E1/E2 ให้ confluence score แม่นขึ้น
3. **Portfolio/execution จริง** — ถ้าอยากให้ AI "เทรด" จริงๆ ไม่ใช่แค่ทำนายเฉยๆ
4. A4/D2 rules — เสริมความแม่นยำของ scanner
5. Kill switch + no-trade window — ต้องรอข้อ 3 (มีพอร์ตจริง) และปฏิทินข่าวก่อน
6. เอาผล backtest ไปโชว์บน dashboard — ตอนนี้ผลอยู่ใน Supabase (`portfolios` mode=`backtest`) เฉยๆ ยังไม่ได้ขึ้นหน้าเว็บ
