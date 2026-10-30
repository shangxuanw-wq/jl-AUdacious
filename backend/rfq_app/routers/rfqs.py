"""詢價單、報價、送出（給人員介面用；全部要登入）。"""

from __future__ import annotations

import secrets
import time
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text

from .. import config, db, payload as pl, spec_fields
from ..auth import require_user
from ..dispatcher import TERMINAL
from ..queue_worker import enqueue, sweep

router = APIRouter(prefix="/api", dependencies=[Depends(require_user)])
TPE = ZoneInfo("Asia/Taipei")


def taipei_today() -> date:
    return datetime.now(TPE).date()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class RfqIn(BaseModel):
    rfq_number: str = Field(max_length=40)
    item_name: str = Field(min_length=1, max_length=120)
    material_text: str = Field(min_length=1, max_length=120)
    quantity: int = Field(ge=1, le=100000)
    unit: Literal["pcs", "sets"] = "pcs"
    need_date: date | None = None
    sync_mock: bool = True

    @field_validator("rfq_number")
    @classmethod
    def _num(cls, v: str) -> str:
        v = v.strip().upper()
        if not pl.AUD_RFQ_RE.match(v):
            raise ValueError("詢價編號要像 AUD-RFQ-2026-0099")
        return v

    @field_validator("item_name", "material_text")
    @classmethod
    def _single_line(cls, v: str) -> str:
        if "\n" in v or "\r" in v:
            raise ValueError("不能換行")
        return v


class QuoteIn(BaseModel):
    unit_price: Decimal = Field(gt=0, le=Decimal("1000000000"), max_digits=12, decimal_places=2)
    lead_days: int = Field(ge=0, le=365)
    qty: int | None = Field(default=None, ge=1, le=100000)
    unit: Literal["pcs", "sets"] | None = None
    part: str | None = Field(default=None, max_length=120)
    material: str | None = Field(default=None, max_length=120)
    quote_date: date | None = None
    valid_until: date | None = None
    tax_included: bool = False
    lead_basis: Literal["po", "quote"] = "po"
    delivery_date: date | None = None
    note: str = Field(default="", max_length=1000)


class QuotePatch(BaseModel):
    unit_price: Decimal | None = Field(default=None, gt=0, le=Decimal("1000000000"), max_digits=12, decimal_places=2)
    lead_days: int | None = Field(default=None, ge=0, le=365)
    qty: int | None = Field(default=None, ge=1, le=100000)
    unit: Literal["pcs", "sets"] | None = None
    part: str | None = Field(default=None, max_length=120)
    material: str | None = Field(default=None, max_length=120)
    quote_date: date | None = None
    valid_until: date | None = None
    tax_included: bool | None = None
    lead_basis: Literal["po", "quote"] | None = None
    delivery_date: date | None = None
    clear_delivery_date: bool = False
    note: str | None = Field(default=None, max_length=1000)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _next_quote_no(conn, day: date) -> str:
    seq = (
        await conn.execute(
            text(
                "INSERT INTO rfq.quote_no_counters (day, last_seq) VALUES (:d, 1) "
                "ON CONFLICT (day) DO UPDATE SET last_seq = rfq.quote_no_counters.last_seq + 1 RETURNING last_seq"
            ),
            {"d": day},
        )
    ).scalar_one()
    if seq > 99:
        raise HTTPException(400, {"code": "quote_no_exhausted", "message": "今天的報價單號已經用完（最多 99 張）"})
    return pl.quote_no_for(day, seq)


async def _rfq(conn, rfq_id: int, lock: bool = False) -> dict:
    row = (await conn.execute(text("SELECT * FROM rfq.rfqs WHERE id=:id" + (" FOR UPDATE" if lock else "")), {"id": rfq_id})).mappings().first()
    if not row:
        raise HTTPException(404, "找不到詢價單")
    return dict(row)


async def _quote(conn, quote_id: int, lock: bool = False) -> dict:
    row = (await conn.execute(text("SELECT * FROM rfq.quotes WHERE id=:id" + (" FOR UPDATE" if lock else "")), {"id": quote_id})).mappings().first()
    if not row:
        raise HTTPException(404, "找不到報價")
    return dict(row)


async def _items(conn, quote_id: int) -> list[dict]:
    return [dict(r) for r in (await conn.execute(text("SELECT * FROM rfq.quote_items WHERE quote_id=:id ORDER BY line_no"), {"id": quote_id})).mappings()]


