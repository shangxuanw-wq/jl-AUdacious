"""假澳得仕報價 API 的純邏輯（從 rfq-mock-partner/app.py 搬來，行為對照澳得仕原始碼）。"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date
from typing import Any

RFQ_NUMBER = re.compile(r"^AUD-RFQ-\d{4}-\d{4,}$")
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
UNSET = object()


def js_num(v: float | int) -> str:
    """數字印成 JS 的樣子：350.0 → "350"、17.5 → "17.5"。"""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def to_cents(v: float | int) -> int:
    return math.floor(v * 100 + 0.5)  # JS Math.round


def from_cents(c: int) -> float | int:
    return c // 100 if c % 100 == 0 else c / 100


def is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def canonical(v: Any) -> Any:
    """正規化：整數值的 float 轉 int（JS 裡 350 與 350.0 是同一個數），鍵排序交給 dumps。"""
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return v
    if isinstance(v, float) and v.is_integer() and abs(v) < 2**53:
        return int(v)
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, list):
        return [canonical(x) for x in v]
    if isinstance(v, dict):
        return {k: canonical(x) for k, x in v.items()}
    return v


def payload_hash(body: Any) -> str:
    text = json.dumps(canonical(body), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_calendar_date(value: str) -> bool:
    m = DATE_RE.match(value)
    if not m:
        return False
    y, mo, d = int(m[1]), int(m[2]), int(m[3])
    if y < 1990 or y > 2100:
        return False
    try:
        date(y, mo, d)
    except ValueError:
        return False
    return True


def js_trim(s: str) -> str:
    return s.strip().strip("﻿").strip()


def issue(code: str, level: str, field: str | None, message: str, got: Any = UNSET, expected: Any = UNSET) -> dict:
    out = {"code": code, "level": level, "field": field, "message": message}
    if got is not UNSET:
        out["got"] = got
    if expected is not UNSET:
        out["expected"] = expected
    return out


def pick(o: dict, *names: str) -> tuple[str | None, Any]:
    for n in names:
        if n in o:
            return n, o[n]
    return None, None


def id_text(raw: Any, max_len: int) -> tuple[str | None, bool]:
    """識別碼：字串或整數（含 2.0 這種）都收；其他型別是「給了但不對」。回 (值, invalid)。"""
    if raw is None:
        return None, False
    if is_number(raw):
        if isinstance(raw, float) and (not raw.is_integer() or abs(raw) > 2**53 - 1):
            return None, True
        if isinstance(raw, int) and abs(raw) > 2**53 - 1:
            return None, True
        return str(int(raw)), False
    if not isinstance(raw, str):
        return None, True
    t = js_trim(re.sub(r"[\r\n]+", " ", raw))
    return (t[:max_len] if t else None), False


class PayloadError(Exception):
    def __init__(self, message: str, issues: list[dict]):
        super().__init__(message)
        self.issues = issues


class Conflict(Exception):
    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


class NotFound(Exception):
    pass


def payload_number(body: Any) -> str:
    if not isinstance(body, dict):
        raise ValueError("要是 JSON 物件")
    _, raw = pick(body, "rfq", "rfq_no", "rfq_number", "number")
    if not isinstance(raw, str):
        raise ValueError("缺 rfq（我們的詢價編號）")
    number = js_trim(raw).upper()
    if not RFQ_NUMBER.match(number):
        raise ValueError(f"rfq 格式不對：{js_trim(raw)[:40]}（應該像 AUD-RFQ-2026-0001）")
    return number


# ---------------------------------------------------------------------------
# 解析報價（parseVendorQuotePayload，api 模式）
# ---------------------------------------------------------------------------


def parse_quote(body: dict, expect: dict, today: str) -> dict:
    issues: list[dict] = []

    def err(code, field, message, **kw):
        issues.append(issue(code, "error", field, message, **kw))

    def review(code, field, message, **kw):
        issues.append(issue(code, "review", field, message, **kw))

    def info(code, field, message):
        issues.append(issue(code, "info", field, message))

    o = body

    items = o.get("items", UNSET)
    if items is UNSET and pick(o, "unit_price", "price")[0]:
        items = [o]
    if not isinstance(items, list) or len(items) == 0:
        err("no_items", "items", "缺 items（逐件報價，剛好 1 筆）")
    elif len(items) > 1:
        err("multiple_items", "items", f"這張詢價單只有 1 個工件，JSON 卻有 {len(items)} 筆 items；不會只取第一筆或自行加總", got=len(items), expected=1)
    it = items[0] if isinstance(items, list) and len(items) == 1 else None
    if isinstance(items, list) and len(items) == 1 and not isinstance(it, dict):
        err("bad_item", "items[0]", "items[0] 要是物件")
    item = it if isinstance(it, dict) else {}

    currency = "TWD"
    cur_raw = o.get("currency")
    if cur_raw is not None:
        if not isinstance(cur_raw, str) or not re.fullmatch(r"[A-Za-z]{3}", js_trim(cur_raw)):
            err("invalid_currency", "currency", "幣別要是三個字母（例如 TWD）", got=cur_raw)
        else:
            currency = js_trim(cur_raw).upper()
    else:
        info("currency_default", "currency", "沒給幣別，當作 TWD")

    def parse_number(raw):
        if raw is None:
            return {"missing": True}
        if is_number(raw):
            if isinstance(raw, float) and not math.isfinite(raw):
                return {"error": "不是有限的數字"}
            return {"value": raw}
        if isinstance(raw, str):
            return {"error": "API 要送 JSON 數字，不是字串"}
        return {"error": "不是數字"}

    def take_money(field, raw, required):
        p = parse_number(raw)
        if p.get("missing"):
            if required:
                err("missing_field", field, f"缺 {field}")
            return None
        if "error" in p:
            err("invalid_number", field, f"{field}：{p['error']}", got=raw)
            return None
        v = p["value"]
        if v < 0 or v > 1e9:
            err("out_of_range", field, f"{field} 要在 0–1,000,000,000 之間", got=v)
            return None
        if abs(v * 100 - round(v * 100)) > 1e-6:
            err("invalid_number", field, f"{field} 最多到小數第 2 位", got=raw)
            return None
        return from_cents(to_cents(v))

    def take_integer(field, raw, lo, hi, required):
        p = parse_number(raw)
        if p.get("missing"):
            if required:
                err("missing_field", field, f"缺 {field}")
            return None
        if "error" in p:
            err("invalid_number", field, f"{field}：{p['error']}", got=raw)
            return None
        v = p["value"]
        if (isinstance(v, float) and not v.is_integer()) or v < lo or v > hi:
            err("invalid_integer", field, f"{field} 要是 {lo}–{hi} 的整數", got=v)
            return None
        return int(v)

    unit_price = take_money("items[0].unit_price", pick(item, "unit_price", "price")[1], True)
    if unit_price is not None and unit_price <= 0:
        err("out_of_range", "items[0].unit_price", "單價要大於 0", got=unit_price)
    quantity = take_integer("items[0].qty", pick(item, "qty", "quantity")[1], 1, 100000, True)
    lead_days = take_integer("items[0].lead_days", pick(item, "lead_days", "lead_time_days", "lead")[1], 0, 365, True)
    subtotal_rep = take_money("items[0].subtotal", pick(item, "subtotal", "amount")[1], False)
    total_rep = take_money("total", o.get("total"), False)
    tax = take_money("tax", pick(o, "tax", "vat")[1], False)

    unit = "件"
    unit_raw = item.get("unit")
    if unit_raw is not None:
        u = js_trim(unit_raw).lower() if isinstance(unit_raw, str) else ""
        if u in ("pcs", "pc", "件"):
            unit = "件"
        elif u in ("sets", "set", "套"):
            unit = "套"
        else:
            err("invalid_unit", "items[0].unit", "unit 只能是 pcs 或 sets", got=unit_raw)

    ti_raw = o.get("tax_included")
    tax_included = None
    if ti_raw is not None:
        if isinstance(ti_raw, bool):
            tax_included = ti_raw
        else:
            err("invalid_boolean", "tax_included", f"tax_included 要是 true 或 false，收到 {json.dumps(ti_raw, ensure_ascii=False)[:30]}", got=ti_raw)
    if ti_raw is None:
        review("tax_unknown", "tax_included", "沒說合計含不含稅；稅別待確認")

    def parse_date(raw):
        if raw is None:
            return None, None
        if not isinstance(raw, str):
            return None, "日期要是字串 YYYY-MM-DD"
        t = js_trim(raw)
        if not t:
            return None, "日期是空字串"
        if not DATE_RE.match(t):
            return None, f"日期格式不對：{t[:30]}（要 YYYY-MM-DD）"
        if not is_calendar_date(t):
            return None, f"不存在的日期：{t[:30]}"
        return t, None

    valid_raw = pick(o, "valid_until", "valid_to", "validity")[1]
    valid, e = parse_date(valid_raw)
    if e:
        err("invalid_date", "valid_until", f"valid_until：{e}", got=valid_raw)
    delivery_raw = pick(o, "delivery_date", "promised_date", "delivery")[1]
    delivery, e = parse_date(delivery_raw)
    if e:
        err("invalid_date", "delivery_date", f"delivery_date：{e}", got=delivery_raw)
    qd_raw = pick(o, "quote_date", "date")[1]
    qd, e = parse_date(qd_raw)
    if e:
        err("invalid_date", "quote_date", f"quote_date：{e}", got=qd_raw)

    lead_basis = "unknown"
    lb = o.get("lead_basis")
    if lb is not None:
        if lb in ("po", "quote"):
            lead_basis = lb
        else:
            err("invalid_lead_basis", "lead_basis", "lead_basis 只能是 po 或 quote", got=lb)
    if lead_basis == "unknown":
        info("lead_basis_unknown", "lead_basis", "沒說交期從哪一天起算；畫面會寫「起算條件待確認」")

    def text_field(field, raw, max_len):
        if raw is not None and not isinstance(raw, str):
            err("invalid_field", field, f"{field} 要是字串", got=raw)
            return None
        if raw is None:
            return None
        t = js_trim(re.sub(r"[\r\n]+", " ", raw))
        return t[:max_len] if t else None

    def id_field(field, raw, max_len):
        v, invalid = id_text(raw, max_len)
        if invalid:
            err("invalid_field", field, f"{field} 要是字串或整數", got=raw)
        return v

    vendor_name = text_field("vendor", pick(o, "vendor", "vendor_name", "supplier")[1], 80) or "兆臨"
    quote_no = id_field("quote_no", pick(o, "quote_no", "quotation_no")[1], 60)
    event_id = id_field("event_id", pick(o, "event_id", "eventId")[1], 120)
    quote_revision = id_field("quote_revision", pick(o, "quote_revision", "revision")[1], 60)
    note_raw = pick(o, "note", "notes", "remarks")[1]
    if note_raw is not None and not isinstance(note_raw, str):
        err("invalid_field", "note", "note 要是字串", got=note_raw)
    note = js_trim(re.sub(r"\r\n?", "\n", note_raw))[:1000] if isinstance(note_raw, str) else ""
    part_text = text_field("items[0].part", item.get("part"), 120)
    mat_text = text_field("items[0].material", item.get("material"), 120)

    errors = [i for i in issues if i["level"] == "error"]
    if errors:
        raise PayloadError("報價 JSON 有錯：" + "；".join(i["message"] for i in errors), issues)

    line_cents = to_cents(unit_price) * quantity
    line_total = from_cents(line_cents)
    total_cents = line_cents
    if subtotal_rep is not None:
        sc = to_cents(subtotal_rep)
        if sc != line_cents:
            review("amount_mismatch", "items[0].subtotal", f"廠商的小計 {js_num(subtotal_rep)} 跟 單價 × 數量 ＝ {js_num(line_total)} 對不上（差 {js_num(from_cents(sc - line_cents))}）；要確認是折扣、額外費用還是錯誤", got=subtotal_rep, expected=line_total)
        total_cents = sc
    if total_rep is not None:
        tc = to_cents(total_rep)
        if subtotal_rep is not None and tc != to_cents(subtotal_rep):
            review("total_mismatch", "total", f"total {js_num(total_rep)} 跟工件小計 {js_num(subtotal_rep)} 不同（只有一個工件時應該一樣）", got=total_rep, expected=subtotal_rep)
        elif subtotal_rep is None and tc != line_cents:
            review("amount_mismatch", "total", f"total {js_num(total_rep)} 跟 單價 × 數量 ＝ {js_num(line_total)} 對不上（差 {js_num(from_cents(tc - line_cents))}）；沒有 subtotal 也不能略過核對", got=total_rep, expected=line_total)
            total_cents = tc
    total = from_cents(total_cents)
    adjustment_cents = total_cents - line_cents

    if expect.get("quantity") and quantity != expect["quantity"]:
        review("quantity_mismatch", "items[0].qty", f"廠商報的數量是 {quantity}，寄出的詢價是 {expect['quantity']}", got=quantity, expected=expect["quantity"])
    if expect.get("unit") and unit != expect["unit"]:
        review("unit_mismatch", "items[0].unit", f"廠商的單位是「{unit}」，寄出的是「{expect['unit']}」", got=unit, expected=expect["unit"])
    if part_text and expect.get("item_name") and part_text != expect["item_name"]:
        review("item_mismatch", "items[0].part", f"品名「{part_text}」跟寄出的「{expect['item_name']}」不同", got=part_text, expected=expect["item_name"])
    if mat_text and expect.get("material_text") and mat_text != expect["material_text"]:
        review("item_mismatch", "items[0].material", f"材質「{mat_text}」跟寄出的「{expect['material_text']}」不同", got=mat_text, expected=expect["material_text"])

    if valid and valid < today:
        review("expired", "valid_until", f"報價有效期 {valid} 已過（今天 {today}）", got=valid)
    if delivery and delivery < today:
        review("promised_in_past", "delivery_date", f"承諾交貨日 {delivery} 已經過了", got=delivery)
    if not qd:
        info("quote_date_missing", "quote_date", "廠商沒給報價日期；畫面只會標示我方接收日期")

    if tax_included is True:
        grand_total = total
    elif tax_included is False and tax is not None:
        grand_total = from_cents(to_cents(total) + to_cents(tax))
    else:
        grand_total = None

    quote = {
        "vendor_name": vendor_name,
        "quote_no": quote_no,
        "quote_date": qd,
        "unit_price": unit_price,
        "currency": currency,
        "quantity": quantity,
        "unit": unit,
        "line_total": line_total,
        "adjustment": None if adjustment_cents == 0 else from_cents(adjustment_cents),
        "adjustment_reason": None,
        "total": total,
        "tax": tax,
        "tax_included": tax_included,
        "grand_total": grand_total,
        "lead_days": lead_days,
        "lead_basis": lead_basis,
        "promised_date": delivery,
        "valid_until": valid,
        "note": note,
    }
    return {"quote": quote, "issues": issues, "event_id": event_id, "quote_revision": quote_revision}


TERM_KEYS = ["currency", "unit_price", "quantity", "unit", "line_total", "adjustment", "total", "tax", "tax_included", "lead_days", "lead_basis", "promised_date", "valid_until", "quote_date"]


def same_terms(a: dict, b: dict) -> bool:
    return all(canonical(a.get(k)) == canonical(b.get(k)) for k in TERM_KEYS)


def compare_revisions(a: str | None, b: str | None) -> int | None:
    if not a or not b:
        return None

    def num(s):
        s = s.strip()
        return int(s) if re.fullmatch(r"\d+", s) else None

    na, nb = num(a), num(b)
    if na is not None and nb is not None:
        return 0 if na == nb else (1 if na > nb else -1)
    ma = re.match(r"^(.*?)(\d+)$", a)
    mb = re.match(r"^(.*?)(\d+)$", b)
    if ma and mb and ma[1] == mb[1]:
        x, y = int(ma[2]), int(mb[2])
        return 0 if x == y else (1 if x > y else -1)
    return 0 if a == b else None
