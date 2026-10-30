"""登入：Google＋白名單；Google 還沒設定好之前，可以用臨時金鑰（APP_ACCESS_KEY）登入。

Session 存在簽章 cookie（SESSION_SECRET）。
"""

from __future__ import annotations

import asyncio
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from fastapi.responses import RedirectResponse

from . import access, config

router = APIRouter(prefix="/api/auth")

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"


def _redirect_uri() -> str:
    return config.settings.app_base_url + "/api/auth/callback"


def _session_email(request: Request) -> tuple[str | None, str | None]:
    """session 裡的登入者 (email, via)；金鑰換掉或拿掉後舊的金鑰登入就失效。"""
    s = config.settings
    if s.dev_login_email:
        return s.dev_login_email, "dev"
    email = request.session.get("email")
    if not email:
        return None, None
    if request.session.get("via") == "key":
        if s.key_login_configured and secrets.compare_digest(request.session.get("kf", ""), key_fingerprint(s.access_key)):
            return email, "key"
        return None, None
    return email, "google"


async def current_user(request: Request) -> dict | None:
    """{"email", "role"}；不在白名單（或被停用）回 None。"""
    cached = getattr(request.state, "user", None)
    if cached is not None:
        return cached or None
    email, via = _session_email(request)
    user = None
    if email:
        if via == "dev":
            role = config.settings.dev_login_role if config.settings.dev_login_role in access.ROLES else "admin"
        elif via == "key":
            role = "member"
        else:
            role, _ = await access.resolve(email)
        if role:
            user = {"email": email, "role": role, "via": via}
    request.state.user = user or False
    return user


def key_fingerprint(key: str) -> str:
    import hashlib

    return hashlib.sha256(("rfq-key:" + key).encode()).hexdigest()[:16]


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


async def require_user(request: Request) -> str:
    user = await current_user(request)
    if not user:
        raise HTTPException(401, "請先登入")
    if user["role"] == "viewer" and request.method not in SAFE_METHODS:
        raise HTTPException(403, "唯讀帳號不能修改")
    return user["email"]


async def require_admin(request: Request) -> str:
    email = await require_user(request)
    if request.state.user["role"] != "admin":
        raise HTTPException(403, "只有管理員可以使用")
    return email


@router.get("/me")
async def me(request: Request) -> dict:
    s = config.settings
    user = await current_user(request)
    return {
        "email": user["email"] if user else None,
        "role": user["role"] if user else None,
        "name": request.session.get("name", "") if user else "",
        "login_configured": s.google_login_configured or s.key_login_configured,
        "google_login": s.google_login_configured,
        "key_login": s.key_login_configured,
    }


class KeyLogin(BaseModel):
    key: str = Field(min_length=1, max_length=200)
    name: str = Field(default="", max_length=40)


@router.post("/key")
async def key_login(request: Request, body: KeyLogin) -> dict:
    s = config.settings
    if not s.key_login_configured:
        raise HTTPException(404, "沒有開放金鑰登入")
    if not secrets.compare_digest(body.key.strip().encode(), s.access_key.encode()):
        await asyncio.sleep(1.0)  # 拖慢猜金鑰
        raise HTTPException(401, "金鑰不對")
    name = "".join(ch for ch in body.name.strip() if ch.isprintable())[:40] or "臨時登入"
    request.session.clear()
    request.session.update({"email": f"key:{name}", "via": "key", "kf": key_fingerprint(s.access_key)})
    return {"email": f"key:{name}"}


@router.get("/login")
async def login(request: Request) -> RedirectResponse:
    s = config.settings
    if not (s.login_client_id and s.login_client_secret and s.app_base_url):
        raise HTTPException(503, "Google 登入還沒設定（LOGIN_GOOGLE_CLIENT_ID／LOGIN_GOOGLE_CLIENT_SECRET）")
    state = secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    q = urlencode(
        {
            "client_id": s.login_client_id,
            "redirect_uri": _redirect_uri(),
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "prompt": "select_account",
        }
    )
    return RedirectResponse(f"{GOOGLE_AUTH}?{q}", status_code=302)


@router.get("/callback")
async def callback(request: Request, code: str = "", state: str = "", error: str = "") -> RedirectResponse:
    s = config.settings
    expected = request.session.pop("oauth_state", None)
    if error or not code or not expected or not secrets.compare_digest(state, expected):
        return RedirectResponse("/login?error=oauth", status_code=302)
    async with httpx.AsyncClient(timeout=15) as client:
        tok = await client.post(
            GOOGLE_TOKEN,
            data={
                "code": code,
                "client_id": s.login_client_id,
                "client_secret": s.login_client_secret,
                "redirect_uri": _redirect_uri(),
                "grant_type": "authorization_code",
            },
        )
        if tok.status_code != 200:
            return RedirectResponse("/login?error=token", status_code=302)
        access_token = tok.json().get("access_token")
        info = await client.get(GOOGLE_USERINFO, headers={"Authorization": f"Bearer {access_token}"})
    if info.status_code != 200:
        return RedirectResponse("/login?error=userinfo", status_code=302)
    data = info.json()
    email = str(data.get("email", "")).lower()
    role, via = (await access.resolve(email)) if data.get("email_verified") else (None, None)
    if not role:
        request.session.clear()
        return RedirectResponse("/login?error=not_allowed", status_code=302)
    name = str(data.get("name") or "")[:80]
    await access.record_login(email, name, role, via)
    request.session.clear()
    request.session.update({"email": email, "name": name})
    return RedirectResponse("/", status_code=302)


@router.post("/logout")
async def logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True}
