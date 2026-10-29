"""Gmail API（只用 REST，不裝 Google SDK）＋ refresh token 加密。"""

from __future__ import annotations

import base64
import os
import time
from typing import Any, Callable

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .. import config

TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://gmail.googleapis.com/gmail/v1/users/me"
SCOPES = "openid email https://www.googleapis.com/auth/gmail.modify"

# 測試可以換掉
client_factory: Callable[[], httpx.AsyncClient] = lambda: httpx.AsyncClient(timeout=20)

_token_cache: dict[str, tuple[str, float]] = {}


class MailAuthError(RuntimeError):
    """授權失效（被撤銷、密碼改了…）：要重新連接信箱。"""


# ---------------------------------------------------------------------------
# refresh token 加密
# ---------------------------------------------------------------------------


def _key() -> bytes:
    raw = config.settings.mail_token_key
    try:
        key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("MAIL_TOKEN_KEY 格式不對") from e
    if len(key) != 32:
        raise RuntimeError("MAIL_TOKEN_KEY 要是 32 bytes（base64）")
    return key


def encrypt(plain: str) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(_key()).encrypt(nonce, plain.encode(), b"rfq-mailbox")
    return "v1:" + base64.urlsafe_b64encode(nonce + ct).decode()


def decrypt(blob: str) -> str:
    if not blob.startswith("v1:"):
        raise RuntimeError("unknown token format")
    raw = base64.urlsafe_b64decode(blob[3:])
    return AESGCM(_key()).decrypt(raw[:12], raw[12:], b"rfq-mailbox").decode()


# ---------------------------------------------------------------------------
# OAuth
# ---------------------------------------------------------------------------


async def exchange_code(code: str, redirect_uri: str) -> dict:
    s = config.settings
    async with client_factory() as c:
        r = await c.post(
            TOKEN_URL,
            data={"code": code, "client_id": s.google_client_id, "client_secret": s.google_client_secret, "redirect_uri": redirect_uri, "grant_type": "authorization_code"},
        )
    if r.status_code != 200:
        raise MailAuthError(f"token_exchange_{r.status_code}")
    return r.json()


async def access_token(refresh_token: str) -> str:
    cached = _token_cache.get(refresh_token)
    if cached and cached[1] > time.time() + 60:
        return cached[0]
    s = config.settings
    async with client_factory() as c:
        r = await c.post(
            TOKEN_URL,
            data={"client_id": s.google_client_id, "client_secret": s.google_client_secret, "refresh_token": refresh_token, "grant_type": "refresh_token"},
        )
    if r.status_code in (400, 401):
        _token_cache.pop(refresh_token, None)
        raise MailAuthError((r.json() if r.headers.get("content-type", "").startswith("application/json") else {}).get("error", f"http_{r.status_code}"))
    r.raise_for_status()
    j = r.json()
    _token_cache[refresh_token] = (j["access_token"], time.time() + int(j.get("expires_in", 3600)))
    return j["access_token"]


async def revoke(refresh_token: str) -> None:
    try:
        async with client_factory() as c:
            await c.post(REVOKE_URL, data={"token": refresh_token})
    except httpx.HTTPError:
        pass
    _token_cache.pop(refresh_token, None)


# ---------------------------------------------------------------------------
# Gmail
# ---------------------------------------------------------------------------


async def _get(token: str, path: str, params: dict | None = None) -> dict:
    async with client_factory() as c:
        r = await c.get(API + path, params=params, headers={"Authorization": f"Bearer {token}"})
    if r.status_code == 401:
        raise MailAuthError("access_token_rejected")
    r.raise_for_status()
    return r.json()


async def profile_email(token: str) -> str:
    return str((await _get(token, "/profile")).get("emailAddress", "")).lower()


async def list_message_ids(token: str, q: str, max_results: int = 25) -> list[str]:
    j = await _get(token, "/messages", {"q": q, "maxResults": max_results})
    return [m["id"] for m in j.get("messages", [])]


async def get_message(token: str, msg_id: str) -> dict:
    return await _get(token, f"/messages/{msg_id}", {"format": "full"})


async def get_attachment(token: str, msg_id: str, att_id: str) -> bytes:
    j = await _get(token, f"/messages/{msg_id}/attachments/{att_id}")
    return b64decode(j.get("data", ""))


# ---------------------------------------------------------------------------
# 訊息內容
# ---------------------------------------------------------------------------


def b64decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def header(msg: dict, name: str) -> str | None:
    for h in msg.get("payload", {}).get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value")
    return None


def _walk(part: dict):
    yield part
    for p in part.get("parts", []) or []:
        yield from _walk(p)


def _charset(part: dict) -> str:
    for h in part.get("headers", []) or []:
        if h.get("name", "").lower() == "content-type":
            for piece in h.get("value", "").split(";"):
                k, _, v = piece.strip().partition("=")
                if k.lower() == "charset" and v:
                    return v.strip('"')
    return "utf-8"


def plain_text(msg: dict) -> str:
    for p in _walk(msg.get("payload", {})):
        if p.get("mimeType") == "text/plain" and not p.get("filename") and p.get("body", {}).get("data"):
            raw = b64decode(p["body"]["data"])
            try:
                return raw.decode(_charset(p))
            except (LookupError, UnicodeDecodeError):
                return raw.decode("utf-8", errors="replace")
    return ""


def attachments(msg: dict) -> list[dict[str, Any]]:
    out = []
    for p in _walk(msg.get("payload", {})):
        body = p.get("body", {}) or {}
        if p.get("filename") and body.get("attachmentId"):
            out.append({"filename": p["filename"], "mime": p.get("mimeType") or "application/octet-stream", "size": body.get("size", 0), "attachment_id": body["attachmentId"]})
    return out


def address(value: str | None) -> str | None:
    if not value:
        return None
    from email.utils import parseaddr

    return parseaddr(value)[1].lower() or None
