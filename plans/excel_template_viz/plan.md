# Excel Template Visualization Technical Plan (plan.md)

## 1. Architecture Context

```
┌─────────────────────────────────────────────────────────────┐
│  Streamlit app (streamlit_app.py)                           │
│  ┌──────────────┐  ┌──────────────────────────────────────┐ │
│  │ Sidebar nav  │  │ Main panel                           │ │
│  │ - Template A │  │  template_form.render_template()     │ │
│  │ - Template B │  │  OR google_sheet_test.render()       │ │
│  │ - Google测试 │  └──────────────────────────────────────┘ │
│  └──────────────┘                                           │
└─────────────────────────────────────────────────────────────┘
         │                              │
         ▼                              ▼
  config/templates.json          services/
                                 ├── registry.py
                                 ├── excel_parser.py
                                 └── google_sheets.py
```

### 1.1 Navigation Model
* Single `streamlit_app.py` entry; `st.session_state["page"]` driven by sidebar radio.
* One radio option per registry template plus fixed "Google Sheet 连通性测试".
* No Streamlit multipage folder required—keeps template count dynamic from JSON.

### 1.2 GIN LOT Template (List Sheet)
Source: `GIN LOT TEMPLATE.xlsx`, sheet `List` (case-insensitive).

| Row | Role | Content |
|-----|------|---------|
| 0 | Header | order, YY, MM, DD, P.O. No., … Truck Line |
| 1+ | Data | Sample rows (YY=26, MM=04, Product=FRESH GINGER, etc.) |

Registry fields:
* `header_row`: 0
* `data_start_row`: 1
* `file_path`: user WeChat path or copied `templates/gin_lot_template.xlsx`

### 1.3 Excel Parser
* `read_template_sheet(path, sheet_name, header_row, data_start_row) -> pd.DataFrame`
* `write_template_sheet(path, sheet_name, df, header_row) -> bytes` for download
* Sheet name resolution: case-insensitive match against workbook sheet list.

### 1.4 Google Sheets Connector
* `parse_spreadsheet_id(url_or_id) -> str`
* `fetch_sheet_preview(credentials, spreadsheet_id, worksheet_name, max_rows) -> pd.DataFrame`
* Auth branches:
  1. **Service account**: user uploads JSON; sheet must be shared with service account email.
  2. **OAuth user**: optional `credentials/oauth_client.json` + `InstalledAppFlow`; token in `st.session_state` only.

### 1.5 End-User Test Page
* Streamlit page: paste URL, pick auth, run test, show dataframe or error expander with troubleshooting bullets (Chinese).

---

## 2. Directory Structure

```
excel-template-viz/
├── streamlit_app.py
├── app/
│   ├── components/
│   │   └── template_form.py
│   └── services/
│       ├── registry.py
│       ├── excel_parser.py
│       └── google_sheets.py
├── config/
│   └── templates.json
├── templates/
│   └── README.txt          # instruct copy sample xlsx here
├── docs/plans/excel_template_viz/
├── tests/
│   ├── test_excel_parser.py
│   └── test_google_sheets.py
├── pyproject.toml
├── requirements.txt
├── README.md
└── .gitignore
```

---

## 3. Dependencies

| Package | Purpose |
|---------|---------|
| streamlit | UI |
| pandas | DataFrame |
| openpyxl | xlsx I/O |
| gspread | Google Sheets API |
| google-auth | Credentials |
| google-auth-oauthlib | OAuth flow |
| pytest | Unit tests |

---

## 4. Implementation Phases

1. **Planning** — Speckit docs (this package).
2. **Core services** — registry, excel_parser, google_sheets.
3. **UI** — streamlit_app.py sidebar + template_form + Google test section.
4. **Config** — templates.json pointing to sample path.
5. **Tests** — parse ID, sheet name matching, error messages.
6. **GitHub** — `gh repo create`, initial push.

---

## 5. Known Constraints

* Developer may lack Google Sheet access; live Google test is end-user only via UI.
* Example xlsx lives outside repo (WeChat path); registry uses env override `GIN_LOT_TEMPLATE_PATH` or local copy under `templates/`.
