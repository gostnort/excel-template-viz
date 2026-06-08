import json

import pytest

from app.services.data_source import (
    DEFAULT_ID_COLUMN,
    DataSourceConfig,
    clear_template_data_source,
    load_template_data_source,
    save_template_data_source,
)


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    # 将配置路径指向临时目录，避免污染真实 config/
    config_file = tmp_path / "templates.json"
    monkeypatch.setattr("app.services.data_source.TEMPLATES_CONFIG_PATH", config_file)
    payload = {
        "templates": [
            {
                "id": "gin_lot",
                "display_name": "GIN LOT Template",
                "file_path": "templates/gin_lot_template.xlsx",
                "sheet_name": "List",
                "header_row": 0,
                "data_start_row": 1,
            }
        ]
    }
    config_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    yield config_file
    if config_file.exists():
        config_file.unlink()


def test_load_returns_none_when_missing(isolated_config) -> None:
    assert load_template_data_source("gin_lot") is None


def test_save_and_load_roundtrip(isolated_config) -> None:
    config = DataSourceConfig(
        sheet_url="https://docs.google.com/spreadsheets/d/abc123/edit",
        spreadsheet_id="abc123",
        worksheet_name="Sheet1",
        id_column="PO",
    )
    save_template_data_source("gin_lot", config)
    loaded = load_template_data_source("gin_lot")
    assert loaded is not None
    assert loaded.sheet_url == config.sheet_url
    assert loaded.spreadsheet_id == config.spreadsheet_id
    assert loaded.worksheet_name == config.worksheet_name
    assert loaded.id_column == DEFAULT_ID_COLUMN


def test_load_uses_default_id_column(isolated_config) -> None:
    payload = json.loads(isolated_config.read_text(encoding="utf-8"))
    payload["templates"][0]["data_source"] = {
        "spreadsheet_id": "xyz",
        "worksheet_name": "List",
    }
    isolated_config.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    loaded = load_template_data_source("gin_lot")
    assert loaded is not None
    assert loaded.id_column == DEFAULT_ID_COLUMN


def test_clear_data_source(isolated_config) -> None:
    save_template_data_source(
        "gin_lot",
        DataSourceConfig(
            sheet_url="https://example.com",
            spreadsheet_id="id1",
            worksheet_name="W",
            id_column="PO",
        )
    )
    clear_template_data_source("gin_lot")
    loaded = load_template_data_source("gin_lot")
    assert loaded is None