def _iso(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


def _plain(d: dict) -> dict:
    return {k: _iso(v) for k, v in d.items()}


def _quote_view(rfq: dict, quote: dict, items: list[dict]) -> dict:
    out = _plain(quote)
    out["currency"] = quote["currency"].strip()
    out["items"] = [_plain(i) for i in items]
    if items:
        t = pl.compute_totals(items[0]["unit_price"], items[0]["qty"], quote["tax_included"], quote["tax_rate"], quote["currency"])
        out["totals"] = t.as_numbers()
        tax = t.tax_cents or 0
        out["totals"]["grand_total"] = pl.json_number(t.total_cents + (0 if quote["tax_included"] else tax))
        out["warnings"] = pl.item_warnings(rfq, items)
        if quote.get("rfq_revision") and rfq.get("spec_revision") and quote["rfq_revision"] < rfq["spec_revision"]:
            out["warnings"].append("spec_outdated")
    return out


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------


@router.get("/config")
async def app_config() -> dict:
    s = config.settings
    return {
        "worker_enabled": s.worker_enabled,
        "target_url": s.aud_quote_api_url,
        "target_is_partner_prod": s.target_is_partner_prod,
        "allow_partner_prod": s.allow_partner_prod,
        "vendor_name": s.vendor_name,
        "mock_enabled": s.mock_enabled,
        "manual_rfq_enabled": s.manual_rfq_enabled,
        "today": taipei_today().isoformat(),
        "reply_mode": __import__("rfq_app.mail.reply", fromlist=["reply_mode"]).reply_mode(),
    }


# 列表上的「進度」：todo 待報價、draft 草稿、sending 送出中、failed 送出失敗、review 審核中、published 已發布、closed 完成
_DISPATCH_STAGE = {
    "pending": "sending", "sending": "sending", "retry_wait": "sending",
    "accepted": "review", "duplicate": "review", "published": "published",
}


def _stage(rfq_status: str, q_status: str | None, d_status: str | None) -> str:
    if rfq_status == "closed":
        return "closed"
    if not q_status:
        return "todo"
    if q_status == "draft":
        return "draft"
    if d_status in _DISPATCH_STAGE:
        return _DISPATCH_STAGE[d_status]
    return "failed" if q_status == "failed" or d_status else "review"


@router.get("/rfqs")
async def list_rfqs() -> dict:
    async with db.tx() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT r.*, c.code AS customer_code, lq.q_id, lq.quote_no, lq.quote_revision, lq.q_status, lq.tax_included, lq.tax_rate, lq.currency, "
                    "       li.unit_price, li.qty AS q_qty, ld.status AS d_status "
                    "FROM rfq.rfqs r JOIN rfq.customers c ON c.id = r.customer_id "
                    "LEFT JOIN LATERAL (SELECT q.id AS q_id, q.quote_no, q.quote_revision, q.status AS q_status, q.tax_included, q.tax_rate, q.currency "
                    "                   FROM rfq.quotes q WHERE q.rfq_id = r.id ORDER BY q.id DESC LIMIT 1) lq ON true "
                    "LEFT JOIN LATERAL (SELECT i.unit_price, i.qty FROM rfq.quote_items i WHERE i.quote_id = lq.q_id ORDER BY i.line_no LIMIT 1) li ON true "
                    "LEFT JOIN LATERAL (SELECT d.status FROM rfq.quote_dispatches d WHERE d.quote_id = lq.q_id ORDER BY d.id DESC LIMIT 1) ld ON true "
                    "ORDER BY r.id DESC LIMIT 200"
                )
            )
        ).mappings()
        out = []
        for r in rows:
            r = dict(r)
            lq = None
            if r["q_id"]:
                lq = {"id": r["q_id"], "quote_no": r["quote_no"], "quote_revision": r["quote_revision"], "status": r["q_status"], "dispatch_status": r["d_status"]}
                if r["unit_price"] is not None:
                    t = pl.compute_totals(r["unit_price"], r["q_qty"], r["tax_included"], r["tax_rate"], r["currency"])
                    lq["currency"] = r["currency"].strip()
                    lq["grand_total"] = pl.json_number(t.total_cents + (0 if r["tax_included"] else (t.tax_cents or 0)))
            row = _plain({k: v for k, v in r.items() if k not in ("q_id", "quote_no", "quote_revision", "q_status", "tax_included", "tax_rate", "currency", "unit_price", "q_qty", "d_status")})
            row["latest_quote"] = lq
            row["stage"] = _stage(r["status"], r["q_status"], r["d_status"])
            out.append(row)
        return {"rfqs": out}


