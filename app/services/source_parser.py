from datetime import datetime
import re

# 源数据制表符分隔字段索引
IDX_PO_NO = 0
IDX_CONTAINER_NO = 4
IDX_RECEIVING_DATE = 12

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


def parse_source_line(line: str, order: int, reference_year: int | None = None) -> dict[str, str]:
    # 解析单行制表符分隔源数据，映射到 GIN LOT List 表单字段
    fields = line.split("\t")
    if len(fields) <= IDX_RECEIVING_DATE:
        raise ValueError(f"字段数量不足，需要至少 {IDX_RECEIVING_DATE + 1} 列")
    yy, mm, dd, receiving_date = parse_md_date(fields[IDX_RECEIVING_DATE], reference_year)
    return {
        "order": str(order),
        "YY": yy,
        "MM": mm,
        "DD": dd,
        "P.O. No.": fields[IDX_PO_NO].strip(),
        "Container No.": fields[IDX_CONTAINER_NO].strip(),
        "Receiving Date": receiving_date,
    }


def parse_source_text(text: str, reference_year: int | None = None) -> list[dict[str, str]]:
    # 解析多行源文本，每行对应一条表单记录
    rows: list[dict[str, str]] = []
    order = 1
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        rows.append(parse_source_line(line, order, reference_year))
        order += 1
    return rows


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


def map_tab_line_with_mappings(
    line: str,
    mappings: list[dict[str, str]],
    order: int,
    reference_year: int | None = None,
) -> dict[str, str]:
    # 按配置映射将制表符行转为表单字段
    fields = line.split("\t")
    parsed: dict[str, str] = {"order": str(order)}
    for item in mappings:
        if item.get("kind") != "tab":
            continue
        source = item["source"]
        target = item["target"]
        if not source.isdigit():
            continue
        idx = int(source)
        if idx >= len(fields):
            continue
        raw = fields[idx].strip()
        if not raw:
            continue
        if target.strip() == "Receiving Date":
            _apply_date_mapping(parsed, target, raw, reference_year)
        else:
            parsed[target] = raw
    return parsed


def parse_source_text_with_mappings(
    text: str,
    mappings: list[dict[str, str]],
    reference_year: int | None = None,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    order = 1
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        rows.append(map_tab_line_with_mappings(line, mappings, order, reference_year))
        order += 1
    return rows


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
