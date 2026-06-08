# Template Auto-Discovery Constitution (constitution.md)

## 1. Core Principles

The Excel Template Visualization project now relies on template auto-discovery and per-template configuration. All design and implementation must comply with:

* **Single Drop-In Template**: Users only copy a single `.xlsx` file into `templates/`; the app must discover it automatically.
* **Sidecar Configuration**: Each template uses a same-name `.json` or `.config.json` file stored alongside the workbook.
* **Config-Driven Defaults**: Default sheet name, header row, and data start row come from the sidecar config (with sensible defaults).
* **Per-Template Data Source**: Google Sheets settings are stored in the template’s sidecar config, not a shared registry.
* **Minimal Setup**: The app should run without editing any registry file.

---

## 2. Tech Stack Constraints

### 2.1 Runtime
* **UI**: Streamlit.
* **Excel**: `openpyxl` + `pandas`.
* **Google Sheets**: `gspread` + `google-auth` + `google-auth-oauthlib`.
* **Config**: JSON sidecar files next to templates.

### 2.2 Python Coding Standards
* **Paths**: Use `pathlib.Path`.
* **Comments**: Chinese in code.
* **Function spacing**: Exactly 2 empty lines between functions; no empty lines inside functions.

### 2.3 Project Layout
```
excel-template-viz/
├── app/
├── templates/            # xlsx + sidecar json
├── plans/                # Speckit planning artifacts
└── tests/
```
