"""C3.3：gemma_only 档视觉纠错——Pic2Str 读图 + 逐单元择优合并（保结构）。

4GB ≤ 预算 < 10GB（或 10GB+ 无加速器）时，PaddleVL 不加载；Gemma4 先做语义检查，
有问题则走本模块：
  1) 从 fast 结果派生角色 character（如"机场地勤人员的遗失物品交接单"、"银行支票"）；
  2) Pic2Str 用该角色读图，得到 Gemma4 自己的同形 JSON（string*/table*）；
  3) 逐单元（string* / table* 每行/每格）文本裁判 fast vs gemma 择优；
  4) 合并保持 fast 的键/行数/列数不变，返回 mode="gemma_vision_corrected"。

幻觉策略（见 docs/embed_gemma4.md §3.1d 末段）：Pic2Str 对密集小字中文会"编出
通顺但与图不符的文字"。本模块接受该幻觉——角色 character 是关键约束，幻觉作为
语义上的"模糊/再创造"可接受；逐单元择优只在 gemma 明显更顺时替换 fast。
"""

from __future__ import annotations

import copy
import json
from typing import Any

from paddle_ocr import config
from paddle_ocr.runtime.image_decode import load_for_ocr



def _fast_to_text(fast: dict[str, Any]) -> str:
    """
    函数名: _fast_to_text
    作用: 把 fast 结果摊成可读文本，喂给 Gemma4 派生角色用。
    输入:
        fast (dict): fast 路径 §3.3 JSON（string*/table*）。
    输出:
        str: 每行一个单元的文本视图（string1: ... / table1:row1: ...）。
    """
    from paddle_ocr.gate.semantic_gate import iter_string_units
    lines: list[str] = []
    # 中文注释：string* 单元按 key 序输出。
    for key, text in iter_string_units(fast):
        lines.append(f"{key}: {text}")
    # 中文注释：table* 按 key 序展开每行。
    for key in sorted(fast):
        if not key.startswith("table"):
            continue
        rows = fast[key]
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            cells = " | ".join(str(c).strip() for c in (row.get("cells") or []) if str(c).strip())
            lines.append(f"{key}:row{row.get('row', '?')}: {cells}")
    return "\n".join(lines)



def _derive_character(fast: dict[str, Any]) -> str:
    """
    函数名: _derive_character
    作用: 调 ConversationOnce 让 Gemma4 从 fast 结果判断这份文档的类型/角色背景，
        返回一句中文角色描述（如"机场地勤人员的旅客遗失物品交接单"）。
        角色是后续 Pic2Str 与逐单元裁判的共同约束，幻觉可接受的前提。
    输入:
        fast (dict): fast 路径 §3.3 JSON。
    输出:
        str: 一句话角色描述。
    """
    import llm_gemma4.__main__ as gemma_main
    text = _fast_to_text(fast)
    prompt = (
        "下面是一份文档的快速 OCR 结果（可能有错字）。请判断这份文档的类型和角色"
        "背景，用一句中文描述（例如'机场地勤人员的旅客遗失物品交接单'、'银行支票'"
        "、'医院检验报告'）。只输出这一句角色描述，不要其他内容。\n"
        f"---\n{text}\n---"
    )
    return gemma_main.ConversationOnce(prompt).strip()



def _encode_cropped_jpg(pic: Any, rectangle: tuple[int, int, int, int] | None) -> bytes:
    """
    函数名: _encode_cropped_jpg
    作用: 解码 + 裁剪 → jpg 已编码字节。Pic2Str 要的是已编码图片字节（jpg/png 原始
        字节），不是解码后的像素数组（见 docs/embed_gemma4.md §3.1d ImageBytes）。
    输入:
        pic (bytes|Path|str|ndarray): 同 PaddleOcr 入参。
        rectangle (tuple|None): OpenCV ROI (x,y,w,h)。
    输出:
        bytes: jpg 编码字节。
    """
    import cv2
    img = load_for_ocr(pic, rectangle)
    ok, buf = cv2.imencode(".jpg", img)
    if not ok:
        raise RuntimeError("jpg encode failed")
    return buf.tobytes()



