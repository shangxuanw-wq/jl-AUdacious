"""把詢價信「規格與備註」裡的「欄位：內容」拆成條列（只給畫面用，不改原文）。

例：
    製程：CNC 三軸銑削
    表面處理：原色（加工面／列印原色）（黑色）
    公差與要求：外形 100.0 × 70.0 × 25.0 mm；未標註公差依一般加工公差，詳見 2D 圖。
    備註：無
→ [製程, 表面處理, 外形, 公差, 備註]，外形另外回傳給摘要卡用。
"""

from __future__ import annotations

import re

KEYS = ("製程", "表面處理", "公差與要求", "公差", "備註")
_LINE = re.compile(r"^\s*(" + "|".join(KEYS) + r")\s*[：:]\s*(.+?)\s*$")
_DIMS = re.compile(r"外形\s*([\d.]+\s*[×xX＊*]\s*[\d.]+(?:\s*[×xX＊*]\s*[\d.]+)?)\s*(mm|毫米)?", re.IGNORECASE)


def _norm_dims(raw: str) -> str:
    parts = [p.strip() for p in re.split(r"[×xX＊*]", raw)]
    return " × ".join(parts) + " mm"


def parse(spec_text: str | None) -> dict:
    """回傳 {"fields": [{"label", "value"}...], "dims": "100.0 × 70.0 × 25.0 mm" | None}。"""
    fields: list[dict] = []
    dims: str | None = None
    for line in (spec_text or "").splitlines():
        m = _LINE.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2)
        if key in ("公差與要求", "公差"):
            rest = []
            for piece in re.split(r"[；;]", val):
                piece = piece.strip().rstrip("。")
                if not piece:
                    continue
                d = _DIMS.search(piece)
                if d and dims is None:
                    dims = _norm_dims(d.group(1))
                    leftover = _DIMS.sub("", piece).strip(" ，,")
                    if leftover:
                        rest.append(leftover)
                else:
                    rest.append(piece)
            if dims:
                fields.append({"label": "外形", "value": dims})
            if rest:
                fields.append({"label": "公差", "value": "；".join(rest)})
            continue
        fields.append({"label": key, "value": val.rstrip("。")})
    return {"fields": fields, "dims": dims}
