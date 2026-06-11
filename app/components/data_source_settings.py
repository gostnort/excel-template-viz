import json

import pandas as pd
import streamlit as st

from app.services.data_source import (
    DEFAULT_COLUMN_MAPPINGS,
    DEFAULT_ID_COLUMN,
    DataSourceConfig,
    clear_template_data_source,
    load_template_data_source,
    save_template_data_source,
    save_template_id_column,
)
from app.services.excel_parser import parse_spreadsheet_id
from app.services.paste_parse_config import (
    load_paste_parse_config,
    id_column_from_config,
    validate_yaml_against_sheet_headers,
)
from app.services.google_sheets import (
    GoogleSheetsError,
    credentials_from_service_account_json,
    fetch_sheet_preview,
    list_worksheet_titles,
    run_oauth_flow,
)

CREDENTIALS_SESSION_KEY = "gs_credentials"
AUTH_METHOD_SESSION_KEY = "gs_auth_method"
ID_LOOKUP_DELAY_SECONDS = 2.0


def get_session_credentials():
    # 从 session 读取当前 Google 凭证
    return st.session_state.get(CREDENTIALS_SESSION_KEY)



def _suffix(template_id: str) -> str:
    return f"_{template_id}"


def _test_ok_key(template_id: str) -> str:
    return f"ds_test_ok{_suffix(template_id)}"


def _columns_key(template_id: str) -> str:
    return f"ds_sheet_columns{_suffix(template_id)}"


def _worksheets_key(template_id: str) -> str:
    return f"ds_worksheet_titles{_suffix(template_id)}"


def _meta_key(template_id: str) -> str:
    return f"ds_last_meta{_suffix(template_id)}"


def _mappings_editor_key(template_id: str) -> str:
    return f"ds_mappings_editor{_suffix(template_id)}"


def is_sheet_test_ok(template_id: str) -> bool:
    return bool(st.session_state.get(_test_ok_key(template_id)))


def get_validated_sheet_columns(template_id: str) -> list[str]:
    return list(st.session_state.get(_columns_key(template_id), []))


def get_validated_worksheet_titles(template_id: str) -> list[str]:
    return list(st.session_state.get(_worksheets_key(template_id), []))


def _restore_validation_state(template_id: str, saved: DataSourceConfig | None) -> None:
    if saved is None or is_sheet_test_ok(template_id):
        return
    if saved.spreadsheet_id:
        st.session_state[_test_ok_key(template_id)] = True
        sheet_columns = [
            item["source"]
            for item in saved.column_mappings
            if item.get("kind", "sheet") == "sheet"
        ]
        if saved.id_column and saved.id_column not in sheet_columns:
            sheet_columns.append(saved.id_column)
        if sheet_columns:
            st.session_state[_columns_key(template_id)] = sheet_columns
        if saved.worksheet_name:
            st.session_state[_worksheets_key(template_id)] = [saved.worksheet_name]



def _render_auth_controls() -> None:
    if CREDENTIALS_SESSION_KEY in st.session_state:
        auth_method_saved = st.session_state.get(AUTH_METHOD_SESSION_KEY, "service_account")
        auth_label = "服务账号 JSON" if auth_method_saved == "service_account" else "OAuth 用户授权"
        st.success(f"✅ Google Sheets 认证成功！当前已加载并激活「{auth_label}」会话凭证。")
        if st.button("重新认证 / 切换账号", key="ds_reauth_btn"):
            st.session_state.pop(CREDENTIALS_SESSION_KEY, None)
            st.session_state.pop(AUTH_METHOD_SESSION_KEY, None)
            st.rerun()
        return

    auth_method = st.radio("认证方式", ["服务账号 JSON", "OAuth 用户授权"], horizontal=True, key="ds_auth_method")
    if auth_method == "服务账号 JSON":
        uploaded = st.file_uploader("上传服务账号 JSON 密钥", type=["json"], key="ds_sa_upload")
        if uploaded is not None:
            raw = uploaded.getvalue().decode("utf-8")
            try:
                credentials = credentials_from_service_account_json(raw)
                st.session_state[CREDENTIALS_SESSION_KEY] = credentials
                st.session_state[AUTH_METHOD_SESSION_KEY] = "service_account"
                email = json.loads(raw).get("client_email", "")
                if email:
                    st.info(f"服务账号邮箱: `{email}` — 请确保 Google Sheet 已共享给该邮箱。")
            except GoogleSheetsError as exc:
                st.error(str(exc))
                for hint in exc.hints:
                    st.markdown(f"- {hint}")
    else:
        st.caption("OAuth 需要项目根目录 `credentials/oauth_client.json`。")
        if st.button("启动 OAuth 授权", key="ds_oauth_start"):
            try:
                credentials = run_oauth_flow()
                st.session_state[CREDENTIALS_SESSION_KEY] = credentials
                st.session_state[AUTH_METHOD_SESSION_KEY] = "oauth"
                st.success("OAuth 授权成功。")
            except GoogleSheetsError as exc:
                st.error(str(exc))
                for hint in exc.hints:
                    st.markdown(f"- {hint}")
            except Exception as exc:
                st.error(f"OAuth 失败: {exc}")



