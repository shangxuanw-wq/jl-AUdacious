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
規格版次：1
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
SUBJECT = "[詢價][測試] AUD-RFQ-2026-0099 工件 AUD-RFQ-2026-0099-1 ×3"


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
    assert p.spec_revision == 1 and p.is_test is True


def test_parse_spec_revision():
    assert parse_rfq_mail("[詢價] AUD-RFQ-2026-0099 x", SAMPLE.replace("規格版次：1", "規格版次：3")).spec_revision == 3
    assert parse_rfq_mail("[詢價] AUD-RFQ-2026-0099 x", SAMPLE).is_test is False
    old = parse_rfq_mail(SUBJECT, SAMPLE.replace("規格版次：1\n", ""))
    assert old.spec_revision is None and old.warnings == ["spec_revision_missing"]
    with pytest.raises(ParseError) as e:
        parse_rfq_mail(SUBJECT, SAMPLE.replace("規格版次：1", "規格版次：一"))
    assert e.value.code == "bad_spec_revision"


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
        self.sent: list[dict] = []
        self.signature = '<div>張先生 Jimmy<br>兆臨企業有限公司<br>TEL 02-1234-5678</div>'

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
        if req.method == "POST" and path.endswith("/messages/send"):
            j = json.loads(req.content)
            self.sent.append({"raw": base64.urlsafe_b64decode(j["raw"]), "threadId": j.get("threadId")})
            return httpx.Response(200, json={"id": f"sent-{len(self.sent)}", "threadId": j.get("threadId")})
        if path.endswith("/settings/sendAs"):
            return httpx.Response(200, json={"sendAs": [{"sendAsEmail": MAILBOX, "isPrimary": True, "signature": self.signature}]})
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
    fake.messages["m2"] = make_msg("m2", SAMPLE.replace("3 pcs", "5 pcs").replace("規格版次：1", "規格版次：2"), at=1_790_000_100_000)
    assert (await client.post("/api/gmail/poll")).json()["results"][0]["status"] == "updated"
    d = (await client.get(f"/api/rfqs/{rfqs[0]['id']}")).json()
    assert d["rfq"]["quantity"] == 5 and d["rfq"]["mail_count"] == 2 and len(d["mails"]) == 2

    # 附件下載
    r = await client.get(f"/api/rfqs/{rfqs[0]['id']}/attachments/0")
    assert r.status_code == 200 and r.content == b"STEP!" and "AUD-RFQ-2026-0099-1.stp" in r.headers["content-disposition"]
    assert (await client.get(f"/api/rfqs/{rfqs[0]['id']}/attachments/5")).status_code == 404
    # 預覽模式：STEP 不是瀏覽器能直接顯示的格式 → 仍是下載
    r = await client.get(f"/api/rfqs/{rfqs[0]['id']}/attachments/0", params={"inline": 1})
    assert r.headers["content-type"] == "application/octet-stream" and r.headers["content-disposition"].startswith("attachment;")
    assert r.headers["x-content-type-options"] == "nosniff"


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


async def test_spec_revision_flow(client, fake):
    await connect_mailbox()
    fake.messages["m1"] = make_msg("m1", SAMPLE)
    await client.post("/api/gmail/poll")
    rid = (await client.get("/api/rfqs")).json()["rfqs"][0]["id"]
    d = (await client.get(f"/api/rfqs/{rid}")).json()["rfq"]
    assert d["spec_revision"] == 1 and d["is_test"] is True

    # 同版次重寄（數量看起來不同也不動規格）：不用重新報價
    fake.messages["m2"] = make_msg("m2", SAMPLE.replace("3 pcs", "4 pcs"), at=1_790_000_100_000)
    r = (await client.post("/api/gmail/poll")).json()["results"][0]
    assert r["status"] == "updated" and r["error"] == "same_spec_resent"
    d = (await client.get(f"/api/rfqs/{rid}")).json()
    assert d["rfq"]["quantity"] == 3 and d["rfq"]["mail_count"] == 2

    # 版次變大：更新規格
    fake.messages["m3"] = make_msg("m3", SAMPLE.replace("規格版次：1", "規格版次：2").replace("3 pcs", "6 pcs"), at=1_790_000_200_000)
    r = (await client.post("/api/gmail/poll")).json()["results"][0]
    assert r["status"] == "updated" and r["error"] == "spec_revision_up"
    d = (await client.get(f"/api/rfqs/{rid}")).json()["rfq"]
    assert d["spec_revision"] == 2 and d["quantity"] == 6 and d["spec_changed_at"]

    # 舊版次晚到：略過
    fake.messages["m4"] = make_msg("m4", SAMPLE.replace("3 pcs", "9 pcs"), at=1_790_000_300_000)
    r = (await client.post("/api/gmail/poll")).json()["results"][0]
    assert r["status"] == "ignored" and r["error"] == "older_spec_revision"
    assert (await client.get(f"/api/rfqs/{rid}")).json()["rfq"]["quantity"] == 6


