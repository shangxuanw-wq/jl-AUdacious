"""收詢價信：從連接的信箱撈新信 → 解析 → 建立或更新詢價單。

- 不改信箱內容（不加標籤、不標已讀）；用 inbound_messages 記錄處理過哪些信。
- 同一個詢價編號再寄一次：更新同一張單，以最新一封為準（Q12）。
- 已結案的單不動，只記錄。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from .. import config, db
from ..dispatcher import INTERNAL_MOCK
from . import gmail
from .parser import ParseError, parse_rfq_mail

log = logging.getLogger("rfq.mail")

QUERY = "subject:AUD-RFQ -from:me newer_than:30d"


def _sender_allowed(addr: str | None) -> bool:
    allow = config.settings.rfq_sender_allow
    if not allow:
        return True
    if not addr:
        return False
    domain = "@" + addr.split("@")[-1]
    return addr in allow or domain in allow


def _sync_mock() -> bool:
    url = config.settings.aud_quote_api_url
    return url == INTERNAL_MOCK or "/api/mock-aud/" in url


async def poll(limit: int = 25) -> dict:
    """處理所有連接的信箱。回傳摘要；授權失效等錯誤記在 mailboxes.last_error。"""
    async with db.tx() as conn:
        boxes = [dict(r) for r in (await conn.execute(text("SELECT * FROM rfq.mailboxes ORDER BY id"))).mappings()]
    out = {"mailboxes": len(boxes), "new": 0, "results": []}
    for box in boxes:
        try:
            res = await _poll_box(box, limit)
            out["new"] += len(res)
            out["results"].extend(res)
            async with db.tx() as conn:
                await conn.execute(text("UPDATE rfq.mailboxes SET last_poll_at=now(), last_poll_ok_at=now(), last_error=NULL WHERE id=:id"), {"id": box["id"]})
        except Exception as e:  # noqa: BLE001 - 記下來，下次再試
            code = f"auth:{e}" if isinstance(e, gmail.MailAuthError) else type(e).__name__
            log.warning("mail poll failed for mailbox %s: %s", box["id"], code)
            async with db.tx() as conn:
                await conn.execute(text("UPDATE rfq.mailboxes SET last_poll_at=now(), last_error=:e WHERE id=:id"), {"e": code[:300], "id": box["id"]})
            out["results"].append({"mailbox": box["email"], "error": code})
    return out


async def _poll_box(box: dict, limit: int) -> list[dict]:
    token = await gmail.access_token(gmail.decrypt(box["refresh_token_enc"]))
    ids = await gmail.list_message_ids(token, QUERY, limit)
    if not ids:
        return []
    async with db.tx() as conn:
        known = set(
            (await conn.execute(text("SELECT gmail_id FROM rfq.inbound_messages WHERE mailbox_id=:m AND gmail_id = ANY(:ids)"), {"m": box["id"], "ids": ids})).scalars()
        )
    msgs = [await gmail.get_message(token, i) for i in ids if i not in known]
    msgs.sort(key=lambda m: int(m.get("internalDate", 0)))  # 舊的先處理，最新一封最後蓋過
    return [await _handle(box, m) for m in msgs]


async def _handle(box: dict, msg: dict) -> dict:
    subject = gmail.header(msg, "Subject") or ""
    from_addr = gmail.address(gmail.header(msg, "From"))
    reply_to = gmail.address(gmail.header(msg, "Reply-To")) or from_addr
    received = datetime.fromtimestamp(int(msg.get("internalDate", 0)) / 1000, tz=timezone.utc)
    base = {
        "m": box["id"],
        "gid": msg["id"],
        "tid": msg.get("threadId"),
        "mid": gmail.header(msg, "Message-ID"),
        "subj": subject[:500],
        "from": from_addr,
        "rt": reply_to,
        "at": received,
        "att": json.dumps(gmail.attachments(msg), ensure_ascii=False),
    }
    status, error, number, rfq_id = "error", None, None, None
    parsed = None
    if from_addr == box["email"]:
        status, error = "ignored", "own_message"
    elif not _sender_allowed(from_addr):
        status, error = "ignored", "sender_not_allowed"
    else:
        try:
            parsed = parse_rfq_mail(subject, gmail.plain_text(msg))
            number = parsed.rfq_number
        except ParseError as e:
            status, error = "error", e.code

    async with db.tx() as conn:
        inbound_id = (
            await conn.execute(
                text(
                    "INSERT INTO rfq.inbound_messages (mailbox_id, gmail_id, thread_id, message_id_header, subject, from_addr, reply_to, received_at, rfq_number, status, error, attachments, spec_revision, is_test) "
                    "VALUES (:m, :gid, :tid, :mid, :subj, :from, :rt, :at, :num, :st, :err, CAST(:att AS jsonb), :srev, :test) "
                    "ON CONFLICT (mailbox_id, gmail_id) DO NOTHING RETURNING id"
                ),
                {**base, "num": number, "st": status, "err": error, "srev": parsed.spec_revision if parsed else None, "test": bool(parsed and parsed.is_test)},
            )
        ).scalar()
        if inbound_id is None:  # 另一個執行同時處理了
            return {"gmail_id": msg["id"], "status": "skipped"}
        if parsed is not None:
            status, error, rfq_id = await _upsert_rfq(conn, parsed, inbound_id, reply_to, received)
            if status in ("created", "updated"):
                error = ",".join([*([error] if error else []), *parsed.warnings]) or None
            await conn.execute(
                text("UPDATE rfq.inbound_messages SET status=:st, error=:err, rfq_id=:r WHERE id=:id"),
                {"st": status, "err": error, "r": rfq_id, "id": inbound_id},
            )
    log.info("mail %s -> %s %s (%s)", msg["id"], status, number, error)
    return {"gmail_id": msg["id"], "rfq_number": number, "status": status, "error": error}


async def _upsert_rfq(conn, p, inbound_id: int, reply_to: str | None, received: datetime) -> tuple[str, str | None, int | None]:
    cust = (await conn.execute(text("SELECT id FROM rfq.customers WHERE code='AUD'"))).scalar_one()
    row = (
        await conn.execute(
            text(
                "SELECT r.id, r.status, r.spec_revision, m.received_at AS last_at FROM rfq.rfqs r LEFT JOIN rfq.inbound_messages m ON m.id = r.last_message_id "
                "WHERE r.customer_id=:c AND r.rfq_number=:n FOR UPDATE OF r"
            ),
            {"c": cust, "n": p.rfq_number},
        )
    ).mappings().first()
    vals = {
        "i": p.item_name,
        "mt": p.material_text,
        "q": p.quantity,
        "u": p.unit,
        "nd": p.need_date,
        "ndt": p.need_date_text,
        "pn": p.project_name,
        "cn": p.contact_name,
        "ce": p.contact_email,
        "rt": reply_to,
        "sp": p.spec_text,
        "lm": inbound_id,
        "srev": p.spec_revision or 1,
        "test": p.is_test,
    }
    if row is None:
        rid = (
            await conn.execute(
                text(
                    "INSERT INTO rfq.rfqs (customer_id, rfq_number, item_name, material_text, quantity, unit, need_date, need_date_text, project_name, "
                    "contact_name, contact_email, reply_to, spec_text, last_message_id, mail_count, source, created_by, spec_revision, is_test) "
                    "VALUES (:c, :n, :i, :mt, :q, :u, :nd, :ndt, :pn, :cn, :ce, :rt, :sp, :lm, 1, 'email', 'mail', :srev, :test) RETURNING id"
                ),
                {"c": cust, "n": p.rfq_number, **vals},
            )
        ).scalar_one()
        status = "created"
        changed = False
    else:
        rid = row["id"]
        if row["status"] == "closed":
            return "ignored", "rfq_closed", rid
        cur = row["spec_revision"]
        vals["srev"] = p.spec_revision or cur  # 舊格式信件沒有規格版次：維持原值
        if p.spec_revision is not None and p.spec_revision < cur:
            await conn.execute(text("UPDATE rfq.rfqs SET mail_count = mail_count + 1 WHERE id=:id"), {"id": rid})
            return "ignored", "older_spec_revision", rid
        if p.spec_revision is None and row["last_at"] is not None and row["last_at"] > received:
            await conn.execute(text("UPDATE rfq.rfqs SET mail_count = mail_count + 1 WHERE id=:id"), {"id": rid})
            return "ignored", "older_than_latest", rid
        if p.spec_revision is not None and p.spec_revision == cur:
            # 同一份規格重寄：不用重新報價；只更新聯絡資訊與「最新一封」（回信用）
            await conn.execute(
                text("UPDATE rfq.rfqs SET contact_name=:cn, contact_email=:ce, reply_to=:rt, last_message_id=:lm, mail_count = mail_count + 1, updated_at=now() WHERE id=:id"),
                {"cn": p.contact_name, "ce": p.contact_email, "rt": reply_to, "lm": inbound_id, "id": rid},
            )
            return "updated", "same_spec_resent", rid
        await conn.execute(
            text(
                "UPDATE rfq.rfqs SET item_name=:i, material_text=:mt, quantity=:q, unit=:u, need_date=:nd, need_date_text=:ndt, project_name=:pn, "
                "contact_name=:cn, contact_email=:ce, reply_to=:rt, spec_text=:sp, last_message_id=:lm, mail_count = mail_count + 1, "
                "spec_revision=:srev, is_test=:test, spec_changed_at = CASE WHEN :srev > spec_revision THEN now() ELSE spec_changed_at END, updated_at=now() WHERE id=:id"
            ),
            {**vals, "id": rid},
        )
        status = "updated"
        changed = p.spec_revision is not None and p.spec_revision > cur
    if _sync_mock():
        await conn.execute(
            text(
                "INSERT INTO mock_partner.rfqs (number, status, quantity, unit, item_name, material_text, spec_revision, is_test) VALUES (:n, 'sent', :q, :u, :i, :m, :srev, :test) "
                "ON CONFLICT (number) DO UPDATE SET quantity=EXCLUDED.quantity, unit=EXCLUDED.unit, item_name=EXCLUDED.item_name, material_text=EXCLUDED.material_text, "
                "spec_revision=GREATEST(mock_partner.rfqs.spec_revision, EXCLUDED.spec_revision), is_test=EXCLUDED.is_test"
            ),
            {"n": p.rfq_number, "q": p.quantity, "u": "套" if p.unit == "sets" else "件", "i": p.item_name, "m": p.material_text, "srev": p.spec_revision or 1, "test": p.is_test},
        )
    return status, ("spec_revision_up" if changed else None), rid
