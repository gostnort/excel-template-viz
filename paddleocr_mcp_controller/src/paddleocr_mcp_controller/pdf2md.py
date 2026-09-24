"""PaddleOcr_PDF2MDs: split PDF into pages, write per-page Markdown.

Compressed from the old paddle_ocr/pdf2md/ package (split.py + text_page.py
+ image_page.py + api.py + __init__.py) into a single module.

Per-page routing in _convert_one_page (three branches):

1. has_native and not has_images:
   - _page_has_vector_table(pdfplumber) detects vector-drawn table grids.
   - Vector table + HasTableGrid(render) -> PP-StructureV3 (markdown table).
   - Otherwise -> pypdfium2 native text -> Markdown (no OCR, no Structure).
2. has_images: pdfplumber text + images interleaved by top; each image ->
   HasTableGrid -> Structure (chart) / OCR (textimg).
3. not has_native and not has_images: render whole page -> HasTableGrid ->
   Structure (chart) / OCR (textimg).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from paddleocr_mcp_controller import config
from paddleocr_mcp_controller.mcp_runtime import (
    stop_structure_mcp,
)


def _open_pdf(path: Path) -> Any:
    """open PDF document; caller must _close_pdf."""
    import pypdfium2 as pdfium
    return pdfium.PdfDocument(str(path))


def _close_pdf(doc: Any) -> None:
    if doc is None:
        return
    close = getattr(doc, "close", None)
    if close is not None:
        close()


def _page_count(doc: Any) -> int:
    return int(len(doc))


def _extract_page_text(page: Any) -> str:
    """extract copyable native text from one page (no OCR)."""
    textpage = page.get_textpage()
    try:
        getter = getattr(textpage, "get_text_range", None)
        if getter is not None:
            return str(getter() or "")
        return str(textpage.get_text_bounded() or "")
    finally:
        closer = getattr(textpage, "close", None)
        if closer is not None:
            closer()


def _compact_len(s: str) -> int:
    """length of string after stripping all whitespace."""
    return len("".join((s or "").split()))


def _pypdf_page_text(pdf_path: Path, page_index: int, cache: dict[str, Any]) -> str:
    """
    函数名: _pypdf_page_text
    作用: 用 pypdf 抽取指定页文本；reader 缓存在 cache 里避免每页重开。
    输入:
        pdf_path (Path): PDF 路径。
        page_index (int): 0-based 页码。
        cache (dict): 模块级缓存字典，键 'pypdf' 存 PdfReader。
    输出:
        str: 抽到的文本；不可用或失败返回空串。
    """
    # lazy import：pypdf 是可选回退依赖，缺失时直接返回空
    try:
        from pypdf import PdfReader
    except Exception:
        return ""
    # 复用缓存的 reader
    reader = cache.get("pypdf")
    if reader is None:
        try:
            reader = PdfReader(str(pdf_path))
        except Exception:
            return ""
        cache["pypdf"] = reader
    try:
        if 0 <= page_index < len(reader.pages):
            return str(reader.pages[page_index].extract_text() or "")
    except Exception:
        return ""
    return ""


def _pdfplumber_page_text(pdf_path: Path, page_index: int, cache: dict[str, Any]) -> str:
    """
    函数名: _pdfplumber_page_text
    作用: 用 pdfplumber 抽取指定页文本；pdf 对象缓存于 cache。
    输入:
        pdf_path (Path): PDF 路径。
        page_index (int): 0-based 页码。
        cache (dict): 模块级缓存字典，键 'pdfplumber' 存打开的 pdf 句柄。
    输出:
        str: 抽到的文本；不可用或失败返回空串。
    """
    # lazy import：pdfplumber 是可选回退依赖
    try:
        import pdfplumber
    except Exception:
        return ""
    pdf = cache.get("pdfplumber")
    if pdf is None:
        try:
            pdf = pdfplumber.open(str(pdf_path))
        except Exception:
            return ""
        cache["pdfplumber"] = pdf
    try:
        pages = pdf.pages
        if 0 <= page_index < len(pages):
            return str(pages[page_index].extract_text() or "")
    except Exception:
        return ""
    return ""


def _close_fallback_cache(cache: dict[str, Any]) -> None:
    """关闭回退提取器持有的文件句柄，避免句柄泄漏。"""
    # pdfplumber 需要显式 close
    pdf = cache.pop("pdfplumber", None)
    if pdf is not None:
        try:
            pdf.close()
        except Exception:
            pass
    # pypdf reader 无外部句柄，丢弃即可
    cache.pop("pypdf", None)


def _extract_page_text_best(
    page: Any,
    pdf_path: Path | None,
    page_index: int,
    cache: dict[str, Any] | None,
) -> str:
    """
    函数名: _extract_page_text_best
    作用: 先 pypdfium2 抽原生文本；去空白后字符数不足 PDF2MD_TEXT_CHAR_MIN 时，依次回退 pypdf、pdfplumber，返回最长的结果。
    输入:
        page: pypdfium2 PdfPage。
        pdf_path (Path|None): PDF 路径；None 则不做回退。
        page_index (int): 0-based 页码。
        cache (dict|None): 回退 reader 缓存；None 则每次新建（慢但无状态）。
    输出:
        str: 抽到的最长文本（可能为空串）。
    """
    # 第一手：pypdfium2 原生抽取
    best = _extract_page_text(page)
    best_len = _compact_len(best)
    # 已足够长，无需回退
    if best_len >= int(config.PDF2MD_TEXT_CHAR_MIN):
        return best
    # 没有 pdf_path 或 cache，无法回退
    if pdf_path is None:
        return best
    local_cache: dict[str, Any] = cache if cache is not None else {}
    # 依次回退：pypdf -> pdfplumber，取最长
    candidates = [best]
    t_pypdf = _pypdf_page_text(pdf_path, page_index, local_cache)
    if t_pypdf:
        candidates.append(t_pypdf)
    t_plumber = _pdfplumber_page_text(pdf_path, page_index, local_cache)
    if t_plumber:
        candidates.append(t_plumber)
    # 选去空白后最长的那个；并列时保留先到者优先
    winner = best
    winner_len = best_len
    for txt in candidates[1:]:
        n = _compact_len(txt)
        if n > winner_len:
            winner = txt
            winner_len = n
    return winner


def _page_has_images(page: Any) -> bool:
    """
    函数名: _page_has_images
    作用: 用 pypdfium2 page.get_images() 判断页是否引用了嵌入图片 XObject。
    输入:
        page: pypdfium2 PdfPage。
    输出:
        bool: 有嵌入图片返回 True；拿不到 API 或异常时返回 False。
    """
    # pypdfium2 的 get_images 在部分版本可能不存在或返回不同类型，统一 try
    try:
        imgs = page.get_images()
    except Exception:
        return False
    try:
        return len(list(imgs)) > 0
    except Exception:
        return bool(imgs)


def _pdfplumber_page(
    pdf_path: Path,
    page_index: int,
    cache: dict[str, Any] | None,
) -> Any:
    """
    函数名: _pdfplumber_page
    作用: 取 pdfplumber 的页对象；pdf 句柄缓存于 cache（与文本回退共用）。
    输入:
        pdf_path (Path): PDF 路径。
        page_index (int): 0-based 页码。
        cache (dict|None): 缓存字典；None 则临时打开（调用方需自行关闭）。
    输出:
        pdfplumber Page 或 None（不可用/越界）。
    """
    # lazy import：pdfplumber 是可选依赖
    try:
        import pdfplumber
    except Exception:
        return None
    local_cache: dict[str, Any] = cache if cache is not None else {}
    pdf = local_cache.get("pdfplumber")
    if pdf is None:
        try:
            pdf = pdfplumber.open(str(pdf_path))
        except Exception:
            return None
        local_cache["pdfplumber"] = pdf
    try:
        pages = pdf.pages
        if 0 <= page_index < len(pages):
            return pages[page_index]
    except Exception:
        return None
    return None


def _pdfplumber_text_lines(page: Any) -> list[tuple[float, str]]:
    """
    函数名: _pdfplumber_text_lines
    作用: 用 pdfplumber extract_words 按行聚合，返回 [(top, line_text), ...]；top 升序=从上到下。
    输入:
        page: pdfplumber Page。
    输出:
        list[tuple[float, str]]: 每行文本及其 top 坐标；无字返回空。
    """
    # 取词带位置；use_text_flow 让同行词不被切断
    try:
        words = page.extract_words(use_text_flow=True)
    except Exception:
        return []
    if not words:
        return []
    # 按 top 聚合成行（容差 3px）；同行词按 x0 排序拼回
    rows: list[tuple[float, list[tuple[float, str]]]] = []
    for w in words:
        top = float(w.get("top", 0.0))
        x0 = float(w.get("x0", 0.0))
        text = str(w.get("text", "") or "")
        placed = False
        # 倒序比较最近的行
        for idx in range(len(rows) - 1, -1, -1):
            row_top, items = rows[idx]
            if abs(row_top - top) <= 3.0:
                items.append((x0, text))
                placed = True
                break
            if row_top < top - 3.0:
                break
        if not placed:
            rows.append((top, [(x0, text)]))
    # 每行词按 x0 排序拼回
    out: list[tuple[float, str]] = []
    for top, items in rows:
        items.sort(key=lambda pair: pair[0])
        line = " ".join(t for _, t in items if t)
        if line.strip():
            out.append((top, line))
    return out


def _pdfplumber_images(page: Any) -> list[tuple[float, Any]]:
    """
    函数名: _pdfplumber_images
    作用: 从 pdfplumber page.images 解码嵌入图为 BGR ndarray，返回 [(top, img), ...]；过滤过小图。
    输入:
        page: pdfplumber Page。
    输出:
        list[tuple[float, ndarray]]: 每张图的 top 坐标与 BGR ndarray；解码失败/过小跳过。
    """
    import numpy as np
    try:
        raw_images = list(page.images)
    except Exception:
        return []
    out: list[tuple[float, Any]] = []
    for img_dict in raw_images:
        # 优先用 pdfplumber 已解码的 PIL image
        pil = img_dict.get("image")
        if pil is None:
            # 退而用 stream 解码
            stream = img_dict.get("stream")
            if stream is None:
                continue
            try:
                from PIL import Image
                import io
                data = stream.get_data() if hasattr(stream, "get_data") else bytes(stream)
                pil = Image.open(io.BytesIO(data))
            except Exception:
                continue
        try:
            arr = np.array(pil.convert("RGB"))
        except Exception:
            continue
        if arr.ndim != 3 or arr.shape[2] != 3:
            continue
        bgr = np.ascontiguousarray(arr[:, :, ::-1])
        h, w = bgr.shape[:2]
        if min(h, w) < int(config.PDF2MD_IMAGE_MIN_SIDE):
            continue
        top = float(img_dict.get("top", 0.0))
        out.append((top, bgr))
    return out


def _classify_image_grid(img: Any) -> str:
    """
    函数名: _classify_image_grid
    作用: 用 HasTableGrid 判断嵌入图是表/图表（有网格线）还是纯文本图。
    输入:
        img: BGR ndarray。
    输出:
        str: 'chart'（有网格→送 Structure）或 'text'（无网格→送 OCR）。
    """
    from paddleocr_mcp_controller.table_grid import HasTableGrid
    try:
        if HasTableGrid(img):
            return "chart"
    except Exception:
        pass
    return "text"


def _ocr_image_markdown(img: Any) -> str:
    """
    函数名: _ocr_image_markdown
    作用: 送 PaddleOcr（PP-OCRv6）识别嵌入图文本，拼成 markdown 字符串。
    输入:
        img: BGR ndarray。
    输出:
        str: 拼接后的 markdown；ok=False 或无文本返回空串。
    """
    from paddleocr_mcp_controller.mcp_runtime import call_ocr_mcp
    result = call_ocr_mcp(img)
    if not isinstance(result, dict) or not result.get("ok"):
        return ""
    # 收集 string1..stringN 文本
    parts: list[str] = []
    for key, val in result.items():
        if key.startswith("string") and isinstance(val, str) and val.strip():
            parts.append(val.strip())
    return "\n\n".join(parts)


def _structure_image_markdown(img: Any) -> str:
    """
    函数名: _structure_image_markdown
    作用: 送 PP-StructureV3 识别嵌入图（表/图表），把 string*/table* 拼成 markdown。
    输入:
        img: BGR ndarray。
    输出:
        str: 拼接后的 markdown；ok=False 或无内容返回空串。
    """
    from paddleocr_mcp_controller.mcp_runtime import call_structure_mcp
    result = call_structure_mcp(img, mode="structure")
    if not isinstance(result, dict) or not result.get("ok"):
        return ""
    parts: list[str] = []
    for key, val in result.items():
        if key.startswith("string") and isinstance(val, str) and val.strip():
            parts.append(val.strip())
        elif key.startswith("table") and isinstance(val, list):
            # 把 table 行渲染成 markdown 表格
            md = _table_rows_to_markdown(val)
            if md:
                parts.append(md)
    return "\n\n".join(parts)


def _table_rows_to_markdown(rows: list[dict[str, Any]]) -> str:
    """
    函数名: _table_rows_to_markdown
    作用: 把 HtmlTableToRows 的 [{row, cells}, ...] 渲染成 markdown 表格字符串。
    输入:
        rows (list[dict]): 每项 {row:int, cells:list[str]}。
    输出:
        str: markdown 表格；空行表返回空串。
    """
    if not rows:
        return ""
    # 取最大列数对齐
    max_cols = 0
    for r in rows:
        cells = r.get("cells") or []
        if len(cells) > max_cols:
            max_cols = len(cells)
    if max_cols == 0:
        return ""
    lines: list[str] = []
    header = (rows[0].get("cells") or []) + [""] * (max_cols - len(rows[0].get("cells") or []))
    lines.append("| " + " | ".join(c.replace("|", "\\|") for c in header) + " |")
    lines.append("| " + " | ".join("---" for _ in range(max_cols)) + " |")
    for r in rows[1:]:
        cells = (r.get("cells") or []) + [""] * (max_cols - len(r.get("cells") or []))
        lines.append("| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |")
    return "\n".join(lines)


def _text_to_markdown(raw: str) -> str:
    """compress native text into Markdown paragraphs (no invented headings)."""
    lines = [line.rstrip() for line in str(raw or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    out: list[str] = []
    blank = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if out and not blank:
                out.append("")
                blank = True
            continue
        out.append(stripped)
        blank = False
    if not out:
        return ""
    return "\n".join(out).rstrip() + "\n"


def _render_page_bgr(page: Any) -> Any:
    """render PDF page to OpenCV BGR ndarray at PDF2MD_RENDER_DPI."""
    import numpy as np
    scale = float(config.PDF2MD_RENDER_DPI) / 72.0
    bitmap = page.render(scale=scale)
    try:
        arr = np.asarray(bitmap.to_numpy())
    finally:
        closer = getattr(bitmap, "close", None)
        if closer is not None:
            closer()
    if arr.ndim != 3 or arr.shape[2] not in (3, 4):
        raise RuntimeError(config.MSG_PDF2MD_PAGE_FAIL)
    # pypdfium2 default BGRA; drop alpha -> BGR. 3-channel RGB -> flip to BGR.
    if arr.shape[2] == 4:
        bgr = arr[:, :, :3]
    else:
        bgr = arr[:, :, ::-1]
    return np.ascontiguousarray(bgr)


def _page_has_vector_table(plumber_page: Any) -> bool:
    """
    函数名: _page_has_vector_table
    作用: 用 pdfplumber 矢量几何判断页面是否含有表格网格（多条水平边+多条垂直边交叉）。不渲染不 OCR，轻量启发式。
    输入:
        plumber_page: pdfplumber Page 对象；None 直接返回 False。
    输出:
        bool: 检测到表格网格（≥3 条去重水平边 且 ≥3 条去重垂直边）返回 True；否则 False。
    """
    if plumber_page is None:
        return False
    # 取 page.edges（由 lines/rects 等聚合的边集合）；缺失则回退 lines+rects
    try:
        edges = list(plumber_page.edges)
    except Exception:
        edges = []
    if not edges:
        try:
            for ln in list(plumber_page.lines):
                edges.append(ln)
        except Exception:
            pass
        try:
            for rc in list(plumber_page.rects):
                edges.append(rc)
        except Exception:
            pass
    if not edges:
        return False
    # 收集水平边(y0≈y1)的 y 中心与垂直边(x0≈x1)的 x 中心；按 2px 容差分桶去重
    h_ys: set[float] = set()
    v_xs: set[float] = set()
    for e in edges:
        try:
            x0 = float(e["x0"]); y0 = float(e["y0"])
            x1 = float(e["x1"]); y1 = float(e["y1"])
        except Exception:
            continue
        # 水平边：y 几乎不变、x 跨度足够长
        if abs(y0 - y1) <= 1.5 and abs(x1 - x0) > 5.0:
            yc = round((y0 + y1) / 2 / 2.0) * 2.0
            h_ys.add(yc)
        # 垂直边：x 几乎不变、y 跨度足够长
        elif abs(x0 - x1) <= 1.5 and abs(y1 - y0) > 5.0:
            xc = round((x0 + x1) / 2 / 2.0) * 2.0
            v_xs.add(xc)
    return len(h_ys) >= 3 and len(v_xs) >= 3


def _resolve_output_dir(file_path: Path, output_path: str | Path | None) -> Path:
    """
    函数名: _resolve_output_dir
    作用: None/empty -> PDF 同名文件夹; '.' -> PDF parent dir; other -> given dir.
    输入:
        file_path (Path): PDF path.
        output_path (str|Path|None): caller OutputPath.
    输出:
        Path: output directory (created if missing).
    """
    # None 或空字符串 -> PDF 同名文件夹
    if output_path is None:
        raw = ""
    else:
        raw = str(output_path).strip()
    if raw == "":
        target = file_path.resolve().parent / file_path.stem
    elif raw == ".":
        target = file_path.resolve().parent
    else:
        target = Path(raw)
    target.mkdir(parents=True, exist_ok=True)
    return target


def _page_md_path(output_dir: Path, stem: str, page: int) -> Path:
    name = config.PDF2MD_PAGE_NAME.format(stem=stem, page=page)
    return output_dir / name


def _write_page_md(path: Path, markdown: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(markdown or ""), encoding="utf-8")


def _convert_one_page(
    page: Any,
    *,
    page_no: int,
    output_dir: Path,
    stem: str,
    structure_used: list[bool],
    ocr_used: list[bool],
    write_page: bool,
    pdf_path: Path | None = None,
    fallback_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    函数名: _convert_one_page
    作用: 三分支路由转换一页：纯文本页直接抽文本；有嵌入图页按位置交错文本块与各图(网格→Structure/无网格→OCR)；矢量轮廓页渲染整页后按网格判断走 Structure 或 OCR。
    输入:
        page: PdfPage。
        page_no (int): 1-based 页码。
        output_dir (Path): 输出目录。
        stem (str): PDF stem。
        structure_used (list[bool]): 单元素标志，Structure 被启动过则置 True。
        ocr_used (list[bool]): 单元素标志，OCR 被使用过则置 True（仅记录，不 stop）。
        write_page (bool): True -> 写每页 .md；False -> 只返回 markdown。
        pdf_path (Path|None): PDF 路径，用于文本回退与 pdfplumber 取图。
        fallback_cache (dict|None): 回退 reader 缓存，跨页复用。
    输出:
        dict: page / kind / path / ok / message / markdown。
    """
    page_index = page_no - 1
    # 原生文本（pypdfium2 + 回退）；分支判断与分支1/2 文本来源共用
    native_text = _extract_page_text_best(page, pdf_path, page_index, fallback_cache)
    has_native = _compact_len(native_text) >= int(config.PDF2MD_TEXT_CHAR_MIN)
    has_images = _page_has_images(page)
    md = ""
    kind = "text"
    message = config.MSG_PDF2MD_PAGE_OK
    # 分支1：纯文本页（有原生文本且无嵌入图）-> 先检测矢量表格网格
    if has_native and not has_images:
        # 检测矢量绘制的表格网格；命中则渲染整页走 Structure，否则原生抽文本
        took_structure = False
        vector_table = False
        if pdf_path is not None:
            pl_page = _pdfplumber_page(pdf_path, page_index, fallback_cache)
            vector_table = _page_has_vector_table(pl_page)
        if vector_table:
            # 渲染整页 -> HasTableGrid 确认 -> Structure 或回退文本
            try:
                img = _render_page_bgr(page)
            except Exception:
                img = None
            if img is not None and _classify_image_grid(img) == "chart":
                kind = "chart"
                structure_used[0] = True
                took_structure = True
                md = _structure_image_markdown(img)
            else:
                # 矢量几何命中但渲染网格未确认 -> 回退原生抽文本
                md = _text_to_markdown(native_text)
                kind = "text"
        else:
            md = _text_to_markdown(native_text)
            kind = "text"
        if not took_structure and not md.strip():
            # 文本抽取有长度但全是空白符号等异常，退为矢量轮廓处理
            has_native = False
    # 分支2：有嵌入图 -> 文本块与各图按 top 交错
    # 用 elif 与分支1/3 互斥：分支1 可能把 has_native 置 False 以故意落到分支3，
    # 此处 has_images 仍为 False 故会跳过，再到分支3，保留该有意落空。
    elif has_images:
        kind = "mixed"
        md = _convert_page_with_images(
            page,
            native_text=native_text,
            pdf_path=pdf_path,
            page_index=page_index,
            fallback_cache=fallback_cache,
            structure_used=structure_used,
            ocr_used=ocr_used,
        )
    # 分支3：矢量轮廓页（无原生文本且无嵌入图）-> 渲染整页后按网格判断
    elif not has_native and not has_images:
        kind = "textimg"
        try:
            img = _render_page_bgr(page)
        except Exception:
            return {
                "page": page_no,
                "kind": kind,
                "path": "",
                "ok": False,
                "message": config.MSG_PDF2MD_PAGE_FAIL,
                "markdown": "",
            }
        if _classify_image_grid(img) == "chart":
            kind = "chart"
            structure_used[0] = True
            md = _structure_image_markdown(img)
        else:
            ocr_used[0] = True
            md = _ocr_image_markdown(img)
    # 合并模式：不写每页文件，只返回 markdown 文本
    if not write_page:
        return {
            "page": page_no,
            "kind": kind,
            "path": "",
            "ok": True,
            "message": message,
            "markdown": md,
        }
    out_path = _page_md_path(output_dir, stem, page_no)
    try:
        _write_page_md(out_path, md)
    except Exception:
        return {
            "page": page_no,
            "kind": kind,
            "path": "",
            "ok": False,
            "message": config.MSG_PDF2MD_PAGE_FAIL,
            "markdown": md,
        }
    return {
        "page": page_no,
        "kind": kind,
        "path": str(out_path),
        "ok": True,
        "message": message,
        "markdown": md,
    }


