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
    GOOGLE_CLOUD_HOME_URL,
    GOOGLE_CREDENTIALS_URL,
    GOOGLE_OAUTH_AUDIENCE_URL,
    GOOGLE_OAUTH_CONSENT_URL,
    GOOGLE_OAUTH_CREATE_CLIENT_URL,
    GOOGLE_SHEETS_API_URL,
    GoogleSheetsError,
    fetch_sheet_preview,
    has_oauth_client,
    list_worksheet_titles,
    remove_stored_oauth,
    run_oauth_flow,
    save_oauth_client_json,
    stored_oauth_client_path,
)

CREDENTIALS_SESSION_KEY = "gs_credentials"
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
    if saved is None:
        # If no config is saved, ensure we clear any leftover state from memory
        st.session_state.pop(_test_ok_key(template_id), None)
        st.session_state.pop(_columns_key(template_id), None)
        st.session_state.pop(_worksheets_key(template_id), None)
        st.session_state.pop(_meta_key(template_id), None)
        return
    if is_sheet_test_ok(template_id):
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



def _start_google_oauth() -> None:
    try:
        credentials = run_oauth_flow()
        st.session_state[CREDENTIALS_SESSION_KEY] = credentials
        st.success("Google 账号连接成功。")
        st.rerun()
    except GoogleSheetsError as exc:
        st.error(str(exc))
        for hint in exc.hints:
            st.markdown(f"- {hint}")
    except Exception as exc:
        st.error(f"连接失败: {exc}")


def _render_oauth_setup_guide() -> None:
    st.markdown("### 首次连接 Google（本机只需配置一次）")
    st.error(
        "**重要：JSON 只能在创建弹窗里下载一次！**\n\n"
        "点 **Create** 后会弹出 **OAuth client created**。弹窗**底部**有 **Download JSON**。\n\n"
        "在点 **OK** 关闭弹窗**之前**，必须先点 **Download JSON** 并把文件保存好。"
        "弹窗一关，Google **不会再让你下载**，列表页也**没有**下载按钮（只有铅笔和垃圾桶）。\n\n"
        "如果已经关掉了弹窗、没下到文件：删掉该客户端 → 重新 **+ Create client** → "
        "在**新弹窗**里立刻 **Download JSON**。"
    )
    link_col1, link_col2, link_col3 = st.columns(3)
    with link_col1:
        st.markdown("**① 启用 Google Sheets API**")
        st.caption("打开后点「启用」。")
        st.link_button("打开 API 页面", GOOGLE_SHEETS_API_URL, use_container_width=True)
    with link_col2:
        st.markdown("**② 受众（Audience）**")
        st.caption("必须选 **External**（外部），不能用 Internal。用 Gmail 登录必填。")
        st.link_button("打开 Audience", GOOGLE_OAUTH_AUDIENCE_URL, use_container_width=True)
    with link_col3:
        st.markdown("**③ 创建 OAuth 客户端**")
        st.caption("+ Create client → Desktop → Create → **立刻 Download JSON** → 再点 OK。")
        st.link_button("打开 Clients 页面", GOOGLE_OAUTH_CREATE_CLIENT_URL, use_container_width=True)
    st.warning(
        "若浏览器出现 **Access blocked** / **Error 403: org_internal**："
        "说明 OAuth 设成了 **Internal（仅组织内）**。"
        "请打开 **Audience**，改为 **External**，保存后重新点「连接 Google 账号」。"
        "用 `@gmail.com` 个人账号时不能选 Internal。"
    )
    st.caption(
        f"没有 Google Cloud 项目？先打开 [Google Cloud 控制台]({GOOGLE_CLOUD_HOME_URL}) 新建项目。"
        f" 同意屏幕：{GOOGLE_OAUTH_CONSENT_URL}"
    )
    st.markdown("**④ 上传第 ③ 步下载的 JSON 文件（不要点 OK 就关弹窗）**")
    uploaded = st.file_uploader(
        "选择 JSON 文件",
        type=["json"],
        key="ds_oauth_client_upload",
        label_visibility="collapsed",
    )
    if uploaded is not None:
        try:
            save_oauth_client_json(uploaded.getvalue())
            st.success("配置文件已保存。正在打开浏览器，请登录 Google 并点「允许」…")
            _start_google_oauth()
        except GoogleSheetsError as exc:
            st.error(str(exc))
            for hint in exc.hints:
                st.markdown(f"- {hint}")


