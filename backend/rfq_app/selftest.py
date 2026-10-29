"""雲端自我測試：照人員操作的順序走一遍真正的 API（建詢價→報價→送出→等結果）。

- 只在設了 SELFTEST_KEY（至少 24 字元）時開放，金鑰放在網址 ?key=（只用 GET，方便從外部檢查）。
  驗證完請把 SELFTEST_KEY 從 Vercel 拿掉，這組端點就會變成 404。
- 只送假澳得仕：送出目標不是假澳得仕（internal-mock 或 /api/mock-aud/）時一律拒絕，
  絕不會送到澳得仕正式站。
"""

from __future__ import annotations

import asyncio
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from . import config, db
from .dispatcher import INTERNAL_MOCK

router = APIRouter(prefix="/api/selftest")

WAITING = {"pending", "sending"}
SCENARIOS = {
    "happy": [],
    "retry": [{"status": 503}],  # 第 1 次 503 → 60 秒後佇列再送 → 202
    "rate_limited": [{"status": 429}],
    "gave_up": [{"status": 503}] * 6,
}


def _check_key(key: str) -> None:
    s = config.settings
    if len(s.selftest_key) < 24 or not secrets.compare_digest(key.encode(), s.selftest_key.encode()):
        raise HTTPException(404, "Not Found")


def _target_is_mock() -> bool:
    url = config.settings.aud_quote_api_url
    return url == INTERNAL_MOCK or "/api/mock-aud/" in url


@asynccontextmanager
async def _client():
    from main import app  # 避免循環匯入

    s = config.settings
    if not s.dev_login_email and not s.key_login_configured:
        raise HTTPException(503, "自我測試要先設定 APP_ACCESS_KEY 與 SESSION_SECRET")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://internal", timeout=s.http_timeout + 10) as c:
        if not s.dev_login_email:
            r = await c.post("/api/auth/key", json={"key": s.access_key, "name": "selftest"})
            if r.status_code != 200:
                raise HTTPException(503, f"自我測試登入失敗（{r.status_code}）")
        yield c


def _summary(q: dict) -> dict:
    d = q["dispatches"][0] if q.get("dispatches") else None
    return {
        "quote_id": q["id"],
        "quote_no": q["quote_no"],
        "quote_revision": q["quote_revision"],
        "quote_status": q["status"],
        "dispatch": None
        if d is None
        else {
            "id": d["id"],
            "event_id": d["event_id"],
            "status": d["status"],
            "attempt_count": d["attempt_count"],
            "next_attempt_at": d["next_attempt_at"],
            "last_http_status": d["last_http_status"],
            "last_error_code": d["last_error_code"],
            "candidate_id": d.get("candidate_id"),
            "attempts": [
                {"no": a["attempt_no"], "http": a["http_status"], "error": a["error"], "started_at": a["started_at"], "request_id": a["request_id"]}
                for a in d["attempts"]
            ],
        },
    }


def _expect(r: httpx.Response, status: int, step: str):
    if r.status_code != status:
        raise HTTPException(500, {"step": step, "http": r.status_code, "body": r.text[:500]})
    return r.json()


