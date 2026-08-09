# สถานะโปรเจกต์ — Crypto AI Paper Trading

อัปเดตล่าสุด: 2026-08-09

Repo: https://github.com/SINGHAr5r5/crypto-ai-paper-trading (public)
Dashboard: https://singhar5r5.github.io/crypto-ai-paper-trading/
Supabase project: `fanjxckcjfghvxsubwey`

---

## ทำไปแล้ว

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
- **risk_monitor job** (เช็ค SL/TP ทุก 1 นาที, §8) — ไม่มีความหมายถ้าไม่มี position จริง
- **daily_snapshot job** — ไม่มีความหมายถ้าไม่มี portfolio จริง
- **Backtest engine** (§9 สัปดาห์ 3) — ยังไม่เริ่มเลย ทั้งที่ spec บอกให้ทำ rule-based backtest ก่อนต่อ AI
- **Walk-forward validation / parameter tuning** (§10.3, §10.6) — ยังไม่เริ่ม เพราะยังไม่มี backtest engine
- **Look-ahead bias guard** — ยังไม่เกี่ยวข้องเพราะยังไม่มี backtest

### ความเบี่ยงเบนจากสเปกที่ควรรู้ไว้
- ใช้ **OpenRouter** แทน Anthropic API ตรง (Anthropic key ที่ให้มามี credit ไม่พอ) — ถ้าจะเปลี่ยนกลับ แก้ที่ `src/ai/claude_client.py`
- Deploy บน **GitHub Actions + Pages** แทน Raspberry Pi ตามสเปก §2 — เพราะเซ็ตอัปเร็วกว่ามากและฟรี ถ้าต้องการรันบน Pi จริงๆ ทีหลังค่อยย้าย
- Dashboard เป็น static site ไม่ใช่ Flutter/Next.js — ข้อมูลอัปเดตทุก 15 นาทีผ่านการ rebuild ไม่ใช่ live connection

---

## ลำดับที่แนะนำถ้าจะทำต่อ

1. **Backtest engine** — ควรทำก่อนอย่างอื่น เพราะ spec เน้นว่าต้อง validate กลยุทธ์ด้วยข้อมูลย้อนหลังก่อนเชื่อผล live (ตอนนี้มีข้อมูล 3 ปีพร้อมอยู่แล้ว ไม่ต้องรอ)
2. **fetch_context job** (funding rate + Fear & Greed) — ปลดล็อก E1/E2 ให้ confluence score แม่นขึ้น
3. **Portfolio/execution จริง** — ถ้าอยากให้ AI "เทรด" จริงๆ ไม่ใช่แค่ทำนายเฉยๆ
4. A4/D2 rules — เสริมความแม่นยำของ scanner
5. Kill switch + no-trade window — ต้องรอข้อ 3 (มีพอร์ตจริง) และปฏิทินข่าวก่อน
