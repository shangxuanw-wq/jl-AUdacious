"""成員與權限（只有管理員）。"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from .. import access, config, db
from ..auth import require_admin

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])

Role = Literal["admin", "member", "viewer"]


class RuleIn(BaseModel):
    target: str = Field(min_length=3, max_length=254)
    role: Role
    note: str = Field(default="", max_length=200)


class RulePatch(BaseModel):
    role: Role | None = None
    active: bool | None = None
    note: str | None = Field(default=None, max_length=200)


def _iso(row: dict) -> dict:
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items()}


@router.get("/access")
async def list_access() -> dict:
    async with db.tx() as conn:
        rules = [_iso(dict(r)) for r in (await conn.execute(text("SELECT * FROM rfq.access_rules ORDER BY kind DESC, value"))).mappings()]
        logins = [_iso(dict(r)) for r in (await conn.execute(text("SELECT * FROM rfq.user_logins ORDER BY last_login_at DESC LIMIT 100"))).mappings()]
    return {
        "rules": rules,
        "fixed_admins": sorted(config.settings.allowed_emails),
        "logins": logins,
        "roles": access.ROLE_LABEL,
    }


async def _guard_self(conn, request: Request) -> None:
    """改完之後自己還必須是管理員，不然整筆改動取消。"""
    user = request.state.user
    if user.get("via") != "google":
        return  # 開發／金鑰登入的角色不是從名單來的
    role, _ = await access.resolve(user["email"], conn=conn)
    if role != "admin":
        raise HTTPException(409, "這樣改你會失去管理員權限，已取消")


@router.post("/access", status_code=201)
async def add_rule(body: RuleIn, request: Request) -> dict:
    try:
        kind, value = access.parse_target(body.target)
    except ValueError as e:
        raise HTTPException(400, str(e))
    async with db.tx() as conn:
        dup = (await conn.execute(text("SELECT id FROM rfq.access_rules WHERE kind=:k AND value=:v"), {"k": kind, "v": value})).scalar()
        if dup:
            raise HTTPException(409, f"{'@' + value if kind == 'domain' else value} 已經在名單裡")
        row = (
            await conn.execute(
                text("INSERT INTO rfq.access_rules (kind, value, role, note, created_by) VALUES (:k, :v, :r, :n, :by) RETURNING *"),
                {"k": kind, "v": value, "r": body.role, "n": body.note.strip(), "by": request.state.user["email"]},
            )
        ).mappings().one()
        await _guard_self(conn, request)
    access.invalidate()
    return _iso(dict(row))


@router.patch("/access/{rule_id}")
async def update_rule(rule_id: int, body: RulePatch, request: Request) -> dict:
    sets, params = [], {"id": rule_id}
    for k in ("role", "active", "note"):
        v = getattr(body, k)
        if v is not None:
            sets.append(f"{k}=:{k}")
            params[k] = v.strip() if isinstance(v, str) else v
    if not sets:
        raise HTTPException(400, "沒有要改的欄位")
    async with db.tx() as conn:
        row = (await conn.execute(text(f"UPDATE rfq.access_rules SET {', '.join(sets)}, updated_at=now() WHERE id=:id RETURNING *"), params)).mappings().first()
        if not row:
            raise HTTPException(404, "找不到這筆")
        await _guard_self(conn, request)
    access.invalidate()
    return _iso(dict(row))


@router.delete("/access/{rule_id}")
async def delete_rule(rule_id: int, request: Request) -> dict:
    async with db.tx() as conn:
        row = (await conn.execute(text("DELETE FROM rfq.access_rules WHERE id=:id RETURNING id"), {"id": rule_id})).scalar()
        if not row:
            raise HTTPException(404, "找不到這筆")
        await _guard_self(conn, request)
    access.invalidate()
    return {"ok": True}
