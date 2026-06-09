import time
from datetime import timedelta
from pathlib import Path

import streamlit as st

from app.components.data_source_settings import (
    ID_LOOKUP_DELAY_SECONDS,
    get_session_credentials,
    render_data_sources_tab,
)
from app.components.paste_parse_settings import render_paste_mapping_tab
from app.services.paste_parse_config import (
    id_target_field_from_config,
    load_paste_parse_config,
    parse_text_with_config,
    resolve_id_target_field,
)
from app.services.data_source import (
    load_template_data_source,
    sheet_mappings,
)
from app.services.excel_parser import (
    build_dataframe_from_form_rows,
    format_cell_display,
    list_sheet_names,
    read_template_sheet,
    write_template_sheet,
)
from app.services.excel_print import (
    ensure_print_image,
    open_print_preview_dialog,
    persist_export_file,
    primary_print_area,
)
from app.services.export_naming import build_export_filename
from app.services.google_sheets import GoogleSheetsError, fetch_row_by_id
from app.services.registry import TemplateConfig, update_template_sheet_name
from app.services.source_parser import (
    merge_parsed_into_headers,
    sheet_row_to_form_fields,
)


def _form_rows_key(config_id: str) -> str:
    return f"form_rows_{config_id}"


def _pending_export_bytes_key(config_id: str) -> str:
    return f"pending_export_bytes_{config_id}"


def _pending_export_filename_key(config_id: str) -> str:
    return f"pending_export_filename_{config_id}"


def _last_export_path_key(config_id: str) -> str:
    return f"last_export_path_{config_id}"


def _persist_export_on_save_as(config_id: str) -> None:
    xlsx_bytes = st.session_state.get(_pending_export_bytes_key(config_id))
    filename = st.session_state.get(_pending_export_filename_key(config_id))
    if not xlsx_bytes or not filename:
        return
    saved_path = persist_export_file(config_id, xlsx_bytes, filename)
    st.session_state[_last_export_path_key(config_id)] = str(saved_path)
    area = primary_print_area(saved_path)
    if area:
        ensure_print_image(saved_path, area.sheet, area.range)


def _get_last_export_path(config_id: str) -> Path | None:
    raw = st.session_state.get(_last_export_path_key(config_id))
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_file() else None



def _source_text_key(config_id: str) -> str:
    return f"source_text_{config_id}"



def _cell_key(config_id: str, row_idx: int, col_idx: int) -> str:
    return f"cell_{config_id}_{row_idx}_{col_idx}"



def _row_select_key(config_id: str) -> str:
    return f"row_select_{config_id}"



def _auto_id_state_key(config_id: str, row_idx: int) -> str:
    return f"auto_id_{config_id}_{row_idx}"



def _summarize_row(row: dict[str, str], row_idx: int) -> str:
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



def _resolve_selected_index(config_id: str, row_count: int) -> int:
    if row_count <= 0:
        return 0
    key = _row_select_key(config_id)
    selected = st.session_state.get(key, 0)
    if isinstance(selected, int) and 0 <= selected < row_count:
        return selected
    return 0



def _form_sheet_key(config_id: str) -> str:
    return f"form_loaded_sheet_{config_id}"


def _form_mtime_key(config_id: str) -> str:
    return f"form_loaded_mtime_{config_id}"


def _rows_from_dataframe(headers: list[str], dataframe) -> list[dict[str, str]]:
    return [
        {header: format_cell_display(dataframe.iloc[row_idx][header]) for header in headers}
        for row_idx in range(len(dataframe))
    ]


def _ensure_form_rows_from_sheet(
    config: TemplateConfig,
    headers: list[str],
    dataframe,
    selected_sheet: str,
) -> None:
    rows_key = _form_rows_key(config.id)
    sheet_key = _form_sheet_key(config.id)
    mtime_key = _form_mtime_key(config.id)
    if dataframe.empty:
        if rows_key not in st.session_state:
            st.session_state[rows_key] = []
        return
    mtime = config.file_path.stat().st_mtime_ns
    reload = (
        rows_key not in st.session_state
        or st.session_state.get(sheet_key) != selected_sheet
        or st.session_state.get(mtime_key) != mtime
    )
    if reload:
        st.session_state[rows_key] = _rows_from_dataframe(headers, dataframe)
        st.session_state[sheet_key] = selected_sheet
        st.session_state[mtime_key] = mtime


