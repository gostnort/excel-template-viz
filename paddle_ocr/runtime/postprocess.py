"""Convert PPStructure HTML / parsing blocks into PaddleOcr JSON pieces."""

from __future__ import annotations

from typing import Any

from paddle_ocr.runtime import OcrLine


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
                if not rows:
                    # content may be empty; fall through to table_res_list later
                    continue
                tables.append(rows)
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



def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if hasattr(value, "tolist"):
        try:
            return list(value.tolist())
        except Exception:
            pass
    if isinstance(value, (list, tuple)):
        return list(value)
    return []



def extract_lines(predict_result: Any) -> list[OcrLine]:
    """Parse field-OCR predict() output into OcrLine rows (legacy/debug)."""
    items: list[Any]
    if predict_result is None:
        return []
    if isinstance(predict_result, list):
        items = predict_result
    else:
        items = [predict_result]
    lines: list[OcrLine] = []
    for item in items:
        lines.extend(_lines_from_one(item))
    return lines



def _lines_from_one(item: Any) -> list[OcrLine]:
    data = _result_to_mapping(item)
    texts = _as_list(data.get("rec_texts") or data.get("texts"))
    scores = _as_list(data.get("rec_scores") or data.get("scores"))
    polys = _as_list(data.get("rec_polys") or data.get("dt_polys") or data.get("boxes"))
    if not texts and "ocr_result" in data:
        return extract_lines(data["ocr_result"])
    out: list[OcrLine] = []
    for i, text in enumerate(texts):
        t = "" if text is None else str(text)
        conf = 0.0
        if i < len(scores):
            try:
                conf = float(scores[i])
            except (TypeError, ValueError):
                conf = 0.0
        box: list[Any] = []
        if i < len(polys):
            box = _as_list(polys[i])
        out.append(OcrLine(text=t, confidence=conf, box=box))
    return out



def _result_to_mapping(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    for attr in ("json", "res", "data"):
        if hasattr(item, attr):
            val = getattr(item, attr)
            if callable(val):
                try:
                    val = val()
                except TypeError:
                    pass
            if isinstance(val, dict):
                if "res" in val and isinstance(val["res"], dict):
                    return val["res"]
                return val
    mapping: dict[str, Any] = {}
    for key in ("rec_texts", "rec_scores", "rec_polys", "dt_polys", "texts", "scores", "boxes"):
        if hasattr(item, key):
            mapping[key] = getattr(item, key)
    return mapping



def join_text(lines: list[OcrLine]) -> str:
    """Engine original text, reading order, newline-joined; no business cleanup."""
    parts = [ln.text for ln in lines if ln.text is not None]
    kept = [p for p in parts if str(p).strip() != ""]
    return "\n".join(kept)
