"""为 decide() 构建 design_doc 摘要。"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DESIGN_MD = _REPO_ROOT / "docs" / "toml_config_design.md"
_MAX_TOTAL = 8000
_MAX_DESIGN_EXCERPT = 5000
_MAX_SIDECAR = 2000

def _read_design_excerpt() -> str:
    if not _DESIGN_MD.is_file():
        return "(design doc not found)"
    text = _DESIGN_MD.read_text(encoding="utf-8")
    # 取全文前段 + 关键语义说明（控制长度）
    excerpt = text[:_MAX_DESIGN_EXCERPT]
    if len(text) > _MAX_DESIGN_EXCERPT:
        excerpt += "\n...(truncated)..."
    return excerpt


def _read_sidecar_snippet(template_id: str, template_path: Path | None) -> str:
    candidates: list[Path] = []
    if template_path is not None:
        sidecar = template_path.with_suffix(".toml")
        if sidecar.is_file():
            candidates.append(sidecar)
    if template_id:
        candidates.append(_REPO_ROOT / "templates" / template_id / f"{template_id}.toml")
    for path in candidates:
        if path.is_file():
            raw = path.read_text(encoding="utf-8")
            snippet = raw[:_MAX_SIDECAR]
            if len(raw) > _MAX_SIDECAR:
                snippet += "\n...(truncated)..."
            return snippet
    return ""


def build_design_doc(
    template_id: str,
    template_path: Path | None,
    labels: list[str],
) -> str:
    """
    函数名: build_design_doc
    作用: 组合 toml_config_design 摘要 + 模板标签 + 已有 sidecar 片段
    输入:
        template_id (str): 模板 ID
        template_path (Path | None): 模板 xlsx 路径
        labels (list[str]): 模板字段标签
    输出:
        str: design_doc 文本（最长约 8000 字符）
    """
    parts: list[str] = [
        "# TOML configuration design (excerpt)\n",
        _read_design_excerpt(),
        "\n\n## Key semantics for wizard\n",
        "- determiner: plain-text segment delimiter; brace_json uses empty determiner\n",
        "- index: 0-based segment index in indexed_segments; -1 means no ghost column\n",
        "- [[input_section]]: input_area (str or list), move_to (direction), offset (int>=1)\n",
        "- [[fields]]: Input_label, index, id, field, source_file, source_sheet, regex\n",
        "- db_id: optional top-level key naming the primary-key Input_label\n",
        "- id=true on a field marks primary-key / external lookup semantics\n",
        f"\n\nTemplate ID: {template_id}\n",
        f"Template labels: {labels}\n",
    ]
    sidecar = _read_sidecar_snippet(template_id, template_path)
    if sidecar:
        parts.append("\n\n## Existing sidecar TOML (snippet)\n```toml\n")
        parts.append(sidecar)
        parts.append("\n```\n")
    doc = "".join(parts)
    if len(doc) > _MAX_TOTAL:
        return doc[:_MAX_TOTAL] + "\n...(truncated)..."
    return doc
