# Excel Template Visualization Functional Specification (spec.md)

## 1. User Scenarios

### P1: Fill GIN LOT List Sheet via Visual Form
* **User Story**: As a warehouse operator, I want to open the GIN LOT template in a browser, see the List sheet columns as labeled fields, enter or edit row data, and export back to Excel without opening Excel desktop.
* **Acceptance Criteria**:
  * Sidebar shows "GIN LOT Template" as a navigation item.
  * Form displays columns: order, YY, MM, DD, P.O. No., Container No., Container Seal No., Lot No., Receiving Date, Product Description, Supplier, Truck Line.
  * Pre-filled sample rows from the workbook are shown and editable.
  * User can download updated workbook.

### P2: Verify Google Sheets Access (End User)
* **User Story**: As an end user whose developer lacks Google Sheet permissions, I want to paste a Sheet URL/ID, choose auth (service account or OAuth), and see whether I can read the first rows—so I can debug sharing and credentials myself.
* **Acceptance Criteria**:
  * Dedicated sidebar page "Google Sheet 连通性测试".
  * Inputs: Sheet URL or ID, worksheet name (optional), auth method selector.
  * Service account: upload JSON key file.
  * OAuth: initiate browser flow with stored token in session only.
  * Success: show first N rows in a table plus green confirmation.
  * Failure: show red error with likely causes (403, 404, invalid JSON, wrong sheet name).

### P3: Register Additional Templates
* **User Story**: As a maintainer, I want to add new templates by editing JSON registry without changing core navigation code.
* **Acceptance Criteria**:
  * `config/templates.json` defines id, display name, file path, sheet name, header row, data start row.
  * New entry automatically appears in sidebar after app restart.

---

## 2. Functional Requirements

### FR-001: Template Registry
* Load `config/templates.json` at startup; skip entries whose workbook path does not exist (warn in UI).

### FR-002: List Sheet Parser
* Read workbook with pandas/openpyxl; match sheet name case-insensitively.
* Treat configured header row as column labels; data rows from `data_start_row` onward.

### FR-003: Streamlit Form Renderer
* Render one text/date field per column per data row (compact table via `st.data_editor` or column layout).
* Preserve trailing spaces in headers where present (e.g. "Lot No. ").

### FR-004: Excel Export
* Write edited dataframe back to the same sheet name; offer `st.download_button` for `.xlsx` bytes.

### FR-005: Google Sheets Connector
* Parse spreadsheet ID from URL or raw ID.
* Service account: `gspread.service_account_from_dict`.
* OAuth: `google_auth_oauthlib.flow.InstalledAppFlow` with readonly spreadsheets scope.
* Fetch worksheet by name or first sheet; return head rows as DataFrame.

### FR-006: Automated Test Hook
* pytest module validates Sheet ID parsing and mock/auth error paths without live Google calls by default.

---

## 3. Non-Functional Requirements

### NFR-001: Local-first
* App runs with `streamlit run streamlit_app.py`; no cloud deployment required for MVP.

### NFR-002: Secrets
* Never commit service account JSON; `.gitignore` excludes `*.json` credentials except `config/templates.json`.

### NFR-003: Documentation
* README (Chinese) covers install, run, template registration, and Google test steps.