def _clear_google_auth_session() -> None:
    st.session_state.pop(CREDENTIALS_SESSION_KEY, None)


def _remove_oauth_config() -> None:
    _clear_google_auth_session()
    removed = remove_stored_oauth()
    if removed:
        st.success("已删除本机 OAuth 配置文件，可重新上传 JSON 或重新连接。")
    else:
        st.info("本机没有已保存的 OAuth 配置文件。")
    st.rerun()


def _render_auth_controls() -> None:
    if CREDENTIALS_SESSION_KEY in st.session_state:
        st.success("✅ Google 账号已连接，可以读取 Google Sheet。")
        reconnect_col, remove_col = st.columns(2)
        with reconnect_col:
            if st.button("重新连接 / 切换账号", key="ds_reauth_btn", use_container_width=True):
                _clear_google_auth_session()
                st.rerun()
        with remove_col:
            if st.button("删除 OAuth 配置", key="ds_remove_oauth_connected", use_container_width=True):
                _remove_oauth_config()
        return

    if not has_oauth_client():
        _render_oauth_setup_guide()
        return

    client_path = stored_oauth_client_path()
    if client_path:
        st.caption(f"配置文件：`{client_path}`")
    st.caption("点击下方按钮，在弹出网页中登录 Google 并允许访问。")
    connect_col, remove_col = st.columns(2)
    with connect_col:
        if st.button("连接 Google 账号", type="primary", key="ds_oauth_start", use_container_width=True):
            _start_google_oauth()
    with remove_col:
        if st.button("删除 OAuth 配置", key="ds_remove_oauth_idle", use_container_width=True):
            _remove_oauth_config()



def _run_sheet_test(
    template_id: str,
    sheet_url: str,
    worksheet_name: str | None,
    max_rows: int,
) -> None:
    credentials = get_session_credentials()
    if credentials is None:
        st.warning("请先点击「连接 Google 账号」完成授权。")
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
        "预览行数",
        min_value=1,
        max_value=20,
        value=5,
        key=f"ds_max_rows{suffix}",
    )

    test_ok = is_sheet_test_ok(template_id)
    # Clear test_ok if sheet_url changed so user must retest
    if test_ok and saved and sheet_url.strip() != saved.sheet_url:
        test_ok = False
        st.session_state[_test_ok_key(template_id)] = False

    if st.button("连接 Sheet", type="primary", key=f"ds_test{suffix}"):
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

    default_worksheet = saved_worksheet
    yaml_worksheet = paste_config.worksheet if paste_config else None
    if yaml_worksheet and yaml_worksheet in worksheet_titles:
        default_worksheet = yaml_worksheet

    if not test_ok:
        current_worksheet = st.selectbox("工作表", options=["请先连接 Sheet"], disabled=True, key=f"ds_worksheet_locked{suffix}")
        current_id_col = st.selectbox("ID 列", options=["请先连接 Sheet"], disabled=True, key=f"ds_id_col_locked{suffix}")
    else:
        current_worksheet = st.selectbox(
            "工作表",
            worksheet_titles or [default_worksheet or "默认"],
            index=_default_worksheet_index(worksheet_titles, default_worksheet),
            key=f"ds_worksheet_select{suffix}",
        )
        current_id_col = st.selectbox(
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

    # 自动保存配置
    if test_ok and sheet_url.strip():
        try:
            spreadsheet_id = parse_spreadsheet_id(sheet_url.strip())
            current_mappings = _extract_mappings(template_id, saved)
            ws_val = str(current_worksheet) if current_worksheet and current_worksheet != "请先连接 Sheet" else ""
            id_val = str(current_id_col) if current_id_col and current_id_col != "请先连接 Sheet" else DEFAULT_ID_COLUMN
            
            needs_save = False
            if not saved:
                needs_save = True
            else:
                if (saved.sheet_url != sheet_url.strip() or
                    saved.spreadsheet_id != spreadsheet_id or
                    saved.worksheet_name != ws_val or
                    saved.id_column != id_val or
                    saved.column_mappings != current_mappings):
                    needs_save = True
            
            if needs_save:
                config = DataSourceConfig(
                    sheet_url=sheet_url.strip(),
                    spreadsheet_id=spreadsheet_id,
                    worksheet_name=ws_val,
                    id_column=id_val,
                    column_mappings=current_mappings,
                )
                save_template_data_source(template_id, config)
        except Exception:
            pass

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
