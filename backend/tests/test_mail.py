import base64
import json
from datetime import date
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import text

from rfq_app import config, db
from rfq_app.mail import gmail, ingest
from rfq_app.mail.parser import ParseError, parse_rfq_mail

pytestmark = pytest.mark.anyio

MAILBOX = "jl-jimmy@jauhlirn.com"
KEY = base64.urlsafe_b64encode(b"k" * 32).decode()

SAMPLE = """詢價編號：AUD-RFQ-2026-0099
專案：工件 AUD-RFQ-2026-0099-1
需求日：2026/12/31
聯絡人：王小明 <pm@audacious.example>（澳得仕教育 AUdaciousEdu）
工件1｜工件 AUD-RFQ-2026-0099-1｜PLA｜3 pcs
附件 2 個：AUD-RFQ-2026-0099-1.stp（169 KB）、AUD-RFQ-2026-0099-1-2D1.pdf（47 KB）
--- 規格與備註（自由文字，到信末為止）---
　製程：FDM
　需求日：這行在分隔線後，不能當欄位
　備註：【串接試跑】這是測試件
"""
SUBJECT = "[詢價] AUD-RFQ-2026-0099 工件 AUD-RFQ-2026-0099-1 ×3"


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------


def test_parse_sample():
    p = parse_rfq_mail(SUBJECT, SAMPLE)
    assert p.rfq_number == "AUD-RFQ-2026-0099"
    assert p.item_name == "工件 AUD-RFQ-2026-0099-1" and p.material_text == "PLA"
    assert p.quantity == 3 and p.unit == "pcs"
    assert p.need_date == date(2026, 12, 31)
    assert p.contact_name == "王小明" and p.contact_email == "pm@audacious.example"
    assert p.spec_text.startswith("製程：FDM") and "需求日：這行" in p.spec_text
    assert p.warnings == []


def test_parse_variants():
    p = parse_rfq_mail(SUBJECT, SAMPLE.replace("需求日：2026/12/31", "需求日：請報交期").replace("3 pcs", "2 sets").replace("\n", "\r\n"))
    assert p.need_date is None and p.need_date_text == "請報交期" and p.unit == "sets" and p.quantity == 2
    p = parse_rfq_mail("[詢價] AUD-RFQ-2026-0100 x", SAMPLE + "")
    assert p.warnings == ["subject_rfq_mismatch"]


@pytest.mark.parametrize(
    "body,code",
    [
        (SAMPLE.replace("詢價編號：AUD-RFQ-2026-0099\n", ""), "missing_rfq_number"),
        (SAMPLE.replace("詢價編號：AUD-RFQ-2026-0099", "詢價編號：RFQ-2026-0099"), "bad_rfq_number"),
        (SAMPLE.replace("工件1｜", "工件一｜"), "missing_item"),
        (SAMPLE.replace("｜3 pcs", "｜三件"), "bad_item_line"),
        (SAMPLE.replace("｜PLA｜", "｜PLA｜x｜"), "bad_item_line"),
    ],
)
def test_parse_errors(body, code):
    with pytest.raises(ParseError) as e:
        parse_rfq_mail(SUBJECT, body)
    assert e.value.code == code


# ---------------------------------------------------------------------------
# 假 Gmail
# ---------------------------------------------------------------------------


def _b64(s: str | bytes) -> str:
    return base64.urlsafe_b64encode(s.encode() if isinstance(s, str) else s).decode().rstrip("=")


def make_msg(gid: str, body: str, subject: str = SUBJECT, frm: str = "澳得仕 3D 工作室 <rfq@audacious.example>", at: int = 1_790_000_000_000, thread: str = "t1") -> dict:
    return {
        "id": gid,
        "threadId": thread,
        "internalDate": str(at),
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": frm},
                {"name": "Reply-To", "value": "pm@audacious.example"},
                {"name": "Message-ID", "value": f"<{gid}@audacious.example>"},
            ],
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "parts": [
                        {"mimeType": "text/plain", "headers": [{"name": "Content-Type", "value": 'text/plain; charset="UTF-8"'}], "body": {"data": _b64(body)}},
                        {"mimeType": "text/html", "body": {"data": _b64("<p>x</p>")}},
                    ],
                },
                {"mimeType": "application/octet-stream", "filename": "AUD-RFQ-2026-0099-1.stp", "body": {"attachmentId": f"att-{gid}", "size": 5}},
            ],
        },
    }


