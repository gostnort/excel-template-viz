import pytest

from app.services.source_parser import (
    IDX_RECEIVING_DATE,
    merge_parsed_into_headers,
    parse_md_date,
    parse_source_line,
    parse_source_text,
    sheet_row_to_form_fields,
)

EXAMPLE_LINE = (
    "10073\tGIN\tShandong Santao\tS26167FG\tEMCU5484116\t140601104991\t"
    "5/9\t5/30\t$2,612\trel\teverport\t6/2\t6/1\t"
    "600000 Fresh Ginger, China. (F7)\t1780\t57294"
)


def test_parse_md_date_6_1() -> None:
    yy, mm, dd, receiving_date = parse_md_date("6/1", reference_year=2026)
    assert yy == "26"
    assert mm == "06"
    assert dd == "01"
    assert receiving_date == "06/01/26"


def test_parse_example_line() -> None:
    parsed = parse_source_line(EXAMPLE_LINE, order=1, reference_year=2026)
    assert parsed["order"] == "1"
    assert parsed["YY"] == "26"
    assert parsed["MM"] == "06"
    assert parsed["DD"] == "01"
    assert parsed["P.O. No."] == "10073"
    assert parsed["Container No."] == "EMCU5484116"
    assert parsed["Receiving Date"] == "06/01/26"
    fields = EXAMPLE_LINE.split("\t")
    assert fields[IDX_RECEIVING_DATE] == "6/1"


def test_manual_fields_not_in_parsed_output() -> None:
    parsed = parse_source_line(EXAMPLE_LINE, order=1, reference_year=2026)
    assert "Container Seal No." not in parsed
    assert "Lot No." not in parsed


def test_parse_multiple_lines() -> None:
    text = f"{EXAMPLE_LINE}\n{EXAMPLE_LINE}"
    rows = parse_source_text(text, reference_year=2026)
    assert len(rows) == 2
    assert rows[0]["order"] == "1"
    assert rows[1]["order"] == "2"
    assert rows[1]["P.O. No."] == "10073"


def test_parse_source_text_skips_empty_lines() -> None:
    text = f"\n{EXAMPLE_LINE}\n\n"
    rows = parse_source_text(text, reference_year=2026)
    assert len(rows) == 1


def test_merge_parsed_preserves_manual_fields() -> None:
    headers = [
        "order",
        "YY",
        "MM",
        "DD",
        "P.O. No.",
        "Container No.",
        "Container Seal No.",
        "Lot No. ",
        "Receiving Date",
    ]
    existing = {
        "order": "9",
        "YY": "25",
        "MM": "01",
        "DD": "01",
        "P.O. No.": "OLD",
        "Container No.": "OLD",
        "Container Seal No.": "SEAL-1",
        "Lot No. ": "LOT-1",
        "Receiving Date": "01/01/25",
    }
    parsed = parse_source_line(EXAMPLE_LINE, order=1, reference_year=2026)
    merged = merge_parsed_into_headers(headers, parsed, existing)
    assert merged["order"] == "1"
    assert merged["P.O. No."] == "10073"
    assert merged["Container No."] == "EMCU5484116"
    assert merged["Receiving Date"] == "06/01/26"
    assert merged["Container Seal No."] == "SEAL-1"
    assert merged["Lot No. "] == "LOT-1"


def test_parse_source_line_insufficient_fields() -> None:
    with pytest.raises(ValueError, match="字段数量不足"):
        parse_source_line("a\tb\tc", order=1, reference_year=2026)


def test_parse_md_date_invalid() -> None:
    with pytest.raises(ValueError, match="无效日期格式"):
        parse_md_date("invalid", reference_year=2026)


def test_sheet_row_to_form_fields() -> None:
    row = {
        "PO": "10073",
        "Group": "GIN",
        "Container#": "EMCU5484116",
        "recv. date": "6/1",
    }
    parsed = sheet_row_to_form_fields(row, id_column="PO", reference_year=2026)
    assert parsed["P.O. No."] == "10073"
    assert parsed["Container No."] == "EMCU5484116"
    assert parsed["Receiving Date"] == "06/01/26"
    assert parsed["YY"] == "26"
    assert parsed["MM"] == "06"
    assert parsed["DD"] == "01"
