import json

import streamlit as st

from app.services.data_source import (
    DEFAULT_ID_COLUMN,
    DataSourceConfig,
    clear_template_data_source,
    list_template_data_sources,
    load_template_data_source,
    save_template_data_source,
)
from app.services.excel_parser import parse_spreadsheet_id
from app.services.google_sheets import (
    GoogleSheetsError,
    credentials_from_service_account_json,
    fetch_sheet_preview,
    list_worksheet_titles,
    run_oauth_flow,
)

CREDENTIALS_SESSION_KEY = "gs_credentials"
AUTH_METHOD_SESSION_KEY = "gs_auth_method"


def get_session_credentials():
    # 从 session 读取当前 Google 凭证
    return st.session_state.get(CREDENTIALS_SESSION_KEY)



def _render_auth_controls() -> None:
    # 认证方式选择与凭证加载
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
        if CREDENTIALS_SESSION_KEY in st.session_state:
            st.success("已加载会话中的 OAuth 凭证。")



def _render_config_form(template_id: str, saved: DataSourceConfig | None) -> None:
    # 数据源 URL、工作表与 ID 列配置表单
    suffix = f"_{template_id}"
    default_url = saved.sheet_url if saved else ""
    default_worksheet = saved.worksheet_name if saved else ""
    default_id_col = saved.id_column if saved else DEFAULT_ID_COLUMN
    sheet_url = st.text_input(
        "Google Sheet URL",
        value=default_url,
        placeholder="https://docs.google.com/spreadsheets/d/...",
        key=f"ds_sheet_url{suffix}",
    )
    worksheet_name = st.text_input(
        "工作表名称（留空则使用第一个）",
        value=default_worksheet,
        key=f"ds_worksheet_name{suffix}",
    )
    id_column = st.text_input(
        "ID 列名（对应模板 P.O. No.）",
        value=default_id_col,
        help="Google Sheet 中用于匹配订单号的列，默认 PO。",
        key=f"ds_id_column{suffix}",
    )
    max_rows = st.number_input(
        "测试预览行数",
        min_value=1,
        max_value=20,
        value=5,
        key=f"ds_max_rows{suffix}",
    )
    credentials = get_session_credentials()
    if st.button("测试连接", type="primary", key=f"ds_test{suffix}"):
        if not sheet_url.strip():
            st.warning("请先填写 Google Sheet URL。")
            return
        if credentials is None:
            st.warning("请先上传服务账号 JSON 或完成 OAuth 授权。")
            return
        with st.spinner("正在连接 Google Sheets..."):
            try:
                preview, meta = fetch_sheet_preview(
                    credentials,
                    sheet_url,
                    worksheet_name.strip() or None,
                    int(max_rows),
                )
                st.session_state[f"ds_last_meta{suffix}"] = meta
                st.success(
                    f"连接成功 — 表格「{meta['spreadsheet_title']}」"
                    f" / 工作表「{meta['worksheet_title']}」"
                    f"（共约 {meta['row_count']} 行）"
                )
                if preview.empty:
                    st.info("工作表为空或仅有标题行。")
                else:
                    st.dataframe(preview, use_container_width=True)
                    headers = list(preview.columns)
                    if id_column.strip() not in headers:
                        st.warning(f"未找到 ID 列「{id_column.strip()}」，可用列: {', '.join(headers)}")
            except GoogleSheetsError as exc:
                st.error(str(exc))
                if exc.hints:
                    for hint in exc.hints:
                        st.markdown(f"- {hint}")
            except Exception as exc:
                st.error(f"未知错误: {exc}")
    if st.button("保存为模板数据源", key=f"ds_save_{template_id}"):
        if not sheet_url.strip():
            st.warning("请先填写 Google Sheet URL。")
            return
        try:
            spreadsheet_id = parse_spreadsheet_id(sheet_url)
        except ValueError as exc:
            st.error(str(exc))
            return
        meta = st.session_state.get(f"ds_last_meta{suffix}")
        resolved_worksheet = worksheet_name.strip()
        if not resolved_worksheet and meta:
            resolved_worksheet = meta.get("worksheet_title", "")
        config = DataSourceConfig(
            sheet_url=sheet_url.strip(),
            spreadsheet_id=spreadsheet_id,
            worksheet_name=resolved_worksheet,
            id_column=id_column.strip() or DEFAULT_ID_COLUMN,
        )
        save_template_data_source(template_id, config)
        st.success("已保存为当前模板的数据源。")
        st.rerun()
    if credentials is not None and sheet_url.strip():
        if st.button("列出可用工作表", key=f"ds_list_ws{suffix}"):
            try:
                titles = list_worksheet_titles(credentials, sheet_url)
                st.info("可用工作表: " + ", ".join(titles))
            except GoogleSheetsError as exc:
                st.error(str(exc))



