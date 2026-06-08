import streamlit as st

from app.services.excel_parser import read_template_sheet, write_template_sheet
from app.services.registry import TemplateConfig


def render_template_page(config: TemplateConfig) -> None:
    # 渲染单个模板的可视化录入表单
    st.title(config.display_name)
    if config.description:
        st.caption(config.description)
    if not config.file_path.exists():
        st.error(f"模板文件不存在: {config.file_path}")
        st.info("请将 GIN LOT TEMPLATE.xlsx 复制到 templates/gin_lot_template.xlsx，或设置环境变量 GIN_LOT_TEMPLATE_PATH。")
        return
    st.markdown(f"**工作表**: `{config.sheet_name}`  |  **文件**: `{config.file_path}`")
    try:
        dataframe = read_template_sheet(
            config.file_path,
            config.sheet_name,
            config.header_row,
            config.data_start_row,
        )
    except Exception as exc:
        st.error(f"读取模板失败: {exc}")
        return
    st.subheader("数据录入")
    st.caption("在下方表格中编辑各行内容，完成后点击下载。")
    edited = st.data_editor(dataframe, num_rows="dynamic", use_container_width=True, key=f"editor_{config.id}")
    xlsx_bytes = write_template_sheet(
        config.file_path,
        config.sheet_name,
        edited,
        config.header_row,
        config.data_start_row,
    )
    st.download_button(
        label="下载更新后的 Excel",
        data=xlsx_bytes,
        file_name=f"{config.id}_filled.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"download_{config.id}",
    )
