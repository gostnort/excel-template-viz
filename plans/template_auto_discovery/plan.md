# Template Auto-Discovery Technical Plan (plan.md)

## 1. Architecture Context

```
templates/                         app/services/
├── gin_lot.xlsx                   ├── registry.py
├── gin_lot.config.json            └── data_source.py
```

### 1.1 Template Registry Flow
* Scan `templates/` for `*.xlsx`.
* For each workbook, resolve sidecar config:
  * Prefer `<name>.config.json`, else `<name>.json`.
  * If missing, generate default config content and write to disk.
* Build `TemplateConfig` objects from sidecar metadata.

### 1.2 Data Source Flow
* Data source is stored as `data_source` in the sidecar config.
* `load_template_data_source()` reads the sidecar config.
* `save_template_data_source()` writes to the same config file.

---

## 2. Directory Structure

```
excel-template-viz/
├── app/
│   ├── components/
│   └── services/
├── templates/
│   ├── *.xlsx
│   ├── *.json
│   └── *.config.json
├── plans/
│   └── template_auto_discovery/
└── tests/
```

---

## 3. Implementation Phases

1. **Planning** — add new Speckit docs under `plans/`.
2. **Registry Update** — scan templates, load sidecar config, create defaults.
3. **Data Source Update** — store data source in sidecar config.
4. **UI/Docs Update** — new empty-state messaging and README instructions.
5. **Tests** — update data source unit tests for sidecar config.

---

## 4. Known Constraints

* Sidecar config is the single source of truth for template settings.
* Defaults are applied if missing fields or missing config.
