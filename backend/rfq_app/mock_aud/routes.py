"""假澳得仕報價 API（狀態存在 Supabase 的 mock_partner schema）。

公開端點：GET/POST /api/mock-aud/api/rfq/quotes —— 回應照澳得仕契約 2026-10-29.5。
控制端點：/api/mock-aud/_admin/* —— 要登入，用來發布／退回候選、改詢價單狀態、注入故障。
"""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import hmac
import json
import re
import secrets
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from rfq_app import config, db
from rfq_app.auth import require_user
from . import logic as L

router = APIRouter(prefix="/api/mock-aud")
admin = APIRouter(prefix="/api/mock-aud/_admin", dependencies=[Depends(require_user)])

MAX_BODY = 64 * 1024
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:/+=@-]{1,80}$")
CONTRACT = json.loads((Path(__file__).with_name("contract-2026-10-29.5.json")).read_text("utf-8"))
CONTRACT_VERSION = CONTRACT["contract_version"]
TPE = ZoneInfo("Asia/Taipei")
SEEDS = {
    "AUD-RFQ-2026-0099": ("sent", False, True),
    "AUD-RFQ-2026-0098": ("closed", False, True),
    "AUD-RFQ-2026-0097": ("preparing", True, True),
    "AUD-RFQ-2026-0096": ("preparing", False, True),
    "AUD-RFQ-2026-0095": ("sent", False, False),
    "AUD-RFQ-2026-0094": ("sent", False, True),
}


def _today() -> str:
    return datetime.now(TPE).date().isoformat()


@router.get("/api/rfq/quotes")
async def contract(request: Request) -> JSONResponse:
    data = copy.deepcopy(CONTRACT)
    base = config.settings.app_base_url or str(request.base_url).rstrip("/")
    data["endpoint"] = base + "/api/mock-aud/api/rfq/quotes"
    data["enabled"] = L.js_trim(config.settings.mock_aud_token) != "" and len(config.settings.mock_aud_token) >= 24
    return JSONResponse(data, headers={"Cache-Control": "no-store"})


async def _pop_fault() -> dict | None:
    async with db.tx() as conn:
        row = (
            await conn.execute(
                text("DELETE FROM mock_partner.faults WHERE id = (SELECT id FROM mock_partner.faults ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING spec")
            )
        ).first()
        return row[0] if row else None


async def _log(entry: dict) -> None:
    async with db.tx() as conn:
        await conn.execute(
            text(
                "INSERT INTO mock_partner.request_log (request_id, status, rfq, event_id, body, response, fault) "
                "VALUES (:rid, :st, :rfq, :ev, :body, CAST(:resp AS jsonb), CAST(:fault AS jsonb))"
            ),
            {
                "rid": entry["request_id"],
                "st": entry["status"],
                "rfq": entry.get("rfq"),
                "ev": entry.get("event_id"),
                "body": entry.get("body"),
                "resp": json.dumps(entry.get("response"), ensure_ascii=False),
                "fault": json.dumps(entry.get("fault"), ensure_ascii=False) if entry.get("fault") else None,
            },
        )


def _cand_from_row(r) -> dict:
    d = dict(r)
    d["id"] = str(d["id"])
    return d


