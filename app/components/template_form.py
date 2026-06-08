import streamlit as st

from app.components.data_source_settings import get_session_credentials
from app.services.data_source import load_template_data_source
from app.services.excel_parser import (
    build_dataframe_from_form_rows,
    format_cell_display,
    list_sheet_names,
    read_template_sheet,
    write_template_sheet,
)
from app.services.export_naming import build_export_filename
from app.services.google_sheets import GoogleSheetsError, fetch_row_by_id
from app.services.registry import TemplateConfig, update_template_sheet_name
from app.services.source_parser import (
    merge_parsed_into_headers,
    parse_source_text,
    sheet_row_to_form_fields,
)


def _form_rows_key(config_id: str) -> str:
    return f"form_rows_{config_id}"



def _source_text_key(config_id: str) -> str:
    return f"source_text_{config_id}"



def _cell_key(config_id: str, row_idx: int, col_idx: int) -> str:
    return f"cell_{config_id}_{row_idx}_{col_idx}"



def _row_select_key(config_id: str) -> str:
    return f"row_select_{config_id}"



def _summarize_row(row: dict[str, str], row_idx: int) -> str:
    # 生成行摘要供下拉选择
    candidates = [
        ("P.O. No.", "PO"),
        ("Container No.", "箱号"),
        ("Receiving Date", "日期"),
        ("Product", "品名"),
    ]
    parts: list[str] = []
    for field, label in candidates:
        value = row.get(field, "").strip()
        if value:
            parts.append(f"{label}:{value}")
    if not parts:
        return f"{row_idx + 1}. 空行"
    return f"{row_idx + 1}. " + " | ".join(parts)



def _build_row_options(rows: list[dict[str, str]]) -> list[str]:
    # 构建行摘要列表
    return [_summarize_row(row, idx) for idx, row in enumerate(rows)]



def _resolve_selected_index(config_id: str, options: list[str]) -> int:
    # 解析已选行索引
    if not options:
        return 0
    key = _row_select_key(config_id)
    selected = st.session_state.get(key, options[0])
    if selected in options:
        return options.index(selected)
    return 0



def _init_form_rows(config: TemplateConfig, headers: list[str], dataframe) -> list[dict[str, str]]:
    # 从模板初始化表单行，存入 session_state
    key = _form_rows_key(config.id)
    if key not in st.session_state:
        st.session_state[key] = [
            {header: format_cell_display(dataframe.iloc[row_idx][header]) for header in headers}
            for row_idx in range(len(dataframe))
        ]
    return st.session_state[key]



def _sync_cell_keys(config_id: str, headers: list[str], rows: list[dict[str, str]]) -> None:
    # 将行数据同步到各单元格 widget 的 session_state 键
    for row_idx, row in enumerate(rows):
        for col_idx, header in enumerate(headers):
            st.session_state[_cell_key(config_id, row_idx, col_idx)] = row.get(header, "")



def _apply_source_parse(config: TemplateConfig, headers: list[str], source_text: str) -> bool:
    # 解析粘贴的源数据并写入表单行
    try:
        parsed_rows = parse_source_text(source_text)
    except ValueError as exc:
        st.error(f"解析失败: {exc}")
        return False
    if not parsed_rows:
        st.warning("未解析到有效数据行，请检查粘贴内容。")
        return False
    existing_rows = st.session_state.get(_form_rows_key(config.id), [])
    merged_rows: list[dict[str, str]] = []
    for idx, parsed in enumerate(parsed_rows):
        existing = existing_rows[idx] if idx < len(existing_rows) else None
        merged_rows.append(merge_parsed_into_headers(headers, parsed, existing))
    st.session_state[_form_rows_key(config.id)] = merged_rows
    _sync_cell_keys(config.id, headers, merged_rows)
    return True



def _apply_sheet_lookup(config: TemplateConfig, headers: list[str], po_value: str) -> bool:
    # 按 P.O. No. / PO 从默认数据源拉取行并填入表单
    data_source = load_template_data_source(config.id)
    if data_source is None:
        st.warning("请先在侧边栏「添加数据源」配置当前模板的 Google Sheet。")
        return False
    credentials = get_session_credentials()
    if credentials is None:
        st.warning("请先在侧边栏完成 Google 认证（服务账号或 OAuth）。")
        return False
    with st.spinner("正在从 Google Sheet 查询..."):
        try:
            row = fetch_row_by_id(
                credentials,
                data_source.spreadsheet_id,
                data_source.worksheet_name or None,
                data_source.id_column,
                po_value,
            )
        except GoogleSheetsError as exc:
            st.error(str(exc))
            for hint in exc.hints:
                st.markdown(f"- {hint}")
            return False
        except Exception as exc:
            st.error(f"查询失败: {exc}")
            return False
    if row is None:
        st.warning(f"未找到 {data_source.id_column}={po_value!r} 的记录。")
        return False
    try:
        parsed = sheet_row_to_form_fields(row, data_source.id_column)
    except ValueError as exc:
        st.error(f"行数据映射失败: {exc}")
        return False
    existing_rows = st.session_state.get(_form_rows_key(config.id), [])
    merged = merge_parsed_into_headers(headers, parsed, existing_rows[0] if existing_rows else None)
    st.session_state[_form_rows_key(config.id)] = [merged]
    _sync_cell_keys(config.id, headers, [merged])
    return True