@router.get("/run")
async def run(key: str = Query(""), scenario: str = Query("happy"), wait: int = Query(20, ge=0, le=60)) -> dict:
    _check_key(key)
    if scenario not in SCENARIOS:
        raise HTTPException(400, f"scenario 只能是 {', '.join(SCENARIOS)}")
    if not _target_is_mock():
        raise HTTPException(409, "送出目標不是假澳得仕，自我測試不執行")
    s = config.settings
    t0 = time.monotonic()
    steps: list[dict] = []
    async with _client() as c:
        _expect(await c.delete("/api/mock-aud/_admin/faults"), 200, "clear_faults")
        if SCENARIOS[scenario]:
            _expect(await c.post("/api/mock-aud/_admin/faults", json={"next": SCENARIOS[scenario]}), 200, "add_faults")
            steps.append({"step": "faults", "next": SCENARIOS[scenario]})

        year = datetime.now(ZoneInfo("Asia/Taipei")).year
        for _ in range(5):
            number = f"AUD-RFQ-{year}-9{secrets.randbelow(10000):04d}"
            r = await c.post(
                "/api/rfqs",
                json={"rfq_number": number, "item_name": "自我測試零件", "material_text": "AL6061-T6", "quantity": 10, "unit": "pcs"},
            )
            if r.status_code != 409:
                break
        rfq = _expect(r, 201, "create_rfq")
        steps.append({"step": "create_rfq", "rfq_id": rfq["id"], "rfq_number": rfq["rfq_number"]})

        quote = _expect(await c.post(f"/api/rfqs/{rfq['id']}/quotes", json={"unit_price": 120.5, "lead_days": 7, "note": "selftest"}), 201, "create_quote")
        steps.append({"step": "create_quote", "quote_id": quote["id"], "quote_no": quote["quote_no"]})

        sent = _expect(await c.post(f"/api/quotes/{quote['id']}/send"), 200, "send")
        steps.append({"step": "send", "dispatch_id": sent["dispatch_id"], "enqueue": sent["enqueue"]})

        deadline = time.monotonic() + wait
        q = sent["quote"]
        while True:
            d = q["dispatches"][0] if q["dispatches"] else None
            if d and d["status"] not in WAITING:
                break
            if time.monotonic() >= deadline:
                break
            await asyncio.sleep(1.5)
            q = _expect(await c.get(f"/api/quotes/{quote['id']}"), 200, "poll")

        result = _summary(q)

        # 同一個 event_id、同一份內容再送一次 → 對方應回 200 duplicate（只在程式內的假澳得仕做）
        if scenario == "happy" and result["dispatch"] and result["dispatch"]["status"] == "accepted" and s.aud_quote_api_url == INTERNAL_MOCK:
            async with db.tx() as conn:
                row = (await conn.execute(text("SELECT event_id, payload_text FROM rfq.quote_dispatches WHERE id=:id"), {"id": sent["dispatch_id"]})).mappings().one()
            r = await c.post(
                "/api/mock-aud/api/rfq/quotes",
                content=row["payload_text"].encode(),
                headers={"Authorization": f"Bearer {s.aud_quote_api_token}", "Content-Type": "application/json", "X-Event-Id": row["event_id"], "X-Request-Id": f"selftest-dup-{sent['dispatch_id']}"},
            )
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else None
            steps.append({"step": "duplicate_resend", "http": r.status_code, "outcome": (body or {}).get("outcome")})

    expected = {"happy": "accepted", "retry": "retry_wait", "rate_limited": "retry_wait", "gave_up": "retry_wait"}[scenario]
    got = result["dispatch"]["status"] if result["dispatch"] else None
    ok = got == expected
    if scenario == "happy":
        dup = next((x for x in steps if x["step"] == "duplicate_resend"), None)
        ok = ok and (dup is None or (dup["http"] == 200 and dup["outcome"] == "duplicate"))
    return {
        "ok": ok,
        "scenario": scenario,
        "expected_status": expected,
        "target": "internal-mock" if s.aud_quote_api_url == INTERNAL_MOCK else "mock-url",
        "on_vercel": s.on_vercel,
        "elapsed_s": round(time.monotonic() - t0, 1),
        "steps": steps,
        "result": result,
        "next": None if scenario == "happy" else f"/api/selftest/status?quote_id={result['quote_id']}（約 {60 if scenario != 'gave_up' else 3900} 秒後看是否由佇列重送）",
    }


@router.get("/status")
async def status(key: str = Query(""), quote_id: int = Query(...), sweep: bool = Query(False)) -> dict:
    _check_key(key)
    async with _client() as c:
        if sweep:
            _expect(await c.post("/api/dispatches/sweep"), 200, "sweep")
        q = _expect(await c.get(f"/api/quotes/{quote_id}"), 200, "get_quote")
    return _summary(q)
