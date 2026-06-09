from datetime import datetime
import re

MD_DATE_REGEX = re.compile(r"(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])")


def _extract_md_date_text(date_text: str) -> str | None:
    match = MD_DATE_REGEX.search(date_text)
    if not match:
        return None
    return match.group(0)


def parse_md_date(date_text: str, reference_year: int | None = None) -> tuple[str, str, str, str]:
    # 解析 M/D 或 MM/DD，返回 YY、MM、DD 及 Receiving Date（MM/DD/YY）
    text = date_text.strip()
    extracted = _extract_md_date_text(text)
    if not extracted:
        raise ValueError(f"无效日期格式: {date_text!r}")
    parts = extracted.split("/")
    if len(parts) != 2:
        raise ValueError(f"无效日期格式: {date_text!r}")
    month_str, day_str = parts[0].strip(), parts[1].strip()
    if not month_str.isdigit() or not day_str.isdigit():
        raise ValueError(f"无效日期格式: {date_text!r}")
    month = int(month_str)
    day = int(day_str)
    if month < 1 or month > 12 or day < 1 or day > 31:
        raise ValueError(f"无效日期: {date_text!r}")
    year = reference_year if reference_year is not None else datetime.now().year
    yy = str(year % 100).zfill(2)
    mm = str(month).zfill(2)
    dd = str(day).zfill(2)
    receiving_date = f"{mm}/{dd}/{yy}"
    return yy, mm, dd, receiving_date


SHEET_CONTAINER_COLUMN = "Container#"
SHEET_RECV_DATE_COLUMN = "recv. date"


def _apply_date_mapping(parsed: dict[str, str], target: str, raw: str, reference_year: int | None) -> None:
    yy, mm, dd, receiving_date = parse_md_date(raw, reference_year)
    parsed["YY"] = yy
    parsed["MM"] = mm
    parsed["DD"] = dd
    parsed[target] = receiving_date


def map_sheet_row_with_mappings(
    row: dict[str, str],
    mappings: list[dict[str, str]],
    reference_year: int | None = None,
) -> dict[str, str]:
    # 按配置映射将 Sheet 行转为表单字段
    parsed: dict[str, str] = {}
    for item in mappings:
        if item.get("kind", "sheet") != "sheet":
            continue
        source = item["source"]
        target = item["target"]
        raw = row.get(source, "").strip()
        if not raw:
            continue
        if target.strip() == "Receiving Date" or source.strip() in {SHEET_RECV_DATE_COLUMN, "recv. date"}:
            _apply_date_mapping(parsed, target, raw, reference_year)
        else:
            parsed[target] = raw
    return parsed


def sheet_row_to_form_fields(
    row: dict[str, str],
    id_column: str = "PO",
    reference_year: int | None = None,
    mappings: list[dict[str, str]] | None = None,
) -> dict[str, str]:
    # 将 Google Sheet 行映射为表单字段
    if mappings:
        return map_sheet_row_with_mappings(row, mappings, reference_year)
    po_value = row.get(id_column, "").strip()
    container = row.get(SHEET_CONTAINER_COLUMN, "").strip()
    recv_raw = row.get(SHEET_RECV_DATE_COLUMN, "").strip()
    if not recv_raw:
        raise ValueError(f"缺少日期列「{SHEET_RECV_DATE_COLUMN}」")
    yy, mm, dd, receiving_date = parse_md_date(recv_raw, reference_year)
    return {
        "YY": yy,
        "MM": mm,
        "DD": dd,
        "P.O. No.": po_value,
        "Container No.": container,
        "Receiving Date": receiving_date,
    }


def merge_parsed_into_headers(
    headers: list[str],
    parsed: dict[str, str],
    existing: dict[str, str] | None = None,
) -> dict[str, str]:
    row = {header: existing.get(header, "") if existing else "" for header in headers}
    parsed_by_stripped = {key.strip(): value for key, value in parsed.items() if str(value).strip()}
    for header in headers:
        stripped = header.strip()
        if stripped in parsed_by_stripped:
            row[header] = parsed_by_stripped[stripped]
    return row
