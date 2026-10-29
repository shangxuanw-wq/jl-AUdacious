"""報價金額計算與契約 payload（純函式，不碰資料庫）。

契約：澳得仕 2026-10-29.4 第 4.2 節。數字一律是 JSON 數字，絕不送字串。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

QUOTE_NO_RE = re.compile(r"^AU\d{8}$")
JL_REPLY_HAZARD = re.compile(r"[TJRL]\d{6,}", re.I)  # JL 的 vendor reply handler 會誤判的樣式
AUD_RFQ_RE = re.compile(r"^AUD-RFQ-\d{4}-\d{4,}$")


def quote_no_for(day: date, seq: int) -> str:
    if not 1 <= seq <= 99:
        raise ValueError("quote_no_exhausted")
    no = f"AU{day:%y%m%d}{seq:02d}"
    assert QUOTE_NO_RE.match(no) and not JL_REPLY_HAZARD.search(no)
    return no


def to_cents(v: Decimal | int | float) -> int:
    return int((Decimal(str(v)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def json_number(cents: int) -> int | float:
    """以「分」表示的金額 → JSON 數字（整數值輸出 int，否則最多 2 位小數的 float）。"""
    if cents % 100 == 0:
        return cents // 100
    return float(Decimal(cents) / 100)


@dataclass(frozen=True)
class Totals:
    subtotal_cents: int
    total_cents: int
    tax_cents: int | None  # tax_included=True 時不送 tax

    def as_numbers(self) -> dict[str, Any]:
        out: dict[str, Any] = {"subtotal": json_number(self.subtotal_cents), "total": json_number(self.total_cents)}
        if self.tax_cents is not None:
            out["tax"] = json_number(self.tax_cents)
        return out


def compute_totals(unit_price: Decimal | int | float, qty: int, tax_included: bool, tax_rate: Decimal | float, currency: str = "TWD") -> Totals:
    sub = to_cents(unit_price) * qty
    total = sub
    tax = None
    if not tax_included:
        raw = Decimal(total) * Decimal(str(tax_rate))  # 分
        if currency.upper() == "TWD":
            # 台幣稅額取整數元，四捨五入
            tax = int((raw / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) * 100
        else:
            tax = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return Totals(sub, total, tax)


def build_payload(*, rfq: dict, quote: dict, items: list[dict], event_id: str, vendor_name: str) -> dict[str, Any]:
    """依契約組出 JSON。rfq/quote/items 是資料庫列（dict）。"""
    if len(items) != 1:
        raise ValueError("too_many_items" if len(items) > 1 else "no_items")
    it = items[0]
    totals = compute_totals(it["unit_price"], it["qty"], quote["tax_included"], quote["tax_rate"], quote["currency"])
    nums = totals.as_numbers()
    item: dict[str, Any] = {
        "part": it["part"],
        "material": it["material"],
        "qty": int(it["qty"]),
        "unit": it["unit"],
        "unit_price": json_number(to_cents(it["unit_price"])),
        "subtotal": nums["subtotal"],
        "lead_days": int(it["lead_days"]),
    }
    payload: dict[str, Any] = {
        "rfq": rfq["rfq_number"],
        "event_id": event_id,
        "quote_no": quote["quote_no"],
        "quote_revision": int(quote["quote_revision"]),
        "quote_date": quote["quote_date"].isoformat(),
        "valid_until": quote["valid_until"].isoformat(),
        "currency": quote["currency"].strip(),
        "tax_included": bool(quote["tax_included"]),
        "lead_basis": quote["lead_basis"],
        "vendor": vendor_name,
        "items": [item],
        "total": nums["total"],
    }
    if "tax" in nums:
        payload["tax"] = nums["tax"]
    if quote.get("delivery_date"):
        payload["delivery_date"] = quote["delivery_date"].isoformat()
    if quote.get("note"):
        payload["note"] = quote["note"]
    return payload


def payload_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def item_warnings(rfq: dict, items: list[dict]) -> list[str]:
    w = []
    for it in items:
        if it["part"] != rfq["item_name"] or it["material"] != rfq["material_text"]:
            w.append("item_mismatch")
        if int(it["qty"]) != int(rfq["quantity"]):
            w.append("quantity_mismatch")
        if it["unit"] != rfq["unit"]:
            w.append("unit_mismatch")
    return sorted(set(w))
