# Geodesic Alignment Dirty Data Benchmark: Robustness & Diagnostics Report

## Executive Summary
- **Benchmark Suites Executed**: 11 / 11
- **Total Destination Columns Evaluated**: 64
- **Clean Recovery Rate (Carry / Regex / Formula)**: 59 / 64 (92.2%)
- **Graceful Fallback Rate (Input / Outspan)**: 5 / 64 (7.8%)
- **Uncaught Exceptions / Numerical Crashes**: 0 (100% Stability across SDE & SVD steps)

## Domain Matrix & Classification Breakdown

| Slot | Domain | Dirty Pattern | Cols | Data | Regex | Formula | Fallback (Input) | Recovery Rate |
|:---|:---|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| `01_hr_payroll` | HR Compensation | Currency symbols ($ / ¥), negative in parentheses (500.00), thousand commas | 6 | 6 | 0 | 0 | 0 | 100.0% |
| `02_clinical` | Medical Trials | Inconsistent dates (YYYY/MM/DD, DD-MM-YYYY, serial 46160, textual months) | 6 | 5 | 0 | 0 | 1 | 83.3% |
| `03_inventory` | Retail Warehouse | Regex anchor variations (SKU-[101] vs Item# 102 vs REF:103), barcode prefixes | 4 | 3 | 1 | 0 | 0 | 100.0% |
| `04_telemetry` | IoT Sensors | Heavy missing value sentinels (NaN, None, N/A, '-', whitespace) | 6 | 6 | 0 | 0 | 0 | 100.0% |
| `05_waybill` | Cross-border Logistics | Shuffled topological row orders, orphan source rows, non-1:1 matching | 5 | 5 | 0 | 0 | 0 | 100.0% |
| `06_banking` | Wire Transactions | European comma decimals (1.234,56), high-precision timestamps | 5 | 5 | 0 | 0 | 0 | 100.0% |
| `07_crm_leads` | Sales Leads | Header distortions (leading/trailing whitespace, snake_case, typos) | 6 | 6 | 0 | 0 | 0 | 100.0% |
| `08_education` | University Grades | Composite formula derivations (First_Name & Last_Name), grade score addition | 4 | 2 | 0 | 2 | 0 | 100.0% |
| `09_property` | Real Estate Listings | Mixed dimension strings (120sqm), price ranges (100k-150k) | 6 | 4 | 1 | 1 | 0 | 100.0% |
| `10_factory_qc` | Manufacturing QC | Intentional pure outspan / manual sign-off columns with zero source lineage | 6 | 4 | 0 | 0 | 2 | 66.7% |
| `11_real_estate_chart` | Real Estate Valuation & Analytics | Mixed area text (120sqm), name combination formula, outspan inspector signoffs | 10 | 4 | 1 | 3 | 2 | 80.0% |

## Fallback & Topological Behavior Analysis

1. **Intentional Outspan Columns**: In `10_factory_qc` (`Inspector_Signature`, `Shift_Supervisor_Note`) and `02_clinical` (`Investigator_Signoff`), columns without lineage correctly defaulted to `cell_role = 'input'` with `confidence = 0.0`.
2. **Grassmannian Manifold Sediment**: Normal residuals from outspan columns were absorbed by `record_manifold_sediment`, successfully growing tangent subspace dimension without numerical singularity.
3. **Missing Value Sentinels**: `04_telemetry` passed through complex plane quantizer without NaN poisoning or LinAlgError.
4. **Topological Order Invariance**: `05_waybill` correctly aligned shuffled rows and ignored orphan source rows via bijective ID pointers.
5. **High-Precision Timestamps & Comma Decimals**: `06_banking` accurately aligned sub-second timestamps and European decimal wire values.

## Emitted TOML Artifacts
All 10 emitted configuration files in `test/dirty_data_tests/results/*_mapping.toml` were validated as syntactically conformant TOML via `tomllib`.
