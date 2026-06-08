# Data Source Tab in Form Plan

## Goal
Move data source configuration into the template page's "数据源" tab. Sidebar navigation should only list Excel templates. Data source columns become dropdowns populated after a successful sheet test. Allow setting a default ID column and enable auto lookup when the user enters an ID. Add a mapping list that binds source columns to target template fields.

## Scope
- UI: Add "数据源" tab inside each template page.
- Sidebar: Only template navigation; remove data source config entry.
- Data source config: Drive all inputs inside the tab.
- Column mapping: Provide editable mapping list per template.
- Auto lookup: When ID column value changes, fetch row and fill fields.

## User Flow
1. User selects a template from the sidebar.
2. In the template page, user opens the "数据源" tab.
3. User authenticates and tests a Google Sheet inside the tab.
4. Once test succeeds, column names are loaded.
5. User picks worksheet and ID column from dropdowns.
6. User clicks "设为默认 ID 列" to persist the ID column.
7. User configures column mappings (source column -> target field).
8. In "数据录入" tab, typing into the ID field auto-fetches row data and fills fields.

## Data Model Updates
- Store `worksheet_name`, `id_column`, `spreadsheet_id`, and `column_mappings` in per-template sidecar config.
- Store `id_column` only after the "设为默认 ID 列" action.
- Cache the latest validated sheet columns for the current template session.

## UI Components
- `template_form` tabs: `数据录入` and `数据源`.
- 数据源 tab:
  - Auth inputs and test button.
  - Sheet selector (dropdown).
  - ID column selector (dropdown).
  - "设为默认 ID 列" button.
  - Column mapping editor (table-like list).
  - Preview table for the sheet after successful test.
- 数据录入 tab:
  - ID input triggers auto lookup on change.
  - Mappings are applied to fill target fields.

## Behavior Details
- Column dropdowns are disabled until sheet test succeeds.
- On successful test:
  - Persist `spreadsheet_id` and worksheet name.
  - Load column headers and make them available to dropdowns.
- Auto lookup:
  - When ID input changes and ID column is set, call fetch by ID.
  - Fill target fields using the mapping list.

## Implementation Steps
1. Refactor `main.py` sidebar to only list templates.
2. Add tabs in `template_form.render_template_page`.
3. Move data source config UI from sidebar into data source tab.
4. Update data source services to store mapping list and default ID column.
5. Add auto-lookup trigger tied to ID field input.
6. Update tests for data source flow and mapping behavior.

## Acceptance Criteria
- Sidebar shows only templates.
- Data source settings are only visible under the template "数据源" tab.
- Column dropdowns appear only after a successful test.
- "设为默认 ID 列" persists and is reused next time.
- Entering an ID auto-fills mapped fields.
- Mapping list can be saved and reused per template.
