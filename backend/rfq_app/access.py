"""權限與白名單（rfq.access_rules）。

角色由低到高：viewer 唯讀 < member 成員 < admin 管理員。
判斷順序：
1. 環境變數 ALLOWED_EMAILS 裡的帳號 → 一律管理員（不會被鎖在門外）
2. 有這個 email 的規則 → 規則啟用就用它的角色；停用 = 擋下（即使網域有開放）
3. 有這個網域的規則且啟用 → 用網域規則的角色
4. 其他 → 不能進
"""

from __future__ import annotations

import logging
import re
import time

from sqlalchemy import text

from . import config, db

log = logging.getLogger("rfq.access")

ROLES = ("viewer", "member", "admin")
ROLE_LABEL = {"admin": "管理員", "member": "成員", "viewer": "唯讀"}

# 免費信箱網域：開放整個網域等於誰都能進，一律不允許
PUBLIC_DOMAINS = frozenset(
    {
        "gmail.com", "googlemail.com", "yahoo.com", "yahoo.com.tw", "ymail.com", "hotmail.com", "hotmail.com.tw",
        "outlook.com", "live.com", "msn.com", "icloud.com", "me.com", "mac.com", "aol.com", "proton.me",
        "protonmail.com", "gmx.com", "mail.com", "yandex.com", "qq.com", "163.com", "126.com", "pchome.com.tw",
        "hinet.net", "msa.hinet.net", "seed.net.tw",
    }
)

_EMAIL = re.compile(r"^[a-z0-9._%+'-]+@([a-z0-9-]+(\.[a-z0-9-]+)+)$")
_DOMAIN = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")

_CACHE_TTL = 30.0
_cache: dict[str, tuple[str | None, str | None, float]] = {}


def rank(role: str | None) -> int:
    return ROLES.index(role) + 1 if role in ROLES else 0


def parse_target(raw: str) -> tuple[str, str]:
    """「someone@x.com」→ ("email", …)；「@x.com」或「x.com」→ ("domain", "x.com")。格式不對丟 ValueError。"""
    v = (raw or "").strip().lower()
    if v.startswith("@"):
        v = v[1:]
        kind = "domain"
    elif "@" in v:
        kind = "email"
    else:
        kind = "domain"
    if kind == "email":
        if not _EMAIL.match(v) or len(v) > 254:
            raise ValueError("email 格式不對")
        return "email", v
    if not _DOMAIN.match(v) or len(v) > 253:
        raise ValueError("網域格式不對（例如 @jauhlirn.com）")
    if v in PUBLIC_DOMAINS:
        raise ValueError(f"{v} 是公用信箱，不能整個網域開放，請改成一個一個 email 加")
    return "domain", v


def invalidate() -> None:
    _cache.clear()


async def resolve(email: str, conn=None) -> tuple[str | None, str | None]:
    """回傳 (角色, 來源)；來源 env／email／domain。不能進回 (None, None)。"""
    email = (email or "").lower()
    if not email or "@" not in email:
        return None, None
    if email in config.settings.allowed_emails:
        return "admin", "env"
    hit = _cache.get(email)
    if hit and hit[2] > time.monotonic() and conn is None:
        return hit[0], hit[1]
    domain = email.rsplit("@", 1)[1]

    async def _q(c):
        rows = (
            await c.execute(
                text("SELECT kind, role, active FROM rfq.access_rules WHERE (kind='email' AND value=:e) OR (kind='domain' AND value=:d)"),
                {"e": email, "d": domain},
            )
        ).mappings().all()
        by = {r["kind"]: r for r in rows}
        if "email" in by:
            return (by["email"]["role"], "email") if by["email"]["active"] else (None, None)
        if "domain" in by and by["domain"]["active"]:
            return by["domain"]["role"], "domain"
        return None, None

    if conn is not None:
        return await _q(conn)
    async with db.tx() as c:
        role, via = await _q(c)
    _cache[email] = (role, via, time.monotonic() + _CACHE_TTL)
    return role, via


async def record_login(email: str, name: str, role: str, via: str) -> None:
    """記錄登入（失敗不影響登入）。"""
    try:
        await _record_login(email, name, role, via)
    except Exception as e:  # noqa: BLE001
        log.warning("record_login failed: %s", type(e).__name__)


async def _record_login(email: str, name: str, role: str, via: str) -> None:
    async with db.tx() as conn:
        await conn.execute(
            text(
                "INSERT INTO rfq.user_logins (email, name, role, via) VALUES (:e, :n, :r, :v) "
                "ON CONFLICT (email) DO UPDATE SET name=EXCLUDED.name, role=EXCLUDED.role, via=EXCLUDED.via, "
                "last_login_at=now(), login_count=rfq.user_logins.login_count+1"
            ),
            {"e": email, "n": name[:80], "r": role, "v": via},
        )
