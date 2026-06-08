# Excel Template Visualization Task Breakdown (tasks.md)

Speckit-style phased tasks for `excel-template-viz`.

---

## Phase 1: Planning Package

### [x] [Task 1.1] Publish Speckit docs
* **Description**: Create `docs/plans/excel_template_viz/` with constitution, spec, plan, tasks (+ Chinese counterparts).
* **Acceptance**: All 8 files exist and reference Streamlit + Google test page.

### [x] [Task 1.2] Analyze GIN LOT List sheet
* **Description**: Read sample xlsx; document columns and row layout in plan.md.
* **Acceptance**: Sheet name `List` (not `list`); 12 columns, header row 0.

---

## Phase 2: Core Services

### [x] [Task 2.1] Template registry loader
* **Description**: `app/services/registry.py` loads `config/templates.json`.
* **Acceptance**: Returns list of TemplateConfig; resolves path env overrides.

### [x] [Task 2.2] Excel parser
* **Description**: `app/services/excel_parser.py` read/write List sheet.
* **Acceptance**: Case-insensitive sheet match; round-trip download bytes.

### [x] [Task 2.3] Google Sheets connector
* **Description**: `app/services/google_sheets.py` ID parse + fetch preview.
* **Acceptance**: Service account dict auth; OAuth flow helper; clear exceptions.

---

## Phase 3: Streamlit UI

### [x] [Task 3.1] Main app sidebar navigation
* **Description**: `streamlit_app.py` dynamic template nav + Google test page.
* **Acceptance**: Each registry entry = sidebar option.

### [x] [Task 3.2] Template form component
* **Description**: `app/components/template_form.py` data_editor + download.
* **Acceptance**: GIN LOT columns editable; export xlsx.

### [x] [Task 3.3] Google Sheet test page
* **Description**: Embedded in app.py or component; URL, auth, preview table.
* **Acceptance**: Success green / failure red with troubleshooting text.

---

## Phase 4: Config & Docs

### [x] [Task 4.1] templates.json
* **Description**: Register gin_lot template with path and sheet metadata.
* **Acceptance**: Env `GIN_LOT_TEMPLATE_PATH` supported.

### [x] [Task 4.2] README and .gitignore
* **Description**: Chinese README with setup and Google test instructions.
* **Acceptance**: `streamlit run` documented; credentials excluded from git.

---

## Phase 5: Tests & GitHub

### [x] [Task 5.1] pytest modules
* **Description**: `tests/test_google_sheets.py`, `tests/test_excel_parser.py`.
* **Acceptance**: ID parsing tests pass without network.

### [x] [Task 5.2] GitHub repository
* **Description**: `gh repo create excel-template-viz --public`; push initial scaffold.
* **Acceptance**: Remote URL returned; local git initialized.

---

## Phase 6: Follow-up (User)

### [ ] [Task 6.1] Copy sample xlsx to templates/
* **Description**: User copies `GIN LOT TEMPLATE.xlsx` to `templates/gin_lot_template.xlsx`.
* **Acceptance**: App loads without path warning.

### [ ] [Task 6.2] Configure Google credentials
* **Description**: User shares sheet with service account or completes OAuth.
* **Acceptance**: Google test page shows first rows.