def _data_source_summary_rows() -> list[dict[str, str]]:
    # 构建数据源汇总表行
    rows: list[dict[str, str]] = []
    for entry in list_template_data_sources():
        data_source = entry.data_source
        rows.append(
            {
                "模板": entry.display_name,
                "状态": "已配置" if data_source else "未配置",
                "工作表": data_source.worksheet_name or "(默认)" if data_source else "—",
                "ID 列": data_source.id_column if data_source else "—",
                "Spreadsheet ID": data_source.spreadsheet_id if data_source else "—",
            }
        )
    return rows



def render_data_sources_tab(current_template_id: str) -> None:
    # 填写侧数据源 Tab：集中展示全部模板的数据源
    st.subheader("数据源汇总")
    entries = list_template_data_sources()
    configured_count = sum(1 for entry in entries if entry.data_source is not None)
    st.caption(
        f"共 {len(entries)} 个模板，{configured_count} 个已配置 Google Sheet。"
        " 在侧边栏「添加数据源」可编辑当前模板的数据源。"
    )
    if not entries:
        st.info("未发现任何模板，请将 xlsx 文件复制到 templates/ 目录。")
        return
    st.dataframe(_data_source_summary_rows(), use_container_width=True, hide_index=True)
    current = next((entry for entry in entries if entry.template_id == current_template_id), None)
    if current is None:
        return
    st.markdown(f"**当前模板：{current.display_name}**")
    if current.data_source is None:
        st.warning("当前模板尚未配置数据源。请使用侧边栏「添加数据源」进行配置。")
        return
    saved = current.data_source
    st.markdown(f"- **Sheet URL**: `{saved.sheet_url}`")
    st.markdown(f"- **Spreadsheet ID**: `{saved.spreadsheet_id}`")
    st.markdown(f"- **工作表**: `{saved.worksheet_name or '(默认)'}`")
    st.markdown(f"- **ID 列**: `{saved.id_column}`")
    credentials = get_session_credentials()
    if credentials is None:
        st.caption("上传 Google 凭证后可在此预览数据。")
        return
    if st.button("预览当前模板数据源", key=f"ds_tab_preview_{current_template_id}"):
        with st.spinner("正在加载预览..."):
            try:
                preview, meta = fetch_sheet_preview(
                    credentials,
                    saved.sheet_url,
                    saved.worksheet_name or None,
                    5,
                )
                st.success(
                    f"「{meta['spreadsheet_title']}」/「{meta['worksheet_title']}」"
                    f"（约 {meta['row_count']} 行）"
                )
                if preview.empty:
                    st.info("工作表为空或仅有标题行。")
                else:
                    st.dataframe(preview, use_container_width=True)
            except GoogleSheetsError as exc:
                st.error(str(exc))
                for hint in exc.hints:
                    st.markdown(f"- {hint}")
            except Exception as exc:
                st.error(f"预览失败: {exc}")



def render_data_source_sidebar(template_id: str, template_label: str) -> None:
    # 侧边栏数据源设置入口
    st.sidebar.divider()
    st.sidebar.subheader("数据源")
    saved = load_template_data_source(template_id)
    if saved:
        st.sidebar.caption(
            f"{template_label} 已配置: `{saved.worksheet_name or '(默认工作表)'}` · ID 列 `{saved.id_column}`"
        )
    else:
        st.sidebar.caption(f"{template_label} 尚未配置数据源。")
    if get_session_credentials() is None:
        st.sidebar.caption("当前会话未加载 Google 凭证，查询前需先认证。")
    form_key = f"ds_form_open_{template_id}"
    show_form = st.sidebar.button("添加数据源", key=f"ds_toggle_{template_id}")
    if show_form or st.session_state.get(form_key):
        st.session_state[form_key] = True
        with st.sidebar.expander("数据源设置", expanded=True):
            _render_auth_controls()
            _render_config_form(template_id, saved)
            if saved and st.button("清除已保存配置", key=f"ds_clear_{template_id}"):
                clear_template_data_source(template_id)
                st.session_state.pop(f"ds_last_meta_{template_id}", None)
                st.success("已清除数据源配置。")
                st.rerun()
