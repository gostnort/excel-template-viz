import streamlit as st
import streamlit.components.v1 as components

from app.components.template_form import (
    FORM_TAB_LABELS,
    FORM_TAB_SESSION_KEY,
    render_template_page,
)
from app.services.registry import load_templates
from app.services.shutdown import CLOSE_TAB_HTML, schedule_shutdown, write_pid_file


def build_nav_options() -> list[tuple[str, str]]:
    # 构建侧边栏选项：(显示标签, 内部 id)
    options: list[tuple[str, str]] = []
    for template in load_templates():
        options.append((template.display_name, template.id))
    return options



def render_shutdown_control() -> None:
    st.sidebar.divider()
    if st.sidebar.button("关闭应用", type="secondary", help="停止后台服务并关闭当前浏览器标签页"):
        components.html(CLOSE_TAB_HTML, height=0, width=0)
        schedule_shutdown()
        st.stop()



def main() -> None:
    st.set_page_config(page_title="Excel 模板可视化", page_icon="📋", layout="wide")
    write_pid_file()
    st.sidebar.markdown("## 选择模版")
    st.sidebar.markdown(
        """
        <style>
        [data-testid="stSidebar"] .stRadio label p {
            font-size: 1.5rem;
            font-weight: 600;
            line-height: 1.3;
        }
        [data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label {
            padding: 0.4rem 0;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    nav_options = build_nav_options()
    if not nav_options:
        st.sidebar.warning("未加载任何模板，请将 xlsx 文件复制到 templates/ 目录。")
        st.stop()
    labels = [label for label, _ in nav_options]
    id_by_label = {label: page_id for label, page_id in nav_options}
    default_label = labels[0]
    if "nav_label" not in st.session_state:
        st.session_state["nav_label"] = default_label
    selected_label = st.sidebar.radio(
        "选择模版",
        labels,
        index=labels.index(st.session_state["nav_label"]),
        label_visibility="collapsed",
    )
    st.session_state["nav_label"] = selected_label
    page_id = id_by_label[selected_label]
    if st.session_state.get("nav_page_id") != page_id:
        st.session_state["nav_page_id"] = page_id
        st.session_state[FORM_TAB_SESSION_KEY] = FORM_TAB_LABELS[0]
    templates = {t.id: t for t in load_templates()}
    config = templates.get(page_id)
    if config is None:
        st.error("模板配置不存在。")
        return
    render_shutdown_control()
    render_template_page(config)


if __name__ == "__main__":
    main()
