"""第 3 步 score-then-threshold：按 JSON 字段/单元格打 0–100 分，仅低分采纳 LM 提议。"""

from __future__ import annotations

import copy
import json
import re
from typing import Any

from paddle_ocr import config
from paddle_ocr.gate.gemma_vision_correct import _encode_cropped_jpg, _parse_gemma_json


_BAG_KEYS = frozenset({"engine_draft", "lm_draft", "lm_scores", "lm_adopted"})
_TABLE_CELL_ID = re.compile(r"^(table\d+):r(\d+)c(\d+)$")


def _strip_bag(payload: dict[str, Any]) -> dict[str, Any]:
    """
    函数名: _strip_bag
    作用: 去掉对照袋字段，避免引擎 JSON 嵌套自己。
    输入:
        payload (dict): 引擎或终稿 JSON。
    输出:
        dict: 不含 engine_draft / lm_* 的浅拷贝。
    """
    return {k: v for k, v in payload.items() if k not in _BAG_KEYS}


def iter_score_units(draft: dict[str, Any]) -> list[tuple[str, str]]:
    """
    函数名: iter_score_units
    作用: 列出打分单元：每个 string* 一格、每个 table* 单元格一格；禁止拆成 character。
    输入:
        draft (dict): 引擎 JSON（string*/table*）。
    输出:
        list[tuple[str, str]]: (unit_id, 引擎文本)；table 为 table1:r0c2。
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
    """
    函数名: _set_unit_text
    作用: 把一段文本写回同形 JSON 的 string* 或 table 单元格。
    输入:
        doc (dict): 待改的同形 JSON。
        unit_id (str): string1 或 table1:r0c2。
        text (str): 写入文本。
    输出: 无。
    """
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
    """
    函数名: _lookup_parsed
    作用: 从 LM JSON 取某单元：扁平 id 或嵌套 table[ri].cells[ci]。
    输入:
        parsed (dict): 解析后的 LM 对象。
        unit_id (str): string1 或 table1:r0c2。
    输出:
        Any: 该单元的值；找不到为 None。
    """
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
    """
    函数名: _as_score_item
    作用: 从 LM 单元抽出 0–100 整数分与 proposed；无分则不采纳。
    输入:
        value (Any): {score, proposed}、裸数字或裸字符串。
    输出:
        tuple: (score 或 None, proposed 文本)。
    """
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
    """
    函数名: _build_score_prompt
    作用: 构造按字段/单元格打分的 prompt；每个 id 一整段，禁止逐字。
    输入:
        engine (dict): 引擎 JSON。
    输出:
        str: 喂给 pic2str 的提示。
    """
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
    """
    函数名: _keep
    作用: 解析失败或无视觉时全部保留引擎草稿，job 不失败。
    输入:
        engine (dict): 引擎 JSON。
        lm_draft (Any): 提议稿；失败时默认 None。
    输出:
        dict: result / lm_draft / 空分数 / 空采纳列表。
    """
    clean = copy.deepcopy(_strip_bag(engine)) if isinstance(engine, dict) else {}
    return {
        "ok": True,
        "result": clean,
        "lm_draft": lm_draft,
        "lm_scores": {},
        "lm_adopted": [],
    }


def lm_similarity_score(
    pic: Any,
    rectangle: tuple[int, int, int, int] | None,
    engine_draft: dict[str, Any],
) -> dict[str, Any]:
    """
    函数名: lm_similarity_score
    作用: 多模态按 JSON 值打 0–100 分；仅 score < SIMILARITY_ADOPT_BELOW 且 proposed 非空才替换。
        不整份覆盖、不逐字打分、runner 不 load_model；异常则 keep 引擎草稿。
    输入:
        pic (bytes|Path|str|ndarray): 图片（同 PaddleOcr）。
        rectangle (tuple|None): OpenCV ROI (x, y, w, h)。
        engine_draft (dict): paddleocr-mcp 引擎 JSON 深拷贝。
    输出:
        dict: result（终稿）/ lm_draft（同形提议）/ lm_scores / lm_adopted。
    """
    engine = copy.deepcopy(_strip_bag(engine_draft)) if isinstance(engine_draft, dict) else {}
    try:
        from llm_lmstudio.models import has_vision
        import llm_lmstudio.facade as llm_facade
        if not has_vision():
            return _keep(engine)
        jpg = _encode_cropped_jpg(pic, rectangle)
        raw = llm_facade.pic2str(
            jpg,
            _build_score_prompt(engine),
            system=(
                "你是文档 OCR 校对员。看图给每个字段/单元格 0-100 整数分（像不像图上的字），"
                "可选 proposed 替换。禁止逐字打分。只输出 JSON。"
            ),
        )
        parsed = _parse_gemma_json(raw)
    except Exception:
        return _keep(engine)
    if not isinstance(parsed, dict):
        return _keep(engine)
    # 中文注释: 若顶层包在 scores 里且没有 string*/table*，则展开
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
        # 中文注释: 默认留引擎；只信低分尾且 proposed 非空
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