async def test_closed_rfq_not_changed(client, fake):
    await connect_mailbox()
    fake.messages["m1"] = make_msg("m1", SAMPLE)
    await client.post("/api/gmail/poll")
    async with db.tx() as conn:
        await conn.execute(text("UPDATE rfq.rfqs SET status='closed'"))
    fake.messages["m2"] = make_msg("m2", SAMPLE.replace("3 pcs", "9 pcs").replace("規格版次：1", "規格版次：2"), at=1_790_000_100_000)
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


# ---------------------------------------------------------------------------
# 報價 PDF 與回信
# ---------------------------------------------------------------------------


async def _quote_from_mail(client, fake):
    await connect_mailbox()
    fake.messages["m1"] = make_msg("m1", SAMPLE)
    await client.post("/api/gmail/poll")
    rid = (await client.get("/api/rfqs")).json()["rfqs"][0]["id"]
    r = await client.post(f"/api/rfqs/{rid}/quotes", json={"unit_price": "350.5", "lead_days": 10, "note": "測試"})
    assert r.status_code == 201, r.text
    return rid, r.json()


def _parse(raw: bytes):
    import email
    from email import policy

    return email.message_from_bytes(raw, policy=policy.default)


async def test_send_replies_in_thread_with_pdf(client, fake):
    rid, q = await _quote_from_mail(client, fake)
    r = await client.post(f"/api/quotes/{q['id']}/send")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["enqueue"] == "accepted"
    assert j["mail"]["status"] == "sent" and j["mail"]["mode"] == "self" and j["mail"]["to"] == MAILBOX
    assert len(fake.sent) == 1 and fake.sent[0]["threadId"] == "t1"
    m = _parse(fake.sent[0]["raw"])
    assert m["To"] == MAILBOX and m["Subject"] == "Re: " + SUBJECT
    assert m["In-Reply-To"] == "<m1@audacious.example>" and m["References"] == "<m1@audacious.example>"
    body = m.get_body(("plain",)).get_content()
    assert "開發期測試" in body and "AUD-RFQ-2026-0099" in body and "規格版次 1" in body and q["quote_no"] in body
    assert "\n您好：\n" in body and "王小明" not in body
    assert body.rstrip().endswith("張先生 Jimmy\n兆臨企業有限公司\nTEL 02-1234-5678")
    html = m.get_body(("html",)).get_content()
    assert '<div class="gmail_signature"><div>張先生 Jimmy<br>兆臨企業有限公司' in html
    atts = list(m.iter_attachments())
    assert len(atts) == 1 and atts[0].get_content_type() == "application/pdf"
    pdf = atts[0].get_content()
    assert pdf.startswith(b"%PDF") and atts[0].get_filename() == f"報價單_{q['quote_no']}_r1.pdf"
    # JSON 帶規格版次
    full = (await client.get(f"/api/quotes/{q['id']}")).json()
    assert full["dispatches"][0]["payload"]["rfq_revision"] == 1
    assert full["mails"][0]["status"] == "sent" and full["reply_mode"] == "self"

    # 自動流程不重寄；手動重寄會再寄一封
    r = await client.post(f"/api/quotes/{q['id']}/mail")
    assert r.json()["status"] == "sent" and len(fake.sent) == 2


