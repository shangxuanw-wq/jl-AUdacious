"""權限與白名單。"""

import pytest

from rfq_app import access, auth, config

pytestmark = pytest.mark.anyio


def test_parse_target():
    assert access.parse_target(" Someone@Example.COM ") == ("email", "someone@example.com")
    assert access.parse_target("@jauhlirn.com") == ("domain", "jauhlirn.com")
    assert access.parse_target("audaciousedu.org") == ("domain", "audaciousedu.org")
    for bad in ("@gmail.com", "gmail.com", "not an email", "a@b", "@", "x@@y.com"):
        with pytest.raises(ValueError):
            access.parse_target(bad)


def as_google(monkeypatch, email):
    """把登入者換成某個 Google 帳號（角色照名單判斷）。"""
    monkeypatch.setattr(auth, "_session_email", lambda request: (email, "google"))


async def add(client, target, role, **kw):
    r = await client.post("/api/admin/access", json={"target": target, "role": role, **kw})
    assert r.status_code == 201, r.text
    return r.json()


async def test_resolve_order(client, monkeypatch):
    monkeypatch.setattr(config, "settings", config.Settings(**{**config.settings.__dict__, "allowed_emails": frozenset({"boss@jauhlirn.com"})}))
    await add(client, "@jauhlirn.com", "member")
    blocked = await add(client, "bad@jauhlirn.com", "viewer")
    await add(client, "partner@gmail.com", "viewer")
    assert await access.resolve("boss@jauhlirn.com") == ("admin", "env")
    assert await access.resolve("amy@jauhlirn.com") == ("member", "domain")
    assert await access.resolve("partner@gmail.com") == ("viewer", "email")
    assert await access.resolve("other@gmail.com") == (None, None)
    assert await access.resolve("bad@jauhlirn.com") == ("viewer", "email")
    assert (await client.patch(f"/api/admin/access/{blocked['id']}", json={"active": False})).status_code == 200
    assert await access.resolve("bad@jauhlirn.com") == (None, None)  # email 規則停用 = 擋下，網域開放也進不來
    r = await client.post("/api/admin/access", json={"target": "@jauhlirn.com", "role": "viewer"})
    assert r.status_code == 409
    r = await client.post("/api/admin/access", json={"target": "@gmail.com", "role": "viewer"})
    assert r.status_code == 400


async def test_roles_enforced(client, monkeypatch):
    await add(client, "viewer@x-corp.com", "viewer")
    await add(client, "member@x-corp.com", "member")
    await add(client, "admin@x-corp.com", "admin")

    as_google(monkeypatch, "viewer@x-corp.com")
    me = (await client.get("/api/auth/me")).json()
    assert me["role"] == "viewer"
    assert (await client.get("/api/rfqs")).status_code == 200
    assert (await client.post("/api/rfqs/1/quotes", json={})).status_code == 403
    assert (await client.post("/api/gmail/poll")).status_code == 403
    assert (await client.get("/api/admin/access")).status_code == 403

    as_google(monkeypatch, "member@x-corp.com")
    assert (await client.get("/api/admin/access")).status_code == 403
    assert (await client.post("/api/gmail/disconnect")).status_code == 403
    assert (await client.post("/api/rfqs/999/quotes", json={"unit_price": "1", "lead_days": 1})).status_code == 404  # 過了權限檢查

    as_google(monkeypatch, "stranger@x-corp.com")
    assert (await client.get("/api/rfqs")).status_code == 401
    assert (await client.get("/api/auth/me")).json()["email"] is None

    as_google(monkeypatch, "admin@x-corp.com")
    j = (await client.get("/api/admin/access")).json()
    assert {r["value"] for r in j["rules"]} == {"viewer@x-corp.com", "member@x-corp.com", "admin@x-corp.com"}


async def test_admin_cannot_lock_self_out(client, monkeypatch):
    rule = await add(client, "admin@x-corp.com", "admin")
    as_google(monkeypatch, "admin@x-corp.com")
    r = await client.patch(f"/api/admin/access/{rule['id']}", json={"role": "member"})
    assert r.status_code == 409
    assert (await client.delete(f"/api/admin/access/{rule['id']}")).status_code == 409
    assert (await client.patch(f"/api/admin/access/{rule['id']}", json={"active": False})).status_code == 409
    access.invalidate()
    assert await access.resolve("admin@x-corp.com") == ("admin", "email")
    # 有網域管理員規則撐著時，可以把自己的個別規則刪掉
    await add(client, "@x-corp.com", "admin")
    assert (await client.delete(f"/api/admin/access/{rule['id']}")).status_code == 200
