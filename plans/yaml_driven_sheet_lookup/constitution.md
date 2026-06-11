# YAML-Driven Google Sheet Lookup — Constitution (constitution.md)

## 1. Core Principles

This constitution keeps Google Sheet → `.paste.yaml` mapping strict, the architecture clean, and failure modes safe.

* **YAML is the single source of truth**
  - Field names, regexes, and column matching for auto lookup and fill come only from `*.paste.yaml`.
  - Sidecar `.config.json` `column_mappings` is a backward-compatible fallback only; the two configs must not conflict on the primary path.
* **Minimal configuration**
  - One `.paste.yaml` (Phi-3.5 vision or manual edit) should power both TSV paste parsing and Google Sheet ID lookup without duplicate column mapping.
* **Do not destroy manual input**
  - If lookup fails to extract a field or regex parsing fails, **never** clear or overwrite values the user already entered in the form.

## 2. Technical Constraints

* **Dependencies**
  - No `os` library; use `pathlib.Path` for paths in all Python services and UI code.
  - Keep `requirements.txt` as the only dependency source; do not add external mapping/parsing libraries.
* **Loose string matching**
  - Sheet headers and YAML `filed` values may differ by whitespace/case. Column matching must be two-stage:
    1. Exact match first.
    2. If no exact match, loose match (strip + lowercase).
* **No narrating comments**
  - Do not add obvious statement comments in new or changed Python code. Comments only for non-obvious API, network, or framework behavior.

## 3. Explicit Prohibitions

* **Do not break backward compatibility**
  - Templates without `*.paste.yaml` must keep working sidecar lookup and `column_mappings` fallback; upgrade must not crash them.
* **Do not duplicate date conversion**
  - Do not reinvent date extraction. Spec §1 `MM` / `DD` / `Receiving Date` / `YY` regex behavior is sufficient. Keep splitting in YAML regex; do not port sidecar hard-coded date splitting into the YAML primary path.
* **Do not bind parsing to UI**
  - Parsing and errors must not be tied to the Streamlit main process. `paste_parse_config` must run and be testable independently of UI.
