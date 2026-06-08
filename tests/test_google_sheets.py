import pytest

from app.services.excel_parser import parse_spreadsheet_id


@pytest.mark.parametrize(
    "raw,expected",
    [
        (
            "https://docs.google.com/spreadsheets/d/1abcDEFghiJKLmnop/edit#gid=0",
            "1abcDEFghiJKLmnop",
        ),
        ("1abcDEFghiJKLmnop1234567890", "1abcDEFghiJKLmnop1234567890"),
    ],
)
def test_parse_spreadsheet_id(raw: str, expected: str) -> None:
    assert parse_spreadsheet_id(raw) == expected


def test_parse_spreadsheet_id_empty_raises() -> None:
    with pytest.raises(ValueError, match="不能为空"):
        parse_spreadsheet_id("")


def test_parse_spreadsheet_id_invalid_raises() -> None:
    with pytest.raises(ValueError, match="无法解析"):
        parse_spreadsheet_id("not-a-valid-id")
