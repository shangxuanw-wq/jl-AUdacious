"""連接信箱（Google OAuth，gmail.modify）、收信狀態、手動收信、附件下載。全部要登入。"""

from __future__ import annotations

import secrets
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import text

from .. import config, db
from ..auth import GOOGLE_AUTH, require_admin, require_user
from . import gmail, ingest

router = APIRouter(prefix="/api/gmail", dependencies=[Depends(require_user)])
files = APIRouter(prefix="/api", dependencies=[Depends(require_user)])


def _redirect_uri() -> str:
    return config.settings.app_base_url + "/api/gmail/callback"


def _check_configured() -> None:
    s = config.settings
    if not s.mail_configured:
        raise HTTPException(503, "信箱功能還沒設定（GOOGLE_CLIENT_ID／GOOGLE_CLIENT_SECRET／MAIL_TOKEN_KEY）")


@router.get("/connect", dependencies=[Depends(require_admin)])
async def connect(request: Request) -> RedirectResponse:
    _check_configured()
    state = secrets.token_urlsafe(24)
    request.session["gmail_state"] = state
    q = urlencode(
        {
            "client_id": config.settings.google_client_id,
            "redirect_uri": _redirect_uri(),
            "response_type": "code",
            "scope": gmail.SCOPES,
            "access_type": "offline",
            "prompt": "consent",
            "login_hint": config.settings.rfq_mailbox,
            "state": state,
        }
    )
    return RedirectResponse(f"{GOOGLE_AUTH}?{q}", status_code=302)


@router.get("/callback")
async def callback(request: Request, code: str = "", state: str = "", error: str = "", user: str = Depends(require_admin)) -> RedirectResponse:
    expected = request.session.pop("gmail_state", None)
    if error or not code or not expected or not secrets.compare_digest(state, expected):
        return RedirectResponse("/mail?error=oauth", status_code=302)
    try:
        tok = await gmail.exchange_code(code, _redirect_uri())
    except gmail.MailAuthError:
        return RedirectResponse("/mail?error=token", status_code=302)
    refresh = tok.get("refresh_token")
    if not refresh:
        return RedirectResponse("/mail?error=no_refresh_token", status_code=302)
    email = await gmail.profile_email(tok["access_token"])
    if email != config.settings.rfq_mailbox:
        await gmail.revoke(refresh)
        return RedirectResponse(f"/mail?error=wrong_mailbox&got={quote(email)}", status_code=302)
    async with db.tx() as conn:
        await conn.execute(
            text(
                "INSERT INTO rfq.mailboxes (email, refresh_token_enc, connected_by) VALUES (:e, :t, :by) "
                "ON CONFLICT (email) DO UPDATE SET refresh_token_enc=EXCLUDED.refresh_token_enc, connected_by=EXCLUDED.connected_by, connected_at=now(), last_error=NULL"
            ),
            {"e": email, "t": gmail.encrypt(refresh), "by": user},
        )
    return RedirectResponse("/mail?connected=1", status_code=302)


@router.get("/status")
async def status() -> dict:
    s = config.settings
    async with db.tx() as conn:
        boxes = [
            {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()}
            for r in (await conn.execute(text("SELECT id, email, connected_by, connected_at, last_poll_at, last_poll_ok_at, last_error FROM rfq.mailboxes ORDER BY id"))).mappings()
        ]
        msgs = [
            {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()}
            for r in (
                await conn.execute(
                    text(
                        "SELECT id, subject, from_addr, received_at, rfq_number, rfq_id, status, error, jsonb_array_length(attachments) AS attachment_count, created_at "
                        "FROM rfq.inbound_messages ORDER BY id DESC LIMIT 30"
                    )
                )
            ).mappings()
        ]
    return {
        "configured": s.mail_configured,
        "expected_mailbox": s.rfq_mailbox,
        "sender_allow": sorted(s.rfq_sender_allow),
        "query": ingest.QUERY,
        "mailboxes": boxes,
        "messages": msgs,
    }


@router.post("/poll")
async def poll_now() -> dict:
    _check_configured()
    return await ingest.poll()


@router.post("/disconnect", dependencies=[Depends(require_admin)])
async def disconnect() -> dict:
    async with db.tx() as conn:
        rows = (await conn.execute(text("DELETE FROM rfq.mailboxes RETURNING refresh_token_enc"))).scalars().all()
    for blob in rows:
        try:
            await gmail.revoke(gmail.decrypt(blob))
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True, "removed": len(rows)}


# 可以在瀏覽器裡直接顯示的格式（只開放圖片與 PDF；SVG/HTML 這類會跑程式的一律下載）
INLINE_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
    "bmp": "image/bmp",
    "pdf": "application/pdf",
}


def _ext(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


@files.get("/rfqs/{rfq_id}/attachments/{n}")
async def download_attachment(rfq_id: int, n: int, inline: bool = False) -> Response:
    async with db.tx() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT m.gmail_id, m.attachments, b.refresh_token_enc FROM rfq.rfqs r JOIN rfq.inbound_messages m ON m.id = r.last_message_id "
                    "JOIN rfq.mailboxes b ON b.id = m.mailbox_id WHERE r.id=:id"
                ),
                {"id": rfq_id},
            )
        ).mappings().first()
    if not row or not 0 <= n < len(row["attachments"]):
        raise HTTPException(404, "找不到附件")
    att = row["attachments"][n]
    try:
        token = await gmail.access_token(gmail.decrypt(row["refresh_token_enc"]))
        data = await gmail.get_attachment(token, row["gmail_id"], att["attachment_id"])
    except gmail.MailAuthError:
        raise HTTPException(503, "信箱授權失效，請到「信箱」重新連接")
    media = INLINE_TYPES.get(_ext(att["filename"])) if inline else None
    disposition = "inline" if media else "attachment"
    return Response(
        content=data,
        media_type=media or "application/octet-stream",
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(att['filename'])}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