@router.post("/rfqs", status_code=201)
async def create_rfq(body: RfqIn, user: str = Depends(require_user)) -> dict:
    if not config.settings.manual_rfq_enabled:
        raise HTTPException(404, "詢價單只從詢價信自動建立")
    async with db.tx() as conn:
        cust = (await conn.execute(text("SELECT id FROM rfq.customers WHERE code='AUD'"))).scalar_one()
        dup = (await conn.execute(text("SELECT id FROM rfq.rfqs WHERE customer_id=:c AND rfq_number=:n"), {"c": cust, "n": body.rfq_number})).scalar()
        if dup:
            raise HTTPException(409, {"code": "duplicate", "message": f"{body.rfq_number} 已經存在", "id": dup})
        row = (
            await conn.execute(
                text(
                    "INSERT INTO rfq.rfqs (customer_id, rfq_number, item_name, material_text, quantity, unit, need_date, created_by) "
                    "VALUES (:c, :n, :i, :m, :q, :u, :d, :by) RETURNING *"
                ),
                {"c": cust, "n": body.rfq_number, "i": body.item_name, "m": body.material_text, "q": body.quantity, "u": body.unit, "d": body.need_date, "by": user},
            )
        ).mappings().one()
        if body.sync_mock:
            await conn.execute(
                text(
                    "INSERT INTO mock_partner.rfqs (number, status, quantity, unit, item_name, material_text) VALUES (:n, 'sent', :q, :u, :i, :m) "
                    "ON CONFLICT (number) DO UPDATE SET quantity=EXCLUDED.quantity, unit=EXCLUDED.unit, item_name=EXCLUDED.item_name, material_text=EXCLUDED.material_text"
                ),
                {"n": body.rfq_number, "q": body.quantity, "u": "套" if body.unit == "sets" else "件", "i": body.item_name, "m": body.material_text},
            )
        return _plain(dict(row))


@router.get("/rfqs/{rfq_id}")
async def get_rfq(rfq_id: int) -> dict:
    async with db.tx() as conn:
        rfq = await _rfq(conn, rfq_id)
        quotes = [dict(r) for r in (await conn.execute(text("SELECT * FROM rfq.quotes WHERE rfq_id=:id ORDER BY id DESC"), {"id": rfq_id})).mappings()]
        out = []
        for q in quotes:
            v = _quote_view(rfq, q, await _items(conn, q["id"]))
            d = (await conn.execute(text("SELECT id, status, attempt_count, last_http_status, last_error_code, created_at, updated_at FROM rfq.quote_dispatches WHERE quote_id=:id ORDER BY id DESC LIMIT 1"), {"id": q["id"]})).mappings().first()
            v["latest_dispatch"] = _plain(dict(d)) if d else None
            out.append(v)
        mock = (await conn.execute(text("SELECT number FROM mock_partner.rfqs WHERE number=:n"), {"n": rfq["rfq_number"]})).scalar()
        mails = [
            _plain(dict(m))
            for m in (
                await conn.execute(
                    text("SELECT id, subject, from_addr, reply_to, received_at, status, error, attachments FROM rfq.inbound_messages WHERE rfq_number=:n ORDER BY received_at DESC LIMIT 20"),
                    {"n": rfq["rfq_number"]},
                )
            ).mappings()
        ]
        latest = next((m for m in mails if m["id"] == rfq.get("last_message_id")), None)
        attachments = [{"n": i, "filename": a["filename"], "size": a.get("size", 0), "mime": a.get("mime")} for i, a in enumerate(latest["attachments"])] if latest else []
        for m in mails:
            m["attachment_count"] = len(m.pop("attachments") or [])
        spec = spec_fields.parse(rfq.get("spec_text"))
        return {"rfq": _plain(rfq), "quotes": out, "in_mock": bool(mock), "attachments": attachments, "mails": mails, "spec_fields": spec["fields"], "dims": spec["dims"]}