def _build_pic_prompt(fast: dict[str, Any]) -> str:
    """
    函数名: _build_pic_prompt
    作用: 构造要求 Pic2Str 输出"与 fast 同形 JSON"的 prompt。把期望的键、table 行列
        数写死，强制 Gemma4 输出可对齐的结构，便于第 3 步逐单元择优。
    输入:
        fast (dict): fast 路径 §3.3 JSON。
    输出:
        str: 喂给 Pic2Str 的文本提示。
    """
    shape: dict[str, str] = {}
    # 中文注释：string* 描述为"文本"。
    for k in sorted(fast):
        if k.startswith("string"):
            shape[k] = "文本"
    # 中文注释：table* 描述行列数，便于 Gemma4 对齐。
    for k in sorted(fast):
        if not k.startswith("table"):
            continue
        rows = fast[k]
        if not isinstance(rows, list):
            continue
        nrows = len(rows)
        ncols = len(rows[0].get("cells", [])) if nrows and isinstance(rows[0], dict) else 0
        shape[k] = f"数组，{nrows} 行 × {ncols} 列，每行 {{row, cells:[...]}}"
    shape_str = json.dumps(shape, ensure_ascii=False)
    return (
        "请仔细看这张图片，按下面的结构输出严格的 JSON（不要 markdown 围栏，"
        "不要任何解释，只输出 JSON 对象）：\n"
        f"{shape_str}\n"
        "key 与原结构一一对应；table 每行是 {\"row\": 行号, \"cells\": [单元格文本...]};"
        "行数和列数必须与给定结构完全一致；读不准的格子也填最可能的猜测，不要留空。"
    )



def _parse_gemma_json(text: str) -> dict[str, Any] | None:
    """
    函数名: _parse_gemma_json
    作用: 宽容解析 Gemma4 输出的 JSON——去 markdown 围栏、截首个 { 到末个 }、
        json.loads；任何一步失败返回 None（调用方回退保留 fast）。
    输入:
        text (str): Pic2Str 返回的原始文本。
    输出:
        dict | None: 解析成功返回 dict，否则 None。
    """
    s = text.strip()
    # 中文注释：去 ```json ... ``` 围栏。
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.strip()
    # 中文注释：截第一个 { 到最后一个 }，容忍前后噪声文字。
    lo = s.find("{")
    hi = s.rfind("}")
    if lo == -1 or hi == -1 or hi <= lo:
        return None
    try:
        obj = json.loads(s[lo:hi + 1])
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None



def _pick_better(fast_text: str, gemma_text: str, character: str, *, verbose: bool = False, unit_id: str = "") -> str:
    """
    函数名: _pick_better
    作用: 文本裁判（ConversationOnce，纯文本不看图）——在"这是{character}"语境下，
        A=fast / B=gemma 哪个更可能是正确的，只输出 A 或 B。歧义/异常时保守保留 fast。
        幻觉可接受：裁判挑"更顺/更合角色"的版本，正是本档要的语义再创造。
    输入:
        fast_text (str): fast 单元文本。
        gemma_text (str): gemma 单元文本。
        character (str): 派生角色描述。
        verbose (bool): True 时打印 A/B 原文 + 裁判回答 + 胜者（调试/测试用）。
        unit_id (str): 单元标识（如 "string1" / "table1:row0 cell1"），verbose 时打印。
    输出:
        str: 胜者文本。
    """
    import llm_gemma4.__main__ as gemma_main
    if not gemma_text:
        if verbose:
            print(f"    [pick {unit_id}] gemma 空 → 保留 fast: {fast_text!r}", flush=True)
        return fast_text
    if not fast_text:
        if verbose:
            print(f"    [pick {unit_id}] fast 空 → 用 gemma: {gemma_text!r}", flush=True)
        return gemma_text
    prompt = (
        f"这是「{character}」。下面同一段内容的两种 OCR 读数，哪个更可能是正确的？\n"
        f"A: {fast_text}\n"
        f"B: {gemma_text}\n"
        "只输出 A 或 B（仅字母）。"
    )
    ans = gemma_main.ConversationOnce(prompt).strip().upper()
    # 中文注释：取首字母；B 才替换，其余（A/歧义/异常）保守保留 fast。
    winner = "B" if ans.startswith("B") else "A"
    if verbose:
        print(f"    [pick {unit_id}] A(fast)={fast_text!r}", flush=True)
        print(f"                     B(gemma)={gemma_text!r}", flush=True)
        print(f"                     judge={ans!r} → winner={winner}", flush=True)
    return gemma_text if winner == "B" else fast_text



