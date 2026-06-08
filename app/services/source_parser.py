from datetime import datetime

# 源数据制表符分隔字段索引
IDX_PO_NO = 0
IDX_CONTAINER_NO = 4
IDX_RECEIVING_DATE = 12

# 仅手动填写的表单列（解析时不写入）
MANUAL_ONLY_FIELDS = frozenset({"Container Seal No.", "Lot No."})


def parse_md_date(date_text: str, reference_year: int | None = None) -> tuple[str, str, str, str]:
    # 解析 M/D 或 MM/DD，返回 YY、MM、DD 及 Receiving Date（MM/DD/YY）
    text = date_text.strip()
    if not text or "/" not in text:
        raise ValueError(f"无效日期格式: {date_text!r}")
    parts = text.split("/")
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


def sheet_row_to_form_fields(
    row: dict[str, str],
    id_column: str = "PO",
    reference_year: int | None = None,
) -> dict[str, str]:
    # 将 Google Sheet 行映射为 GIN LOT 表单字段（与制表符粘贴逻辑一致）
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
    # 将解析结果合并到以列标题为键的行字典，保留手动字段
    row = {header: "" for header in headers}
    if existing:
        for header in headers:
            stripped = header.strip()
            if stripped in MANUAL_ONLY_FIELDS:
                row[header] = existing.get(header, "")
    parsed_by_stripped = {key.strip(): value for key, value in parsed.items()}
    for header in headers:
        stripped = header.strip()
        if stripped in MANUAL_ONLY_FIELDS:
            continue
        if stripped in parsed_by_stripped:
            row[header] = parsed_by_stripped[stripped]
    return row
