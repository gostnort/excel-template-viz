"""对外端口 PaddleOcr_PDF2MDs：PDF 拆页后分别出 Markdown。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from paddle_ocr import config
from paddle_ocr.mcp_runtime import start_structure_mcp, stop_structure_mcp
from paddle_ocr.pdf2md.image_page import page_structure_markdown
from paddle_ocr.pdf2md.split import classify_page, close_pdf, extract_page_text, open_pdf, page_count
from paddle_ocr.pdf2md.text_page import text_to_markdown
from paddle_ocr.runtime.infer_lock import INFER_LOCK


def resolve_output_dir(file_path: Path, output_path: str | Path | None) -> Path:
    """
    函数名: resolve_output_dir
    作用: 默认 "." / 空表示输入 PDF 所在目录；其它值作为输出目录。
    输入:
        file_path (Path): PDF 路径。
        output_path (str|Path|None): 调用方给出的 OutputPath。
    输出:
        Path: 输出目录（尚未 mkdir）。
    """
    raw = "." if output_path is None else str(output_path).strip()
    if raw in ("", "."):
        return file_path.resolve().parent
    return Path(raw)


def page_md_path(output_dir: Path, stem: str, page: int) -> Path:
    """
    函数名: page_md_path
    作用: 按模板生成一页 Markdown 路径。
    输入:
        output_dir (Path): 输出目录。
        stem (str): PDF 文件名（无后缀）。
        page (int): 从 1 起的页码。
    输出:
        Path: md 文件路径。
    """
    name = config.PDF2MD_PAGE_NAME.format(stem=stem, page=page)
    return output_dir / name


def _write_page_md(path: Path, markdown: str) -> None:
    """
    函数名: _write_page_md
    作用: 把一页 Markdown 写成 UTF-8 文件。
    输入:
        path (Path): 目标文件。
        markdown (str): 正文。
    输出:
        无。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(markdown or ""), encoding="utf-8")


def _convert_one_page(page: Any, *, page_no: int, output_dir: Path, stem: str, structure_used: list[bool]) -> dict[str, Any]:
    """
    函数名: _convert_one_page
    作用: 分类并转换单页；文字页为空则改走 Structure。
    输入:
        page: PdfPage。
        page_no (int): 从 1 起的页码。
        output_dir (Path): 输出目录。
        stem (str): PDF stem。
        structure_used (list[bool]): 单元素标记本任务是否动过 Structure。
    输出:
        dict: page / kind / path / ok / message。
    """
    kind = classify_page(page)
    md = ""
    message = config.MSG_PDF2MD_PAGE_OK
    if kind == "text":
        md = text_to_markdown(extract_page_text(page))
        if not md.strip():
            kind = "image"
            message = config.MSG_PDF2MD_EMPTY_FALLBACK
    if kind == "image":
        if not structure_used[0]:
            if not start_structure_mcp():
                return {
                    "page": page_no,
                    "kind": kind,
                    "path": "",
                    "ok": False,
                    "message": config.MSG_NOT_READY,
                }
            structure_used[0] = True
        try:
            md = page_structure_markdown(page)
        except Exception:
            return {
                "page": page_no,
                "kind": kind,
                "path": "",
                "ok": False,
                "message": config.MSG_PDF2MD_PAGE_FAIL,
            }
    # 中文注释：转换成功则按页码写出 Markdown
    out_path = page_md_path(output_dir, stem, page_no)
    try:
        _write_page_md(out_path, md)
    except Exception:
        return {
            "page": page_no,
            "kind": kind,
            "path": "",
            "ok": False,
            "message": config.MSG_PDF2MD_PAGE_FAIL,
        }
    return {
        "page": page_no,
        "kind": kind,
        "path": str(out_path),
        "ok": True,
        "message": message,
    }


def PaddleOcr_PDF2MDs(FilePath, OutputPath=".") -> dict[str, Any]:
    """
    函数名: PaddleOcr_PDF2MDs
    作用: 将 PDF 按页拆成 Markdown；文字页原生抽文本，图片/扫描页走 PP-StructureV3。
    输入:
        FilePath (str|Path): PDF 输入路径。
        OutputPath (str|Path): Markdown 输出目录；默认 "." 表示 PDF 所在目录。
    输出:
        dict: ok / message / output_dir / pages。
    """
    src = Path(FilePath)
    if not src.is_file():
        return {"ok": False, "message": config.MSG_PDF2MD_BAD_FILE, "output_dir": "", "pages": []}
    out_dir = resolve_output_dir(src, OutputPath)
    stem = src.stem
    doc = None
    structure_used = [False]
    pages: list[dict[str, Any]] = []
    with INFER_LOCK:
        try:
            try:
                doc = open_pdf(src)
            except Exception:
                return {"ok": False, "message": config.MSG_PDF2MD_BAD_FILE, "output_dir": str(out_dir), "pages": []}
            # 中文注释：逐页转换；首次图片页才拉 Structure；finally 仅在本任务启动过时释放
            n = page_count(doc)
            for index in range(n):
                page = doc[index]
                pages.append(_convert_one_page(
                    page,
                    page_no=index + 1,
                    output_dir=out_dir,
                    stem=stem,
                    structure_used=structure_used,
                ))
        finally:
            close_pdf(doc)
            # 中文注释：本任务启动或复用过 Structure 则释放，避免外部调用留下子进程
            if structure_used[0]:
                stop_structure_mcp()
    all_ok = bool(pages) and all(bool(item.get("ok")) for item in pages)
    if not pages:
        return {"ok": False, "message": config.MSG_PDF2MD_BAD_FILE, "output_dir": str(out_dir), "pages": []}
    message = config.MSG_PDF2MD_OK if all_ok else config.MSG_PDF2MD_PARTIAL
    return {"ok": all_ok, "message": message, "output_dir": str(out_dir), "pages": pages}


def main(argv: list[str] | None = None) -> int:
    """
    函数名: main
    作用: PDF2MD 独立 CLI：--input PDF，可选 --output 目录。
    输入:
        argv (list[str]|None): 参数；None 则用 sys.argv[1:]。
    输出:
        int: 0 成功，1 失败。
    """
    parser = argparse.ArgumentParser(prog="python -m paddle_ocr.pdf2md", add_help=True)
    parser.add_argument("--input", required=True, help="PDF 输入路径")
    parser.add_argument("--output", default=".", help="Markdown 输出目录；默认 PDF 所在目录")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    result = PaddleOcr_PDF2MDs(args.input, args.output)
    print(result.get("message") or "")
    return 0 if result.get("ok") else 1