def _convert_page_with_images(
    page: Any,
    *,
    native_text: str,
    pdf_path: Path | None,
    page_index: int,
    fallback_cache: dict[str, Any] | None,
    structure_used: list[bool],
    ocr_used: list[bool],
) -> str:
    """
    函数名: _convert_page_with_images
    作用: 分支2 核心——用 pdfplumber 取文本行(top)与嵌入图(top)，按 top 升序交错；每图网格判断走 Structure 或 OCR；连续文本行聚成段落。pdfplumber 不可用则退化为"原生文本在前+图片在后"。
    输入:
        page: pypdfium2 PdfPage（仅用于回退）。
        native_text (str): 已抽到的原生文本（pdfplumber 不可用时的文本来源）。
        pdf_path (Path|None): PDF 路径。
        page_index (int): 0-based 页码。
        fallback_cache (dict|None): pdfplumber 句柄缓存。
        structure_used (list[bool]): Structure 使用标志。
        ocr_used (list[bool]): OCR 使用标志。
    输出:
        str: 拼接后的页 markdown。
    """
    text_lines: list[tuple[float, str]] = []
    images: list[tuple[float, Any]] = []
    # 尝试用 pdfplumber 拿带位置的文本行与嵌入图
    if pdf_path is not None:
        pl_page = _pdfplumber_page(pdf_path, page_index, fallback_cache)
        if pl_page is not None:
            text_lines = _pdfplumber_text_lines(pl_page)
            images = _pdfplumber_images(pl_page)
    # 退化：pdfplumber 拿不到位置 -> 原生文本作一个 top=0 块，图片按拿到的顺序
    if not text_lines and native_text.strip():
        text_lines = [(0.0, native_text)]
    # 统一成 (top, kind, content) 列表并按 top 升序（从上到下）
    items: list[tuple[float, str, Any]] = []
    for top, line in text_lines:
        items.append((top, "text", line))
    for top, img in images:
        items.append((top, "image", img))
    items.sort(key=lambda triple: triple[0])
    # 按顺序交错：连续文本行聚成段落，遇图则先冲掉已攒文本行再处理图
    blocks: list[str] = []
    pending_lines: list[str] = []
    for top, ikind, content in items:
        if ikind == "text":
            pending_lines.append(str(content))
            continue
        # image：先冲掉已攒的文本行
        if pending_lines:
            blocks.append(_text_to_markdown("\n".join(pending_lines)))
            pending_lines = []
        img_md = _process_one_image(content, structure_used, ocr_used)
        if img_md:
            blocks.append(img_md)
    if pending_lines:
        blocks.append(_text_to_markdown("\n".join(pending_lines)))
    return "\n\n".join(b for b in blocks if b.strip())


