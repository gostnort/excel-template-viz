import json

import streamlit as st

from app.services.google_sheets import (
    GoogleSheetsError,
    credentials_from_service_account_json,
    fetch_sheet_preview,
    run_oauth_flow,
)


def render_google_sheet_test_page() -> None:
    # 终端用户 Google Sheet 连通性测试页
    st.title("Google Sheet 连通性测试")
    st.markdown(
        "在此粘贴表格 URL 或 ID，选择认证方式并测试读取权限。"
        "开发者环境无权限时，**请由终端用户自行验证**。"
    )
    sheet_input = st.text_input("Spreadsheet URL 或 ID", placeholder="https://docs.google.com/spreadsheets/d/...")
    worksheet_name = st.text_input("工作表名称（留空则使用第一个）", value="")
    max_rows = st.number_input("预览行数", min_value=1, max_value=50, value=5)
    auth_method = st.radio("认证方式", ["服务账号 JSON", "OAuth 用户授权"], horizontal=True)
    credentials = None
    if auth_method == "服务账号 JSON":
        uploaded = st.file_uploader("上传服务账号 JSON 密钥", type=["json"])
        if uploaded is not None:
            raw = uploaded.getvalue().decode("utf-8")
            try:
                credentials = credentials_from_service_account_json(raw)
                email = json.loads(raw).get("client_email", "")
                if email:
                    st.info(f"服务账号邮箱: `{email}` — 请确保 Google Sheet 已共享给该邮箱（至少查看权限）。")
            except GoogleSheetsError as exc:
                st.error(str(exc))
                for hint in exc.hints:
                    st.markdown(f"- {hint}")
    else:
        st.caption("OAuth 需要项目根目录 `credentials/oauth_client.json`（Google Cloud 下载的 OAuth 客户端）。")
        if st.button("启动 OAuth 授权"):
            try:
                credentials = run_oauth_flow()
                st.session_state["oauth_credentials"] = credentials
                st.success("OAuth 授权成功，可点击下方「测试连接」。")
            except GoogleSheetsError as exc:
                st.error(str(exc))
                for hint in exc.hints:
                    st.markdown(f"- {hint}")
            except Exception as exc:
                st.error(f"OAuth 失败: {exc}")
        if "oauth_credentials" in st.session_state:
            credentials = st.session_state["oauth_credentials"]
            st.success("已加载会话中的 OAuth 凭证。")
    if st.button("测试连接", type="primary"):
        if not sheet_input.strip():
            st.warning("请先填写 Spreadsheet URL 或 ID。")
            return
        if credentials is None:
            st.warning("请先上传服务账号 JSON 或完成 OAuth 授权。")
            return
        with st.spinner("正在连接 Google Sheets..."):
            try:
                preview, meta = fetch_sheet_preview(
                    credentials,
                    sheet_input,
                    worksheet_name.strip() or None,
                    int(max_rows),
                )
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
                    st.markdown("**排查建议：**")
                    for hint in exc.hints:
                        st.markdown(f"- {hint}")
            except Exception as exc:
                st.error(f"未知错误: {exc}")
    with st.expander("常见问题"):
        st.markdown(
            """
            - **403 无权限**：服务账号需在 Google Sheet「共享」中添加 `client_email`；OAuth 需用有权限的 Google 账号登录。
            - **404 找不到**：检查 URL/ID 是否正确。
            - **工作表不存在**：检查工作表名称大小写与空格。
            - **API 未启用**：在 Google Cloud Console 启用 Google Sheets API。
            """
        )