def _prime_cell_keys(config_id: str, headers: list[str], rows: list[dict[str, str]]) -> None:
    for row_idx, row in enumerate(rows):
        for col_idx, header in enumerate(headers):
            st.session_state[_cell_key(config_id, row_idx, col_idx)] = row.get(header, "")


def _apply_source_parse(config: TemplateConfig, headers: list[str], source_text: str) -> bool:
    paste_config = load_paste_parse_config(config.id)
    if paste_config is None:
        st.warning("请先在「粘贴映射」Tab 生成并保存 YAML。")
        return False
    try:
        parsed_rows = parse_text_with_config(source_text, paste_config)
    except ValueError as exc:
        st.error(f"解析失败: {exc}")
        return False
    if not parsed_rows:
        st.warning("未解析到有效数据行，请检查粘贴内容。")
        return False
    existing_rows = list(st.session_state.get(_form_rows_key(config.id), []))
    for idx, parsed in enumerate(parsed_rows):
        existing = existing_rows[idx] if idx < len(existing_rows) else None
        merged = merge_parsed_into_headers(headers, parsed, existing)
        if idx < len(existing_rows):
            existing_rows[idx] = merged
        else:
            existing_rows.append(merged)
    st.session_state[_form_rows_key(config.id)] = existing_rows
    _prime_cell_keys(config.id, headers, existing_rows)
    return True



def _apply_sheet_lookup(
    config: TemplateConfig,
    headers: list[str],
    po_value: str,
    target_row_index: int,
    *,
    show_errors: bool = True,
) -> bool:
    data_source = load_template_data_source(config.id)
    if data_source is None:
        if show_errors:
            st.warning("请先在「数据源」Tab 配置并保存 Google Sheet。")
        return False
    credentials = get_session_credentials()
    if credentials is None:
        if show_errors:
            st.warning("请先在「数据源」Tab 完成 Google 认证。")
        return False
    mappings = sheet_mappings(data_source)
    spinner = st.spinner("正在从 Google Sheet 查询...") if show_errors else _null_context()
    with spinner:
        try:
            row = fetch_row_by_id(
                credentials,
                data_source.spreadsheet_id,
                data_source.worksheet_name or None,
                data_source.id_column,
                po_value,
            )
        except GoogleSheetsError as exc:
            if show_errors:
                st.error(str(exc))
                for hint in exc.hints:
                    st.markdown(f"- {hint}")
            return False
        except Exception as exc:
            if show_errors:
                st.error(f"查询失败: {exc}")
            return False
    if row is None:
        if show_errors:
            st.warning(f"未找到 {data_source.id_column}={po_value!r} 的记录。")
        return False
    try:
        parsed = sheet_row_to_form_fields(
            row,
            data_source.id_column,
            mappings=mappings or None,
        )
    except ValueError as exc:
        if show_errors:
            st.error(f"行数据映射失败: {exc}")
        return False
    existing_rows = list(st.session_state.get(_form_rows_key(config.id), []))
    if not existing_rows:
        existing_rows = [{header: "" for header in headers}]
    while len(existing_rows) <= target_row_index:
        existing_rows.append({header: "" for header in headers})
    merged = merge_parsed_into_headers(headers, parsed, existing_rows[target_row_index])
    existing_rows[target_row_index] = merged
    st.session_state[_form_rows_key(config.id)] = existing_rows
    _prime_cell_keys(config.id, headers, existing_rows)
    return True



class _null_context:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False



def _poll_auto_id_lookup(
    config: TemplateConfig,
    headers: list[str],
    selected_index: int,
) -> None:
    data_source = load_template_data_source(config.id)
    id_field = resolve_id_target_field(config.id, data_source, headers)
    if not id_field or not data_source or not data_source.id_column:
        return
    col_idx = headers.index(id_field)
    cell_key = _cell_key(config.id, selected_index, col_idx)
    current = str(st.session_state.get(cell_key, "")).strip()
    state_key = _auto_id_state_key(config.id, selected_index)
    state = st.session_state.setdefault(state_key, {"value": "", "since": 0.0, "done": ""})
    now = time.time()
    if current != state["value"]:
        state["value"] = current
        state["since"] = now
        state["done"] = ""
        return
    if not current or current == state["done"]:
        return
    elapsed = now - state["since"]
    if elapsed < ID_LOOKUP_DELAY_SECONDS:
        return
    if _apply_sheet_lookup(config, headers, current, selected_index, show_errors=False):
        state["done"] = current
        st.rerun()



