"""解析澳得仕詢價信（契約 2026-10-29.4 第 3.2 節）。純函式，不碰網路與資料庫。

- 只讀分隔線「--- 規格與備註…---」之前、以行首關鍵字（全形「：」）開頭的固定欄位。
- 分隔線之後是給人看的自由文字，原樣保留（去掉每行開頭的全形空白）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

RFQ_NO_RE = re.compile(r"AUD-RFQ-\d{4}-\d{4,}")
FULL_RFQ_RE = re.compile(r"^AUD-RFQ-\d{4}-\d{4,}$")
SEPARATOR_PREFIX = "--- 規格與備註"
CONTACT_RE = re.compile(r"^(?P<name>.*?)\s*<(?P<email>[^<>\s]+@[^<>\s]+)>")
QTY_RE = re.compile(r"^(?P<qty>\d+)\s*(?P<unit>pcs|sets)$", re.I)


class ParseError(ValueError):
    """信件不符合契約格式（code 給人員介面顯示）。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass
class ParsedRfq:
    rfq_number: str
    project_name: str | None
    need_date: date | None
    need_date_text: str | None
    contact_name: str | None
    contact_email: str | None
    item_name: str
    material_text: str
    quantity: int
    unit: str
    attachments_line: str | None
    spec_text: str
    warnings: list[str] = field(default_factory=list)


def _field(lines: list[str], key: str) -> str | None:
    for ln in lines:
        if ln.startswith(key):
            return ln[len(key):].strip()
    return None


def parse_rfq_mail(subject: str, body: str) -> ParsedRfq:
    text = body.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    head: list[str] = []
    spec: list[str] = []
    seen_sep = False
    for ln in lines:
        if not seen_sep and ln.strip().startswith(SEPARATOR_PREFIX):
            seen_sep = True
            continue
        (spec if seen_sep else head).append(ln)
    head = [ln.rstrip() for ln in head]

    number = _field(head, "詢價編號：")
    if not number:
        raise ParseError("missing_rfq_number", "找不到「詢價編號：」")
    if not FULL_RFQ_RE.match(number):
        raise ParseError("bad_rfq_number", number)

    warnings: list[str] = []
    subj_nums = RFQ_NO_RE.findall(subject or "")
    if subj_nums and number not in subj_nums:
        warnings.append("subject_rfq_mismatch")

    item_line = next((ln for ln in head if ln.startswith("工件1｜")), None)
    if not item_line:
        raise ParseError("missing_item", "找不到「工件1｜」")
    parts = item_line.split("｜")
    if len(parts) != 4:
        raise ParseError("bad_item_line", item_line)
    _, item_name, material, qty_text = (p.strip() for p in parts)
    m = QTY_RE.match(qty_text)
    if not m or not item_name or not material:
        raise ParseError("bad_item_line", item_line)
    qty = int(m["qty"])
    if not 1 <= qty <= 100000:
        raise ParseError("bad_quantity", qty_text)
    if any(ln.startswith("工件2｜") for ln in head):
        warnings.append("multiple_items_ignored")

    need_text = _field(head, "需求日：")
    need: date | None = None
    if need_text:
        dm = re.fullmatch(r"(\d{4})/(\d{1,2})/(\d{1,2})", need_text)
        if dm:
            try:
                need = date(int(dm[1]), int(dm[2]), int(dm[3]))
            except ValueError:
                warnings.append("bad_need_date")

    contact = _field(head, "聯絡人：")
    cname = cemail = None
    if contact:
        cm = CONTACT_RE.match(contact)
        if cm:
            cname, cemail = cm["name"].strip() or None, cm["email"].lower()
        else:
            cname = contact

    spec_text = "\n".join(ln.lstrip("　").rstrip() for ln in spec).strip()

    return ParsedRfq(
        rfq_number=number,
        project_name=_field(head, "專案："),
        need_date=need,
        need_date_text=need_text,
        contact_name=cname,
        contact_email=cemail,
        item_name=item_name,
        material_text=material,
        quantity=qty,
        unit=m["unit"].lower(),
        attachments_line=next((ln for ln in head if re.match(r"^附件 \d+ 個：", ln)), None),
        spec_text=spec_text[:8000],
        warnings=warnings,
    )
