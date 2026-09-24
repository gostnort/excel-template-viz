"""LM similarity scoring: per-field/per-cell 0-100 score, adopt proposed only below threshold.

Standalone: no hard dependency on llm_lmstudio. The caller injects a vision_fn
(image_bytes, prompt, system) -> str. If vision_fn is None, scoring is skipped.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any, Callable

from paddleocr_mcp_controller import config


_BAG_KEYS = frozenset({"engine_draft", "lm_draft", "lm_scores", "lm_adopted"})
_TABLE_CELL_ID = re.compile(r"^(table\d+):r(\d+)c(\d+)$")


VisionFn = Callable[[bytes, str, str], str]


def _strip_bag(payload: dict[str, Any]) -> dict[str, Any]:
    """remove bag fields to avoid self-nesting."""
    return {k: v for k, v in payload.items() if k not in _BAG_KEYS}


def iter_score_units(draft: dict[str, Any]) -> list[tuple[str, str]]:
    """
    函数名: iter_score_units
    作用: list scoring units: each string* one unit, each table* cell one unit.
    输入:
        draft (dict): engine JSON (string*/table*).
    输出:
        list[tuple[str, str]]: (unit_id, engine text); table as table1:r0c2.
    """
    units: list[tuple[str, str]] = []
    for key in sorted(draft):
        if key.startswith("string"):
            units.append((key, str(draft.get(key) or "")))
            continue
        if not key.startswith("table"):
            continue
        table = draft.get(key)
        if not isinstance(table, list):
            continue
        for ri, row in enumerate(table):
            if not isinstance(row, dict):
                continue
            cells = row.get("cells")
            if not isinstance(cells, list):
                continue
            for ci, cell in enumerate(cells):
                units.append((f"{key}:r{ri}c{ci}", str(cell)))
    return units


def _set_unit_text(doc: dict[str, Any], unit_id: str, text: str) -> None:
    """write text back into same-shape JSON string* or table cell."""
    if unit_id.startswith("string"):
        doc[unit_id] = text
        return
    matched = _TABLE_CELL_ID.match(unit_id)
    if matched is None:
        return
    table_key = matched.group(1)
    ri = int(matched.group(2))
    ci = int(matched.group(3))
    table = doc.get(table_key)
    if not isinstance(table, list) or ri < 0 or ri >= len(table):
        return
    row = table[ri]
    if not isinstance(row, dict):
        return
    cells = list(row.get("cells") or [])
    if ci < 0 or ci >= len(cells):
        return
    cells[ci] = text
    row["cells"] = cells


def _lookup_parsed(parsed: dict[str, Any], unit_id: str) -> Any:
    """fetch a unit from LM JSON: flat id or nested table[ri].cells[ci]."""
    if unit_id in parsed:
        return parsed[unit_id]
    matched = _TABLE_CELL_ID.match(unit_id)
    if matched is None:
        return None
    table_key = matched.group(1)
    ri = int(matched.group(2))
    ci = int(matched.group(3))
    table = parsed.get(table_key)
    if not isinstance(table, list) or ri < 0 or ri >= len(table):
        return None
    row = table[ri]
    cells = None
    if isinstance(row, dict):
        cells = row.get("cells")
    elif isinstance(row, list):
        cells = row
    if not isinstance(cells, list) or ci < 0 or ci >= len(cells):
        return None
    return cells[ci]


def _as_score_item(value: Any) -> tuple[int | None, str]:
    """extract 0-100 int score and proposed from LM cell."""
    if isinstance(value, dict):
        proposed = str(value.get("proposed") or "").strip()
        raw = value.get("score")
        try:
            score = int(round(float(raw)))
        except (TypeError, ValueError):
            return None, proposed
        return max(0, min(100, score)), proposed
    if isinstance(value, bool):
        return None, ""
    if isinstance(value, (int, float)):
        return max(0, min(100, int(round(float(value))))), ""
    if isinstance(value, str):
        return None, value.strip()
    return None, ""


def _build_score_prompt(engine: dict[str, Any]) -> str:
    """build per-field/per-cell scoring prompt."""
    units = [{"id": key, "engine": text} for key, text in iter_score_units(engine)]
    units_json = json.dumps(units, ensure_ascii=False)
    return (
        "请看图，对照下列 OCR 引擎读数。对每个 id 给出 0-100 整数分数"
        "（该整段文字有多像图上对应位置），以及可选 proposed 替换（仅当非常不像时给出）。"
        "禁止逐字/逐 character 打分；每个 id 是一个字段或一个单元格整段。"
        "只输出 JSON 对象，不要 markdown。"
        "格式：每个 id 为键，值为 {\"score\": 0-100, \"proposed\": \"替换或空串\"}。\n"
        f"{units_json}"
    )


def _keep(engine: dict[str, Any], *, lm_draft: Any = None) -> dict[str, Any]:
    """on parse failure or no vision: keep engine draft, job does not fail."""
    clean = copy.deepcopy(_strip_bag(engine)) if isinstance(engine, dict) else {}
    return {
        "ok": True,
        "result": clean,
        "lm_draft": lm_draft,
        "lm_scores": {},
        "lm_adopted": [],
    }


def _encode_cropped_jpg(pic: Any, rectangle: tuple[int, int, int, int] | None) -> bytes:
    """
    函数名: _encode_cropped_jpg
    作用: decode + crop -> jpg-encoded bytes. vision_fn wants encoded image bytes.
    输入:
        pic (bytes|Path|str|ndarray): same as run_ocr_job input.
        rectangle (tuple|None): OpenCV ROI (x,y,w,h).
    输出:
        bytes: jpg-encoded bytes.
    """
    import cv2
    from paddleocr_mcp_controller.image_decode import load_for_ocr
    img = load_for_ocr(pic, rectangle)
    ok, buf = cv2.imencode(".jpg", img)
    if not ok:
        raise RuntimeError("jpg encode failed")
    return buf.tobytes()


def _parse_json_text(text: str) -> dict[str, Any] | None:
    """
    函数名: _parse_json_text
    作用: lenient parse of LM JSON output: strip markdown fence, cut first { to last }, json.loads.
    输入:
        text (str): raw text from vision_fn.
    输出:
        dict | None: parsed dict or None.
    """
    s = text.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.strip()
    lo = s.find("{")
    hi = s.rfind("}")
    if lo == -1 or hi == -1 or hi <= lo:
        return None
    try:
        obj = json.loads(s[lo:hi + 1])
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def lm_similarity_score(
    pic: Any,
    rectangle: tuple[int, int, int, int] | None,
    engine_draft: dict[str, Any],
    *,
    vision_fn: VisionFn | None = None,
) -> dict[str, Any]:
    """
    函数名: lm_similarity_score
    作用: multimodal per-JSON-value 0-100 scoring; only score < SIMILARITY_ADOPT_BELOW
        and non-empty proposed replaces. No full overwrite, no per-char scoring,
        no load_model. On exception keep engine draft.
    输入:
        pic (bytes|Path|str|ndarray): image (same as run_ocr_job).
        rectangle (tuple|None): OpenCV ROI (x,y,w,h).
        engine_draft (dict): paddleocr-mcp engine JSON deep copy.
        vision_fn (VisionFn|None): callable (image_bytes, prompt, system) -> str.
            If None, scoring is skipped and engine draft is kept.
    输出:
        dict: result / lm_draft / lm_scores / lm_adopted.
    """
    engine = copy.deepcopy(_strip_bag(engine_draft)) if isinstance(engine_draft, dict) else {}
    if vision_fn is None:
        return _keep(engine)
    try:
        jpg = _encode_cropped_jpg(pic, rectangle)
        raw = vision_fn(
            jpg,
            _build_score_prompt(engine),
            (
                "你是文档 OCR 校对员。看图给每个字段/单元格 0-100 整数分（像不像图上的字），"
                "可选 proposed 替换。禁止逐字打分。只输出 JSON。"
            ),
        )
        parsed = _parse_json_text(raw)
    except Exception:
        return _keep(engine)
    if not isinstance(parsed, dict):
        return _keep(engine)
    nested = parsed.get("scores")
    has_units = any(str(k).startswith("string") or str(k).startswith("table") for k in parsed)
    if isinstance(nested, dict) and not has_units:
        parsed = nested
    lm_draft = copy.deepcopy(engine)
    result = copy.deepcopy(engine)
    scores: dict[str, int] = {}
    adopted: list[str] = []
    threshold = int(config.SIMILARITY_ADOPT_BELOW)
    for unit_id, _engine_text in iter_score_units(engine):
        item = _lookup_parsed(parsed, unit_id)
        if item is None:
            continue
        score, proposed = _as_score_item(item)
        if score is not None:
            scores[unit_id] = score
        if proposed:
            _set_unit_text(lm_draft, unit_id, proposed)
        if score is None or proposed == "":
            continue
        if score >= threshold:
            continue
        _set_unit_text(result, unit_id, proposed)
        adopted.append(unit_id)
    return {
        "ok": True,
        "result": result,
        "lm_draft": lm_draft,
        "lm_scores": scores,
        "lm_adopted": adopted,
    }