@router.post("/rfqs/{rfq_id}/quotes", status_code=201)
async def create_quote(rfq_id: int, body: QuoteIn, user: str = Depends(require_user)) -> dict:
    today = taipei_today()
    qd = body.quote_date or today
    vu = body.valid_until or (qd + timedelta(days=28))
    if vu < qd:
        raise HTTPException(400, "有效期不能早於報價日")
    async with db.tx() as conn:
        rfq = await _rfq(conn, rfq_id, lock=True)
        if rfq["status"] == "closed":
            raise HTTPException(409, "詢價單已結案")
        no = await _next_quote_no(conn, today)
        q = (
            await conn.execute(
                text(
                    "INSERT INTO rfq.quotes (rfq_id, quote_no, quote_revision, rfq_revision, quote_date, valid_until, tax_included, lead_basis, delivery_date, note, created_by) "
                    "VALUES (:r, :no, 1, :srev, :qd, :vu, :ti, :lb, :dd, :note, :by) RETURNING *"
                ),
                {"r": rfq_id, "no": no, "srev": rfq["spec_revision"], "qd": qd, "vu": vu, "ti": body.tax_included, "lb": body.lead_basis, "dd": body.delivery_date, "note": body.note.strip(), "by": user},
            )
        ).mappings().one()
        await conn.execute(
            text("INSERT INTO rfq.quote_items (quote_id, line_no, part, material, qty, unit, unit_price, lead_days) VALUES (:q, 1, :p, :m, :qty, :u, :up, :ld)"),
            {
                "q": q["id"],
                "p": body.part if body.part is not None else rfq["item_name"],
                "m": body.material if body.material is not None else rfq["material_text"],
                "qty": body.qty or rfq["quantity"],
                "u": body.unit or rfq["unit"],
                "up": body.unit_price,
                "ld": body.lead_days,
            },
        )
        await conn.execute(text("UPDATE rfq.rfqs SET status='quoting', updated_at=now() WHERE id=:id AND status='received'"), {"id": rfq_id})
        return _quote_view(rfq, dict(q), await _items(conn, q["id"]))


@router.get("/quotes/{quote_id}")
async def get_quote(quote_id: int) -> dict:
    async with db.tx() as conn:
        q = await _quote(conn, quote_id)
        rfq = await _rfq(conn, q["rfq_id"])
        items = await _items(conn, quote_id)
        view = _quote_view(rfq, q, items)
        try:
            view["payload_preview"] = pl.build_payload(rfq=rfq, quote=q, items=items, event_id="（送出時產生）", vendor_name=config.settings.vendor_name)
        except ValueError as e:
            view["payload_preview"] = None
            view["payload_error"] = str(e)
        dispatches = []
        for d in (await conn.execute(text("SELECT * FROM rfq.quote_dispatches WHERE quote_id=:id ORDER BY id DESC"), {"id": quote_id})).mappings():
            dd = _plain(dict(d))
            dd.pop("payload_text", None)
            dd["attempts"] = [_plain(dict(a)) for a in (await conn.execute(text("SELECT * FROM rfq.dispatch_attempts WHERE dispatch_id=:id ORDER BY attempt_no"), {"id": d["id"]})).mappings()]
            dispatches.append(dd)
        view["dispatches"] = dispatches
        revs = (await conn.execute(text("SELECT id, quote_revision, status FROM rfq.quotes WHERE quote_no=:no ORDER BY quote_revision"), {"no": q["quote_no"]})).mappings()
        view["revisions"] = [dict(r) for r in revs]
        view["mails"] = [_plain(dict(m)) for m in (await conn.execute(text("SELECT id, mode, to_addr, subject, status, error, attempt_count, created_at, sent_at FROM rfq.quote_mails WHERE quote_id=:id ORDER BY id DESC"), {"id": quote_id})).mappings()]
        from ..mail.reply import reply_mode

        view["reply_mode"] = reply_mode()
        view["has_source_mail"] = bool(rfq.get("last_message_id"))
        view["rfq"] = _plain(rfq)
        return view


