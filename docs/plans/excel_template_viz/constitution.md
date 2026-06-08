# Excel Template Visualization Constitution (constitution.md)

## 1. Core Principles

The Excel Template Visualization project provides a Streamlit-based UI for filling structured Excel templates and verifying Google Sheets connectivity. All design and implementation must comply with:

* **Template-Driven UI**: Each registered template appears as a sidebar navigation item; the main panel renders a form derived from the template schema, not hard-coded widgets.
* **Excel Fidelity**: The parser reads the designated sheet (case-insensitive name match) and preserves column headers and row structure from the source workbook.
* **User-Owned Credentials**: Google Sheets access uses credentials supplied by the end user (service account JSON or OAuth). The developer environment must not require pre-configured Google permissions.
* **Clear Permission Feedback**: Google connectivity tests must report success or failure with actionable messages (auth method, sheet ID, scope, sharing).
* **Minimal Scope**: Add only what each template needs; avoid generic spreadsheet engines or export pipelines until required.

---

## 2. Tech Stack Constraints

### 2.1 Runtime
* **UI**: Streamlit (multi-section sidebar navigation).
* **Excel**: `openpyxl` + `pandas` for read/write.
* **Google Sheets**: `gspread` + `google-auth` + `google-auth-oauthlib`.
* **Config**: JSON template registry under `config/templates.json`.

### 2.2 Python Coding Standards
* **Imports**: All `import` statements at file top.
* **Paths**: Use `pathlib.Path` only; no `os.path`.
* **Comments**: Chinese in code.
* **Function spacing**: Exactly 2 empty lines between functions; no empty lines inside functions.
* **Minimize scope**: Match existing module layout; no premature abstractions.

### 2.3 Project Layout
```
excel-template-viz/
├── app/                 # Streamlit entry and pages
├── config/              # Template registry JSON
├── templates/           # Bundled sample workbooks (optional)
├── docs/plans/          # Speckit planning artifacts
└── tests/               # pytest (connectivity helpers, parsers)
```