async def _receive(conn, number: str, body: dict, event_id: str | None, request_id: str, self_test: bool = False) -> dict:
    rfq = (await conn.execute(text("SELECT * FROM mock_partner.rfqs WHERE number=:n FOR UPDATE"), {"n": number})).mappings().first()
    if not rfq:
        raise L.NotFound(f"找不到詢價編號 {number}")
    if self_test and not rfq["is_test"]:
        raise L.Conflict(f"{number} 不是測試單；X-Self-Test 只能打測試單，什麼都沒寫", "not_test_rfq")
    cands = [_cand_from_row(r) for r in (await conn.execute(text("SELECT * FROM mock_partner.candidates WHERE rfq_number=:n ORDER BY revision"), {"n": number})).mappings()]
    h = L.payload_hash(body)
    if event_id:
        same = [c for c in cands if c["event_id"] == event_id]
        if same:
            if same[0]["payload_hash"] == h:
                return {"duplicate": True, "candidate": same[0]}
            raise L.Conflict(f"event_id {event_id} 之前送過不同的內容；不覆蓋。要改報價請用新的 event_id", "event_conflict")
    same_content = sorted([c for c in cands if c["payload_hash"] == h and c["status"] != "rejected"], key=lambda c: -c["revision"])
    if same_content:
        return {"duplicate": True, "candidate": same_content[0]}
    if rfq["status"] == "closed":
        raise L.Conflict(f"詢價 {number} 已結案，不收新報價；要處理請另建詢價", "closed")
    if rfq["status"] not in ("sent", "quoted"):
        if rfq["send_pending"]:
            raise L.Conflict(f"詢價 {number} 的寄送結果還在確認中，請稍後重送同一份", "send_pending")
        raise L.Conflict(f"詢價 {number} 目前是「{rfq['status']}」，還沒寄給廠商，不收報價", "status")
    if not rfq["snapshot"]:
        raise L.Conflict(f"詢價 {number} 沒有寄出紀錄，不收報價", "no_snapshot")
    expect = {"quantity": rfq["quantity"], "unit": rfq["unit"], "item_name": rfq["item_name"], "material_text": rfq["material_text"]}
    parsed = L.parse_quote(body, expect, _today())
    quote, issues, qrev = parsed["quote"], parsed["issues"], parsed["quote_revision"]
    spec_rev = parsed["rfq_revision"]
    if spec_rev is not None and spec_rev > rfq["spec_revision"]:
        raise L.Conflict(f"規格版次 {spec_rev} 不是我方寄出過的版次（目前寄到第 {rfq['spec_revision']} 版）", "rfq_revision_unknown")
    if spec_rev is None:
        if rfq["spec_revision"] == 1:
            spec_rev = 1
        else:
            issues.append(L.issue("spec_unbound", "error", "rfq_revision", "沒帶 rfq_revision，可能寄達的規格不只一版，要人工指定"))
    elif spec_rev < rfq["spec_revision"]:
        issues.append(L.issue("spec_outdated", "review", "rfq_revision", f"這份報價對應第 {spec_rev} 版規格，目前是第 {rfq['spec_revision']} 版", got=spec_rev, expected=rfq["spec_revision"]))
    published = next((c for c in cands if rfq["published_candidate_id"] and c["id"] == str(rfq["published_candidate_id"])), None)
    if qrev and published:
        cmp = L.compare_revisions(qrev, published["quote_revision"])
        if cmp == -1:
            issues.append(L.issue("older_revision", "review", "quote_revision", f"這份的修訂 {qrev} 比目前已發布的 {published['quote_revision']} 舊", got=qrev, expected=published["quote_revision"]))
        if cmp is None and published["quote_revision"]:
            issues.append(L.issue("revision_unknown", "review", "quote_revision", f"分不出修訂 {qrev} 跟已發布的 {published['quote_revision']} 哪個新", got=qrev, expected=published["quote_revision"]))
    elif not qrev and published:
        issues.append(L.issue("revision_unknown", "review", "quote_revision", "已經有發布的報價，這份沒帶修訂版次，分不出新舊", got=None))
    if qrev:
        same_rev = sorted([c for c in cands if c["quote_revision"] == qrev and c["status"] in ("pending", "published")], key=lambda c: -c["revision"])
        if same_rev and not L.same_terms(quote, same_rev[0]["parsed"]):
            issues.append(L.issue("revision_reused", "review", "quote_revision", f"修訂 {qrev} 之前收過（第 {same_rev[0]['revision']} 版），這次數字不同；改報價請把修訂版次加 1", got=qrev, expected=same_rev[0]["revision"]))
    cand = {
        "id": str(uuid.uuid4()),
        "revision": max([c["revision"] for c in cands], default=0) + 1,
        "status": "pending",
        "event_id": event_id,
        "quote_revision": qrev,
        "issues": issues,
        "spec_revision": spec_rev,
    }
    await conn.execute(
        text(
            "INSERT INTO mock_partner.candidates (id, rfq_number, revision, status, event_id, quote_revision, payload, payload_hash, parsed, issues, request_id, spec_revision, self_test) "
            "VALUES (:id, :n, :rev, 'pending', :ev, :qrev, CAST(:p AS jsonb), :h, CAST(:parsed AS jsonb), CAST(:issues AS jsonb), :rid, :srev, :st)"
        ),
        {
            "id": cand["id"],
            "n": number,
            "rev": cand["revision"],
            "ev": event_id,
            "qrev": qrev,
            "p": json.dumps(body, ensure_ascii=False),
            "h": h,
            "parsed": json.dumps(L.canonical(quote), ensure_ascii=False),
            "issues": json.dumps(issues, ensure_ascii=False),
            "rid": request_id,
            "srev": spec_rev,
            "st": self_test,
        },
    )
    return {"duplicate": False, "candidate": cand}


