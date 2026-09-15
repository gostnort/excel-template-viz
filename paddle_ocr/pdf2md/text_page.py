"""电子文字页：原生文本整理成 Markdown。"""

from __future__ import annotations


def text_to_markdown(raw: str) -> str:
    """
    函数名: text_to_markdown
    作用: 把 PDF 抽出文本压成 Markdown 段落（保留换行、压缩连续空行，不发明标题）。
    输入:
        raw (str): 一页原生文本。
    输出:
        str: Markdown 文本；无内容则为空串。
    """
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
