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


def _collect_distinct_ids(rows: list[dict[str, str]], id_column: str) -> list[str]:
    # 按行顺序收集去重后的 ID 值
    seen: set[str] = set()
    ids: list[str] = []
    for row in rows:
        raw = row.get(id_column, "")
        if isinstance(raw, str):
            cleaned = _clean_po_value(raw)
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                ids.append(cleaned)
    return ids


def build_export_filename(
    template_path: Path,
    rows: list[dict[str, str]],
    id_column: str = "P.O. No.",
    date_column: str = "Receiving Date",
    today: date | None = None,
) -> str:
    # 生成 template-IDs-data-time.xlsx 格式的导出文件名
    base_name = template_path.stem
    safe_rows = rows or []
    ids = _collect_distinct_ids(safe_rows, id_column)
    if not ids:
        ids = ["no-po"]
    id_part = "-".join(ids)
    data_part = f"{len(safe_rows)}rows"
    ref_date = _resolve_receiving_date(safe_rows, date_column, today or date.today())
    time_part = ref_date.strftime("%Y%m%d")
    return f"{base_name}-{id_part}-{data_part}-{time_part}.xlsx"