@router.post("/api/rfq/quotes")
async def post_quote(req: Request) -> JSONResponse:
    raw_rid = (req.headers.get("x-request-id") or "").strip()
    request_id = raw_rid if REQUEST_ID_RE.match(raw_rid) else "req_" + base64.urlsafe_b64encode(secrets.token_bytes(9)).decode().rstrip("=")
    entry: dict[str, Any] = {"request_id": request_id}

    async def reply(body: dict, status: int, retry_after: int | None = None) -> JSONResponse:
        out = {**body, "request_id": request_id, "contract_version": CONTRACT_VERSION}
        entry.update({"status": status, "response": out})
        try:
            await _log(entry)
        except Exception:  # noqa: BLE001 - 紀錄失敗不影響回應
            pass
        headers = {"X-Request-Id": request_id, "Cache-Control": "no-store"}
        if retry_after is not None:
            headers["Retry-After"] = str(retry_after)
        return JSONResponse(out, status_code=status, headers=headers)

    fault = await _pop_fault()
    if fault:
        entry["fault"] = fault
        # 故障時也記下 event_id 與內容，方便核對「重送是否同一份」
        entry["event_id"] = (req.headers.get("x-event-id") or "").strip()[:120] or None
        raw_peek = await req.body()
        entry["body"] = raw_peek[:4000].decode("utf-8", errors="replace")
        if fault.get("delay"):
            await asyncio.sleep(min(float(fault["delay"]), 55))
        if fault.get("status"):
            b = {"error": fault.get("error", f"模擬故障 {fault['status']}")}
            if fault.get("code"):
                b["code"] = fault["code"]
            ra = fault.get("retry_after")
            return await reply(b, int(fault["status"]), int(ra) if ra is not None else None)

    token = config.settings.mock_aud_token
    if len(token.strip()) < 24:
        return await reply({"error": "這個網址還沒啟用（尚未設定 token）", "code": "disabled"}, 503)
    m = re.match(r"^\s*Bearer\s+(\S+)\s*$", req.headers.get("authorization") or "", re.I)
    if not m or not hmac.compare_digest(hashlib.sha256(m[1].encode()).digest(), hashlib.sha256(token.strip().encode()).digest()):
        return await reply({"error": "未授權：請帶 Authorization: Bearer <token>"}, 401)
    ctype = (req.headers.get("content-type") or "").split(";")[0].strip().lower()
    if not (ctype == "application/json" or ctype.endswith("+json")):
        return await reply({"error": "Content-Type 要是 application/json"}, 415)
    try:
        declared = int(req.headers.get("content-length") or "")
    except ValueError:
        declared = None
    if declared is not None and declared > MAX_BODY:
        return await reply({"error": "資料太大（上限 64 KB）"}, 413)
    raw = await req.body()
    if len(raw) > MAX_BODY:
        return await reply({"error": "資料太大（上限 64 KB）"}, 413)
    body_text = raw.decode("utf-8", errors="replace")
    entry["body"] = body_text[:4000]

    def no_constants(c):
        raise ValueError(c)

    try:
        body = json.loads(body_text, parse_constant=no_constants)
    except ValueError:
        return await reply({"error": "不是合法的 JSON"}, 400)
    try:
        number = L.payload_number(body)
    except ValueError as e:
        return await reply({"error": str(e), "issues": [{"code": "rfq_invalid", "level": "error", "field": "rfq", "message": str(e)}]}, 400)
    h_event = (req.headers.get("x-event-id") or "").strip()[:120] or None
    b_event = L.id_text(body.get("event_id", body.get("eventId")), 120)[0]
    if h_event and b_event and h_event != b_event:
        msg = f"X-Event-Id（{h_event[:40]}）跟 body 的 event_id（{b_event[:40]}）不一樣"
        return await reply({"error": msg, "issues": [{"code": "event_id_mismatch", "level": "error", "field": "event_id", "message": msg}]}, 400)
    event_id = h_event or b_event
    entry.update({"rfq": number, "event_id": event_id})
    self_test = (req.headers.get("x-self-test") or "").strip() == "1"
    try:
        async with db.tx() as conn:
            result = await _receive(conn, number, body, event_id, request_id, self_test)
    except L.NotFound as e:
        return await reply({"error": str(e)}, 404)
    except L.PayloadError as e:
        return await reply({"error": str(e), "issues": [i for i in e.issues if i["level"] == "error"]}, 400)
    except L.Conflict as e:
        return await reply({"error": str(e), "code": e.code}, 409, {"send_pending": 300}.get(e.code))
    except IntegrityError:
        return await reply({"error": "同一個 event_id 正在處理（同時送了兩次），只收一次；稍後重送同一份會拿到既有結果", "code": "event_in_flight"}, 409, 5)
    cand = result["candidate"]
    base = {"ok": True, "rfq": number, "candidate_id": cand["id"], "candidate_revision": cand["revision"]}
    if result["duplicate"]:
        return await reply({**base, "outcome": "duplicate", "status": cand["status"]}, 200)
    return await reply({**base, "outcome": "pending_review", "spec_revision": cand.get("spec_revision"), "issues": [i for i in cand["issues"] if i["level"] != "info"]}, 202)