def _render_auto_lookup_fragment(
    config: TemplateConfig,
    headers: list[str],
    selected_index: int,
) -> None:
    fragment = getattr(st, "fragment", None)
    if fragment is None:
        _poll_auto_id_lookup(config, headers, selected_index)
        return

    @fragment(run_every=timedelta(seconds=1))
    def _auto_lookup_runner() -> None:
        _poll_auto_id_lookup(config, headers, selected_index)

    _auto_lookup_runner()



def _render_source_paste_area(config: TemplateConfig, headers: list[str]) -> None:
    st.subheader("源数据粘贴")
    source_key = _source_text_key(config.id)
    source_text = st.text_area(
        "源数据",
        height=120,
        key=source_key,
        label_visibility="collapsed",
    )
    has_paste_config = load_paste_parse_config(config.id) is not None
    parse_disabled = not has_paste_config
    if st.button("解析并填入", key=f"parse_{config.id}", disabled=parse_disabled):
        if _apply_source_parse(config, headers, source_text):
            st.rerun()
    elif parse_disabled:
        st.caption("请先在「粘贴映射」Tab 保存 YAML 映射。")



LABEL_PEEK_SIZE = 10
MAX_COLS_PER_ROW = 11


def _cols_from_peeked_labels(peeked_headers: list[str]) -> int:
    # 从当前位置往后最多 10 个 label 中最长者决定本行列数（最多 11 列，最少 1 列）
    if not peeked_headers:
        return MAX_COLS_PER_ROW
    max_label_len = max(len(header.strip()) for header in peeked_headers)
    if max_label_len <= 10:
        return MAX_COLS_PER_ROW
    tier = (max_label_len - 1) // 10
    return max(1, MAX_COLS_PER_ROW - tier * 2)


def _header_row_chunks(headers: list[str]) -> list[list[tuple[int, str]]]:
    # 每行：从当前位置往后抓 10 个 label 判断列数，本行最多放该列数个字段，再往后推进
    visual_rows: list[list[tuple[int, str]]] = []
    pos = 0
    while pos < len(headers):
        peeked = headers[pos : pos + LABEL_PEEK_SIZE]
        per_row = _cols_from_peeked_labels(peeked)
        count = min(per_row, len(headers) - pos)
        visual_rows.append(list(enumerate(headers[pos : pos + count], start=pos)))
        pos += count
    return visual_rows



def _render_data_rows(
    config: TemplateConfig,
    headers: list[str],
    rows: list[dict[str, str]],
    selected_index: int,
) -> list[dict[str, str]]:
    _render_auto_lookup_fragment(config, headers, selected_index)
    edited_rows: list[dict[str, str]] = []
    for row_idx, row in enumerate(rows):
        if row_idx != selected_index:
            edited_rows.append(row)
            continue
        st.markdown(f"**第 {row_idx + 1} 行**")
        row_values: dict[str, str] = {}
        for chunk in _header_row_chunks(headers):
            columns = st.columns(len(chunk))
            for col_idx, (global_col_idx, header) in enumerate(chunk):
                with columns[col_idx]:
                    cell_key = _cell_key(config.id, row_idx, global_col_idx)
                    input_value = st.text_input(
                        header,
                        key=cell_key,
                    )
                row_values[header] = input_value
        edited_rows.append(row_values)
    st.session_state[_form_rows_key(config.id)] = edited_rows
    return edited_rows



def _render_sheet_selector(config: TemplateConfig, sheet_names: list[str]) -> str:
    default_sheet = config.sheet_name if config.sheet_name in sheet_names else sheet_names[0]
    st.subheader("工作表")
    selected_sheet = st.selectbox(
        "工作表",
        sheet_names,
        index=sheet_names.index(default_sheet),
        key=f"sheet_select_{config.id}",
        label_visibility="collapsed",
    )
    st.markdown(f"**文件**: `{config.file_path}`")
    if st.button("设为需要填写的表格", key=f"sheet_default_{config.id}"):
        updated = update_template_sheet_name(config.id, selected_sheet)
        if updated is None:
            st.error("未找到对应模板，无法保存工作表设置。")
        else:
            st.success("已设为需要填写的表格。")
        st.rerun()
    return selected_sheet



def _load_template_headers(config: TemplateConfig, sheet_names: list[str]) -> tuple[str, list[str]]:
    default_sheet = config.sheet_name if config.sheet_name in sheet_names else sheet_names[0]
    dataframe = read_template_sheet(
        config.file_path,
        default_sheet,
        config.header_row,
        config.data_start_row,
    )
    return default_sheet, list(dataframe.columns)