def _run_sheet_test(
    template_id: str,
    sheet_url: str,
    worksheet_name: str | None,
    max_rows: int,
) -> None:
    credentials = get_session_credentials()
    if credentials is None:
        st.warning("请先上传服务账号 JSON 或完成 OAuth 授权。")
        return
    with st.spinner("正在连接 Google Sheets..."):
        try:
            preview, meta = fetch_sheet_preview(
                credentials,
                sheet_url,
                worksheet_name,
                int(max_rows),
            )
            titles = list_worksheet_titles(credentials, sheet_url)
            st.session_state[_meta_key(template_id)] = meta
            st.session_state[_test_ok_key(template_id)] = True
            st.session_state[_worksheets_key(template_id)] = titles
            st.session_state[_columns_key(template_id)] = list(preview.columns) if not preview.empty else []
            st.success(
                f"连接成功 — 表格「{meta['spreadsheet_title']}」"
                f" / 工作表「{meta['worksheet_title']}」"
                f"（共约 {meta['row_count']} 行）"
            )
            if preview.empty:
                st.info("工作表为空或仅有标题行。")
            else:
                st.dataframe(preview, use_container_width=True)
        except GoogleSheetsError as exc:
            st.error(str(exc))
            if exc.hints:
                for hint in exc.hints:
                    st.markdown(f"- {hint}")
        except Exception as exc:
            st.error(f"未知错误: {exc}")



def _default_worksheet_index(titles: list[str], saved_name: str) -> int:
    if saved_name and saved_name in titles:
        return titles.index(saved_name)
    return 0



def _default_column_index(columns: list[str], saved_name: str) -> int:
    if saved_name and saved_name in columns:
        return columns.index(saved_name)
    return 0



def _render_mapping_editor(template_id: str, template_fields: list[str], saved: DataSourceConfig | None) -> None:
    st.subheader("列映射")
    st.caption("Sheet 映射用于 Google Sheet 查询；Tab 映射用于制表符粘贴（source 为列索引，从 0 开始）。")
    default_rows = (saved.column_mappings if saved else None) or DEFAULT_COLUMN_MAPPINGS
    editor_key = _mappings_editor_key(template_id)
    if editor_key not in st.session_state:
        st.session_state[editor_key] = pd.DataFrame(default_rows)
    edited = st.data_editor(
        st.session_state[editor_key],
        num_rows="dynamic",
        column_config={
            "source": st.column_config.TextColumn("源列/索引", required=True),
            "target": st.column_config.SelectboxColumn("目标字段", options=template_fields, required=True),
            "kind": st.column_config.SelectboxColumn("类型", options=["sheet", "tab"], required=True),
        },
        use_container_width=True,
        key=f"ds_mapping_widget{_suffix(template_id)}",
    )
    st.session_state[editor_key] = edited



def _extract_mappings(template_id: str, saved: DataSourceConfig | None) -> list[dict[str, str]]:
    editor_key = _mappings_editor_key(template_id)
    frame = st.session_state.get(editor_key)
    if frame is None:
        return list((saved.column_mappings if saved else None) or DEFAULT_COLUMN_MAPPINGS)
    mappings: list[dict[str, str]] = []
    for _, row in frame.iterrows():
        source = str(row.get("source", "")).strip()
        target = str(row.get("target", "")).strip()
        kind = str(row.get("kind", "sheet")).strip() or "sheet"
        if source and target:
            mappings.append({"source": source, "target": target, "kind": kind})
    return mappings or list(DEFAULT_COLUMN_MAPPINGS)



