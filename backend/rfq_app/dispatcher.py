"""送出報價：一次嘗試＝領取→發 HTTP→寫結果。重送照澳得仕契約 2026-10-29.5 第 4.7 節。

- 同一筆送出紀錄（dispatch）永遠用同一個 event_id、同一份 payload_text。
- 可重送：逾時／連線錯誤、5xx（503 disabled 除外）、429、409 event_in_flight、409 send_pending。
- 其他 4xx（含 409 closed／status／no_snapshot／rfq_revision_unknown／event_conflict／not_test_rfq）不重送。
- 間隔：2、5、15 秒（送出當下就地重試），之後 1、5、30 分鐘（背景每分鐘掃描）；總共最多 7 次，之後轉人工。
- 有 Retry-After 就至少等那麼久；沒帶時 429＝60 秒、event_in_flight＝5 秒、send_pending＝300 秒、503 maintenance＝600 秒。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import httpx
from sqlalchemy import text

from . import config, db

log = logging.getLogger("rfq.dispatcher")

INTERNAL_MOCK = "internal-mock"  # AUD_QUOTE_API_URL 設成這個值 → 送到本 app 內的假澳得仕
RETRY_DELAYS = [2, 5, 15, 60, 300, 1800]
MAX_ATTEMPTS = 7
RETRYABLE_409 = {"event_in_flight", "send_pending"}
DEFAULT_WAIT = {"rate_limited": 60, "event_in_flight": 5, "send_pending": 300, "maintenance": 600}
TERMINAL = {"accepted", "duplicate", "published", "rejected", "not_found", "conflict", "gave_up", "blocked"}
SUCCESS = {"accepted", "duplicate", "published"}

# 測試可以換掉：回傳一個 httpx.AsyncClient
client_factory: Callable[[], httpx.AsyncClient] = lambda: httpx.AsyncClient(timeout=config.settings.http_timeout)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Classified:
    status: str  # 送出紀錄的新狀態
    retry: bool
    error_code: str | None
    min_delay: int = 0


def _retry_after(headers: Any) -> int:
    try:
        v = int(str((headers or {}).get("retry-after", "")).strip())
        return max(0, min(v, 3600))
    except ValueError:
        return 0


def classify(http_status: int | None, body: Any, exc: str | None, headers: Any = None) -> Classified:
    if exc is not None:
        return Classified("retry_wait", True, exc)
    assert http_status is not None
    b = body if isinstance(body, dict) else {}
    ra = _retry_after(headers)
    code = str(b.get("code") or "")
    if http_status == 202:
        return Classified("accepted", False, None)
    if http_status == 200:
        outcome = b.get("outcome")
        if outcome == "published":
            return Classified("published", False, None)
        if outcome == "duplicate":
            return Classified("duplicate", False, None)
        return Classified("rejected", False, "unexpected_200")
    if http_status == 503 and code == "disabled":
        return Classified("rejected", False, "endpoint_disabled")
    if http_status >= 500:
        key = "maintenance" if code == "maintenance" else None
        return Classified("retry_wait", True, key or f"http_{http_status}", min_delay=max(ra, DEFAULT_WAIT.get(key or "", 0)))
    if http_status == 429:
        return Classified("retry_wait", True, "rate_limited", min_delay=max(ra, DEFAULT_WAIT["rate_limited"]))
    if http_status == 409:
        code = code or "conflict"
        if code in RETRYABLE_409:
            return Classified("retry_wait", True, code, min_delay=max(ra, DEFAULT_WAIT[code]))
        return Classified("conflict", False, code)
    if http_status == 404:
        return Classified("not_found", False, "not_found")
    if http_status in (400, 401, 413, 415):
        issues = b.get("issues") if isinstance(b.get("issues"), list) else []
        code = issues[0].get("code") if issues and isinstance(issues[0], dict) and issues[0].get("code") else f"http_{http_status}"
        return Classified("rejected", False, code)
    return Classified("rejected", False, "unexpected_status")


def next_delay(attempt_no: int, min_delay: int = 0) -> int:
    """attempt_no 是剛失敗的那一次（1 起算）。"""
    d = RETRY_DELAYS[min(attempt_no, len(RETRY_DELAYS)) - 1]
    return max(d, min_delay)


@dataclass
class ProcessResult:
    state: str
    retry_in: float | None  # 給佇列：多久後再來一次；None 表示不用再來


async def _finish_quote(conn, quote_id: int, dispatch_status: str) -> None:
    if dispatch_status in SUCCESS:
        q = (await conn.execute(text("UPDATE rfq.quotes SET status='sent', updated_at=now() WHERE id=:id RETURNING quote_no, quote_revision, rfq_id"), {"id": quote_id})).mappings().one()
        await conn.execute(
            text("UPDATE rfq.quotes SET status='superseded', updated_at=now() WHERE quote_no=:no AND quote_revision < :rev AND status='sent'"),
            {"no": q["quote_no"], "rev": q["quote_revision"]},
        )
        await conn.execute(text("UPDATE rfq.rfqs SET status='quoted', updated_at=now() WHERE id=:id AND status <> 'closed'"), {"id": q["rfq_id"]})
    elif dispatch_status in TERMINAL:
        await conn.execute(text("UPDATE rfq.quotes SET status='failed', updated_at=now() WHERE id=:id"), {"id": quote_id})
    else:
        await conn.execute(text("UPDATE rfq.quotes SET status='sending', updated_at=now() WHERE id=:id AND status <> 'sent'"), {"id": quote_id})


async def process_dispatch(dispatch_id: int, now: datetime | None = None) -> ProcessResult:
    s = config.settings
    now = now or utcnow()

    # 1) 領取
    async with db.tx() as conn:
        row = (await conn.execute(text("SELECT * FROM rfq.quote_dispatches WHERE id=:id FOR UPDATE SKIP LOCKED"), {"id": dispatch_id})).mappings().first()
        if row is None:
            exists = (await conn.execute(text("SELECT status FROM rfq.quote_dispatches WHERE id=:id"), {"id": dispatch_id})).scalar()
            if exists is None:
                return ProcessResult("missing", None)
            return ProcessResult("locked", 30)
        status = row["status"]
        if status in TERMINAL:
            return ProcessResult(status, None)
        if status == "sending":
            started = row["sending_started_at"] or now
            age = (now - started).total_seconds()
            if age < s.sending_stale_seconds:
                return ProcessResult("in_progress", max(5.0, s.sending_stale_seconds - age))
            # 卡住的（例如函式中途被終止）：視為那次逾時，照常重送同一個 event_id
            log.warning("dispatch %s stale sending (%.0fs)", dispatch_id, age)
        elif row["next_attempt_at"] > now + timedelta(seconds=0.5):
            return ProcessResult("not_due", (row["next_attempt_at"] - now).total_seconds())

        if row["attempt_count"] >= MAX_ATTEMPTS:
            await conn.execute(text("UPDATE rfq.quote_dispatches SET status='gave_up', last_error_code=coalesce(last_error_code,'max_attempts'), updated_at=now() WHERE id=:id"), {"id": dispatch_id})
            await _finish_quote(conn, row["quote_id"], "gave_up")
            return ProcessResult("gave_up", None)

        # 正式站防呆：沒有明確打開就不送澳得仕正式站
        if _host(row["target_url"]) == config.PARTNER_PROD_HOST and not s.allow_partner_prod:
            await conn.execute(text("UPDATE rfq.quote_dispatches SET status='blocked', last_error_code='partner_prod_blocked', updated_at=now() WHERE id=:id"), {"id": dispatch_id})
            await _finish_quote(conn, row["quote_id"], "blocked")
            return ProcessResult("blocked", None)

        attempt_no = row["attempt_count"] + 1
        await conn.execute(
            text("UPDATE rfq.quote_dispatches SET status='sending', attempt_count=:n, sending_started_at=:now, updated_at=now() WHERE id=:id"),
            {"n": attempt_no, "now": now, "id": dispatch_id},
        )
        target_url, body_text, event_id, quote_id = row["target_url"], row["payload_text"], row["event_id"], row["quote_id"]

    # 2) 發 HTTP（transaction 外）
    request_id = f"jl-d{dispatch_id}-a{attempt_no}"
    started = utcnow()
    http_status: int | None = None
    resp_body: Any = None
    resp_headers: Any = None
    resp_text: str | None = None
    exc_code: str | None = None
    if not s.aud_quote_api_token:
        exc_code = "token_missing"
    else:
        headers = {
            "Authorization": f"Bearer {s.aud_quote_api_token}",
            "Content-Type": "application/json",
            "X-Event-Id": event_id,
            "X-Request-Id": request_id,
        }
        try:
            if target_url == INTERNAL_MOCK:
                # 開發期：假澳得仕在同一個 app 裡，直接在程式內呼叫（不走公開網址、不受 Vercel 部署保護影響）
                from main import app as _app

                client_cm = httpx.AsyncClient(transport=httpx.ASGITransport(app=_app), base_url="http://internal", timeout=config.settings.http_timeout)
                url = "/api/mock-aud/api/rfq/quotes"
            else:
                client_cm = client_factory()
                url = target_url
            async with client_cm as client:
                r = await client.post(url, content=body_text.encode("utf-8"), headers=headers)
            http_status = r.status_code
            resp_headers = r.headers
            resp_text = r.text[:4000]
            try:
                resp_body = r.json()
            except ValueError:
                resp_body = None
        except httpx.TimeoutException:
            exc_code = "timeout"
        except httpx.HTTPError as e:
            exc_code = "connection_error:" + type(e).__name__
    finished = utcnow()

    c = classify(http_status, resp_body, exc_code, resp_headers)
    new_status = c.status
    retry_in: float | None = None
    next_at = None
    if c.retry:
        if attempt_no >= MAX_ATTEMPTS:
            new_status = "gave_up"
        else:
            retry_in = next_delay(attempt_no, c.min_delay)
            next_at = now + timedelta(seconds=retry_in)

    # 3) 寫結果
    async with db.tx() as conn:
        await conn.execute(
            text(
                "INSERT INTO rfq.dispatch_attempts (dispatch_id, attempt_no, request_id, started_at, finished_at, http_status, error, response_text) "
                "VALUES (:d, :n, :rid, :s, :f, :hs, :err, :rt)"
            ),
            {"d": dispatch_id, "n": attempt_no, "rid": request_id, "s": started, "f": finished, "hs": http_status, "err": exc_code or c.error_code, "rt": resp_text},
        )
        b = resp_body if isinstance(resp_body, dict) else {}
        await conn.execute(
            text(
                "UPDATE rfq.quote_dispatches SET status=:st, last_http_status=:hs, last_error_code=:ec, last_response=CAST(:lr AS jsonb), "
                "candidate_id=coalesce(:cid, candidate_id), candidate_revision=coalesce(:crev, candidate_revision), "
                "next_attempt_at=coalesce(:na, next_attempt_at), sending_started_at=NULL, updated_at=now() WHERE id=:id"
            ),
            {
                "st": new_status,
                "hs": http_status,
                "ec": c.error_code,
                "lr": json.dumps(resp_body, ensure_ascii=False) if resp_body is not None else None,
                "cid": b.get("candidate_id"),
                "crev": b.get("candidate_revision"),
                "na": next_at,
                "id": dispatch_id,
            },
        )
        await _finish_quote(conn, quote_id, new_status)
    log.info("dispatch %s attempt %s -> %s (http %s, %s)", dispatch_id, attempt_no, new_status, http_status, c.error_code)
    return ProcessResult(new_status, retry_in)


def _host(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).hostname or ""
