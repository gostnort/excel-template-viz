import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.components.google_sheet_test import render_google_sheet_test_page
from app.components.template_form import render_template_page
from app.services.registry import load_templates

GOOGLE_TEST_PAGE_ID = "__google_sheet_test__"


def build_nav_options() -> list[tuple[str, str]]:
    # 构建侧边栏选项：(显示标签, 内部 id)
    options: list[tuple[str, str]] = []
    for template in load_templates():
        options.append((template.display_name, template.id))
    options.append(("Google Sheet 连通性测试", GOOGLE_TEST_PAGE_ID))
    return options


def main() -> None:
    st.set_page_config(page_title="Excel 模板可视化", page_icon="📋", layout="wide")
    st.sidebar.title("导航")
    nav_options = build_nav_options()
    if not nav_options:
        st.sidebar.warning("未加载任何模板，请检查 config/templates.json。")
        st.stop()
    labels = [label for label, _ in nav_options]
    id_by_label = {label: page_id for label, page_id in nav_options}
    default_label = labels[0]
    if "nav_label" not in st.session_state:
        st.session_state["nav_label"] = default_label
    selected_label = st.sidebar.radio("选择页面", labels, index=labels.index(st.session_state["nav_label"]))
    st.session_state["nav_label"] = selected_label
    page_id = id_by_label[selected_label]
    if page_id == GOOGLE_TEST_PAGE_ID:
        render_google_sheet_test_page()
        return
    templates = {t.id: t for t in load_templates()}
    config = templates.get(page_id)
    if config is None:
        st.error("模板配置不存在。")
        return
    render_template_page(config)


if __name__ == "__main__":
    main()
