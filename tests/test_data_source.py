import json

import pytest

from app.services.data_source import (
    DEFAULT_ID_COLUMN,
    DEFAULT_COLUMN_MAPPINGS,
    DataSourceConfig,
    clear_template_data_source,
    id_target_field,
    list_template_data_sources,
    load_template_data_source,
    save_template_data_source,
    save_template_id_column,
    sheet_mappings,
    tab_mappings,
)


@pytest.fixture
def isolated_templates(tmp_path, monkeypatch):
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    template_path = templates_dir / "gin_lot.xlsx"
    template_path.write_text("", encoding="utf-8")
    config_path = templates_dir / "gin_lot.config.json"
    payload = {
        "display_name": "GIN LOT Template",
        "description": "",
        "sheet_name": "List",
        "header_row": 0,
        "data_start_row": 1,
    }
    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    monkeypatch.setattr("app.services.registry.TEMPLATES_DIR", templates_dir)
    yield config_path
    if config_path.exists():
        config_path.unlink()


def test_load_returns_none_when_missing(isolated_templates) -> None:
    assert load_template_data_source("gin_lot") is None


def test_save_and_load_roundtrip(isolated_templates) -> None:
    mappings = [
        {"source": "PO", "target": "P.O. No.", "kind": "sheet"},
        {"source": "0", "target": "P.O. No.", "kind": "tab"},
    ]
    config = DataSourceConfig(
        sheet_url="https://docs.google.com/spreadsheets/d/abc123/edit",
        spreadsheet_id="abc123",
        worksheet_name="Sheet1",
        id_column="PO",
        column_mappings=mappings,
    )
    save_template_data_source("gin_lot", config)
    loaded = load_template_data_source("gin_lot")
    assert loaded is not None
    assert loaded.sheet_url == config.sheet_url
    assert loaded.spreadsheet_id == config.spreadsheet_id
    assert loaded.worksheet_name == config.worksheet_name
    assert loaded.id_column == DEFAULT_ID_COLUMN
    assert loaded.column_mappings == mappings


def test_load_uses_default_id_column(isolated_templates) -> None:
    payload = json.loads(isolated_templates.read_text(encoding="utf-8"))
    payload["data_source"] = {
        "spreadsheet_id": "xyz",
        "worksheet_name": "List",
    }
    isolated_templates.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    loaded = load_template_data_source("gin_lot")
    assert loaded is not None
    assert loaded.id_column == DEFAULT_ID_COLUMN
    assert loaded.column_mappings == DEFAULT_COLUMN_MAPPINGS


def test_clear_data_source(isolated_templates) -> None:
    save_template_data_source(
        "gin_lot",
        DataSourceConfig(
            sheet_url="https://example.com",
            spreadsheet_id="id1",
            worksheet_name="W",
            id_column="PO",
        ),
    )
    clear_template_data_source("gin_lot")
    loaded = load_template_data_source("gin_lot")
    assert loaded is None


def test_list_template_data_sources(isolated_templates) -> None:
    entries = list_template_data_sources()
    assert len(entries) == 1
    assert entries[0].template_id == "gin_lot"
    assert entries[0].display_name == "GIN LOT Template"
    assert entries[0].data_source is None
    save_template_data_source(
        "gin_lot",
        DataSourceConfig(
            sheet_url="https://docs.google.com/spreadsheets/d/abc123/edit",
            spreadsheet_id="abc123",
            worksheet_name="Sheet1",
            id_column="PO",
        ),
    )
    entries = list_template_data_sources()
    assert entries[0].data_source is not None
    assert entries[0].data_source.spreadsheet_id == "abc123"


def test_save_template_id_column(isolated_templates) -> None:
    save_template_data_source(
        "gin_lot",
        DataSourceConfig(
            sheet_url="https://example.com",
            spreadsheet_id="id1",
            worksheet_name="W",
            id_column="PO",
        ),
    )
    save_template_id_column("gin_lot", "Order ID")
    loaded = load_template_data_source("gin_lot")
    assert loaded is not None
    assert loaded.id_column == "Order ID"


def test_mapping_helpers_and_id_target_field() -> None:
    config = DataSourceConfig(
        sheet_url="https://example.com",
        spreadsheet_id="id1",
        worksheet_name="W",
        id_column="PO",
        column_mappings=[
            {"source": "PO", "target": "P.O. No.", "kind": "sheet"},
            {"source": "0", "target": "P.O. No.", "kind": "tab"},
        ],
    )
    assert len(sheet_mappings(config)) == 1
    assert len(tab_mappings(config)) == 1
    assert id_target_field(config, ["P.O. No.", "Container No."]) == "P.O. No."
