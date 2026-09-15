"""扫描/图片页：渲染后走 PP-StructureV3 Markdown。"""

from __future__ import annotations

from typing import Any

import numpy as np

from paddle_ocr import config
from paddle_ocr.mcp_runtime import call_structure_markdown


def render_page_bgr(page: Any) -> Any:
    """
    函数名: render_page_bgr
    作用: 按配置 DPI 把 PDF 页渲染成 OpenCV BGR ndarray。
    输入:
        page: PdfPage。
    输出:
        ndarray: 连续 BGR uint8。
    """
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
    # 中文注释：pypdfium2 默认 BGRA；裁掉 alpha 即 BGR。三通道视为 RGB 再翻成 BGR。
    if arr.shape[2] == 4:
        bgr = arr[:, :, :3]
    else:
        bgr = arr[:, :, ::-1]
    return np.ascontiguousarray(bgr)


def page_structure_markdown(page: Any) -> str:
    """
    函数名: page_structure_markdown
    作用: 渲染一页并调用 PP-StructureV3，返回 Markdown 原文。
    输入:
        page: PdfPage。
    输出:
        str: markdown。
    """
    img = render_page_bgr(page)
    return call_structure_markdown(img)