# ---------------------------------------------------------------------------
# 控制端點
# ---------------------------------------------------------------------------


def _j(v):
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    return v


@admin.get("/state")
async def state() -> dict:
    async with db.tx() as conn:
        rfqs = [{k: _j(v) for k, v in dict(r).items()} for r in (await conn.execute(text("SELECT * FROM mock_partner.rfqs ORDER BY number DESC"))).mappings()]
        cands = [
            {k: _j(v) for k, v in dict(r).items() if k not in ("payload", "parsed")}
            for r in (await conn.execute(text("SELECT * FROM mock_partner.candidates ORDER BY received_at DESC LIMIT 100"))).mappings()
        ]
        faults = [r[0] for r in (await conn.execute(text("SELECT spec FROM mock_partner.faults ORDER BY id")))]
        logs = [{k: _j(v) for k, v in dict(r).items()} for r in (await conn.execute(text("SELECT id, at, request_id, status, rfq, event_id, response, fault FROM mock_partner.request_log ORDER BY id DESC LIMIT 40"))).mappings()]
    for r in rfqs:
        r["candidates"] = [c for c in cands if c["rfq_number"] == r["number"]]
    return {"rfqs": rfqs, "faults": faults, "log": logs, "token_configured": len(config.settings.mock_aud_token) >= 24}


