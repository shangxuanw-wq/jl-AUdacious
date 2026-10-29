import httpx
import pytest

from main import app
from rfq_app import config

pytestmark = pytest.mark.anyio

ACCESS_KEY = "access-key-0123456789-abcdefghij"
SELFTEST_KEY = "selftest-key-0123456789-abcdefgh"


@pytest.fixture
def key_login(monkeypatch):
    monkeypatch.setenv("RFQ_DEV_LOGIN_EMAIL", "")
    monkeypatch.setenv("APP_ACCESS_KEY", ACCESS_KEY)
    monkeypatch.setenv("SELFTEST_KEY", SELFTEST_KEY)
    config.reload_settings()
    yield
    monkeypatch.undo()
    config.reload_settings()


async def test_key_login_flow(client, key_login):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
        me = (await c.get("/api/auth/me")).json()
        assert me == {"email": None, "login_configured": True, "google_login": False, "key_login": True}
        assert (await c.get("/api/rfqs")).status_code == 401

        r = await c.post("/api/auth/key", json={"key": "wrong-key"})
        assert r.status_code == 401
        assert (await c.get("/api/rfqs")).status_code == 401

        r = await c.post("/api/auth/key", json={"key": ACCESS_KEY, "name": "Jimmy"})
        assert r.status_code == 200 and r.json()["email"] == "key:Jimmy"
        assert (await c.get("/api/rfqs")).status_code == 200

        # 換掉金鑰 → 舊登入失效
        import os

        os.environ["APP_ACCESS_KEY"] = "another-access-key-0123456789-xyz"
        config.reload_settings()
        assert (await c.get("/api/rfqs")).status_code == 401
        os.environ["APP_ACCESS_KEY"] = ACCESS_KEY
        config.reload_settings()

        await c.post("/api/auth/logout")
        assert (await c.get("/api/rfqs")).status_code == 401


async def test_key_login_disabled_when_short(client, monkeypatch):
    monkeypatch.setenv("RFQ_DEV_LOGIN_EMAIL", "")
    monkeypatch.setenv("APP_ACCESS_KEY", "short")
    config.reload_settings()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
            assert (await c.post("/api/auth/key", json={"key": "short"})).status_code == 404
            assert (await c.get("/api/auth/me")).json()["key_login"] is False
    finally:
        monkeypatch.undo()
        config.reload_settings()


async def test_selftest_requires_key(client, key_login):
    assert (await client.get("/api/selftest/run")).status_code == 404
    assert (await client.get("/api/selftest/run", params={"key": "nope"})).status_code == 404
    assert (await client.get("/api/selftest/status", params={"key": "nope", "quote_id": 1})).status_code == 404


async def test_selftest_happy(client, key_login):
    r = await client.get("/api/selftest/run", params={"key": SELFTEST_KEY, "scenario": "happy", "wait": 5})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True
    assert j["result"]["dispatch"]["status"] == "accepted"
    assert j["result"]["quote_status"] == "sent"
    assert j["result"]["dispatch"]["attempts"][0]["http"] == 202


async def test_selftest_retry(client, key_login):
    r = await client.get("/api/selftest/run", params={"key": SELFTEST_KEY, "scenario": "retry", "wait": 5})
    j = r.json()
    assert j["ok"] is True, j
    d = j["result"]["dispatch"]
    assert d["status"] == "retry_wait" and d["attempt_count"] == 1 and d["attempts"][0]["http"] == 503
    st = (await client.get("/api/selftest/status", params={"key": SELFTEST_KEY, "quote_id": j["result"]["quote_id"]})).json()
    assert st["dispatch"]["id"] == d["id"]


async def test_selftest_refuses_non_mock_target(client, key_login, monkeypatch):
    monkeypatch.setenv("AUD_QUOTE_API_URL", "https://audacious-3d-studio.vercel.app/api/rfq/quotes")
    config.reload_settings()
    r = await client.get("/api/selftest/run", params={"key": SELFTEST_KEY})
    assert r.status_code == 409


async def test_selftest_happy_internal_mock_duplicate(client, key_login, monkeypatch):
    monkeypatch.setenv("AUD_QUOTE_API_URL", "internal-mock")
    config.reload_settings()
    j = (await client.get("/api/selftest/run", params={"key": SELFTEST_KEY, "wait": 5})).json()
    assert j["ok"] is True, j
    dup = [s for s in j["steps"] if s["step"] == "duplicate_resend"]
    assert dup == [{"step": "duplicate_resend", "http": 200, "outcome": "duplicate"}]


async def test_sweep_processes_due_retry(client, key_login):
    from sqlalchemy import text

    from rfq_app import db

    j = (await client.get("/api/selftest/run", params={"key": SELFTEST_KEY, "scenario": "retry", "wait": 0})).json()
    d = j["result"]["dispatch"]
    assert d["status"] == "retry_wait"
    # 還沒到期：sweep 不動它
    st = (await client.get("/api/selftest/status", params={"key": SELFTEST_KEY, "quote_id": j["result"]["quote_id"], "sweep": True})).json()
    assert st["dispatch"]["status"] == "retry_wait" and st["dispatch"]["attempt_count"] == 1
    async with db.tx() as conn:
        await conn.execute(text("UPDATE rfq.quote_dispatches SET next_attempt_at = now() - interval '1 second' WHERE id=:id"), {"id": d["id"]})
    st = (await client.get("/api/selftest/status", params={"key": SELFTEST_KEY, "quote_id": j["result"]["quote_id"], "sweep": True})).json()
    assert st["dispatch"]["status"] == "accepted" and st["dispatch"]["attempt_count"] == 2
    assert st["quote_status"] == "sent"


async def test_cron_requires_secret(client, monkeypatch):
    assert (await client.get("/api/cron/sweep")).status_code == 404
    monkeypatch.setenv("CRON_SECRET", "cron-secret-0123456789")
    config.reload_settings()
    try:
        assert (await client.get("/api/cron/sweep", headers={"Authorization": "Bearer wrong"})).status_code == 404
        r = await client.get("/api/cron/sweep", headers={"Authorization": "Bearer cron-secret-0123456789"})
        assert r.status_code == 200 and r.json()["processed"] == []
    finally:
        monkeypatch.undo()
        config.reload_settings()


async def test_fake_queue_push_is_rejected(client):
    r = await client.post("/api/anything", headers={"ce-type": "com.vercel.queue.v2beta"}, content=b"{}")
    assert r.status_code == 500  # 沒有有效的推送標頭 → SDK 拒絕，不會處理任何送出紀錄