def _render_sheet_lookup_area(config: TemplateConfig, headers: list[str]) -> None:
    # 已配置数据源时，按 PO 查询并自动填表
    data_source = load_template_data_source(config.id)
    if data_source is None:
        return
    st.subheader("按 PO 查询")
    st.caption(
        f"从当前模板的数据源（工作表 `{data_source.worksheet_name or '默认'}`，"
        f"ID 列 `{data_source.id_column}`）拉取记录，填入 P.O. No. 等字段。"
    )
    po_value = st.text_input(
        "P.O. No. / PO",
        placeholder="例如 10073",
        key=f"po_lookup_{config.id}",
    )
    if st.button("查询并填入", key=f"po_fetch_{config.id}"):
        if not po_value.strip():
            st.warning("请输入 PO 编号。")
            return
        if _apply_sheet_lookup(config, headers, po_value.strip()):
            st.rerun()



def _render_source_paste_area(config: TemplateConfig, headers: list[str]) -> None:
    # 顶部源数据粘贴区与解析按钮
    st.subheader("源数据粘贴")
    st.caption("粘贴制表符分隔的原始数据，每行对应表单中的一行记录。")
    source_key = _source_text_key(config.id)
    source_text = st.text_area(
        "源数据",
        height=120,
        placeholder="粘贴制表符分隔数据，例如：\n10073\tGIN\t...\t6/1\t...",
        key=source_key,
    )
    if st.button("解析并填入", key=f"parse_{config.id}"):
        if _apply_source_parse(config, headers, source_text):
            st.rerun()



def _render_data_rows(
    config: TemplateConfig,
    headers: list[str],
    rows: list[dict[str, str]],
    selected_index: int,
) -> list[dict[str, str]]:
    # 按行分组渲染单元格输入，标签为第 1 行列标题
    edited_rows: list[dict[str, str]] = []
    for row_idx, row in enumerate(rows):
        if row_idx != selected_index:
            edited_rows.append(row)
            continue
        st.markdown(f"**第 {row_idx + 1} 行**")
        columns = st.columns(len(headers))
        row_values: dict[str, str] = {}
        for col_idx, header in enumerate(headers):
            with columns[col_idx]:
                cell_key = _cell_key(config.id, row_idx, col_idx)
                if cell_key not in st.session_state:
                    st.session_state[cell_key] = row.get(header, "")
                input_value = st.text_input(
                    header,
                    key=cell_key,
                )
            row_values[header] = input_value
        edited_rows.append(row_values)
    st.session_state[_form_rows_key(config.id)] = edited_rows
    return edited_rows



def render_template_page(config: TemplateConfig) -> None:
    # 渲染单个模板的可视化录入表单
    st.title(config.display_name)
    if not config.file_path.exists():
        st.error(f"模板文件不存在: {config.file_path}")
        st.info("请将 GIN LOT TEMPLATE.xlsx 复制到 templates/gin_lot_template.xlsx，或设置环境变量 GIN_LOT_TEMPLATE_PATH。")
        return
    try:
        sheet_names = list_sheet_names(config.file_path)
    except Exception as exc:
        st.error(f"读取工作表列表失败: {exc}")
        return
    if not sheet_names:
        st.error("模板内没有可用工作表。")
        return
    default_sheet = config.sheet_name if config.sheet_name in sheet_names else sheet_names[0]
    sheet_col, action_col = st.columns([3, 1])
    with sheet_col:
        selected_sheet = st.selectbox(
            "工作表",
            sheet_names,
            index=sheet_names.index(default_sheet),
            key=f"sheet_select_{config.id}",
        )
    with action_col:
        if st.button("设为默认", key=f"sheet_default_{config.id}"):
            updated = update_template_sheet_name(config.id, selected_sheet)
            if updated is None:
                st.error("未找到对应模板，无法保存默认工作表。")
            else:
                st.success("已更新默认工作表。")
            st.rerun()
    st.markdown(f"**文件**: `{config.file_path}`")
    try:
        dataframe = read_template_sheet(
            config.file_path,
            selected_sheet,
            config.header_row,
            config.data_start_row,
        )
    except Exception as exc:
        st.error(f"读取模板失败: {exc}")
        return
    headers = list(dataframe.columns)
    if dataframe.empty:
        st.info("工作表无数据行，解析源数据后将自动创建表单行。")
        if _form_rows_key(config.id) not in st.session_state:
            st.session_state[_form_rows_key(config.id)] = []
    else:
        _init_form_rows(config, headers, dataframe)
    _render_sheet_lookup_area(config, headers)
    _render_source_paste_area(config, headers)
    st.subheader("数据录入")
    rows = st.session_state.get(_form_rows_key(config.id), [])
    if not rows:
        st.info("暂无数据行，请在上方粘贴源数据并点击「解析并填入」。")
        return
    st.subheader("已存在数据")
    options = _build_row_options(rows)
    selected_index = _resolve_selected_index(config.id, options)
    selected_label = st.selectbox(
        "选择行（显示摘要）",
        options,
        index=selected_index,
        key=_row_select_key(config.id),
    )
    selected_index = options.index(selected_label) if selected_label in options else 0
    edited_rows = _render_data_rows(config, headers, rows, selected_index)
    edited = build_dataframe_from_form_rows(headers, edited_rows)
    xlsx_bytes = write_template_sheet(
        config.file_path,
        selected_sheet,
        edited,
        config.header_row,
        config.data_start_row,
    )
    # 生成带 PO 与日期的导出文件名
    export_filename = build_export_filename(config.file_path, edited_rows)
    st.download_button(
        label="Save As",
        data=xlsx_bytes,
        file_name=export_filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"save_as_{config.id}",
    )
    st.download_button(
        label="下载更新后的 Excel",
        data=xlsx_bytes,
        file_name=f"{config.id}_filled.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"download_{config.id}",
    )
