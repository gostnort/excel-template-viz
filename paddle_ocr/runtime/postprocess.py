"""Convert PPStructure HTML / parsing blocks into PaddleOcr JSON pieces."""

from __future__ import annotations

from typing import Any


def HtmlTableToRows(html: str) -> list[dict[str, Any]]:
    """Parse PPStructure `pred_html` into [{row, cells}, ...].

    colspan/rowspan: cell text is kept once in the first spanned slot;
    extra covered slots are not invented (row length follows visible <td>s).
    """
    if not html or not str(html).strip():
        return []
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(str(html), "html.parser")
    rows: list[dict[str, Any]] = []
    for i, tr in enumerate(soup.find_all("tr"), start=1):
        cells: list[str] = []
        for td in tr.find_all(["td", "th"]):
            cells.append(td.get_text(strip=True))
        rows.append({"row": i, "cells": cells})
    return rows



def _block_label(block: Any) -> str:
    if isinstance(block, dict):
        return str(block.get("block_label") or block.get("label") or "")
    return str(getattr(block, "block_label", None) or getattr(block, "label", "") or "")



def _block_content(block: Any) -> str:
    if isinstance(block, dict):
        return str(block.get("block_content") or block.get("content") or "")
    return str(getattr(block, "block_content", None) or getattr(block, "content", "") or "")



def _block_bbox_y(block: Any) -> float:
    """Sort key: top of block bbox if present, else 0."""
    box = None
    if isinstance(block, dict):
        box = block.get("block_bbox") or block.get("bbox") or block.get("coordinate")
    else:
        box = getattr(block, "block_bbox", None) or getattr(block, "bbox", None)
    if box is None:
        return 0.0
    try:
        if hasattr(box, "tolist"):
            box = box.tolist()
        if isinstance(box, (list, tuple)) and len(box) >= 2:
            # [x1,y1,x2,y2] or [[x,y],...]
            if isinstance(box[0], (list, tuple)):
                return float(min(p[1] for p in box))
            return float(box[1])
    except Exception:
        return 0.0
    return 0.0



def StructureResultToJson(raw: Any, *, mode: str = "fast") -> dict[str, Any]:
    """Map one PPStructureV3 result object/dict to PaddleOcr JSON (string*/table*)."""
    from paddle_ocr import config
    data = _unwrap_structure(raw)
    strings: list[str] = []
    tables: list[list[dict[str, Any]]] = []
    # Prefer parsing_res_list order (layout reading order)
    blocks = data.get("parsing_res_list") or []
    if isinstance(blocks, list) and blocks:
        ordered = sorted(enumerate(blocks), key=lambda pair: (_block_bbox_y(pair[1]), pair[0]))
        for _, block in ordered:
            label = _block_label(block).lower()
            content = _block_content(block)
            if "table" in label:
                rows = HtmlTableToRows(content)
                if rows:
                    tables.append(rows)
                    continue
                # VL 的 OTSL→HTML 转换可能失败，block_content 留下非空原始文本。
                # 不丢内容：把非空 table 文本降级成 string*，避免表格被静默丢弃。
                fallback = content.strip()
                if fallback and not fallback.startswith("<html") and not fallback.startswith("<table"):
                    strings.append(fallback)
                continue
            else:
                text = content.strip()
                # Skip raw html leftovers
                if text.startswith("<html") or text.startswith("<table"):
                    continue
                if text:
                    strings.append(text)
    # Fill tables from table_res_list if parsing missed html
    if not tables:
        for item in data.get("table_res_list") or []:
            html = ""
            if isinstance(item, dict):
                html = str(item.get("pred_html") or "")
            else:
                html = str(getattr(item, "pred_html", "") or "")
            rows = HtmlTableToRows(html)
            if rows:
                tables.append(rows)
    # Fallback strings from overall OCR if nothing else
    if not strings and not tables:
        ocr = data.get("overall_ocr_res") or {}
        if isinstance(ocr, dict):
            texts = ocr.get("rec_texts") or []
            joined = "\n".join(str(t) for t in texts if str(t).strip())
            if joined:
                strings.append(joined)
    out: dict[str, Any] = {"ok": True, "mode": mode}
    for i, s in enumerate(strings, start=1):
        out[f"string{i}"] = s
    for i, rows in enumerate(tables, start=1):
        out[f"table{i}"] = rows
    if not strings and not tables:
        out["message"] = config.MSG_EMPTY
    else:
        out["message"] = config.MSG_OK
    return out



def _unwrap_structure(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, list):
        if not raw:
            return {}
        raw = raw[0]
    if isinstance(raw, dict):
        if "res" in raw and isinstance(raw["res"], dict):
            return raw["res"]
        return raw
    if hasattr(raw, "json"):
        j = raw.json
        if callable(j):
            try:
                j = j()
            except TypeError:
                pass
        if isinstance(j, dict):
            if "res" in j and isinstance(j["res"], dict):
                return j["res"]
            return j
    return {}



def HasContent(result: dict[str, Any]) -> bool:
    """True if any string* or non-empty table* rows exist."""
    for key, val in result.items():
        if key.startswith("string") and str(val).strip():
            return True
        if key.startswith("table") and isinstance(val, list) and len(val) > 0:
            return True
    return False



def FieldPredictToStringJson(raw: Any) -> dict[str, Any]:
    """Map PaddleOCR field predict() to minimal string1 JSON."""
    from paddle_ocr import config
    texts: list[str] = []
    items = raw if isinstance(raw, list) else [raw]
    for item in items:
        data = item
        if hasattr(item, "json"):
            payload = item.json
            data = payload() if callable(payload) else payload
        if isinstance(data, dict) and "res" in data and isinstance(data["res"], dict):
            data = data["res"]
        if not isinstance(data, dict):
            continue
        rec = data.get("rec_texts") or data.get("texts") or []
        if hasattr(rec, "tolist"):
            rec = rec.tolist()
        for text in rec:
            line = "" if text is None else str(text).strip()
            if line:
                texts.append(line)
    out: dict[str, Any] = {"ok": True, "mode": "fast"}
    if texts:
        out["string1"] = "\n".join(texts)
        out["message"] = config.MSG_OK
    else:
        out["message"] = config.MSG_EMPTY
    return out