def _process_one_image(
    img: Any,
    structure_used: list[bool],
    ocr_used: list[bool],
) -> str:
    """
    函数名: _process_one_image
    作用: 对单张嵌入图做网格判断：chart->Structure，text->OCR；返回该图的 markdown 片段。
    输入:
        img: BGR ndarray。
        structure_used (list[bool]): Structure 使用标志（命中则置 True）。
        ocr_used (list[bool]): OCR 使用标志（命中则置 True）。
    输出:
        str: 图的 markdown 片段；识别失败返回空串。
    """
    grid = _classify_image_grid(img)
    if grid == "chart":
        structure_used[0] = True
        return _structure_image_markdown(img)
    ocr_used[0] = True
    return _ocr_image_markdown(img)


def PaddleOcr_PDF2MDs(FilePath, OutputPath=None, multipages=True) -> dict[str, Any]:
    """
    函数名: PaddleOcr_PDF2MDs
    作用: split PDF into per-page Markdown or one combined Markdown; text pages native extract, image/scan pages via PP-StructureV3.
    输入:
        FilePath (str|Path): PDF input path.
        OutputPath (str|Path|None): None/empty -> PDF 同名文件夹; '.' -> PDF parent dir; other -> that dir.
        multipages (bool): True -> one .md per page ({stem}_p{page:04d}.md); False -> merge all pages into one {stem}.md.
    输出:
        dict: ok / message / output_dir / pages[, combined_path]. multipages=False 时额外返回 combined_path。
    """
    src = Path(FilePath)
    if not src.is_file():
        return {"ok": False, "message": config.MSG_PDF2MD_BAD_FILE, "output_dir": "", "pages": []}
    out_dir = _resolve_output_dir(src, OutputPath)
    stem = src.stem
    doc = None
    structure_used = [False]
    ocr_used = [False]
    fallback_cache: dict[str, Any] = {}
    pages: list[dict[str, Any]] = []
    try:
        try:
            doc = _open_pdf(src)
        except Exception:
            return {"ok": False, "message": config.MSG_PDF2MD_BAD_FILE, "output_dir": str(out_dir), "pages": []}
        n = _page_count(doc)
        for index in range(n):
            page = doc[index]
            pages.append(_convert_one_page(
                page,
                page_no=index + 1,
                output_dir=out_dir,
                stem=stem,
                structure_used=structure_used,
                ocr_used=ocr_used,
                write_page=bool(multipages),
                pdf_path=src,
                fallback_cache=fallback_cache,
            ))
    finally:
        _close_pdf(doc)
        _close_fallback_cache(fallback_cache)
        # OCR 子进程按 controller 既定约定懒启动常驻，这里不 stop
        if structure_used[0]:
            stop_structure_mcp()
    if not pages:
        return {"ok": False, "message": config.MSG_PDF2MD_BAD_FILE, "output_dir": str(out_dir), "pages": []}
    all_ok = all(bool(item.get("ok")) for item in pages)
    message = config.MSG_PDF2MD_OK if all_ok else config.MSG_PDF2MD_PARTIAL
    # 每页一个文件：返回结构同旧版（额外带 markdown 字段）
    if multipages:
        return {"ok": all_ok, "message": message, "output_dir": str(out_dir), "pages": pages}
    # 合并模式：按页码顺序用分页符拼接所有页 markdown，写一个 {stem}.md
    combined_path = out_dir / f"{stem}.md"
    parts: list[str] = []
    for item in pages:
        md = str(item.get("markdown") or "")
        if not md.strip():
            continue
        parts.append(md.rstrip("\n"))
    combined_md = "\n\n---\n\n".join(parts)
    if combined_md:
        combined_md += "\n"
    try:
        _write_page_md(combined_path, combined_md)
    except Exception:
        return {"ok": False, "message": config.MSG_PDF2MD_PAGE_FAIL, "output_dir": str(out_dir), "pages": pages}
    return {
        "ok": all_ok,
        "message": message,
        "output_dir": str(out_dir),
        "pages": pages,
        "combined_path": str(combined_path),
    }


def main(argv: list[str] | None = None) -> int:
    """
    函数名: main
    作用: standalone CLI: --input PDF, optional --output dir.
    输入:
        argv (list[str]|None): args; None uses sys.argv[1:].
    输出:
        int: 0 success, 1 failure.
    """
    parser = argparse.ArgumentParser(prog="python -m paddleocr_mcp_controller.pdf2md", add_help=True)
    parser.add_argument("--input", required=True, help="PDF input path")
    parser.add_argument("--output", default=None, help="Markdown output directory; default PDF 同名文件夹")
    parser.add_argument(
        "--multipages",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="True=每页一个文件; --no-multipages=合并成一个文件",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    result = PaddleOcr_PDF2MDs(args.input, args.output, args.multipages)
    print(result.get("message") or "")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
