"""澳得仕串接試跑（步驟 1）：照澳得仕 trial.py（契約 2026-10-29.5）的 13 項檢查，從雲端執行。

- token 只從環境變數 AUD_TRIAL_TOKEN 讀，不會出現在回應或紀錄裡。
- A 組 6 項不寫入；A 組全過、而且呼叫時明確要求（group=ab）才跑 B 組。
- B 組一律帶 X-Self-Test: 1，澳得仕只讓它寫「測試單」、資料標成測試、不會發布給學生。
- 目標網址固定是澳得仕正式站，不能從外面改。
"""

from __future__ import annotations

import json
import re
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

import httpx

from . import config

BASE_URL = "https://audacious-3d-studio.vercel.app"
CONTRACT_VERSION = "2026-10-29.5"
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
TPE = ZoneInfo("Asia/Taipei")

client_factory: Callable[[], httpx.AsyncClient] = lambda: httpx.AsyncClient(timeout=20)


@dataclass
class Reply:
    status: int | None
    json: Any
    text: str
    headers: dict[str, str] = field(default_factory=dict)
    error: str | None = None


@dataclass
class Result:
    name: str
    ok: bool
    problems: list[str]
    reply: Reply | None
    sent: Any = None


def _codes(j: dict) -> list[str]:
    return [i.get("code") for i in j.get("issues", []) if isinstance(i, dict)]


def _header(r: Reply, name: str) -> str | None:
    for k, v in r.headers.items():
        if k.lower() == name.lower():
            return v
    return None


def _check(name: str, r: Reply, expect: int, rules: list[tuple[str, Callable[[Any], bool]]], envelope: bool = True, sent: Any = None) -> Result:
    problems: list[str] = []
    if r.error:
        problems.append(f"連線失敗：{r.error}")
    else:
        if r.status != expect:
            problems.append(f"狀態碼 {r.status}，應該是 {expect}")
        if not isinstance(r.json, dict):
            problems.append("回應不是 JSON 物件")
        else:
            env = [
                (f"contract_version = {CONTRACT_VERSION}", lambda j: j["contract_version"] == CONTRACT_VERSION),
                ("request_id 是非空字串", lambda j: isinstance(j["request_id"], str) and j["request_id"] != ""),
                ("X-Request-Id 標頭 = request_id", lambda j: _header(r, "X-Request-Id") == j["request_id"]),
            ]
            for label, rule in (env if envelope else []) + rules:
                try:
                    good = bool(rule(r.json))
                except Exception as e:  # noqa: BLE001 - 欄位不存在、型別不對
                    good, label = False, f"{label}（{type(e).__name__}）"
                if not good:
                    problems.append(f"內容不符：{label}")
    return Result(name, not problems, problems, r, sent)


@dataclass
class Trial:
    token: str
    rfq: str
    rfq_revision: int
    item: str
    material: str
    qty: int
    unit: str
    run_id: str

    @property
    def url(self) -> str:
        return BASE_URL + "/api/rfq/quotes"

    def headers(self, auth: bool = True, content_type: str = "application/json") -> dict[str, str]:
        h = {"Content-Type": content_type, "X-Request-Id": f"{self.run_id}-req-{uuid.uuid4().hex[:8]}"}
        if auth:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def write_headers(self) -> dict[str, str]:
        return {**self.headers(), "X-Self-Test": "1"}

    def quote(self, case: str, unit_price: float = 350, quote_revision: int = 1, item: str | None = None, note: str = "", rfq_revision: int | None = None) -> dict:
        subtotal = round(unit_price * self.qty, 2)
        today = datetime.now(TPE).date()
        return {
            "rfq": self.rfq,
            "rfq_revision": self.rfq_revision if rfq_revision is None else rfq_revision,
            "event_id": f"{self.run_id}-{case}",
            "quote_no": f"QT-{self.run_id}",
            "quote_revision": quote_revision,
            "quote_date": today.isoformat(),
            "valid_until": (today + timedelta(days=30)).isoformat(),
            "currency": "TWD",
            "tax_included": False,
            "lead_basis": "po",
            "items": [{"part": self.item if item is None else item, "material": self.material, "qty": self.qty, "unit": self.unit, "unit_price": unit_price, "subtotal": subtotal, "lead_days": 10}],
            "total": subtotal,
            "tax": round(subtotal * 0.05),
            "note": note,
        }