def GemmaVisionCorrect(
    pic: Any,
    rectangle: tuple[int, int, int, int] | None,
    fast: dict[str, Any],
    *,
    verbose: bool = False,
) -> dict[str, Any]:
    """
    函数名: GemmaVisionCorrect
    作用: gemma_only 档视觉纠错主流程——
        1) 从 fast 派生角色 character；
        2) Pic2Str 用该角色读图，得到 Gemma4 自己的同形 JSON；
        3) 逐单元（string* / table* 每格）文本裁判 fast vs gemma 择优；
        4) 合并保持 fast 的键/行数/列数不变，返回 mode="gemma_vision_corrected"。
        Gemma4 不可用 / 读图失败 / JSON 解析失败 → 保留 fast，标 MSG_LLM_PARTIAL。
    输入:
        pic (bytes|Path|str|ndarray): 原始图片（同 PaddleOcr 入参）。
        rectangle (tuple|None): OpenCV ROI (x,y,w,h)。
        fast (dict): fast 路径 §3.3 JSON。
        verbose (bool): True 时打印每步中间产物（角色 / Pic2Str 原文 / 解析后 JSON /
            逐单元 A/B 裁判），便于定位"死在哪一步"；生产默认 False。
    输出:
        dict: 与 fast 同形的纠错结果；ok/message/mode 标注。
    """
    out = copy.deepcopy(fast)
    # 中文注释：阶段一——派生角色 + 读图 + 解析；任一失败回退 fast。
    try:
        import llm_gemma4.__main__ as gemma_main
        character = _derive_character(fast)
        if verbose:
            print(f"    [derive character] {character!r}", flush=True)
        jpg = _encode_cropped_jpg(pic, rectangle)
        prompt = _build_pic_prompt(fast)
        raw = gemma_main.Pic2Str(jpg, prompt, system=f"你是文档 OCR 引擎。背景：{character}。")
        if verbose:
            print(f"    [Pic2Str raw] {raw!r}", flush=True)
        gemma = _parse_gemma_json(raw)
        if verbose:
            print(f"    [parsed gemma json] {gemma!r}", flush=True)
    except Exception as e:
        if verbose:
            print(f"    [stage1 exception] {e!r}", flush=True)
        out["message"] = config.MSG_LLM_PARTIAL
        return out
    if gemma is None:
        if verbose:
            print("    [parse failed] gemma=None → 保留 fast", flush=True)
        out["message"] = config.MSG_LLM_PARTIAL
        return out
    # 中文注释：阶段二——逐单元择优，保持 fast 结构（键/行数/列数不变）。
    for key in sorted(out):
        if key.startswith("string"):
            g = str(gemma.get(key) or "").strip()
            out[key] = _pick_better(str(out.get(key) or "").strip(), g, character, verbose=verbose, unit_id=key)
        elif key.startswith("table") and isinstance(out[key], list):
            gtable = gemma.get(key)
            if not isinstance(gtable, list):
                continue
            for ri, row in enumerate(out[key]):
                if not isinstance(row, dict) or ri >= len(gtable):
                    continue
                grow = gtable[ri]
                gcells = grow.get("cells") if isinstance(grow, dict) else None
                if not isinstance(gcells, list):
                    continue
                cells = list(row.get("cells") or [])
                # 中文注释：逐格择优，长度按 fast 为准（多出的 gemma 格丢弃，少的保留 fast）。
                for ci in range(min(len(cells), len(gcells))):
                    uid = f"{key}:row{ri} cell{ci}"
                    cells[ci] = _pick_better(str(cells[ci]).strip(), str(gcells[ci]).strip(), character, verbose=verbose, unit_id=uid)
                row["cells"] = cells
    out["mode"] = "gemma_vision_corrected"
    out["message"] = config.MSG_GEMMA_VISION
    return out