async def _apply_patch(conn, quote_id: int, rfq: dict, base: dict, base_items: list[dict], p: QuotePatch, new_quote: bool, user: str) -> int:
    qd = p.quote_date or (taipei_today() if new_quote else base["quote_date"])
    vu = p.valid_until or (max(base["valid_until"], qd) if not new_quote else max(base["valid_until"], qd))
    if vu < qd:
        raise HTTPException(400, "有效期不能早於報價日")
    vals = {
        "qd": qd,
        "vu": vu,
        "ti": base["tax_included"] if p.tax_included is None else p.tax_included,
        "lb": p.lead_basis or base["lead_basis"],
        "dd": None if p.clear_delivery_date else (p.delivery_date or base["delivery_date"]),
        "note": base["note"] if p.note is None else p.note.strip(),
    }
    it = base_items[0]
    ivals = {
        "p": it["part"] if p.part is None else p.part,
        "m": it["material"] if p.material is None else p.material,
        "qty": p.qty or it["qty"],
        "u": p.unit or it["unit"],
        "up": p.unit_price or it["unit_price"],
        "ld": it["lead_days"] if p.lead_days is None else p.lead_days,
    }
    if new_quote:
        rev = (await conn.execute(text("SELECT max(quote_revision) FROM rfq.quotes WHERE quote_no=:no"), {"no": base["quote_no"]})).scalar_one() + 1
        qid = (
            await conn.execute(
                text(
                    "INSERT INTO rfq.quotes (rfq_id, quote_no, quote_revision, rfq_revision, quote_date, valid_until, tax_included, lead_basis, delivery_date, note, created_by) "
                    "VALUES (:r, :no, :rev, :srev, :qd, :vu, :ti, :lb, :dd, :note, :by) RETURNING id"
                ),
                {"r": base["rfq_id"], "no": base["quote_no"], "rev": rev, "srev": rfq["spec_revision"], "by": user, **vals},
            )
        ).scalar_one()
        await conn.execute(
            text("INSERT INTO rfq.quote_items (quote_id, line_no, part, material, qty, unit, unit_price, lead_days) VALUES (:q, 1, :p, :m, :qty, :u, :up, :ld)"),
            {"q": qid, **ivals},
        )
        return qid
    await conn.execute(
        text("UPDATE rfq.quotes SET quote_date=:qd, valid_until=:vu, tax_included=:ti, lead_basis=:lb, delivery_date=:dd, note=:note, rfq_revision=:srev, updated_at=now() WHERE id=:id"),
        {"id": quote_id, "srev": rfq["spec_revision"], **vals},
    )
    await conn.execute(
        text("UPDATE rfq.quote_items SET part=:p, material=:m, qty=:qty, unit=:u, unit_price=:up, lead_days=:ld WHERE quote_id=:q AND line_no=1"),
        {"q": quote_id, **ivals},
    )
    return quote_id


@router.put("/quotes/{quote_id}")
async def edit_draft(quote_id: int, body: QuotePatch, user: str = Depends(require_user)) -> dict:
    async with db.tx() as conn:
        q = await _quote(conn, quote_id, lock=True)
        if q["status"] != "draft":
            raise HTTPException(409, "只有草稿可以直接修改；已送出的請用「修訂」")
        rfq = await _rfq(conn, q["rfq_id"])
        await _apply_patch(conn, quote_id, rfq, q, await _items(conn, quote_id), body, False, user)
    return await get_quote(quote_id)


@router.post("/quotes/{quote_id}/revise", status_code=201)
async def revise(quote_id: int, body: QuotePatch, user: str = Depends(require_user)) -> dict:
    async with db.tx() as conn:
        q = await _quote(conn, quote_id, lock=True)
        latest = (await conn.execute(text("SELECT max(quote_revision) FROM rfq.quotes WHERE quote_no=:no"), {"no": q["quote_no"]})).scalar_one()
        if q["quote_revision"] != latest:
            raise HTTPException(409, "請從最新的版次修訂")
        draft = (await conn.execute(text("SELECT id FROM rfq.quotes WHERE quote_no=:no AND status='draft'"), {"no": q["quote_no"]})).scalar()
        if draft:
            raise HTTPException(409, {"code": "draft_exists", "message": "已經有尚未送出的版次", "id": draft})
        rfq = await _rfq(conn, q["rfq_id"])
        new_id = await _apply_patch(conn, quote_id, rfq, q, await _items(conn, quote_id), body, True, user)
    return await get_quote(new_id)