class FakeGmail:
    def __init__(self):
        self.messages: dict[str, dict] = {}
        self.token_fail = False
        self.profile = MAILBOX
        self.calls: list[str] = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        self.calls.append(f"{req.method} {req.url.path}")
        if url.startswith(gmail.TOKEN_URL):
            form = parse_qs(req.content.decode())
            if self.token_fail:
                return httpx.Response(400, json={"error": "invalid_grant"})
            if form.get("grant_type") == ["authorization_code"]:
                return httpx.Response(200, json={"access_token": "at-1", "refresh_token": "rt-secret", "expires_in": 3600})
            assert form.get("refresh_token") == ["rt-secret"]
            return httpx.Response(200, json={"access_token": "at-1", "expires_in": 3600})
        if url.startswith(gmail.REVOKE_URL):
            return httpx.Response(200)
        assert req.headers.get("authorization") == "Bearer at-1"
        path = urlparse(url).path
        if path.endswith("/profile"):
            return httpx.Response(200, json={"emailAddress": self.profile})
        if path.endswith("/messages"):
            ids = sorted(self.messages, reverse=True)
            return httpx.Response(200, json={"messages": [{"id": i} for i in ids]} if ids else {})
        if "/attachments/" in path:
            return httpx.Response(200, json={"data": _b64(b"STEP!"), "size": 5})
        gid = path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=self.messages[gid])


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("MAIL_TOKEN_KEY", KEY)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "csecret")
    config.reload_settings()
    f = FakeGmail()
    old = gmail.client_factory
    gmail.client_factory = lambda: httpx.AsyncClient(transport=httpx.MockTransport(f.handler))
    gmail._token_cache.clear()
    yield f
    gmail.client_factory = old
    gmail._token_cache.clear()
    monkeypatch.undo()
    config.reload_settings()


async def connect_mailbox():
    async with db.tx() as conn:
        await conn.execute(text("INSERT INTO rfq.mailboxes (email, refresh_token_enc) VALUES (:e, :t)"), {"e": MAILBOX, "t": gmail.encrypt("rt-secret")})


# ---------------------------------------------------------------------------
# 收信
# ---------------------------------------------------------------------------


def test_token_encryption_roundtrip(fake):
    blob = gmail.encrypt("rt-secret")
    assert "rt-secret" not in blob and gmail.decrypt(blob) == "rt-secret"


async def test_poll_creates_then_updates(client, fake):
    await connect_mailbox()
    fake.messages["m1"] = make_msg("m1", SAMPLE)
    r = await client.post("/api/gmail/poll")
    assert r.status_code == 200, r.text
    assert r.json()["new"] == 1 and r.json()["results"][0]["status"] == "created"

    rfqs = (await client.get("/api/rfqs")).json()["rfqs"]
    assert len(rfqs) == 1 and rfqs[0]["rfq_number"] == "AUD-RFQ-2026-0099" and rfqs[0]["source"] == "email"
    d = (await client.get(f"/api/rfqs/{rfqs[0]['id']}")).json()
    assert d["rfq"]["quantity"] == 3 and d["rfq"]["contact_email"] == "pm@audacious.example" and d["rfq"]["reply_to"] == "pm@audacious.example"
    assert d["attachments"] == [{"n": 0, "filename": "AUD-RFQ-2026-0099-1.stp", "size": 5, "mime": "application/octet-stream"}]
    assert d["in_mock"] is True

    # 再收一次：沒有新信
    assert (await client.post("/api/gmail/poll")).json()["new"] == 0

    # 同一詢價編號補寄（數量改 5）：更新同一張單
    fake.messages["m2"] = make_msg("m2", SAMPLE.replace("3 pcs", "5 pcs"), at=1_790_000_100_000)
    assert (await client.post("/api/gmail/poll")).json()["results"][0]["status"] == "updated"
    d = (await client.get(f"/api/rfqs/{rfqs[0]['id']}")).json()
    assert d["rfq"]["quantity"] == 5 and d["rfq"]["mail_count"] == 2 and len(d["mails"]) == 2

    # 附件下載
    r = await client.get(f"/api/rfqs/{rfqs[0]['id']}/attachments/0")
    assert r.status_code == 200 and r.content == b"STEP!" and "AUD-RFQ-2026-0099-1.stp" in r.headers["content-disposition"]
    assert (await client.get(f"/api/rfqs/{rfqs[0]['id']}/attachments/5")).status_code == 404


