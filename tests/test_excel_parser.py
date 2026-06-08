from pathlib import Path

import pandas as pd
import pytest

from app.services.excel_parser import (
    build_dataframe_from_form_rows,
    format_cell_display,
    read_template_sheet,
    resolve_sheet_name,
    write_template_sheet,
)


@pytest.fixture
def sample_workbook(tmp_path: Path) -> Path:
    # 构造最小 List 风格工作簿
    path = tmp_path / "sample.xlsx"
    dataframe = pd.DataFrame(
        [
            ["order", "YY", "MM", "DD", "P.O. No."],
            [1, 26, 4, 8, "PO-001"],
            [2, 26, 4, 9, "PO-002"],
        ]
    )
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        dataframe.to_excel(writer, sheet_name="List", index=False, header=False)
    return path


def test_resolve_sheet_name_case_insensitive(sample_workbook: Path) -> None:
    assert resolve_sheet_name(sample_workbook, "list") == "List"


def test_read_template_sheet(sample_workbook: Path) -> None:
    df = read_template_sheet(sample_workbook, "List", header_row=0, data_start_row=1)
    assert list(df.columns) == ["order", "YY", "MM", "DD", "P.O. No."]
    assert len(df) == 2
    assert df.iloc[0]["P.O. No."] == "PO-001"


def test_write_template_sheet_roundtrip(sample_workbook: Path) -> None:
    df = read_template_sheet(sample_workbook, "List", header_row=0, data_start_row=1)
    df.loc[0, "P.O. No."] = "PO-UPDATED"
    blob = write_template_sheet(sample_workbook, "List", df, header_row=0, data_start_row=1)
    out = sample_workbook.parent / "out.xlsx"
    out.write_bytes(blob)
    reread = read_template_sheet(out, "List", header_row=0, data_start_row=1)
    assert reread.iloc[0]["P.O. No."] == "PO-UPDATED"


def test_format_cell_display() -> None:
    assert format_cell_display(None) == ""
    assert format_cell_display(float("nan")) == ""
    assert format_cell_display(1) == "1"
    assert format_cell_display(26.0) == "26"
    assert format_cell_display("PO-001") == "PO-001"


def test_build_dataframe_from_form_rows() -> None:
    headers = ["order", "YY", "P.O. No."]
    rows = [
        {"order": "1", "YY": "26", "P.O. No.": "PO-001"},
        {"order": "2", "YY": "27", "P.O. No.": ""},
    ]
    df = build_dataframe_from_form_rows(headers, rows)
    assert list(df.columns) == headers
    assert len(df) == 2
    assert df.iloc[1]["P.O. No."] == ""


def test_read_template_sheet_empty_data(sample_workbook: Path) -> None:
    headers_only = pd.DataFrame([["order", "YY", "MM", "DD", "P.O. No."]])
    path = sample_workbook.parent / "headers_only.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        headers_only.to_excel(writer, sheet_name="List", index=False, header=False)
    df = read_template_sheet(path, "List", header_row=0, data_start_row=1)
    assert list(df.columns) == ["order", "YY", "MM", "DD", "P.O. No."]
    assert len(df) == 0


def test_form_rows_roundtrip(sample_workbook: Path) -> None:
    df = read_template_sheet(sample_workbook, "List", header_row=0, data_start_row=1)
    headers = list(df.columns)
    rows = [
        {header: format_cell_display(df.iloc[row_idx][header]) for header in headers}
        for row_idx in range(len(df))
    ]
    rows[0]["P.O. No."] = "PO-FORM"
    edited = build_dataframe_from_form_rows(headers, rows)
    blob = write_template_sheet(sample_workbook, "List", edited, header_row=0, data_start_row=1)
    out = sample_workbook.parent / "form_out.xlsx"
    out.write_bytes(blob)
    reread = read_template_sheet(out, "List", header_row=0, data_start_row=1)
    assert reread.iloc[0]["P.O. No."] == "PO-FORM"
