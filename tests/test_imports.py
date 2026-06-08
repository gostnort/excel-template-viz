def test_streamlit_entry_imports() -> None:
    # 根目录入口应能正确导入 app 包内模块
    import streamlit_app  # noqa: F401


def test_main_module_imports() -> None:
    from app.main import build_nav_options, main  # noqa: F401

    options = build_nav_options()
    assert isinstance(options, list)
