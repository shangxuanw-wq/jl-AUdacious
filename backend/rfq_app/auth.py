"""Google 登入＋白名單。Session 存在簽章 cookie（SESSION_SECRET）。"""

from __future__ import annotations

import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from . import config

router = APIRouter(prefix="/api/auth")

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"


def _redirect_uri() -> str:
    return config.settings.app_base_url + "/api/auth/callback"


def current_email(request: Request) -> str | None:
    s = config.settings
    if s.dev_login_email:
        return s.dev_login_email
    email = request.session.get("email")
    if email and email in s.allowed_emails:
        return email
    return None


def require_user(request: Request) -> str:
    email = current_email(request)
    if not email:
        raise HTTPException(401, "請先登入")
    return email


@router.get("/me")
async def me(request: Request) -> dict:
    s = config.settings
    return {
        "email": current_email(request),
        "login_configured": bool(s.google_client_id and s.google_client_secret and s.session_secret and s.allowed_emails),
    }


@router.get("/login")
async def login(request: Request) -> RedirectResponse:
    s = config.settings
    if not (s.google_client_id and s.google_client_secret and s.app_base_url):
        raise HTTPException(503, "Google 登入還沒設定（GOOGLE_CLIENT_ID／GOOGLE_CLIENT_SECRET）")
    state = secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    q = urlencode(
        {
            "client_id": s.google_client_id,
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
                "client_id": s.google_client_id,
                "client_secret": s.google_client_secret,
                "redirect_uri": _redirect_uri(),
                "grant_type": "authorization_code",
            },
        )
        if tok.status_code != 200:
            return RedirectResponse("/login?error=token", status_code=302)
        access = tok.json().get("access_token")
        info = await client.get(GOOGLE_USERINFO, headers={"Authorization": f"Bearer {access}"})
    if info.status_code != 200:
        return RedirectResponse("/login?error=userinfo", status_code=302)
    data = info.json()
    email = str(data.get("email", "")).lower()
    if not data.get("email_verified") or email not in s.allowed_emails:
        request.session.clear()
        return RedirectResponse("/login?error=not_allowed", status_code=302)
    request.session.clear()
    request.session["email"] = email
    return RedirectResponse("/", status_code=302)


@router.post("/logout")
async def logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True}
