import re
from typing import Any

from app.services.paste_parse_config import config_to_yaml


def _norm_header(header: str) -> str:
    return header.strip().lower()


def _find_header(template_headers: list[str], *candidates: str) -> str | None:
    by_norm = {_norm_header(header): header for header in template_headers}
    for candidate in candidates:
        key = candidate.lower()
        if key in by_norm:
            return by_norm[key]
    return None


def _classify_columns(parts: list[str]) -> dict[str, list[int]]:
    buckets: dict[str, list[int]] = {
        "po": [],
        "container": [],
        "md_date": [],
        "description": [],
        "text": [],
    }
    for idx, value in enumerate(parts):
        text = value.strip()
        if not text:
            continue
        col = idx + 1
        if re.fullmatch(r"\d{4,8}", text):
            buckets["po"].append(col)
        if re.fullmatch(r"[A-Z]{4}\d{7,10}", text) or (
            re.fullmatch(r"[A-Z0-9]{8,15}", text) and any(ch.isalpha() for ch in text) and any(ch.isdigit() for ch in text)
        ):
            buckets["container"].append(col)
        if re.fullmatch(r"\d{1,2}/\d{1,2}", text):
            buckets["md_date"].append(col)
        if len(text) > 35:
            buckets["description"].append(col)
        elif len(text) > 3:
            buckets["text"].append(col)
    return buckets


def infer_paste_mapping(sample_line: str, template_headers: list[str]) -> dict[str, Any]:
    # 轻量推测器：按列形态 + 表头名推断映射（后续可替换为 LLM）
    parts = sample_line.split("\t")
    if len(parts) < 2:
        raise ValueError("样本至少需要 2 个制表符分隔列")
    buckets = _classify_columns(parts)
    used: set[int] = set()
    fields: list[dict[str, Any]] = []
    index_base = 1
    po_header = _find_header(template_headers, "P.O. No.", "PO", "P.O.No.")
    if po_header and buckets["po"]:
        col = buckets["po"][0]
        used.add(col)
        fields.append({"target": po_header, "index": col})
    container_header = _find_header(template_headers, "Container No.", "Container No")
    if container_header and buckets["container"]:
        col = next((c for c in buckets["container"] if c not in used), buckets["container"][0])
        used.add(col)
        fields.append({"target": container_header, "index": col})
    wants_date = any(_norm_header(h) in {"mm", "dd", "yy", "receiving date"} for h in template_headers)
    if wants_date and buckets["md_date"]:
        col = buckets["md_date"][-1]
        if col not in used:
            used.add(col)
            mm_target = _find_header(template_headers, "MM") or "MM"
            dd_target = _find_header(template_headers, "DD") or "DD"
            recv_target = _find_header(template_headers, "Receiving Date") or "Receiving Date"
            fields.append(
                {
                    "index": col,
                    "split": "/",
                    "index_base": 1,
                    "fields": [
                        {"target": mm_target, "index": 1, "pad": 2},
                        {"target": dd_target, "index": 2, "pad": 2},
                    ],
                    "derive": {
                        "target": recv_target,
                        "from": [mm_target, dd_target],
                        "format": "MM/DD/YY",
                    },
                }
            )
    product_header = _find_header(template_headers, "Product Description", "Product")
    if product_header and buckets["description"]:
        col = next((c for c in buckets["description"] if c not in used), None)
        if col:
            used.add(col)
            fields.append({"target": product_header, "index": col})
    supplier_header = _find_header(template_headers, "Supplier")
    if supplier_header:
        col = next((c for c in buckets["text"] if c not in used), None)
        if col:
            used.add(col)
            fields.append({"target": supplier_header, "index": col})
    fields.sort(key=lambda item: int(item.get("index", item.get("fields", [{}])[0].get("index", 999))))
    if not fields:
        raise ValueError("未能从样本推测出任何映射，请手工编写 YAML")
    return {
        "delimiter": "tab",
        "index_base": index_base,
        "fields": fields,
        "_generated_by": "heuristic_v1",
    }


def infer_paste_mapping_yaml(sample_line: str, template_headers: list[str]) -> str:
    config = infer_paste_mapping(sample_line, template_headers)
    config.pop("_generated_by", None)
    return config_to_yaml(config)