async def test_pdf_contains_required_fields(client, fake, tmp_path):
    import shutil
    import subprocess

    rid, q = await _quote_from_mail(client, fake)
    r = await client.get(f"/api/quotes/{q['id']}/pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF")
    if shutil.which("pdftotext"):
        f = tmp_path / "q.pdf"
        f.write_bytes(r.content)
        txt = subprocess.run(["pdftotext", str(f), "-"], capture_output=True, text=True).stdout
        for needle in ("AUD-RFQ-2026-0099", "規格版次", q["quote_no"], "修訂", "350.50", "1,051.50", "營業稅", "1,104.50", "10 個工作天", "自收到 PO 起算", "有效期限"):
            assert needle in txt, needle


async def test_live_mode_goes_to_reply_to(client, fake, monkeypatch):
    monkeypatch.setenv("RFQ_MAIL_REPLY", "live")
    config.reload_settings()
    rid, q = await _quote_from_mail(client, fake)
    j = (await client.post(f"/api/quotes/{q['id']}/send")).json()
    assert j["mail"]["mode"] == "live" and j["mail"]["to"] == "pm@audacious.example"
    m = _parse(fake.sent[0]["raw"])
    assert m["To"] == "pm@audacious.example" and "開發期測試" not in m.get_body(("plain",)).get_content()


async def test_reply_off_and_manual_rfq(client, fake, monkeypatch):
    r = await client.post("/api/rfqs", json={"rfq_number": "AUD-RFQ-2026-0099", "item_name": "x", "material_text": "PLA", "quantity": 1})
    q = (await client.post(f"/api/rfqs/{r.json()['id']}/quotes", json={"unit_price": "100", "lead_days": 5})).json()
    j = (await client.post(f"/api/quotes/{q['id']}/send")).json()
    assert j["mail"] == {"status": "skipped", "reason": "no_source_mail"} and fake.sent == []
    monkeypatch.setenv("RFQ_MAIL_REPLY", "off")
    config.reload_settings()
    assert (await client.post(f"/api/quotes/{q['id']}/mail")).json()["reason"] == "reply_off"


async def test_reply_failure_recorded(client, fake):
    rid, q = await _quote_from_mail(client, fake)
    fake.token_fail = True
    gmail._token_cache.clear()
    j = (await client.post(f"/api/quotes/{q['id']}/send")).json()
    assert j["enqueue"] == "accepted" and j["mail"]["status"] == "failed" and j["mail"]["error"].startswith("auth:")
    assert (await client.get(f"/api/quotes/{q['id']}")).json()["mails"][0]["status"] == "failed"


async def test_reply_without_signature_uses_vendor(client, fake):
    fake.signature = ""
    rid, q = await _quote_from_mail(client, fake)
    await client.post(f"/api/quotes/{q['id']}/send")
    m = _parse(fake.sent[0]["raw"])
    assert m.get_body(("plain",)).get_content().rstrip().endswith("--\n兆臨")


def test_inline_types_only_safe_formats():
    from rfq_app.mail.routes import INLINE_TYPES, _ext

    assert INLINE_TYPES[_ext("圖.JPG")] == "image/jpeg" and INLINE_TYPES[_ext("2D.pdf")] == "application/pdf"
    for name in ("a.svg", "a.html", "a.htm", "a.xml", "a.stp", "a.stl", "noext"):
        assert _ext(name) not in INLINE_TYPES


def test_spec_fields_parse():
    from rfq_app import spec_fields

    text = "【測試單】說明\n製程：CNC 三軸銑削\n表面處理：原色（黑色）\n公差與要求：外形 100.0 × 70.0 × 25.0 mm；未標註公差依一般加工公差，詳見 2D 圖。\n備註：無\n回覆方式："
    r = spec_fields.parse(text)
    assert r["dims"] == "100.0 × 70.0 × 25.0 mm"
    assert [f["label"] for f in r["fields"]] == ["製程", "表面處理", "外形", "公差", "備註"]
    assert r["fields"][3]["value"] == "未標註公差依一般加工公差，詳見 2D 圖"
    assert spec_fields.parse(None) == {"fields": [], "dims": None}
    assert spec_fields.parse("公差與要求：±0.05")["fields"] == [{"label": "公差", "value": "±0.05"}]