async def _req(c: httpx.AsyncClient, url: str, method: str = "GET", body: Any = None, headers: dict | None = None, raw: bytes | None = None) -> Reply:
    data = raw if raw is not None else (json.dumps(body, ensure_ascii=False).encode() if body is not None else None)
    try:
        r = await c.request(method, url, content=data, headers=headers or {})
    except httpx.HTTPError as e:
        return Reply(None, None, "", error=type(e).__name__)
    try:
        parsed = r.json()
    except ValueError:
        parsed = None
    return Reply(r.status_code, parsed, r.text[:4000], dict(r.headers))


async def run(*, rfq: str, rfq_revision: int, item: str, material: str, qty: int, unit: str, include_b: bool) -> dict:
    token = config.settings.aud_trial_token
    if len(token) < 16:
        raise RuntimeError("AUD_TRIAL_TOKEN 還沒設定")
    run_id = f"jl-trial-{datetime.now(TPE):%Y%m%d%H%M%S}-{secrets.token_hex(2)}"
    t = Trial(token, rfq, rfq_revision, item, material, qty, unit, run_id)
    results: list[Result] = []
    async with client_factory() as c:
        get = await _req(c, t.url)
        results.append(_check("A1 GET 說明頁：已啟用、契約版本、可寫入", get, 200, [
            ("enabled = true", lambda j: j["enabled"] is True),
            (f"contract_version = {CONTRACT_VERSION}", lambda j: j["contract_version"] == CONTRACT_VERSION),
            ("writes_enabled = true", lambda j: j["writes_enabled"] is True),
            ("fields 有 rfq_revision", lambda j: any(f["field"] == "rfq_revision" for f in j["fields"])),
        ], envelope=False))
        has_error = ("error 有說明", lambda j: isinstance(j["error"], str) and j["error"] != "")
        results.append(_check("A2 沒帶 token → 401", await _req(c, t.url, "POST", {}, t.headers(auth=False)), 401, [has_error], sent={}))
        results.append(_check("A3 Content-Type 不是 JSON → 415", await _req(c, t.url, "POST", raw=b"{}", headers=t.headers(content_type="text/plain")), 415, [has_error], sent="{}"))
        a4 = {"rfq": "RFQ-1", "items": []}
        results.append(_check("A4 rfq 格式不對 → 400 rfq_invalid", await _req(c, t.url, "POST", a4, t.headers()), 400, [
            ("issues[0].code = rfq_invalid", lambda j: _codes(j)[0] == "rfq_invalid"),
        ], sent=a4))
        a5 = {"rfq": "AUD-RFQ-0000-0000", "items": [{"qty": 1, "unit_price": 1, "lead_days": 1}]}
        results.append(_check("A5 找不到詢價編號 → 404", await _req(c, t.url, "POST", a5, t.headers()), 404, [has_error], sent=a5))
        bad = t.quote("a6")
        bad["items"][0]["unit_price"] = "350"
        results.append(_check("A6 unit_price 是字串 → 400 invalid_number（不寫入）", await _req(c, t.url, "POST", bad, t.headers()), 400, [
            ("issues 有 invalid_number（items[0].unit_price）", lambda j: any(i["code"] == "invalid_number" and i["field"] == "items[0].unit_price" for i in j["issues"])),
        ], sent=bad))

        a_ok = all(r.ok for r in results)
        b_note = None
        if not include_b:
            b_note = "沒有要求跑 B 組（寫入）"
        elif not a_ok:
            b_note = "A 組有 FAIL，B 組沒有執行"
        else:
            q1 = t.quote("b1")
            r1 = await _req(c, t.url, "POST", q1, t.write_headers())
            if r1.status == 409 and isinstance(r1.json, dict) and r1.json.get("code") == "not_test_rfq":
                results.append(Result("B1 合法報價 → 202 待審", False, [f"{rfq} 不是澳得仕的測試單（409 not_test_rfq），沒有寫入；B 組其他項目沒有執行。"], r1, q1))
            else:
                results.append(_check("B1 合法報價 → 202 待審", r1, 202, [
                    ("outcome = pending_review", lambda j: j["outcome"] == "pending_review"),
                    ("candidate_id 是 uuid", lambda j: bool(UUID_RE.match(j["candidate_id"]))),
                    (f"rfq = {rfq}", lambda j: j["rfq"] == rfq),
                    (f"spec_revision = {rfq_revision}", lambda j: j["spec_revision"] == rfq_revision),
                    ("沒有品名／材質／數量差異", lambda j: not ({"item_mismatch", "quantity_mismatch", "unit_mismatch"} & set(_codes(j)))),
                ], sent=q1))
                cid = r1.json.get("candidate_id") if isinstance(r1.json, dict) else None
                results.append(_check("B2 同一個 event_id、同內容重送 → 200 duplicate、同一個 candidate_id", await _req(c, t.url, "POST", q1, t.write_headers()), 200, [
                    ("outcome = duplicate", lambda j: j["outcome"] == "duplicate"),
                    ("candidate_id 跟 B1 一樣", lambda j: cid is not None and j["candidate_id"] == cid),
                ], sent=q1))
                changed = dict(q1, items=[dict(q1["items"][0], unit_price=360, subtotal=round(360 * qty, 2))], total=round(360 * qty, 2))
                results.append(_check("B3 同一個 event_id、不同內容 → 409 event_conflict", await _req(c, t.url, "POST", changed, t.write_headers()), 409, [
                    ("code = event_conflict", lambda j: j["code"] == "event_conflict"),
                ], sent=changed))
                reused = t.quote("b4", unit_price=340, quote_revision=1)
                results.append(_check("B4 新 event_id、同修訂（1）、不同價格 → 202＋revision_reused", await _req(c, t.url, "POST", reused, t.write_headers()), 202, [
                    ("outcome = pending_review", lambda j: j["outcome"] == "pending_review"),
                    ("issues 有 revision_reused", lambda j: "revision_reused" in _codes(j)),
                    ("candidate_id 跟 B1 不同", lambda j: j["candidate_id"] != cid),
                ], sent=reused))
                b5 = t.quote("b5", unit_price=330, quote_revision=2)
                results.append(_check("B5 新 event_id、修訂 2 → 202（沒有 revision_reused）", await _req(c, t.url, "POST", b5, t.write_headers()), 202, [
                    ("outcome = pending_review", lambda j: j["outcome"] == "pending_review"),
                    ("沒有 revision_reused", lambda j: "revision_reused" not in _codes(j)),
                ], sent=b5))
                tricky = 'Part "A" \\ 測試'
                b6 = t.quote("b6", quote_revision=3, item=tricky)
                results.append(_check("B6 品名含引號與反斜線 → JSON 有效、202＋品名差異原樣回報", await _req(c, t.url, "POST", b6, t.write_headers()), 202, [
                    ("issues 有 item_mismatch（part）", lambda j: any(i["code"] == "item_mismatch" and i["field"] == "part" for i in j["issues"])),
                    ("回報的品名跟送出的一模一樣", lambda j: any(i.get("got") == tricky for i in j["issues"])),
                ], sent=b6))
                b7 = t.quote("b7", rfq_revision=99)
                results.append(_check("B7 rfq_revision 不存在 → 409 rfq_revision_unknown", await _req(c, t.url, "POST", b7, t.write_headers()), 409, [
                    ("code = rfq_revision_unknown", lambda j: j["code"] == "rfq_revision_unknown"),
                ], sent=b7))

    ok = all(r.ok for r in results)
    lines = []
    for r in results:
        lines.append(f"{'PASS' if r.ok else 'FAIL'}  {r.name}")
        lines += [f"      - {p}" for p in r.problems]
    summary = "\n".join(lines) + f"\n\n{'全部通過' if ok else '有 FAIL'}（{sum(r.ok for r in results)}/{len(results)}）"
    if b_note:
        summary += f"\n{b_note}"
    out = {
        "run_id": run_id,
        "contract_version": CONTRACT_VERSION,
        "rfq": rfq,
        "rfq_revision": rfq_revision,
        "ok": ok,
        "passed": sum(r.ok for r in results),
        "total": len(results),
        "b_note": b_note,
        "summary": summary,
        "cases": [
            {
                "name": r.name,
                "ok": r.ok,
                "problems": r.problems,
                "status": r.reply.status if r.reply else None,
                "request_id": (r.reply.json or {}).get("request_id") if r.reply and isinstance(r.reply.json, dict) else None,
                "response": r.reply.json if r.reply else None,
                "sent": r.sent,
                "error": r.reply.error if r.reply else None,
            }
            for r in results
        ],
    }
    # 保險：回應裡絕不出現 token
    blob = json.dumps(out, ensure_ascii=False)
    if token in blob:
        blob = blob.replace(token, "<token>")
        out = json.loads(blob)
    return out