@admin.post("/rfqs/{number}/candidates/{cid}/{action}")
async def candidate_action(number: str, cid: str, action: str) -> dict:
    async with db.tx() as conn:
        rfq = (await conn.execute(text("SELECT * FROM mock_partner.rfqs WHERE number=:n FOR UPDATE"), {"n": number})).mappings().first()
        cand = (await conn.execute(text("SELECT status FROM mock_partner.candidates WHERE id=:id AND rfq_number=:n"), {"id": cid, "n": number})).scalar()
        if not rfq or not cand:
            raise HTTPException(404, "找不到")
        if cand != "pending":
            raise HTTPException(409, f"這個版本是「{cand}」，只有待審的可以{ '發布' if action == 'publish' else '退回' }")
        if action == "publish":
            if rfq["status"] == "closed":
                raise HTTPException(409, "已結案，不能發布")
            await conn.execute(text("UPDATE mock_partner.candidates SET status='superseded' WHERE rfq_number=:n AND status='published'"), {"n": number})
            await conn.execute(text("UPDATE mock_partner.candidates SET status='published' WHERE id=:id"), {"id": cid})
            await conn.execute(text("UPDATE mock_partner.rfqs SET published_candidate_id=:id, status='quoted' WHERE number=:n"), {"id": cid, "n": number})
        elif action == "reject":
            await conn.execute(text("UPDATE mock_partner.candidates SET status='rejected' WHERE id=:id"), {"id": cid})
        else:
            raise HTTPException(400, "action 只能是 publish 或 reject")
    return {"ok": True}


@admin.patch("/rfqs/{number}")
async def patch_rfq(number: str, body: dict) -> dict:
    allowed = {k: body[k] for k in ("status", "send_pending", "snapshot", "spec_revision", "is_test") if k in body}
    if "spec_revision" in allowed and (not isinstance(allowed["spec_revision"], int) or isinstance(allowed["spec_revision"], bool) or allowed["spec_revision"] < 1):
        raise HTTPException(400, "spec_revision 要是正整數")
    if not allowed:
        raise HTTPException(400, "沒有可改的欄位")
    sets = ", ".join(f"{k}=:{k}" for k in allowed)
    async with db.tx() as conn:
        n = (await conn.execute(text(f"UPDATE mock_partner.rfqs SET {sets} WHERE number=:number"), {**allowed, "number": number})).rowcount
    if not n:
        raise HTTPException(404, "找不到")
    return {"ok": True}


@admin.post("/faults")
async def add_faults(body: dict) -> dict:
    items = body.get("next") or []
    if not isinstance(items, list) or len(items) > 20:
        raise HTTPException(400, "next 要是 1～20 筆的陣列")
    async with db.tx() as conn:
        for spec in items:
            await conn.execute(text("INSERT INTO mock_partner.faults (spec) VALUES (CAST(:s AS jsonb))"), {"s": json.dumps(spec)})
        n = (await conn.execute(text("SELECT count(*) FROM mock_partner.faults"))).scalar_one()
    return {"queued": n}


@admin.delete("/faults")
async def clear_faults() -> dict:
    async with db.tx() as conn:
        await conn.execute(text("DELETE FROM mock_partner.faults"))
    return {"queued": 0}


@admin.post("/reset")
async def reset() -> dict:
    async with db.tx() as conn:
        await conn.execute(text("DELETE FROM mock_partner.candidates"))
        await conn.execute(text("DELETE FROM mock_partner.faults"))
        await conn.execute(text("DELETE FROM mock_partner.request_log"))
        await conn.execute(text("UPDATE mock_partner.rfqs SET published_candidate_id=NULL, status=CASE WHEN status='quoted' THEN 'sent' ELSE status END"))
        for n, (st, sp, snap) in SEEDS.items():
            await conn.execute(text("UPDATE mock_partner.rfqs SET status=:st, send_pending=:sp, snapshot=:snap, spec_revision=1, is_test=false WHERE number=:n"), {"st": st, "sp": sp, "snap": snap, "n": n})
    return {"ok": True}
