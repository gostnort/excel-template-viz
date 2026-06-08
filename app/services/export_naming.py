from __future__ import annotations

from datetime import date, datetime
from pathlib import Path


def _clean_po_value(value: str) -> str:
    # 清理 PO 编号中的空白字符
    return "".join(value.split())


def _parse_receiving_date(value: str) -> date | None:
    # 解析 Receiving Date 字符串
    candidates = ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%m-%d-%y")
    cleaned = value.strip()
    if not cleaned:
        return None
    for fmt in candidates:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def _resolve_receiving_date(rows: list[dict[str, str]], date_column: str, fallback: date) -> date:
    # 获取第一条可用的 Receiving Date
    for row in rows:
        raw = row.get(date_column, "")
        if isinstance(raw, str):
            parsed = _parse_receiving_date(raw)
            if parsed:
                return parsed
    return fallback


def _collect_ids(rows: list[dict[str, str]], po_column: str) -> list[str]:
    # 收集并清理 PO 编号
    ids: list[str] = []
    for row in rows:
        raw = row.get(po_column, "")
        if isinstance(raw, str):
            cleaned = _clean_po_value(raw)
            if cleaned:
                ids.append(cleaned)
    return ids


def build_export_filename(
    template_path: Path,
    rows: list[dict[str, str]],
    po_column: str = "P.O. No.",
    date_column: str = "Receiving Date",
    today: date | None = None,
) -> str:
    # 生成带模板名、PO 编号与日期的导出文件名
    base_name = template_path.stem
    safe_rows = rows or []
    ids = _collect_ids(safe_rows, po_column)
    if not ids:
        ids = ["no-po"]
    if len(safe_rows) > 1:
        id_part = "-".join(ids[:3])
        id_part = f"{id_part}-{len(safe_rows)}rows"
    else:
        id_part = ids[0]
    ref_date = _resolve_receiving_date(safe_rows, date_column, today or date.today())
    date_part = ref_date.strftime("%Y%m%d")
    return f"{base_name}-{id_part}-{date_part}.xlsx"
