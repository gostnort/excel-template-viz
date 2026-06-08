# Data Source Tab in Form Task Breakdown (tasks.md)

Speckit-style phased tasks for `data_source_in_form_tab`.

---

## Phase 1: Planning Package

### [x] [Task 1.1] Publish Speckit docs
* **Description**: Ensure `plans/data_source_in_form_tab/` contains plan and tasks documentation.
* **Acceptance**: `plan.md` and `tasks.md` exist in the plans folder.

---

## Phase 2: Template Page UI

### [ ] [Task 2.1] Template-only sidebar
* **Description**: Update the sidebar to show only templates and remove data source config entries.
* **Acceptance**: Sidebar lists only templates and still navigates to template pages.

### [ ] [Task 2.2] Data source tab UI
* **Description**: Add a "data source" tab to the template page and move config UI into it.
* **Acceptance**: Data source inputs are visible only inside the template tab layout.

### [ ] [Task 2.3] Column dropdown gating
* **Description**: Populate worksheet and column dropdowns only after a successful sheet test.
* **Acceptance**: Dropdowns are disabled or empty until test succeeds, then show sheet columns.

### [ ] [Task 2.4] Default ID column action
* **Description**: Add a "set default ID column" button that persists the selected column.
* **Acceptance**: Clicking the button saves the ID column and restores it on next load.

### [ ] [Task 2.5] Column mapping list
* **Description**: Add an editable mapping list linking source columns to template fields.
* **Acceptance**: Users can add, edit, and save mappings per template.

---

## Phase 3: Data Flow Behavior

### [ ] [Task 3.1] Persist per-template data source config
* **Description**: Store worksheet name, spreadsheet ID, ID column, and input & output column mappings into each template configuration.
* **Acceptance**: Switching templates loads the correct saved data source settings.

### [ ] [Task 3.2] Auto lookup on ID input
* **Description**: Watch the ID field for changes. After the value is stable for 2 seconds, query the configured sheet by ID and fill mapped target fields from the returned row.
* **Acceptance**: Entering an ID triggers a lookup and populates mapped fields from the matching row.

### [ ] [Task 3.3] Monitoring logic on source data input
* **Description**: When users paste tab-delimited text, split into columns and map each value into the configured target field based on the mapping list.
* **Acceptance**: Pasted tab-delimited data populates the correct inputs via the mapping list.

---

## Phase 4: Tests and Docs

### [ ] [Task 4.1] Update tests for new flow
* **Description**: Adjust data source tests to cover tab UI, dropdown gating, and mappings.
* **Acceptance**: Tests cover the new behavior and pass.

### [ ] [Task 4.2] Document new workflow
* **Description**: Update README or in-app notes to describe the data source tab workflow.
* **Acceptance**: Documentation reflects template-only sidebar and data source tab usage.