def _render_form_entry_tab(config: TemplateConfig, sheet_names: list[str]) -> None:
    sheet_col, paste_col = st.columns([2, 3])
    with sheet_col:
        selected_sheet = _render_sheet_selector(config, sheet_names)
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
        with sheet_col:
            st.info("工作表无数据行，解析源数据后将自动创建表单行。")
    _ensure_form_rows_from_sheet(config, headers, dataframe, selected_sheet)
    with paste_col:
        _render_source_paste_area(config, headers)
    st.subheader("数据录入")
    rows = st.session_state.get(_form_rows_key(config.id), [])
    if not rows:
        st.info("暂无数据行，请在上方粘贴源数据并点击「解析并填入」。")
        return
    data_source = load_template_data_source(config.id)
    id_field = resolve_id_target_field(config.id, data_source, headers)
    if data_source and id_field:
        st.caption(
            f"在 `{id_field}` 输入 {data_source.id_column} 值，"
            f"稳定 {int(ID_LOOKUP_DELAY_SECONDS)} 秒后自动从 Sheet 查询并填入。"
        )
    st.subheader("已存在数据")
    _prime_cell_keys(config.id, headers, rows)
    selected_index = _resolve_selected_index(config.id, len(rows))
    selected_index = st.selectbox(
        "选择行（显示摘要）",
        options=list(range(len(rows))),
        format_func=lambda row_idx: _summarize_row(rows[row_idx], row_idx),
        index=selected_index,
        key=_row_select_key(config.id),
    )
    edited_rows = _render_data_rows(config, headers, rows, selected_index)
    edited = build_dataframe_from_form_rows(headers, edited_rows)
    xlsx_bytes = write_template_sheet(
        config.file_path,
        selected_sheet,
        edited,
        config.header_row,
        config.data_start_row,
    )
    paste_config = load_paste_parse_config(config.id)
    id_field = id_target_field_from_config(paste_config) or "P.O. No."
    export_filename = build_export_filename(
        config.file_path,
        edited_rows,
        id_column=id_field,
    )
    st.session_state[_pending_export_bytes_key(config.id)] = xlsx_bytes
    st.session_state[_pending_export_filename_key(config.id)] = export_filename
    last_export_path = _get_last_export_path(config.id)
    print_area = primary_print_area(last_export_path) if last_export_path else None
    col_save, col_print = st.columns(2)
    with col_save:
        st.download_button(
            label="Save As",
            data=xlsx_bytes,
            file_name=export_filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"save_as_{config.id}",
            use_container_width=True,
            on_click=_persist_export_on_save_as,
            args=(config.id,),
        )
    with col_print:
        if last_export_path and print_area:
            if st.button(
                f"打印 {print_area.label}",
                key=f"print_{config.id}",
                use_container_width=True,
            ):
                try:
                    preview_path = ensure_print_image(
                        last_export_path,
                        print_area.sheet,
                        print_area.range,
                    )
                    open_print_preview_dialog(preview_path)
                except Exception as exc:
                    st.error(str(exc))
    if last_export_path and print_area:
        try:
            preview_path = ensure_print_image(
                last_export_path,
                print_area.sheet,
                print_area.range,
            )
            st.image(str(preview_path), caption="打印预览", use_container_width=True)
        except Exception as exc:
            st.error(str(exc))



FORM_TAB_LABELS = ["数据录入", "粘贴映射", "数据源"]
FORM_TAB_SESSION_KEY = "form_page_tab"


def render_template_page(config: TemplateConfig) -> None:
    st.title(config.display_name)
    if not config.file_path.exists():
        st.error(f"模板文件不存在: {config.file_path}")
        st.info("请将对应的 xlsx 文件复制到 templates/ 目录。")
        return
    try:
        sheet_names = list_sheet_names(config.file_path)
    except Exception as exc:
        st.error(f"读取工作表列表失败: {exc}")
        return
    if not sheet_names:
        st.error("模板内没有可用工作表。")
        return
    try:
        _, template_fields = _load_template_headers(config, sheet_names)
    except Exception as exc:
        st.error(f"读取模板列失败: {exc}")
        return
    entry_tab, mapping_tab, sources_tab = st.tabs(
        FORM_TAB_LABELS,
        default=FORM_TAB_LABELS[0],
        key=FORM_TAB_SESSION_KEY,
    )
    with entry_tab:
        _render_form_entry_tab(config, sheet_names)
    with mapping_tab:
        render_paste_mapping_tab(config.id, template_fields)
    with sources_tab:
        render_data_sources_tab(config.id, template_fields)
