# Template Auto-Discovery Task Breakdown (tasks.md)

Speckit-style phased tasks for `template_auto_discovery`.

---

## Phase 1: Planning Package

### [x] [Task 1.1] Publish Speckit docs
* **Description**: Create `plans/template_auto_discovery/` with constitution, spec, plan, tasks (+ Chinese spec/plan if needed).
* **Acceptance**: All requested files exist in the new plans folder.

---

## Phase 2: Template Discovery

### [x] [Task 2.1] Registry auto-scan
* **Description**: Scan `templates/` for `.xlsx` files and derive template metadata.
* **Acceptance**: Sidebar lists templates without editing any registry file.

### [x] [Task 2.2] Sidecar config defaults
* **Description**: Generate default config if sidecar json missing.
* **Acceptance**: First run creates `.config.json` with defaults.

---

## Phase 3: Data Source Persistence

### [x] [Task 3.1] Store per-template data source
* **Description**: Save `data_source` into the template sidecar config.
* **Acceptance**: Switching templates keeps separate Google Sheet settings.

### [x] [Task 3.2] Form-side data source tab
* **Description**: Display each template's data sources on the form side. Allow specifying a new tab that lists multiple data sources together.
* **Acceptance**: Users can view multiple data sources in a dedicated tab without leaving the form area.

---

## Phase 4: Docs & Tests

### [x] [Task 4.1] Update README and templates README
* **Description**: Document copy-to-templates workflow and sidecar config.
* **Acceptance**: README references `templates/` auto-discovery.

### [x] [Task 4.2] Update tests
* **Description**: Rewrite data source tests to use sidecar config files.
* **Acceptance**: pytest passes without `config/templates.json`.
