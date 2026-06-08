from datetime import date
from pathlib import Path

from app.services.export_naming import build_export_filename


def test_build_export_filename_single_row_with_date(tmp_path: Path) -> None:
    template_path = tmp_path / "gin_lot_template.xlsx"
    rows = [{"P.O. No.": " PO123 ", "Receiving Date": "6/1/26"}]
    filename = build_export_filename(template_path, rows, today=date(2026, 6, 8))
    assert filename == "gin_lot_template-PO123-20260601.xlsx"


def test_build_export_filename_multiple_rows_with_fallback_date(tmp_path: Path) -> None:
    template_path = tmp_path / "gin_lot_template.xlsx"
    rows = [
        {"P.O. No.": "PO123", "Receiving Date": ""},
        {"P.O. No.": "PO456", "Receiving Date": ""},
        {"P.O. No.": "PO789", "Receiving Date": ""},
        {"P.O. No.": "PO999", "Receiving Date": ""},
    ]
    filename = build_export_filename(template_path, rows, today=date(2026, 6, 8))
    assert filename == "gin_lot_template-PO123-PO456-PO789-4rows-20260608.xlsx"


def test_build_export_filename_missing_ids(tmp_path: Path) -> None:
    template_path = tmp_path / "gin_lot_template.xlsx"
    rows = [{"P.O. No.": "  ", "Receiving Date": ""}]
    filename = build_export_filename(template_path, rows, today=date(2026, 6, 8))
    assert filename == "gin_lot_template-no-po-20260608.xlsx"
