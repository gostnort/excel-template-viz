"""生成 10 组面向真实 Messy 表格场景的基准数据集 (XLSX 物理文件)。

严格对应 R1 规范的 10 个正交领域与脏数据模式矩阵。
"""

from pathlib import Path
import openpyxl


DATASETS_DIR = Path(__file__).resolve().parent / "datasets"


def create_workbook(file_path: Path, sheet_title: str, headers: list[str], rows: list[list[object]]) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_title
    ws.append(headers)
    for row in rows:
        ws.append(row)
    wb.save(file_path)


def generate_all_datasets() -> None:
    DATASETS_DIR.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------------------
    # 01_hr_payroll (HR Compensation): 币符 ($ / ¥), 会计负数括号 (500.00), 千分位
    # -------------------------------------------------------------------------
    src_01_headers = ["Employee_ID", "Staff_Name", "Base_Salary", "Performance_Bonus", "Tax_Deduction", "Gross_Pay"]
    src_01_rows = [
        ["EMP-101", "Alice Smith", "$1,250.00", "$500.00", "$(150.00)", "1750.00"],
        ["EMP-102", "Bob Chen", "¥3,400", "¥800", "¥(300.00)", "4200.00"],
        ["EMP-103", "Charlie Davis", "$2,500.00", "$750.00", "(500.00)", "3250.00"],
        ["EMP-104", "Diana Evans", "¥12,000", "¥3,400", "(1,200.00)", "15400.00"],
        ["EMP-105", "Evan Wright", "$4,800.00", "$1,250.00", "($620.00)", "6050.00"],
    ]
    tpl_01_headers = ["Employee_ID", "Staff_Name", "Base_Salary", "Performance_Bonus", "Tax_Deduction", "Gross_Pay"]
    tpl_01_rows = [
        ["EMP-101", "Alice Smith", "1250.00", "500.00", "-150.00", "1750.00"],
        ["EMP-102", "Bob Chen", "3400.00", "800.00", "-300.00", "4200.00"],
        ["EMP-103", "Charlie Davis", "2500.00", "750.00", "-500.00", "3250.00"],
        ["EMP-104", "Diana Evans", "12000.00", "3400.00", "-1200.00", "15400.00"],
        ["EMP-105", "Evan Wright", "4800.00", "1250.00", "-620.00", "6050.00"],
    ]
    create_workbook(DATASETS_DIR / "01_hr_payroll_source.xlsx", "PayrollSource", src_01_headers, src_01_rows)
    create_workbook(DATASETS_DIR / "01_hr_payroll_template.xlsx", "PayrollTemplate", tpl_01_headers, tpl_01_rows)

    # -------------------------------------------------------------------------
    # 02_clinical (Medical Trials): 异构日期格式 (YYYY/MM/DD, DD-MM-YYYY, Excel序列, 英文月名, 点号, 美式MM/DD/YYYY)
    # -------------------------------------------------------------------------
    src_02_headers = ["Subject_ID", "Patient_Name", "Trial_Arm", "Dosage_mg", "Enrollment_Date", "Lab_Biomarker"]
    src_02_rows = [
        ["SUBJ-201", "John Doe", "Arm-A", "50", "2026/05/18", "12.5"],
        ["SUBJ-202", "Jane Roe", "Arm-B", "100", "18-05-2026", "14.2"],
        ["SUBJ-203", "Alex Ray", "Arm-A", "75", "45430", "11.8"],
        ["SUBJ-204", "Maria Garcia", "Arm-C", "50", "18-May-2026", "15.0"],
        ["SUBJ-205", "Liam Patel", "Arm-B", "100", "2026.05.18", "13.1"],
        ["SUBJ-206", "Oliver Twist", "Arm-A", "75", "05/18/2026", "12.0"],
    ]
    tpl_02_headers = ["Subject_ID", "Patient_Name", "Trial_Arm", "Dosage_mg", "Enrollment_Date", "Investigator_Signoff"]
    tpl_02_rows = [
        ["SUBJ-201", "John Doe", "Arm-A", "50", "2026-05-18", "Signed"],
        ["SUBJ-202", "Jane Roe", "Arm-B", "100", "2026-05-18", "Signed"],
        ["SUBJ-203", "Alex Ray", "Arm-A", "75", "2024-05-18", "Pending"],
        ["SUBJ-204", "Maria Garcia", "Arm-C", "50", "2026-05-18", "Signed"],
        ["SUBJ-205", "Liam Patel", "Arm-B", "100", "2026-05-18", "Exempt"],
        ["SUBJ-206", "Oliver Twist", "Arm-A", "75", "2026-05-18", "Signed"],
    ]
    create_workbook(DATASETS_DIR / "02_clinical_source.xlsx", "ClinicalTrials", src_02_headers, src_02_rows)
    create_workbook(DATASETS_DIR / "02_clinical_template.xlsx", "TrialRegistry", tpl_02_headers, tpl_02_rows)

    # -------------------------------------------------------------------------
    # 03_inventory (Retail Warehouse): 正则锚点变化 (SKU-[...], Item# ..., REF:...), 条码前缀
    # -------------------------------------------------------------------------
    src_03_headers = ["Bin_Location", "Item_Record_Log", "Quantity_On_Hand", "Reorder_Level"]
    src_03_rows = [
        ["BIN-A01", "Scan event BAR-9901-SKU-[101] verified in Bay 1", "45", "10"],
        ["BIN-A02", "Scan event BAR-9902-Item# 102 verified in Bay 2", "30", "5"],
        ["BIN-A03", "Scan event BAR-9903-REF:103 verified in Bay 3", "120", "20"],
        ["BIN-A04", "Scan event BAR-9904-SKU-[104] verified in Bay 4", "85", "15"],
        ["BIN-A05", "Scan event BAR-9905-Item# 105 verified in Bay 5", "60", "10"],
    ]
    tpl_03_headers = ["Bin_Location", "Extracted_SKU", "Quantity_On_Hand", "Reorder_Level"]
    tpl_03_rows = [
        ["BIN-A01", "101", "45", "10"],
        ["BIN-A02", "102", "30", "5"],
        ["BIN-A03", "103", "120", "20"],
        ["BIN-A04", "104", "85", "15"],
        ["BIN-A05", "105", "60", "10"],
    ]
    create_workbook(DATASETS_DIR / "03_inventory_source.xlsx", "InventorySource", src_03_headers, src_03_rows)
    create_workbook(DATASETS_DIR / "03_inventory_template.xlsx", "InventoryTemplate", tpl_03_headers, tpl_03_rows)

    # -------------------------------------------------------------------------
    # 04_telemetry (IoT Sensors): 重度缺失值哨兵 (NaN, None, N/A, -, 全空格, Excel公式错误)
    # -------------------------------------------------------------------------
    src_04_headers = ["Sensor_ID", "Device_Model", "Temperature_C", "Pressure_Bar", "Humidity_Pct", "Battery_V"]
    src_04_rows = [
        ["SENS-401", "Model-X", "23.5", "1.01", "45.2", "3.7"],
        ["SENS-402", "Model-X", "#DIV/0!", "#REF!", "N/A", "-"],
        ["SENS-403", "Model-Y", "24.8", "   ", "暂无", "3.6"],
        ["SENS-404", "Model-Y", "#VALUE!", "1.03", "NaN", "3.8"],
        ["SENS-405", "Model-Z", "22.1", "1.00", "50.1", "3.5"],
    ]
    tpl_04_headers = ["Sensor_ID", "Device_Model", "Temperature_C", "Pressure_Bar", "Humidity_Pct", "Battery_V"]
    tpl_04_rows = [
        ["SENS-401", "Model-X", "23.5", "1.01", "45.2", "3.7"],
        ["SENS-402", "Model-X", "", "", "", ""],
        ["SENS-403", "Model-Y", "24.8", "", "", "3.6"],
        ["SENS-404", "Model-Y", "", "1.03", "", "3.8"],
        ["SENS-405", "Model-Z", "22.1", "1.00", "50.1", "3.5"],
    ]
    create_workbook(DATASETS_DIR / "04_telemetry_source.xlsx", "SensorTelemetry", src_04_headers, src_04_rows)
    create_workbook(DATASETS_DIR / "04_telemetry_template.xlsx", "TelemetryTemplate", tpl_04_headers, tpl_04_rows)

    # -------------------------------------------------------------------------
    # 05_waybill (Cross-border Logistics): 拓扑乱序行、孤立源行、非 1:1 匹配
    # -------------------------------------------------------------------------
    src_05_headers = ["Waybill_ID", "Origin_Airport", "Dest_Airport", "Weight_kg", "Declared_USD", "Carrier_Code"]
    src_05_rows = [
        ["WB-501", "PVG", "FRA", "1500", "45000", "CA"],
        ["WB-502", "HKG", "LHR", "2200", "68000", "CX"],
        ["WB-503", "NRT", "JFK", "800", "25000", "JL"],
        ["WB-504", "ICN", "LAX", "3100", "92000", "KE"],
        ["WB-505", "SIN", "SYD", "1200", "34000", "SQ"],  # Orphan
        ["WB-506", "DXB", "CDG", "2700", "81000", "EK"],  # Orphan
    ]
    tpl_05_headers = ["Waybill_ID", "Origin_Airport", "Dest_Airport", "Weight_kg", "Declared_USD"]
    tpl_05_rows = [
        ["WB-503", "NRT", "JFK", "800", "25000"],
        ["WB-501", "PVG", "FRA", "1500", "45000"],
        ["WB-504", "ICN", "LAX", "3100", "92000"],
        ["WB-502", "HKG", "LHR", "2200", "68000"],
    ]
    create_workbook(DATASETS_DIR / "05_waybill_source.xlsx", "LogisticsManifest", src_05_headers, src_05_rows)
    create_workbook(DATASETS_DIR / "05_waybill_template.xlsx", "WaybillDispatch", tpl_05_headers, tpl_05_rows)

    # -------------------------------------------------------------------------
    # 06_banking (Wire Transactions): 欧洲逗号小数 (1.234,56), 高精度时间戳, 零整数逗号小数 (0,500)
    # -------------------------------------------------------------------------
    src_06_headers = ["Txn_Reference", "Counterparty_IBAN", "Transfer_Amount", "Execution_Time", "Fee_Amount"]
    src_06_rows = [
        ["TXN-601", "DE89370400440532013000", "1.234,56", "2026-05-18 10:15:30.123456", "12,50"],
        ["TXN-602", "FR76300060000112345678", "9.876,50", "2026-05-18 10:16:45.987654", "25,00"],
        ["TXN-603", "IT60X054281110100000012", "450,25", "2026-05-18 10:18:12.500000", "0,500"],
        ["TXN-604", "ES91210004184502000513", "12.500,00", "2026-05-18 10:20:00.112233", "50,00"],
        ["TXN-605", "NL91ABNA0417164300", "3.141,59", "2026-05-18 10:22:15.654321", "0,123456"],
        ["TXN-606", "GB29NWBK60161331926819", "1.234.567", "2026-05-18 02:30:15 PM", "15,00"],
    ]
    tpl_06_headers = ["Txn_Reference", "Counterparty_IBAN", "Transfer_Amount", "Execution_Time", "Fee_Amount"]
    tpl_06_rows = [
        ["TXN-601", "DE89370400440532013000", "1234.56", "2026-05-18 10:15:30.123456", "12.50"],
        ["TXN-602", "FR76300060000112345678", "9876.50", "2026-05-18 10:16:45.987654", "25.00"],
        ["TXN-603", "IT60X054281110100000012", "450.25", "2026-05-18 10:18:12.500000", "0.50"],
        ["TXN-604", "ES91210004184502000513", "12500.00", "2026-05-18 10:20:00.112233", "50.00"],
        ["TXN-605", "NL91ABNA0417164300", "3141.59", "2026-05-18 10:22:15.654321", "0.123456"],
        ["TXN-606", "GB29NWBK60161331926819", "1234567.00", "2026-05-18 14:30:15", "15.00"],
    ]
    create_workbook(DATASETS_DIR / "06_banking_source.xlsx", "WireTransactions", src_06_headers, src_06_rows)
    create_workbook(DATASETS_DIR / "06_banking_template.xlsx", "BankingAudit", tpl_06_headers, tpl_06_rows)

    # -------------------------------------------------------------------------
    # 07_crm_leads (Sales Leads): 表头变形 (空格、snake_case、轻微错别字)
    # -------------------------------------------------------------------------
    src_07_headers = [" Lead_ID ", "firts_name", "last_name", " Company_Name ", "deal_amount", " contact_email "]
    src_07_rows = [
        ["LEAD-701", "Michael", "Scott", "Dunder Mifflin", "45000", "m.scott@dunder.com"],
        ["LEAD-702", "Jim", "Halpert", "Athlead", "85000", "j.halpert@athlead.com"],
        ["LEAD-703", "Pam", "Beesly", "Dunder Mifflin", "32000", "p.beesly@dunder.com"],
        ["LEAD-704", "Dwight", "Schrute", "Schrute Farms", "95000", "d.schrute@farms.com"],
    ]
    tpl_07_headers = ["Lead_ID", "First Name", "Last Name", "Company Name", "Deal Amount", "Contact Email"]
    tpl_07_rows = [
        ["LEAD-701", "Michael", "Scott", "Dunder Mifflin", "45000", "m.scott@dunder.com"],
        ["LEAD-702", "Jim", "Halpert", "Athlead", "85000", "j.halpert@athlead.com"],
        ["LEAD-703", "Pam", "Beesly", "Dunder Mifflin", "32000", "p.beesly@dunder.com"],
        ["LEAD-704", "Dwight", "Schrute", "Schrute Farms", "95000", "d.schrute@farms.com"],
    ]
    create_workbook(DATASETS_DIR / "07_crm_leads_source.xlsx", "RawLeads", src_07_headers, src_07_rows)
    create_workbook(DATASETS_DIR / "07_crm_leads_template.xlsx", "CleanLeads", tpl_07_headers, tpl_07_rows)

    # -------------------------------------------------------------------------
    # 08_education (University Grades): 复合公式派生 (First_Name & Last_Name, 加分)
    # -------------------------------------------------------------------------
    src_08_headers = ["Student_ID", "First_Name", "Last_Name", "Midterm_Exam", "Final_Exam", "Course_Credits"]
    src_08_rows = [
        ["STU-801", "Ada", "Lovelace", "45", "50", "4"],
        ["STU-802", "Alan", "Turing", "48", "47", "4"],
        ["STU-803", "Grace", "Hopper", "42", "46", "3"],
        ["STU-804", "Claude", "Shannon", "50", "49", "4"],
    ]
    tpl_08_headers = ["Student_ID", "Full_Name", "Total_Score", "Course_Credits"]
    tpl_08_rows = [
        ["STU-801", "Ada Lovelace", "95", "4"],
        ["STU-802", "Alan Turing", "95", "4"],
        ["STU-803", "Grace Hopper", "88", "3"],
        ["STU-804", "Claude Shannon", "99", "4"],
    ]
    create_workbook(DATASETS_DIR / "08_education_source.xlsx", "StudentRoster", src_08_headers, src_08_rows)
    create_workbook(DATASETS_DIR / "08_education_template.xlsx", "GradeSummary", tpl_08_headers, tpl_08_rows)

    # -------------------------------------------------------------------------
    # 09_property (Real Estate Listings): 混合量纲字符串 (120sqm), 价格区间 (100k-150k), 单价公式
    # -------------------------------------------------------------------------
    src_09_headers = ["Property_ID", "Floor_Area_Str", "Price_Range_k", "List_Price_USD", "Total_Units"]
    src_09_rows = [
        ["PROP-901", "120sqm", "100k-150k", "240000", "12"],
        ["PROP-902", "85sqm", "80k-95k", "170000", "8"],
        ["PROP-903", "200sqm", "250k-300k", "500000", "20"],
        ["PROP-904", "150sqm", "180k-220k", "375000", "15"],
    ]
    tpl_09_headers = ["Property_ID", "Area_SQM", "Price_Range_k", "List_Price_USD", "Total_Units", "Unit_Price"]
    tpl_09_rows = [
        ["PROP-901", "120", "100k-150k", "240000", "12", "20000.00"],
        ["PROP-902", "85", "80k-95k", "170000", "8", "21250.00"],
        ["PROP-903", "200", "250k-300k", "500000", "20", "25000.00"],
        ["PROP-904", "150", "180k-220k", "375000", "15", "25000.00"],
    ]
    create_workbook(DATASETS_DIR / "09_property_source.xlsx", "MLSProperties", src_09_headers, src_09_rows)
    create_workbook(DATASETS_DIR / "09_property_template.xlsx", "ValuationModel", tpl_09_headers, tpl_09_rows)

    # -------------------------------------------------------------------------
    # 10_factory_qc (Manufacturing QC): 故意纯 outspan / 人工核验留白列
    # -------------------------------------------------------------------------
    src_10_headers = ["Batch_Tag", "Assembly_Line", "Tested_Parts", "Defective_Parts", "Cycle_Seconds"]
    src_10_rows = [
        ["QC-1001", "LINE-Alpha", "1200", "4", "45"],
        ["QC-1002", "LINE-Beta", "950", "1", "48"],
        ["QC-1003", "LINE-Alpha", "1500", "7", "44"],
        ["QC-1004", "LINE-Gamma", "1100", "2", "46"],
    ]
    tpl_10_headers = ["Batch_Tag", "Assembly_Line", "Tested_Parts", "Defective_Parts", "Inspector_Signature", "Shift_Supervisor_Note"]
    tpl_10_rows = [
        ["QC-1001", "LINE-Alpha", "1200", "4", "INSP_APPROVED", "Line alpha certified"],
        ["QC-1002", "LINE-Beta", "950", "1", "INSP_APPROVED", "Routine inspection"],
        ["QC-1003", "LINE-Alpha", "1500", "7", "REWORK_REQUIRED", "High defect variance"],
        ["QC-1004", "LINE-Gamma", "1100", "2", "INSP_APPROVED", "Passed second pass"],
    ]
    create_workbook(DATASETS_DIR / "10_factory_qc_source.xlsx", "BatchProduction", src_10_headers, src_10_rows)
    create_workbook(DATASETS_DIR / "10_factory_qc_template.xlsx", "QualityAudit", tpl_10_headers, tpl_10_rows)

    generate_real_estate_chart()
    print(f"Generated dataset pairs, including 11_real_estate_chart, in {DATASETS_DIR}")



