"""報價回信：在原詢價信的信串回覆，附報價單 PDF（契約 2026-10-29.5 第 4.9 節）。

寄給誰（RFQ_MAIL_REPLY）：
- live：寄給承辦人（Reply-To）。送出目標是澳得仕正式站時的預設。
- self：只寄給我方信箱（同一個信串），開發期預設；不會寄到澳得仕。
- off：不寄。
"""

from __future__ import annotations

import base64
import logging
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

import httpx
from sqlalchemy import text

from .. import config, db
from .. import payload as pl
from ..quote_pdf import build_quote_pdf, pdf_filename
from . import gmail

log = logging.getLogger("rfq.reply")


def reply_mode() -> str:
    s = config.settings
    if s.mail_reply_mode in ("live", "self", "off"):
        return s.mail_reply_mode
    return "live" if s.target_is_partner_prod else "self"


async def load_quote_bundle(conn, quote_id: int) -> tuple[dict, dict, list[dict]]:
    q = (await conn.execute(text("SELECT * FROM rfq.quotes WHERE id=:id"), {"id": quote_id})).mappings().first()
    if not q:
        raise LookupError("quote_not_found")
    r = (await conn.execute(text("SELECT * FROM rfq.rfqs WHERE id=:id"), {"id": q["rfq_id"]})).mappings().one()
    items = [dict(x) for x in (await conn.execute(text("SELECT * FROM rfq.quote_items WHERE quote_id=:id ORDER BY line_no"), {"id": quote_id})).mappings()]
    return dict(r), dict(q), items


def _body(rfq: dict, quote: dict, items: list[dict], vendor: str, mode: str) -> str:
    it = items[0]
    cur = quote["currency"].strip()
    t = pl.compute_totals(it["unit_price"], it["qty"], quote["tax_included"], quote["tax_rate"], cur)
    tax = t.tax_cents or 0

    def money(c: int) -> str:
        v = pl.json_number(c)
        return f"{cur} {v:,.2f}" if isinstance(v, float) else f"{cur} {v:,}"

    unit = {"pcs": "件", "sets": "套"}.get(it["unit"], it["unit"])
    basis = "自收到 PO 起算" if quote["lead_basis"] == "po" else "自報價日起算"
    lines = []
    if mode == "self":
        lines += ["（開發期測試：這封只寄給我方信箱，沒有寄給澳得仕。）", ""]
    lines += [
        "您好：",
        "",
        f"附上詢價編號 {rfq['rfq_number']}（規格版次 {quote.get('rfq_revision') or rfq.get('spec_revision') or 1}）的報價單，",
        f"報價單號 {quote['quote_no']}，修訂 {quote['quote_revision']}。",
        "",
        f"單價：{money(pl.to_cents(it['unit_price']))}",
        f"數量：{int(it['qty']):,} {unit}",
    ]
    if quote["tax_included"]:
        lines.append(f"合計（含稅）：{money(t.total_cents)}")
    else:
        lines += [f"合計（未稅）：{money(t.total_cents)}", f"營業稅：{money(tax)}", f"含稅總額：{money(t.total_cents + tax)}"]
    lines += [
        f"交期：{int(it['lead_days'])} 個工作天（{basis}）",
        f"報價有效期限：{quote['valid_until'].isoformat()}",
    ]
    if quote.get("note"):
        lines += ["", f"備註：{quote['note']}"]
    lines += ["", "以報價單 PDF 為準；如有問題請直接回覆這封信。"]
    return "\n".join(lines)


def _sig_text(sig_html: str) -> str:
    """Gmail 簽名檔（HTML）→ 純文字版。"""
    import html as _html
    import re as _re

    t = _re.sub(r"(?i)<br\s*/?>|</(div|p|tr|li|h[1-6])>", "\n", sig_html)
    t = _re.sub(r"<[^>]+>", "", t)
    t = _html.unescape(t).replace("\xa0", " ")
    return "\n".join(line.rstrip() for line in t.splitlines()).strip()


def _html_body(text_body: str, sig_html: str | None, vendor: str) -> str:
    import html as _html

    paras = "<br>".join(_html.escape(line) for line in text_body.split("\n"))
    sig = f'<br><br><div class="gmail_signature">{sig_html}</div>' if sig_html else f"<br><br>{_html.escape(vendor)}"
    return f'<div dir="ltr" style="font-family:Arial,Helvetica,sans-serif;font-size:14px">{paras}{sig}</div>'


