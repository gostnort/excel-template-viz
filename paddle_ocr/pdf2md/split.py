"""PDF 拆页与文字/图片页分类（pypdfium2）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pypdfium2 as pdfium

from paddle_ocr import config


def open_pdf(path: Path) -> Any:
    """
    函数名: open_pdf
    作用: 打开 PDF 文档；调用方须 close_pdf。
    输入:
        path (Path): PDF 路径。
    输出:
        PdfDocument: pypdfium2 文档。
    """
    return pdfium.PdfDocument(str(path))


def close_pdf(doc: Any) -> None:
    """
    函数名: close_pdf
    作用: 关闭 PDF 文档。
    输入:
        doc: PdfDocument。
    输出:
        无。
    """
    if doc is None:
        return
    close = getattr(doc, "close", None)
    if close is not None:
        close()


def page_count(doc: Any) -> int:
    """
    函数名: page_count
    作用: 返回 PDF 页数。
    输入:
        doc: PdfDocument。
    输出:
        int: 页数。
    """
    return int(len(doc))


def extract_page_text(page: Any) -> str:
    """
    函数名: extract_page_text
    作用: 抽出一页可复制文本（PDF 原生，不 OCR）。
    输入:
        page: PdfPage。
    输出:
        str: 页面文本。
    """
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


def classify_page(page: Any) -> str:
    """
    函数名: classify_page
    作用: 按抽出文本去空白后的字符数判断文字页或图片页。
    输入:
        page: PdfPage。
    输出:
        str: "text" 或 "image"。
    """
    compact = "".join(extract_page_text(page).split())
    if len(compact) < int(config.PDF2MD_TEXT_CHAR_MIN):
        return "image"
    return "text"
