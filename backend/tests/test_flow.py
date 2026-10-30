import asyncio
import json
import re
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import text

from conftest import BASE, TOKEN, app
from rfq_app import config, db, dispatcher
from rfq_app import payload as pl

pytestmark = pytest.mark.anyio

RFQ = "AUD-RFQ-2026-0099"


async def make_rfq(c, number=RFQ, sync=True, **kw):
    body = {"rfq_number": number, "item_name": f"工件 {number}-1", "material_text": "PLA", "quantity": 1, "unit": "pcs", "sync_mock": sync, **kw}
    r = await c.post("/api/rfqs", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def make_quote(c, rfq_id, **kw):
    body = {"unit_price": "350", "lead_days": 10, "valid_until": (date.today() + timedelta(days=60)).isoformat(), **kw}
    r = await c.post(f"/api/rfqs/{rfq_id}/quotes", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def dispatch_row(did):
    async with db.tx() as conn:
        return dict((await conn.execute(text("SELECT * FROM rfq.quote_dispatches WHERE id=:id"), {"id": did})).mappings().one())


async def mock_log():
    async with db.tx() as conn:
        return [dict(r) for r in (await conn.execute(text("SELECT * FROM mock_partner.request_log ORDER BY id"))).mappings()]


async def faults(c, *specs):
    r = await c.post("/api/mock-aud/_admin/faults", json={"next": list(specs)})
    assert r.status_code == 200


# --- 單號與金額 ---------------------------------------------------------------


def test_quote_no_format_and_hazard():
    assert pl.quote_no_for(date(2026, 10, 29), 1) == "AU26102901"
    d = date(2026, 1, 1)
    while d <= date(2035, 12, 31):
        for seq in (1, 99):
            assert not re.search(r"[TJRL]\d{6,}", pl.quote_no_for(d, seq), re.I)
        d += timedelta(days=1)
    with pytest.raises(ValueError):
        pl.quote_no_for(d, 100)


def test_tax_rounding():
    assert pl.compute_totals(Decimal("350"), 1, False, Decimal("0.05")).as_numbers() == {"subtotal": 350, "total": 350, "tax": 18}
    assert pl.compute_totals(Decimal("350"), 3, False, Decimal("0.05")).as_numbers()["tax"] == 53
    assert "tax" not in pl.compute_totals(Decimal("350"), 1, True, Decimal("0.05")).as_numbers()
    assert pl.compute_totals(Decimal("12.34"), 2, False, Decimal("0.05")).as_numbers()["subtotal"] == 24.68


async def test_quote_numbers_daily_sequence(client):
    rfq = await make_rfq(client)
    a = await make_quote(client, rfq["id"])
    b = await make_quote(client, rfq["id"])
    today = date.today()
    assert a["quote_no"][2:8] in (today.strftime("%y%m%d"), (today + timedelta(days=1)).strftime("%y%m%d"))
    assert int(b["quote_no"][-2:]) == int(a["quote_no"][-2:]) + 1


async def test_quote_no_exhausted(client):
    rfq = await make_rfq(client)
    from rfq_app.routers.rfqs import taipei_today

    async with db.tx() as conn:
        await conn.execute(text("INSERT INTO rfq.quote_no_counters (day, last_seq) VALUES (:d, 99)"), {"d": taipei_today()})
    r = await client.post(f"/api/rfqs/{rfq['id']}/quotes", json={"unit_price": "350", "lead_days": 10})
    assert r.status_code == 400 and "quote_no_exhausted" in r.text
    async with db.tx() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM rfq.quotes"))).scalar_one() == 0


async def test_payload_types_and_verbatim(client):
    rfq = await make_rfq(client, item_name="工件　AUD-RFQ-2026-0099-1（全形）", material_text="鋁 6061－T6")
    q = await make_quote(client, rfq["id"], note="測試")
    full = (await client.get(f"/api/quotes/{q['id']}")).json()
    p = full["payload_preview"]
    assert p["rfq"] == RFQ and p["items"][0]["part"] == "工件　AUD-RFQ-2026-0099-1（全形）" and p["items"][0]["material"] == "鋁 6061－T6"
    for k in ("unit_price", "subtotal", "qty", "lead_days"):
        assert not isinstance(p["items"][0][k], str)
    for k in ("total", "tax", "quote_revision"):
        assert not isinstance(p[k], str)
    assert p["rfq_revision"] == 1 and isinstance(p["rfq_revision"], int)
    contract_keys = {"rfq", "rfq_revision", "items", "total", "tax", "tax_included", "currency", "quote_no", "quote_revision", "event_id", "quote_date", "valid_until", "delivery_date", "lead_basis", "vendor", "note"}
    assert set(p) <= contract_keys
    assert set(p["items"][0]) <= {"qty", "unit_price", "lead_days", "subtotal", "unit", "part", "material"}


# --- 送出 -------------------------------------------------------------------


async def send(c, quote_id):
    r = await c.post(f"/api/quotes/{quote_id}/send")
    assert r.status_code == 200, r.text
    return r.json()


async def test_send_accepted(client):
    rfq = await make_rfq(client)
    q = await make_quote(client, rfq["id"])
    res = await send(client, q["id"])
    d = await dispatch_row(res["dispatch_id"])
    assert d["status"] == "accepted" and d["last_http_status"] == 202 and d["last_response"]["issues"] == []
    assert d["candidate_id"]
    quote = (await client.get(f"/api/quotes/{q['id']}")).json()
    assert quote["status"] == "sent"
    assert (await client.get(f"/api/rfqs/{rfq['id']}")).json()["rfq"]["status"] == "quoted"
    # 重送同一份（模擬逾時後重送）→ duplicate，candidate 相同
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as raw:
        r = await raw.post("/api/mock-aud/api/rfq/quotes", content=d["payload_text"].encode(), headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    assert r.status_code == 200 and r.json()["outcome"] == "duplicate" and r.json()["candidate_id"] == d["candidate_id"]
    # 已送出的不能再送
    assert (await client.post(f"/api/quotes/{q['id']}/send")).status_code == 409


async def test_retry_same_event_and_schedule(client):
    rfq = await make_rfq(client)
    q = await make_quote(client, rfq["id"])
    await faults(client, {"status": 503}, {"status": 503})
    res = await send(client, q["id"])
    did = res["dispatch_id"]
    d1 = await dispatch_row(did)
    assert d1["status"] == "retry_wait" and d1["attempt_count"] == 1
    t0 = dispatcher.utcnow()
    r = await dispatcher.process_dispatch(did, now=t0)  # 還沒到時間
    assert r.state == "not_due"
    r = await dispatcher.process_dispatch(did, now=d1["next_attempt_at"] + timedelta(seconds=1))
    assert r.state == "retry_wait" and r.retry_in == 5
    d2 = await dispatch_row(did)
    r = await dispatcher.process_dispatch(did, now=d2["next_attempt_at"] + timedelta(seconds=1))
    assert r.state == "accepted"
    d3 = await dispatch_row(did)
    assert d3["attempt_count"] == 3
    logs = [l for l in await mock_log() if l["event_id"] == d3["event_id"]]
    assert len(logs) == 3 and len({l["body"] for l in logs if l["body"]}) <= 1
    assert [l["status"] for l in logs] == [503, 503, 202]


def test_delays():
    assert [dispatcher.next_delay(n) for n in (1, 2, 3, 4, 5, 6, 7)] == [2, 5, 15, 60, 300, 1800, 1800]
    assert dispatcher.next_delay(1, 60) == 60 and dispatcher.next_delay(5, 60) == 300


def test_classify_contract_v5():
    c = dispatcher.classify
    assert c(503, {"code": "disabled"}, None).retry is False and c(503, {"code": "disabled"}, None).error_code == "endpoint_disabled"
    m = c(503, {"code": "maintenance"}, None, {"retry-after": "600"})
    assert m.retry and m.error_code == "maintenance" and m.min_delay == 600
    assert c(503, {"code": "maintenance"}, None).min_delay == 600
    assert c(502, {}, None).retry and c(502, {}, None).min_delay == 0
    assert c(429, {}, None, {"retry-after": "90"}).min_delay == 90 and c(429, {}, None).min_delay == 60
    assert c(409, {"code": "event_in_flight"}, None, {"retry-after": "5"}).min_delay == 5
    assert c(409, {"code": "send_pending"}, None).min_delay == 300
    for code in ("closed", "status", "no_snapshot", "rfq_revision_unknown", "event_conflict", "not_test_rfq"):
        assert c(409, {"code": code}, None).retry is False
    assert c(400, {"issues": [{"code": "too_long"}]}, None).error_code == "too_long"
    assert c(200, {"outcome": "duplicate", "status": "pending"}, None).status == "duplicate"


async def test_inline_short_retries(client, monkeypatch):
    monkeypatch.setattr(dispatcher, "RETRY_DELAYS", [0.01, 0.01, 0.01, 60, 300, 1800])
    monkeypatch.setenv("RFQ_INLINE_RETRY_SECONDS", "10")
    config.reload_settings()
    rfq = await make_rfq(client)
    q = await make_quote(client, rfq["id"])
    await faults(client, {"status": 503}, {"status": 502})
    res = await send(client, q["id"])
    d = await dispatch_row(res["dispatch_id"])
    assert d["status"] == "accepted" and d["attempt_count"] == 3
    # 長間隔（Retry-After 60）不在送出當下等
    q2 = await make_quote(client, rfq["id"])
    await faults(client, {"status": 429})
    d = await dispatch_row((await send(client, q2["id"]))["dispatch_id"])
    assert d["status"] == "retry_wait" and d["attempt_count"] == 1
    monkeypatch.undo()
    config.reload_settings()


async def test_gave_up_after_7(client):
    rfq = await make_rfq(client)
    q = await make_quote(client, rfq["id"])
    await faults(client, *[{"status": 503}] * 8)
    did = (await send(client, q["id"]))["dispatch_id"]
    for _ in range(8):
        d = await dispatch_row(did)
        await dispatcher.process_dispatch(did, now=d["next_attempt_at"] + timedelta(seconds=1))
    d = await dispatch_row(did)
    assert d["status"] == "gave_up" and d["attempt_count"] == 7
    assert (await client.get(f"/api/quotes/{q['id']}")).json()["status"] == "failed"


async def test_rate_limited_min_60(client):
    rfq = await make_rfq(client)
    q = await make_quote(client, rfq["id"])
    await faults(client, {"status": 429})
    did = (await send(client, q["id"]))["dispatch_id"]
    d = await dispatch_row(did)
    assert d["status"] == "retry_wait" and (d["next_attempt_at"] - d["updated_at"]).total_seconds() >= 55


async def test_timeout_then_success(client):
    rfq = await make_rfq(client)
    q = await make_quote(client, rfq["id"])
    calls = {"n": 0}
    real = dispatcher.client_factory

    def factory():
        calls["n"] += 1
        if calls["n"] == 1:
            def boom(request):
                raise httpx.ReadTimeout("slow", request=request)
            return httpx.AsyncClient(transport=httpx.MockTransport(boom))
        return real()

    dispatcher.client_factory = factory
    did = (await send(client, q["id"]))["dispatch_id"]
    d = await dispatch_row(did)
    assert d["status"] == "retry_wait" and d["last_error_code"] == "timeout"
    await dispatcher.process_dispatch(did, now=d["next_attempt_at"] + timedelta(seconds=1))
    d = await dispatch_row(did)
    assert d["status"] == "accepted" and d["attempt_count"] == 2


@pytest.mark.parametrize("number,status,code", [("AUD-RFQ-2026-0098", "conflict", "closed"), ("AUD-RFQ-2026-0096", "conflict", "status")])
async def test_non_retryable_409(client, number, status, code):
    rfq = await make_rfq(client, number=number, sync=False)
    q = await make_quote(client, rfq["id"])
    did = (await send(client, q["id"]))["dispatch_id"]
    d = await dispatch_row(did)
    assert d["status"] == status and d["last_error_code"] == code and d["attempt_count"] == 1
    r = await dispatcher.process_dispatch(did, now=dispatcher.utcnow() + timedelta(hours=1))
    assert r.retry_in is None


async def test_retryable_409(client):
    rfq = await make_rfq(client, number="AUD-RFQ-2026-0097", sync=False)
    q = await make_quote(client, rfq["id"])
    did = (await send(client, q["id"]))["dispatch_id"]
    d = await dispatch_row(did)
    assert d["status"] == "retry_wait" and d["last_error_code"] == "send_pending"


async def test_event_in_flight_fault(client):
    rfq = await make_rfq(client)
    q = await make_quote(client, rfq["id"])
    await faults(client, {"status": 409, "code": "event_in_flight"})
    did = (await send(client, q["id"]))["dispatch_id"]
    assert (await dispatch_row(did))["last_error_code"] == "event_in_flight"


async def test_not_found_and_wrong_token(client):
    rfq = await make_rfq(client, number="AUD-RFQ-2026-7777", sync=False)
    q = await make_quote(client, rfq["id"])
    did = (await send(client, q["id"]))["dispatch_id"]
    assert (await dispatch_row(did))["status"] == "not_found"
    rfq2 = await make_rfq(client, number="AUD-RFQ-2026-7778")
    q2 = await make_quote(client, rfq2["id"])
    config.settings = config.Settings(**{**config.settings.__dict__, "aud_quote_api_token": "wrong-token-wrong-token-wrong-x"})
    try:
        did2 = (await send(client, q2["id"]))["dispatch_id"]
        d = await dispatch_row(did2)
        assert d["status"] == "rejected" and d["last_http_status"] == 401
    finally:
        config.reload_settings()


async def test_revision_flow(client):
    rfq = await make_rfq(client)
    q1 = await make_quote(client, rfq["id"])
    d1 = await dispatch_row((await send(client, q1["id"]))["dispatch_id"])
    assert (await client.post(f"/api/mock-aud/_admin/rfqs/{RFQ}/candidates/{d1['candidate_id']}/publish")).status_code == 200
    r = await client.post(f"/api/quotes/{q1['id']}/revise", json={"lead_days": 8})
    assert r.status_code == 201, r.text
    q2 = r.json()
    assert q2["quote_no"] == q1["quote_no"] and q2["quote_revision"] == 2 and q2["status"] == "draft"
    d2 = await dispatch_row((await send(client, q2["id"]))["dispatch_id"])
    assert d2["status"] == "accepted" and d2["last_response"]["issues"] == []
    assert (await client.get(f"/api/quotes/{q1['id']}")).json()["status"] == "superseded"
    assert (await client.get(f"/api/quotes/{q2['id']}")).json()["status"] == "sent"


async def test_prod_guard(client):
    rfq = await make_rfq(client)
    q = await make_quote(client, rfq["id"])
    config.settings = config.Settings(**{**config.settings.__dict__, "aud_quote_api_url": "https://audacious-3d-studio.vercel.app/api/rfq/quotes"})
    seen = {"n": 0}

    def factory():
        def h(request):
            seen["n"] += 1
            return httpx.Response(202, json={})
        return httpx.AsyncClient(transport=httpx.MockTransport(h))

    dispatcher.client_factory = factory
    try:
        did = (await send(client, q["id"]))["dispatch_id"]
        d = await dispatch_row(did)
        assert d["status"] == "blocked" and d["last_error_code"] == "partner_prod_blocked" and seen["n"] == 0
    finally:
        config.reload_settings()


async def test_stale_sending_recovery(client):
    rfq = await make_rfq(client)
    q = await make_quote(client, rfq["id"])
    await faults(client, {"status": 503})
    did = (await send(client, q["id"]))["dispatch_id"]
    async with db.tx() as conn:
        await conn.execute(text("UPDATE rfq.quote_dispatches SET status='sending', sending_started_at=now() - interval '200 seconds' WHERE id=:id"), {"id": did})
    r = await dispatcher.process_dispatch(did)
    assert r.state == "accepted"
    d = await dispatch_row(did)
    logs = [l for l in await mock_log() if l["event_id"] == d["event_id"]]
    assert len(logs) == 2 and d["attempt_count"] == 2


async def test_concurrent_processing_sends_once(client):
    rfq = await make_rfq(client)
    q = await make_quote(client, rfq["id"])
    await faults(client, {"status": 503})
    did = (await send(client, q["id"]))["dispatch_id"]
    d = await dispatch_row(did)
    at = d["next_attempt_at"] + timedelta(seconds=1)
    await faults(client, {"delay": 1})  # 讓第一個請求慢一點，第二個一定撞上鎖或 sending
    res = await asyncio.gather(dispatcher.process_dispatch(did, now=at), dispatcher.process_dispatch(did, now=at))
    states = sorted(r.state for r in res)
    assert "accepted" in states and states.count("accepted") == 1
    logs = [l for l in await mock_log() if l["event_id"] == d["event_id"]]
    assert len(logs) == 2


async def test_requires_login(client):
    config.settings = config.Settings(**{**config.settings.__dict__, "dev_login_email": ""})
    try:
        assert (await client.get("/api/rfqs")).status_code == 401
        assert (await client.post("/api/mock-aud/_admin/reset")).status_code == 401
        assert (await client.get("/api/health")).status_code == 200
    finally:
        config.reload_settings()


async def test_token_not_leaked(client, caplog):
    rfq = await make_rfq(client)
    q = await make_quote(client, rfq["id"])
    caplog.set_level("DEBUG")
    res = await send(client, q["id"])
    full = (await client.get(f"/api/quotes/{q['id']}")).text
    assert TOKEN not in full and TOKEN not in caplog.text and TOKEN not in json.dumps(res)
    async with db.tx() as conn:
        rows = (await conn.execute(text("SELECT coalesce(string_agg(response_text, ''), '') FROM rfq.dispatch_attempts"))).scalar_one()
    assert TOKEN not in rows


# --- 假 API 本身 -----------------------------------------------------------------


async def test_mock_basic_errors(client):
    url = "/api/mock-aud/api/rfq/quotes"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as raw:
        assert (await raw.get(url)).json()["contract_version"] == "2026-10-29.5"
        assert (await raw.post(url, json={})).status_code == 401
        h = {"Authorization": f"Bearer {TOKEN}"}
        assert (await raw.post(url, content=b"{}", headers={**h, "Content-Type": "text/plain"})).status_code == 415
        r = await raw.post(url, json={"rfq": "RFQ-1"}, headers=h)
        assert r.status_code == 400 and r.json()["issues"][0]["code"] == "rfq_invalid"
        r = await raw.post(url, json={"rfq": "AUD-RFQ-0000-0000", "event_id": "a"}, headers={**h, "X-Event-Id": "b"})
        assert r.json()["issues"][0]["code"] == "event_id_mismatch"
        assert (await raw.post(url, json={"rfq": "AUD-RFQ-0000-0000", "items": [{"qty": 1, "unit_price": 1, "lead_days": 1}]}, headers=h)).status_code == 404
        big = '{"note":"' + "a" * 70000 + '"}'
        assert (await raw.post(url, content=big.encode(), headers={**h, "Content-Type": "application/json"})).status_code == 413
        r = await raw.post(url, json={"rfq": RFQ, "items": [{"qty": 1, "unit_price": "350", "lead_days": 1}]}, headers=h)
        assert r.status_code == 400 and r.json()["issues"][0]["code"] == "invalid_number"
        assert r.json()["contract_version"] == "2026-10-29.5" and r.json()["request_id"]


def _q(**kw):
    item = {"part": f"工件 {RFQ}-1", "material": "PLA", "qty": 1, "unit": "pcs", "unit_price": 350, "subtotal": 350, "lead_days": 10}
    item.update(kw.pop("item", {}))
    return {"rfq": RFQ, "rfq_revision": 1, "quote_no": "AU26102999", "quote_revision": 1, "tax_included": False, "items": [item], "total": 350, "tax": 18, **kw}


async def test_mock_contract_v5(client):
    url = "/api/mock-aud/api/rfq/quotes"
    h = {"Authorization": f"Bearer {TOKEN}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as raw:
        r = await raw.post(url, json=_q(event_id="v5-a"), headers=h)
        assert r.status_code == 202 and r.json()["spec_revision"] == 1
        # 不存在的規格版次
        r = await raw.post(url, json=_q(event_id="v5-b", rfq_revision=2), headers=h)
        assert r.status_code == 409 and r.json()["code"] == "rfq_revision_unknown"
        # rfq_revision 型別錯
        r = await raw.post(url, json=_q(event_id="v5-c", rfq_revision="1"), headers=h)
        assert r.status_code == 400
        # 超長：整筆拒收
        r = await raw.post(url, json=_q(event_id="v5-d", note="x" * 1001), headers=h)
        assert r.status_code == 400 and r.json()["issues"][0]["code"] == "too_long"
        r = await raw.post(url, json=_q(event_id="v5-e", item={"part": "p" * 121}), headers=h)
        assert r.status_code == 400 and r.json()["issues"][0]["code"] == "too_long"
        # 同修訂、note 不同 → revision_reused
        r = await raw.post(url, json=_q(event_id="v5-f", note="不含運費"), headers=h)
        assert r.status_code == 202 and any(i["code"] == "revision_reused" for i in r.json()["issues"])
        # 自我測試只能打測試單
        r = await raw.post(url, json=_q(event_id="v5-g", quote_revision=5), headers={**h, "X-Self-Test": "1"})
        assert r.status_code == 409 and r.json()["code"] == "not_test_rfq"
        assert (await client.patch(f"/api/mock-aud/_admin/rfqs/{RFQ}", json={"is_test": True, "spec_revision": 2})).status_code == 200
        r = await raw.post(url, json=_q(event_id="v5-h", quote_revision=6), headers={**h, "X-Self-Test": "1"})
        assert r.status_code == 202 and any(i["code"] == "spec_outdated" for i in r.json()["issues"])
        # 沒帶 rfq_revision、規格不只一版 → 收下但要人工指定
        body = _q(event_id="v5-i", quote_revision=7)
        body.pop("rfq_revision")
        r = await raw.post(url, json=body, headers=h)
        assert r.status_code == 202 and any(i["code"] == "spec_unbound" and i["level"] == "error" for i in r.json()["issues"])
        # 故障帶 Retry-After
        await faults(client, {"status": 503, "code": "maintenance", "retry_after": 600})
        r = await raw.post(url, json=_q(event_id="v5-j"), headers=h)
        assert r.status_code == 503 and r.headers["retry-after"] == "600"


async def test_dispatch_send_pending_waits_300(client):
    rfq = await make_rfq(client, number="AUD-RFQ-2026-0097", sync=False)
    q = await make_quote(client, rfq["id"])
    d = await dispatch_row((await send(client, q["id"]))["dispatch_id"])
    assert d["status"] == "retry_wait" and (d["next_attempt_at"] - d["updated_at"]).total_seconds() >= 295


async def test_dispatch_endpoint_disabled_no_retry(client):
    rfq = await make_rfq(client)
    q = await make_quote(client, rfq["id"])
    await faults(client, {"status": 503, "code": "disabled"})
    d = await dispatch_row((await send(client, q["id"]))["dispatch_id"])
    assert d["status"] == "rejected" and d["last_error_code"] == "endpoint_disabled"
    assert (await client.get(f"/api/quotes/{q['id']}")).json()["status"] == "failed"


async def test_internal_mock_target(client):
    config.settings = config.Settings(**{**config.settings.__dict__, "aud_quote_api_url": "internal-mock"})
    dispatcher.client_factory = lambda: (_ for _ in ()).throw(AssertionError("不該走外部 client"))
    try:
        rfq = await make_rfq(client)
        q = await make_quote(client, rfq["id"])
        did = (await send(client, q["id"]))["dispatch_id"]
        d = await dispatch_row(did)
        assert d["target_url"] == "internal-mock" and d["status"] == "accepted"
    finally:
        config.reload_settings()


def test_token_selection(monkeypatch):
    monkeypatch.setenv("AUD_QUOTE_API_TOKEN", "mock-token")
    monkeypatch.setenv("RFQ_WEBHOOK_TOKEN", "partner-token")
    s = config.reload_settings()
    assert s.token_for("https://audacious-3d-studio.vercel.app/api/rfq/quotes") == "partner-token"
    assert s.token_for("internal-mock") == "mock-token"
    assert s.token_for("http://testserver/api/mock-aud/api/rfq/quotes") == "mock-token"
    monkeypatch.undo()
    config.reload_settings()


async def test_prod_target_uses_partner_token(client, monkeypatch):
    seen = {}

    def handler(req):
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(202, json={"ok": True, "outcome": "pending_review", "candidate_id": "c", "candidate_revision": 1, "issues": []})

    monkeypatch.setenv("AUD_QUOTE_API_URL", "https://audacious-3d-studio.vercel.app/api/rfq/quotes")
    monkeypatch.setenv("RFQ_ALLOW_PARTNER_PROD", "true")
    monkeypatch.setenv("RFQ_WEBHOOK_TOKEN", "partner-token-xyz")
    config.reload_settings()
    real = dispatcher.client_factory
    dispatcher.client_factory = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        rfq = await make_rfq(client)
        q = await make_quote(client, rfq["id"])
        d = await dispatch_row((await send(client, q["id"]))["dispatch_id"])
        assert d["status"] == "accepted" and seen["auth"] == "Bearer partner-token-xyz"
    finally:
        dispatcher.client_factory = real
        monkeypatch.undo()
        config.reload_settings()


async def test_mock_can_be_switched_off(client, monkeypatch):
    monkeypatch.setenv("MOCK_AUD_ENABLED", "false")
    config.reload_settings()
    try:
        assert (await client.get("/api/mock-aud/api/rfq/quotes")).status_code == 404
        assert (await client.get("/api/mock-aud/_admin/state")).status_code == 404
        assert (await client.get("/api/config")).json()["mock_enabled"] is False
    finally:
        monkeypatch.undo()
        config.reload_settings()
