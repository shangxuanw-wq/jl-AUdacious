"""報價單 PDF（契約 2026-10-29.5 第 4.9 節）。

PDF 上的數字跟送出的 JSON 用同一個函式算（payload.compute_totals），不會不一致。
上面寫：詢價編號、規格版次、報價單號與修訂、單價、數量、合計、稅別、交期與起算點、有效期。
不放協力廠商名稱或成本。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from fpdf import FPDF

from .. import payload as pl

FONT_DIR = Path(__file__).with_name("fonts")
ACCENT = (232, 130, 12)
INK = (28, 25, 23)
MUTED = (120, 113, 108)
LINE = (214, 211, 209)
CUSTOMER = "澳得仕教育 AUdaciousEdu（澳得仕 3D 工作室）"


def _money(cents: int, currency: str) -> str:
    v = pl.json_number(cents)
    s = f"{v:,.2f}" if isinstance(v, float) else f"{v:,}"
    return f"{currency} {s}"


def _d(v) -> str:
    if isinstance(v, date):
        return v.isoformat()
    return str(v or "—")


def build_quote_pdf(*, rfq: dict, quote: dict, items: list[dict], vendor_name: str) -> bytes:
    if len(items) != 1:
        raise ValueError("too_many_items" if len(items) > 1 else "no_items")
    it = items[0]
    cur = quote["currency"].strip()
    t = pl.compute_totals(it["unit_price"], it["qty"], quote["tax_included"], quote["tax_rate"], cur)
    tax = t.tax_cents or 0
    grand = t.total_cents + (0 if quote["tax_included"] else tax)
    unit_label = {"pcs": "件", "sets": "套"}.get(it["unit"], it["unit"])
    basis = "自收到 PO 起算" if quote["lead_basis"] == "po" else "自報價日起算"
    rate = (Decimal(str(quote["tax_rate"])) * 100).normalize()

    pdf = FPDF(format="A4", unit="mm")
    pdf.set_margins(18, 16, 18)
    pdf.set_auto_page_break(True, 18)
    pdf.add_font("tc", "", str(FONT_DIR / "NotoSansTC-Big5.otf"))
    pdf.add_font("tc", "B", str(FONT_DIR / "NotoSansTC-Big5-Bold.otf"))
    pdf.set_title(f"報價單 {quote['quote_no']} r{quote['quote_revision']}")
    pdf.set_author(vendor_name)
    pdf.add_page()
    w = pdf.epw

    # 抬頭
    pdf.set_text_color(*INK)
    pdf.set_font("tc", "B", 20)
    pdf.cell(w * 0.6, 10, f"{vendor_name}　報價單")
    pdf.set_font("tc", "", 10)
    pdf.set_text_color(*MUTED)
    pdf.cell(w * 0.4, 10, "QUOTATION", align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*ACCENT)
    pdf.set_line_width(0.8)
    pdf.line(pdf.l_margin, pdf.get_y() + 1, pdf.l_margin + w, pdf.get_y() + 1)
    pdf.ln(5)

    # 兩欄：客戶／報價資訊
    def kv(label: str, value: str, x: float, col_w: float) -> None:
        pdf.set_x(x)
        pdf.set_font("tc", "", 9)
        pdf.set_text_color(*MUTED)
        pdf.cell(24, 6.5, label)
        pdf.set_font("tc", "B", 10)
        pdf.set_text_color(*INK)
        pdf.cell(col_w - 24, 6.5, value, new_x="LMARGIN", new_y="NEXT")

    left = [
        ("客戶", CUSTOMER),
        ("聯絡人", rfq.get("contact_name") or "—"),
        ("詢價編號", rfq["rfq_number"]),
        ("規格版次", str(quote.get("rfq_revision") or rfq.get("spec_revision") or 1)),
    ]
    right = [
        ("報價單號", quote["quote_no"]),
        ("修訂", str(quote["quote_revision"])),
        ("報價日期", _d(quote["quote_date"])),
        ("有效期限", f"{_d(quote['valid_until'])}（含當天）"),
    ]
    y0 = pdf.get_y()
    for k, v in left:
        kv(k, v, pdf.l_margin, w * 0.58)
    y1 = pdf.get_y()
    pdf.set_y(y0)
    for k, v in right:
        kv(k, v, pdf.l_margin + w * 0.62, w * 0.38)
    pdf.set_y(max(y1, pdf.get_y()) + 5)

    # 明細
    cols = [("項次", 0.07, "C"), ("品名", 0.33, "L"), ("材質", 0.18, "L"), ("數量", 0.12, "R"), ("單價", 0.14, "R"), ("小計", 0.16, "R")]
    pdf.set_fill_color(245, 245, 244)
    pdf.set_draw_color(*LINE)
    pdf.set_line_width(0.2)
    pdf.set_font("tc", "B", 9)
    pdf.set_text_color(*INK)
    for name, frac, align in cols:
        pdf.cell(w * frac, 8, name, border="TB", align=align, fill=True)
    pdf.ln()
    pdf.set_font("tc", "", 9.5)
    row = ["1", it["part"], it["material"], f"{int(it['qty']):,} {unit_label}", _money(pl.to_cents(it["unit_price"]), cur), _money(t.subtotal_cents, cur)]
    heights = []
    for (name, frac, align), val in zip(cols, row):
        lines = pdf.multi_cell(w * frac, 6, val, dry_run=True, output="LINES")
        heights.append(len(lines) * 6)
    h = max(heights + [8])
    x, y = pdf.get_x(), pdf.get_y()
    for (name, frac, align), val in zip(cols, row):
        pdf.set_xy(x, y)
        pdf.multi_cell(w * frac, 6 if h > 8 else 8, val, align=align)
        x += w * frac
    pdf.set_xy(pdf.l_margin, y + h)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + w, pdf.get_y())
    pdf.ln(3)

    # 金額
    def total_row(label: str, value: str, bold: bool = False) -> None:
        pdf.set_x(pdf.l_margin + w * 0.55)
        pdf.set_font("tc", "B" if bold else "", 11 if bold else 9.5)
        pdf.set_text_color(*(INK if bold else MUTED))
        pdf.cell(w * 0.25, 7, label, align="R")
        pdf.set_text_color(*INK)
        pdf.cell(w * 0.20, 7, value, align="R", new_x="LMARGIN", new_y="NEXT")

    if quote["tax_included"]:
        total_row("合計（含稅）", _money(t.total_cents, cur), bold=True)
    else:
        total_row("合計（未稅）", _money(t.total_cents, cur))
        total_row(f"營業稅 {rate}%", _money(tax, cur))
        total_row("含稅總額", _money(grand, cur), bold=True)
    pdf.ln(4)

    # 條件
    terms = [
        ("稅別", "含稅" if quote["tax_included"] else f"未稅，營業稅 {rate}% 另計"),
        ("交期", f"{int(it['lead_days'])} 個工作天（{basis}）"),
    ]
    if quote.get("delivery_date"):
        terms.append(("承諾交貨日", _d(quote["delivery_date"])))
    terms.append(("幣別", cur))
    if quote.get("note"):
        terms.append(("備註", quote["note"]))
    pdf.set_draw_color(*LINE)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + w, pdf.get_y())
    pdf.ln(2)
    for k, v in terms:
        pdf.set_font("tc", "", 9)
        pdf.set_text_color(*MUTED)
        pdf.cell(24, 6.5, k)
        pdf.set_font("tc", "", 10)
        pdf.set_text_color(*INK)
        pdf.multi_cell(w - 24, 6.5, v, align="L", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(6)
    pdf.set_font("tc", "", 8)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(
        w,
        5,
        f"本報價單與系統送出的報價資料（詢價編號 {rfq['rfq_number']}、規格版次、報價單號 {quote['quote_no']}、修訂 {quote['quote_revision']}）內容一致。"
        "如有疑問請直接回覆報價信。",
        align="L",
    )
    return bytes(pdf.output())


def pdf_filename(quote: dict) -> str:
    return f"報價單_{quote['quote_no']}_r{quote['quote_revision']}.pdf"