async def _send_raw(token: str, raw: bytes, thread_id: str | None) -> str:
    body = {"raw": base64.urlsafe_b64encode(raw).decode()}
    if thread_id:
        body["threadId"] = thread_id
    async with gmail.client_factory() as c:
        r = await c.post(gmail.API + "/messages/send", json=body, headers={"Authorization": f"Bearer {token}"})
    if r.status_code == 401:
        raise gmail.MailAuthError("access_token_rejected")
    r.raise_for_status()
    return r.json().get("id", "")


async def send_quote_reply(quote_id: int, user: str | None, force: bool = False) -> dict:
    """寄出報價回信。回傳 {status, mode, ...}；不丟例外（失敗記在 quote_mails）。"""
    mode = reply_mode()
    if mode == "off":
        return {"status": "skipped", "reason": "reply_off"}
    s = config.settings
    async with db.tx() as conn:
        rfq, quote, items = await load_quote_bundle(conn, quote_id)
        if not force:
            done = (await conn.execute(text("SELECT id FROM rfq.quote_mails WHERE quote_id=:q AND status='sent' AND mode=:m"), {"q": quote_id, "m": mode})).scalar()
            if done:
                return {"status": "skipped", "reason": "already_sent", "mail_id": done}
        src = None
        if rfq.get("last_message_id"):
            src = (
                await conn.execute(
                    text(
                        "SELECT m.thread_id, m.message_id_header, m.subject, b.email, b.refresh_token_enc FROM rfq.inbound_messages m "
                        "JOIN rfq.mailboxes b ON b.id = m.mailbox_id WHERE m.id=:id"
                    ),
                    {"id": rfq["last_message_id"]},
                )
            ).mappings().first()
        if not src:
            return {"status": "skipped", "reason": "no_source_mail"}
        to_addr = rfq.get("reply_to") if mode == "live" else src["email"]
        if not to_addr:
            return {"status": "skipped", "reason": "no_reply_to"}
        orig = src["subject"] or f"[詢價] {rfq['rfq_number']}"
        subject = orig if orig.lower().startswith("re:") else f"Re: {orig}"
        mail_id = (
            await conn.execute(
                text("INSERT INTO rfq.quote_mails (quote_id, mode, to_addr, subject, thread_id, created_by) VALUES (:q, :m, :to, :s, :t, :by) RETURNING id"),
                {"q": quote_id, "m": mode, "to": to_addr, "s": subject, "t": src["thread_id"], "by": user},
            )
        ).scalar_one()

    try:
        pdf = build_quote_pdf(rfq=rfq, quote=quote, items=items, vendor_name=s.vendor_name)
        msg = EmailMessage()
        msg["From"] = src["email"]
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=False)
        msg["Message-ID"] = make_msgid(domain=src["email"].split("@")[-1])
        if src["message_id_header"]:
            msg["In-Reply-To"] = src["message_id_header"]
            msg["References"] = src["message_id_header"]
        token = await gmail.access_token(gmail.decrypt(src["refresh_token_enc"]))
        sig_html = await gmail.signature_html(token, src["email"])
        text_body = _body(rfq, quote, items, s.vendor_name, mode)
        sig_text = _sig_text(sig_html) if sig_html else s.vendor_name
        msg.set_content(f"{text_body}\n\n--\n{sig_text}\n")
        msg.add_alternative(_html_body(text_body, sig_html, s.vendor_name), subtype="html")
        msg.add_attachment(pdf, maintype="application", subtype="pdf", filename=pdf_filename(quote))
        gid = await _send_raw(token, msg.as_bytes(), src["thread_id"])
        async with db.tx() as conn:
            await conn.execute(
                text("UPDATE rfq.quote_mails SET status='sent', gmail_message_id=:g, attempt_count=attempt_count+1, sent_at=now(), error=NULL WHERE id=:id"),
                {"g": gid, "id": mail_id},
            )
        log.info("quote %s reply sent (%s) to %s", quote_id, mode, to_addr)
        return {"status": "sent", "mode": mode, "to": to_addr, "mail_id": mail_id}
    except (gmail.MailAuthError, httpx.HTTPError, RuntimeError, ValueError) as e:
        code = f"auth:{e}" if isinstance(e, gmail.MailAuthError) else type(e).__name__
        async with db.tx() as conn:
            await conn.execute(text("UPDATE rfq.quote_mails SET status='failed', attempt_count=attempt_count+1, error=:e WHERE id=:id"), {"e": code[:300], "id": mail_id})
        log.warning("quote %s reply failed: %s", quote_id, code)
        return {"status": "failed", "mode": mode, "error": code, "mail_id": mail_id}