@router.post("/quotes/{quote_id}/send")
async def send_quote(quote_id: int, user: str = Depends(require_user)) -> dict:
    s = config.settings
    if not s.aud_quote_api_url:
        raise HTTPException(503, "AUD_QUOTE_API_URL 沒有設定")
    async with db.tx() as conn:
        q = await _quote(conn, quote_id, lock=True)
        if q["status"] not in ("draft", "failed"):
            raise HTTPException(409, f"這份報價目前是「{q['status']}」，不能再送")
        active = (
            await conn.execute(
                text("SELECT id FROM rfq.quote_dispatches WHERE quote_id=:id AND status NOT IN ('rejected','not_found','conflict','gave_up','blocked')"),
                {"id": quote_id},
            )
        ).scalar()
        if active:
            raise HTTPException(409, "這份報價已經在送出中或已送出")
        rfq = await _rfq(conn, q["rfq_id"])
        items = await _items(conn, quote_id)
        event_id = f"jl-{q['quote_no']}-r{q['quote_revision']}-{secrets.token_hex(4)}"
        try:
            payload = pl.build_payload(rfq=rfq, quote=q, items=items, event_id=event_id, vendor_name=s.vendor_name)
        except ValueError as e:
            raise HTTPException(400, {"code": str(e)})
        did = (
            await conn.execute(
                text(
                    "INSERT INTO rfq.quote_dispatches (quote_id, event_id, target_url, payload, payload_text, created_by) "
                    "VALUES (:q, :e, :u, CAST(:p AS jsonb), :pt, :by) RETURNING id"
                ),
                {"q": quote_id, "e": event_id, "u": s.aud_quote_api_url, "p": pl.payload_text(payload), "pt": pl.payload_text(payload), "by": user},
            )
        ).scalar_one()
        await conn.execute(text("UPDATE rfq.quotes SET status='sending', updated_at=now() WHERE id=:id"), {"id": quote_id})
    state = await enqueue(did)
    from ..mail.reply import send_quote_reply  # 避免循環匯入

    mail = await send_quote_reply(quote_id, user)
    return {"dispatch_id": did, "event_id": event_id, "enqueue": state, "mail": mail, "quote": await get_quote(quote_id)}


@router.get("/quotes/{quote_id}/pdf")
async def quote_pdf(quote_id: int) -> Response:
    from urllib.parse import quote as urlquote

    from ..mail.reply import load_quote_bundle
    from ..quote_pdf import build_quote_pdf, pdf_filename

    async with db.tx() as conn:
        try:
            rfq, q, items = await load_quote_bundle(conn, quote_id)
        except LookupError:
            raise HTTPException(404, "找不到報價")
    data = build_quote_pdf(rfq=rfq, quote=q, items=items, vendor_name=config.settings.vendor_name)
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f"inline; filename*=UTF-8''{urlquote(pdf_filename(q))}", "Cache-Control": "private, no-store"})


@router.post("/quotes/{quote_id}/mail")
async def resend_mail(quote_id: int, user: str = Depends(require_user)) -> dict:
    from ..mail.reply import send_quote_reply

    async with db.tx() as conn:
        q = await _quote(conn, quote_id)
    if q["status"] == "draft":
        raise HTTPException(409, "草稿還沒送出，不寄回信")
    return await send_quote_reply(quote_id, user, force=True)


@router.post("/dispatches/{dispatch_id}/requeue")
async def requeue(dispatch_id: int) -> dict:
    async with db.tx() as conn:
        d = (await conn.execute(text("SELECT * FROM rfq.quote_dispatches WHERE id=:id FOR UPDATE"), {"id": dispatch_id})).mappings().first()
        if not d:
            raise HTTPException(404, "找不到送出紀錄")
        if d["status"] in TERMINAL:
            raise HTTPException(409, f"這筆已經是「{d['status']}」，不需要重新排入")
        await conn.execute(text("UPDATE rfq.quote_dispatches SET next_attempt_at=now(), updated_at=now() WHERE id=:id"), {"id": dispatch_id})
    state = await enqueue(dispatch_id, key=f"requeue-{int(time.time())}")
    return {"dispatch_id": dispatch_id, "enqueue": state}


@router.post("/dispatches/sweep")
async def sweep_due() -> dict:
    """人員介面在有送出中的報價時呼叫：把到期該重送的處理掉（佇列沒推送時的備援）。"""
    return {"processed": await sweep(limit=10)}
