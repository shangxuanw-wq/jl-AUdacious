# jl-AUdacious：JL × 澳得仕 估價模組

兆臨接澳得仕（AUdacious 3D 工作室）的詢價，建立報價，依契約 `2026-10-29.4` 用 API 送出報價。
全部跑在雲端：**Vercel**（前端＋API＋Queues）＋ **Supabase**（`jl-rfq-dev`，資料表在 `rfq`、`mock_partner` schema）。

## 架構

```
瀏覽器 ──► Vercel（同一個網域）
            ├─ /            frontend/  React 18 + Vite + Tailwind
            └─ /api/*       backend/   FastAPI（main:app）
                               ├─ 報價、送出、重送（Vercel Queues topic: quote-dispatch）
                               └─ /api/mock-aud/*  假澳得仕報價 API（開發用）
                    │
                    ▼
            Supabase Postgres（rfq.*、mock_partner.*）
```

- 送出：`POST /api/quotes/{id}/send` 建立送出紀錄（凍結 payload 與 event_id），當場送第 1 次。
- 重送：可重送的錯誤（5xx、逾時、429、409 event_in_flight／send_pending）間隔 60／300／1800／1800 秒，總共最多 5 次。
  狀態以資料庫為準（`next_attempt_at`），由三條路觸發，誰先到都一樣：
  1. Vercel Queues 延遲訊息（topic `quote-dispatch`，推送由 `main.py` 中介層交給 SDK）
  2. 人員介面開著送出中的報價時，每 5 秒呼叫 `POST /api/dispatches/sweep`
  3. **Supabase pg_cron 每分鐘**呼叫 `https://rfq.jauhlirn.com/api/cron/sweep`（密鑰存在 Supabase Vault `rfq_cron_secret`，排程名 `rfq-sweep-every-minute`）
  4. 每天一次的 Vercel Cron（保險）
- Vercel Queues 的 Python 推送在多服務架構下沒有觸發（2026-10-29 實測），目前送訊息但不依賴它。
- 網址：`https://rfq.jauhlirn.com`（自訂網域不受 Vercel 部署保護，靠 app 自己的登入）；`jl-audacious.vercel.app` 仍有 Vercel 部署保護。
- 防呆：沒設 `RFQ_ALLOW_PARTNER_PROD=true` 時，送往 `audacious-3d-studio.vercel.app` 一律擋下。

## 目錄

| 路徑 | 內容 |
|---|---|
| `backend/main.py` | FastAPI 入口 |
| `backend/rfq_app/payload.py` | 金額計算、報價單號、契約 payload |
| `backend/rfq_app/dispatcher.py` | 一次送出嘗試、結果判斷、重送間隔 |
| `backend/rfq_app/queue_worker.py` | Vercel Queues 消費者 |
| `backend/rfq_app/mock_aud/` | 假澳得仕（行為對照澳得仕原始碼） |
| `backend/sql/` | 資料表 migration（已套用到 Supabase） |
| `backend/rfq_app/selftest.py` | 雲端自我測試（只送假澳得仕） |
| `backend/tests/` | 48 項測試（本機 PostgreSQL 16） |
| `frontend/` | 人員介面 |

## 收詢價信

- 「信箱」頁按「連接」→ 用 `RFQ_MAILBOX`（預設 jl-jimmy@jauhlirn.com）授權 Google（`gmail.modify`）。refresh token 用 `MAIL_TOKEN_KEY` 加密存在 `rfq.mailboxes`。
- 每分鐘的 `/api/cron/sweep` 會順便收信：`subject:AUD-RFQ -from:me newer_than:30d`，用 `rfq.inbound_messages` 記住處理過哪些信，不改信箱內容。
- 解析照契約 3.2（`rfq_app/mail/parser.py`）；同一詢價編號再寄 → 更新同一張單、以最新一封為準；已結案不動。
- 附件不另存，下載時即時向 Gmail 取（要登入）。
- `RFQ_SENDER_ALLOW`：只收這些寄件人（信箱或 `@網域`，逗號分隔）；空的 = 不限制。

## 登入

- Google 登入＋白名單（`GOOGLE_CLIENT_ID`、`GOOGLE_CLIENT_SECRET`、`ALLOWED_EMAILS`）。
- Google 還沒設好之前：臨時金鑰登入（`APP_ACCESS_KEY`，至少 24 字元）。換掉金鑰，所有用舊金鑰登入的 session 立刻失效；拿掉就關閉。
- 外層還有 Vercel 部署保護（Vercel Authentication）。

## 雲端自我測試

設了 `SELFTEST_KEY`（至少 24 字元）才開放，驗證完請拿掉。
送出目標不是假澳得仕時一律拒絕。

- `GET /api/selftest/run?key=…&scenario=happy` 建詢價→報價→送出→202，再用同一 event_id 重送→200 duplicate
- `scenario=retry`：第 1 次 503，約 60 秒後由佇列重送；用 `GET /api/selftest/status?key=…&quote_id=…` 看結果
- 另有 `rate_limited`、`gave_up`

## 環境變數

見 `.env.example`。密鑰只設在 Vercel，不進 repo。

## 本機測試

```bash
cd backend
pip install fastapi==0.162.0 "sqlalchemy[asyncio]==2.1.6" asyncpg==0.32.0 httpx==0.28.1 itsdangerous==2.2.0 vercel==0.12.1 pytest anyio
# 需要一個空的 PG16，先套 sql/001、002
TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55432/rfq_test python -m pytest -q tests
```