def render_data_sources_tab(template_id: str, template_fields: list[str]) -> None:
    # 模板页数据源 Tab：认证、测试、下拉选择与列映射
    saved = load_template_data_source(template_id)
    _restore_validation_state(template_id, saved)
    suffix = _suffix(template_id)
    st.subheader("Google Sheet 数据源")
    _render_auth_controls()
    default_url = saved.sheet_url if saved else ""
    sheet_url = st.text_input(
        "Google Sheet URL",
        value=default_url,
        placeholder="https://docs.google.com/spreadsheets/d/...",
        key=f"ds_sheet_url{suffix}",
    )
    max_rows = st.number_input(
        "测试预览行数",
        min_value=1,
        max_value=20,
        value=5,
        key=f"ds_max_rows{suffix}",
    )
    if st.button("测试连接", type="primary", key=f"ds_test{suffix}"):
        if not sheet_url.strip():
            st.warning("请先填写 Google Sheet URL。")
        else:
            _run_sheet_test(template_id, sheet_url.strip(), None, int(max_rows))
    test_ok = is_sheet_test_ok(template_id)
    worksheet_titles = get_validated_worksheet_titles(template_id)
    sheet_columns = get_validated_sheet_columns(template_id)
    saved_worksheet = saved.worksheet_name if saved else ""
    saved_id_col = saved.id_column if saved else DEFAULT_ID_COLUMN

    paste_config = load_paste_parse_config(template_id)
    yaml_id_col = id_column_from_config(paste_config) if paste_config else None
    default_id_col = saved_id_col
    if yaml_id_col and yaml_id_col in sheet_columns:
        default_id_col = yaml_id_col

    if not test_ok:
        st.selectbox("工作表", options=["请先测试连接"], disabled=True, key=f"ds_worksheet_locked{suffix}")
        st.selectbox("ID 列", options=["请先测试连接"], disabled=True, key=f"ds_id_col_locked{suffix}")
    else:
        st.selectbox(
            "工作表",
            worksheet_titles or [saved_worksheet or "默认"],
            index=_default_worksheet_index(worksheet_titles, saved_worksheet),
            key=f"ds_worksheet_select{suffix}",
        )
        st.selectbox(
            "ID 列",
            sheet_columns or [default_id_col],
            index=_default_column_index(sheet_columns, default_id_col),
            key=f"ds_id_column_select{suffix}",
        )
        if paste_config and sheet_columns:
            st.markdown("### 📋 YAML 与 Google Sheet 在线表头匹配对齐状态")
            res = validate_yaml_against_sheet_headers(paste_config, sheet_columns)
            yaml_fields = []
            for field, rules in paste_config.field_rules.items():
                for rule in rules:
                    if rule.filed and rule.filed != "?":
                        yaml_fields.append((field, rule.filed))
            align_rows = []
            for field, filed in yaml_fields:
                if filed in res["matched"]:
                    status = "✅ 已对齐"
                    actual = res["matched"][filed]
                else:
                    status = "❌ 未在 Sheet 中找到"
                    actual = ""
                align_rows.append({
                    "表单字段": field,
                    "YAML 声明列名 (filed)": filed,
                    "对齐状态": status,
                    "实际匹配 Sheet 列名": actual
                })
            if align_rows:
                st.dataframe(pd.DataFrame(align_rows), use_container_width=True)
            else:
                st.info("YAML 中没有定义任何需要对齐匹配的 `filed` 列名（均为手动字段 `?`）。")
            if not res["id_matched"] and yaml_id_col:
                st.error(f"⚠️ 警告：YAML 中定义的 ID 主键列「{yaml_id_col}」在当前 Google Sheet 中对齐失败，自动查询功能将无法正常工作，请检查列名拼写！")
    if not paste_config:
        _render_mapping_editor(template_id, template_fields, saved)
    action_col, save_col = st.columns(2)
    with action_col:
        set_id_col = st.button("设为默认 ID 列", key=f"ds_set_id_col{suffix}", disabled=not test_ok)
    with save_col:
        save_config = st.button("保存数据源配置", key=f"ds_save{suffix}", disabled=not test_ok)
    if set_id_col:
        try:
            spreadsheet_id = parse_spreadsheet_id(sheet_url)
        except ValueError as exc:
            st.error(str(exc))
        else:
            worksheet_name = st.session_state.get(f"ds_worksheet_select{suffix}", saved_worksheet)
            id_column = st.session_state.get(f"ds_id_column_select{suffix}", saved_id_col)
            config = DataSourceConfig(
                sheet_url=sheet_url.strip(),
                spreadsheet_id=spreadsheet_id,
                worksheet_name=str(worksheet_name),
                id_column=str(id_column) or DEFAULT_ID_COLUMN,
                column_mappings=_extract_mappings(template_id, saved),
            )
            save_template_data_source(template_id, config)
            save_template_id_column(template_id, str(id_column))
            st.success(f"已保存默认 ID 列：{id_column}")
            st.rerun()
    if save_config:
        if not sheet_url.strip():
            st.warning("请先填写 Google Sheet URL。")
        else:
            try:
                spreadsheet_id = parse_spreadsheet_id(sheet_url)
            except ValueError as exc:
                st.error(str(exc))
            else:
                worksheet_name = st.session_state.get(f"ds_worksheet_select{suffix}", saved_worksheet)
                id_column = st.session_state.get(f"ds_id_column_select{suffix}", saved_id_col)
                config = DataSourceConfig(
                    sheet_url=sheet_url.strip(),
                    spreadsheet_id=spreadsheet_id,
                    worksheet_name=str(worksheet_name),
                    id_column=str(id_column) or DEFAULT_ID_COLUMN,
                    column_mappings=_extract_mappings(template_id, saved),
                )
                save_template_data_source(template_id, config)
                st.success("已保存当前模板的数据源配置。")
                st.rerun()
    if saved and st.button("清除已保存配置", key=f"ds_clear{suffix}"):
        clear_template_data_source(template_id)
        for key in (
            _test_ok_key(template_id),
            _columns_key(template_id),
            _worksheets_key(template_id),
            _meta_key(template_id),
            _mappings_editor_key(template_id),
        ):
            st.session_state.pop(key, None)
        st.success("已清除数据源配置。")
        st.rerun()
    if saved:
        st.caption(
            f"已保存：工作表 `{saved.worksheet_name or '(默认)'}` · "
            f"ID 列 `{saved.id_column}` · {len(saved.column_mappings)} 条映射"
        )