async def test_poll_ignores_and_errors(client, fake, monkeypatch):
    await connect_mailbox()
    fake.messages["m1"] = make_msg("m1", "隨便一封信", subject="Re: AUD-RFQ-2026-0099")
    fake.messages["m2"] = make_msg("m2", SAMPLE, frm=f"Jimmy <{MAILBOX}>")
    monkeypatch.setenv("RFQ_SENDER_ALLOW", "@audacious.example")
    config.reload_settings()
    fake.messages["m3"] = make_msg("m3", SAMPLE, frm="someone@evil.example")
    res = {x["gmail_id"]: x for x in (await client.post("/api/gmail/poll")).json()["results"]}
    assert res["m1"]["status"] == "error" and res["m1"]["error"] == "missing_rfq_number"
    assert res["m2"]["status"] == "ignored" and res["m2"]["error"] == "own_message"
    assert res["m3"]["status"] == "ignored" and res["m3"]["error"] == "sender_not_allowed"
    assert (await client.get("/api/rfqs")).json()["rfqs"] == []
    st = (await client.get("/api/gmail/status")).json()
    assert len(st["messages"]) == 3 and st["mailboxes"][0]["last_error"] is None


async def test_closed_rfq_not_changed(client, fake):
    await connect_mailbox()
    fake.messages["m1"] = make_msg("m1", SAMPLE)
    await client.post("/api/gmail/poll")
    async with db.tx() as conn:
        await conn.execute(text("UPDATE rfq.rfqs SET status='closed'"))
    fake.messages["m2"] = make_msg("m2", SAMPLE.replace("3 pcs", "9 pcs"), at=1_790_000_100_000)
    assert (await client.post("/api/gmail/poll")).json()["results"][0]["error"] == "rfq_closed"
    assert (await client.get("/api/rfqs")).json()["rfqs"][0]["quantity"] == 3


async def test_auth_failure_recorded(client, fake):
    await connect_mailbox()
    fake.token_fail = True
    j = (await client.post("/api/gmail/poll")).json()
    assert j["results"][0]["error"].startswith("auth:")
    st = (await client.get("/api/gmail/status")).json()
    assert st["mailboxes"][0]["last_error"].startswith("auth:")


async def test_connect_and_callback(client, fake):
    r = await client.get("/api/gmail/connect")
    assert r.status_code == 302
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["access_type"] == ["offline"] and "gmail.modify" in q["scope"][0] and q["login_hint"] == [MAILBOX]
    state = q["state"][0]

    assert (await client.get("/api/gmail/callback", params={"code": "c", "state": "wrong"})).headers["location"] == "/mail?error=oauth"

    r = await client.get("/api/gmail/connect")
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    fake.profile = "other@jauhlirn.com"
    r = await client.get("/api/gmail/callback", params={"code": "c", "state": state})
    assert r.headers["location"].startswith("/mail?error=wrong_mailbox")

    r = await client.get("/api/gmail/connect")
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    fake.profile = MAILBOX
    r = await client.get("/api/gmail/callback", params={"code": "c", "state": state})
    assert r.headers["location"] == "/mail?connected=1"
    async with db.tx() as conn:
        blob = (await conn.execute(text("SELECT refresh_token_enc FROM rfq.mailboxes"))).scalar_one()
    assert "rt-secret" not in blob and gmail.decrypt(blob) == "rt-secret"

    assert (await client.post("/api/gmail/disconnect")).json()["removed"] == 1


async def test_cron_runs_mail_poll(client, fake, monkeypatch):
    await connect_mailbox()
    fake.messages["m1"] = make_msg("m1", SAMPLE)
    monkeypatch.setenv("CRON_SECRET", "cron-secret-0123456789")
    config.reload_settings()
    r = await client.get("/api/cron/sweep", headers={"Authorization": "Bearer cron-secret-0123456789"})
    assert r.json()["mail"]["new"] == 1