def generate_real_estate_chart() -> None:
    """
    函数名: generate_real_estate_chart
    作用: 写出房产统计脏源表和十列输出表
    输入:
    无
    输出:
    None: 在 datasets 目录写入源表和输出表两个 xlsx
    """
    DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    # 28 列。输出只用其中 5 列；其余列把已有脏格式留在源里，不进入输出。
    src_headers = [
        " Parcel_ID ",
        "distrct_name",
        "list_price",
        "Floor_Area_Str",
        "Closing_Date",
        "Buyer_First",
        "Buyer_Last",
        "Price_Range_k",
        "Permit_Log",
        "HOA_Fee",
        "Listed_At",
        "Bedrooms",
        "Bathrooms",
        "Year_Built",
        "Lot_Size_sqft",
        "Tax_Assessment",
        "Commission_Pct",
        "Listing_Agent",
        "Brokerage",
        "Neighborhood_Code",
        "Occupancy",
        "Garage_Spaces",
        "School_Rating",
        "Days_On_Market",
        "Photo_Count",
        "Internal_Remark",
        "Unit_Count",
        " Contact_Email ",
    ]
    src_rows = [
        ["RE-1101", "Harbor District", "$1,250,000.00", "120sqm", "2026/05/18", "Ada", "Lovelace", "100k-150k", "Scan event BAR-9901-SKU-[1101] verified", "12,50", "2026-05-18 10:15:30.123456", "3", "2", "1998", "2400", "$450,000.00", "2.5", "Kenji Mori", "Harbor Realty", "N-01", "Owner", "2", "8", "21", "12", "Waterfront corner", "4", "ada@harbor.example"],
        ["RE-1102", "Old Town", "¥3,400,000", "85sqm", "18-05-2026", "Alan", "Turing", "80k-95k", "Scan event BAR-9902-Item# 1102 verified", "9.876,50", "2026-05-18 10:16:45.987654", "N/A", "#DIV/0!", "2004", "1800", "¥820,000", "3,00", "Mina Chen", "Old Town Estates", "N-02", "Tenant", "1", "7", "40", "8", "Lane house", "2", "mina@oldtown.example"],
        ["RE-1103", "Lakeview", "($620,000.00)", "200sqm", "45430", "Grace", "Hopper", "250k-300k", "Scan event BAR-9903-REF:1103 verified", "0,500", "2026-05-18 10:18:12.500000", "-", "#REF!", "1986", "5200", "(75,000.00)", "1.5", "Luis Ortega", "Lakeview Partners", "N-03", "Vacant", "0", "6", "90", "4", "Short sale review", "8", "luis@lake.example"],
        ["RE-1104", "Midtown", "$2,500,000.00", "150sqm", "18-May-2026", "Claude", "Shannon", "180k-220k", "Scan event BAR-9904-SKU-[1104] verified", "25,00", "2026-05-18 10:20:00.112233", "NaN", "#VALUE!", "2012", "3000", "$610,000.00", "2,75", "Priya Shah", "Midtown Group", "N-04", "Owner", "1", "9", "15", "20", "High floor", "6", "priya@midtown.example"],
        ["RE-1105", "Riverside", "¥12,000,000", "95sqm", "2026.05.18", "Edsger", "Dijkstra", "400k-480k", "Scan event BAR-9905-Item# 1105 verified", "1.234,56", "2026-05-18 10:22:15.654321", "暂无", "   ", "1979", "4100", "¥2,100,000", "4.0", "Noah Berg", "Riverside Homes", "N-05", "Owner", "2", "8", "33", "6", "River setback", "3", "noah@river.example"],
        ["RE-1106", "Hillcrest", "$4,800,000.00", "110sqm", "05/18/2026", "Barbara", "Liskov", "300k-360k", "Scan event BAR-9906-REF:1106 verified", "15,00", "2026-05-18 02:30:15 PM", "None", "2.5", "2018", "2600", "$980,000.00", "2.0", "Hannah Cole", "Hillcrest Co", "N-06", "Tenant", "2", "10", "12", "15", "Cul-de-sac", "5", "hannah@hill.example"],
        ["RE-1107", "Westend", "1.234.567", "75sqm", "2026-05-18 10:15:30.123456", "Katherine", "Johnson", "70k-90k", "Scan event BAR-9907-SKU-[1107] verified", "0,123456", "2026-05-18 11:01:02.000001", "#N/A", "#NAME?", "1965", "900", "$210,000.00", "1,25", "Omar Farouk", "Westend Realty", "N-07", "Vacant", "0", "5", "120", "3", "Orphan listing not on the chart", "1", "omar@west.example"],
        ["RE-1108", "Northgate", "¥(300,000.00)", "60sqm", "18-05-2026", "Mary", "Jackson", "50k-70k", "Scan event BAR-9908-Item# 1108 verified", "50,00", "2026-05-19 09:00:00.000000", "null", "n/a", "1952", "700", "¥(40,000)", "0,75", "Sophie Nguyen", "Northgate Ltd", "N-08", "Owner", "1", "4", "200", "2", "Withdrawn draft, not on the chart", "1", "sophie@north.example"],
    ]
    # 输出 10 列。行序打乱，且不含 RE-1107 / RE-1108。Buyer_Name 由名和姓拼出。末两列没有源，留给人工填写。
    tpl_headers = [
        "Parcel_ID",
        "District",
        "Closing_Date",
        "Area_SQM",
        "List_Price",
        "Buyer_Name",
        "Area_vs_Mean",
        "Price_Share",
        "Appraiser_Signoff",
        "Compliance_Note",
    ]
    tpl_values = [
        ["RE-1103", "Lakeview", "2024-05-18", 200, -620000, "Grace Hopper"],
        ["RE-1101", "Harbor District", "2026-05-18", 120, 1250000, "Ada Lovelace"],
        ["RE-1106", "Hillcrest", "2026-05-18", 110, 4800000, "Barbara Liskov"],
        ["RE-1102", "Old Town", "2026-05-18", 85, 3400000, "Alan Turing"],
        ["RE-1104", "Midtown", "2026-05-18", 150, 2500000, "Claude Shannon"],
        ["RE-1105", "Riverside", "2026-05-18", 95, 12000000, "Edsger Dijkstra"],
    ]
    wb_src = openpyxl.Workbook()
    ws_src = wb_src.active
    ws_src.title = "ListingFeed"
    ws_src.append(src_headers)
    for row in src_rows:
        ws_src.append(row)
    src_path = DATASETS_DIR / "11_real_estate_chart_source.xlsx"
    wb_src.properties.title = "11_real_estate_chart"
    wb_src.save(src_path)
    wb_src.close()
    wb_out = openpyxl.Workbook()
    ws_out = wb_out.active
    ws_out.title = "11_real_estate_chart"
    ws_out.append(tpl_headers)
    first = 2
    last = 1 + len(tpl_values)
    for offset, row in enumerate(tpl_values):
        excel_row = first + offset
        ws_out.append(row + [
            f'=IF(AVERAGE($D${first}:$D${last})=0,"",D{excel_row}/AVERAGE($D${first}:$D${last}))',
            f'=IF(SUM($E${first}:$E${last})=0,"",E{excel_row}/SUM($E${first}:$E${last}))',
            None,
            None,
        ])
    out_path = DATASETS_DIR / "11_real_estate_chart.xlsx"
    wb_out.properties.title = "11_real_estate_chart"
    wb_out.save(out_path)
    wb_out.close()


if __name__ == "__main__":
    generate_all_datasets()
