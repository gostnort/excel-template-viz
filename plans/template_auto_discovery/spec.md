# Template Auto-Discovery Functional Specification (spec.md)

## 1. User Scenarios

### P1: Drop-In Template Discovery
* **User Story**: As an operator, I want to copy a single xlsx file into `templates/` and immediately see it in the sidebar without editing config files.
* **Acceptance Criteria**:
  * App scans `templates/` for `*.xlsx` on startup.
  * Sidebar shows a navigation item per discovered file.
  * Display name comes from the sidecar config or filename defaults.

### P2: Per-Template Configuration
* **User Story**: As a maintainer, I want each template to have its own JSON config next to the workbook so settings follow the file.
* **Acceptance Criteria**:
  * Config file name is `<template>.json` or `<template>.config.json`.
  * Missing config triggers default creation or in-memory defaults.
  * Sheet name, header row, and data start row are read from the sidecar config.

### P3: Per-Template Data Source
* **User Story**: As a user, I want each template to remember its own Google Sheet settings independently.
* **Acceptance Criteria**:
  * Saved data source settings are written to the template sidecar config.
  * Clearing a data source removes it from the sidecar config only.
  * UI labels show the current template’s stored settings.

---

## 2. Functional Requirements

### FR-001: Template Scan
* Scan `templates/` for `*.xlsx`.
* Order is stable (sorted by filename).

### FR-002: Config Resolution
* Prefer `<name>.config.json` if present, else `<name>.json`.
* If neither exists, create default config (or use defaults in memory).

### FR-003: Template Metadata
* Defaults: `sheet_name=""`, `header_row=0`, `data_start_row=1`.
* `display_name` defaults to filename with `_`/`-` replaced by space and title-cased.

### FR-004: Data Source Persistence
* Load/save data source under `data_source` in the sidecar config.
* Required field to consider configured: `spreadsheet_id`.

---

## 3. Non-Functional Requirements

### NFR-001: Local-First
* App works after copying files; no registry edit required.

### NFR-002: Backward Safety
* `config/templates.json` becomes optional and unused.
