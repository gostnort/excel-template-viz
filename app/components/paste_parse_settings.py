import io

import streamlit as st

from app.services.paste_mapping_infer import infer_paste_mapping_yaml
from app.services.paste_parse_config import (
    load_paste_parse_config,
    paste_config_path,
    save_paste_parse_yaml,
)
from app.services.phi35_vision_model import download_vision_model, get_vision_model_status
from app.services.phi35_vision_paste_infer import VisionInferenceError, infer_paste_mapping_from_image


def _yaml_draft_key(template_id: str) -> str:
    return f"paste_yaml_draft_{template_id}"


def _paste_image_key(template_id: str) -> str:
    return f"paste_image_bytes_{template_id}"


def _paste_sample_key(template_id: str) -> str:
    return f"paste_sample_text_{template_id}"


def _load_yaml_draft(template_id: str) -> str:
    key = _yaml_draft_key(template_id)
    if key in st.session_state:
        return st.session_state[key]
    path = paste_config_path(template_id)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _paste_image_button(label: str, key: str):
    try:
        from streamlit_paste_button import paste_image_button
    except ImportError as exc:
        raise RuntimeError("请安装 streamlit-paste-button: pip install -r requirements.txt") from exc
    return paste_image_button(label=label, key=key)


def _format_size(size_bytes: int | None) -> str:
    if not size_bytes:
        return "未知"
    if size_bytes >= 1024**3:
        return f"{size_bytes / 1024**3:.2f} GB"
    return f"{size_bytes / 1024**2:.1f} MB"


def _render_vision_model_panel() -> bool:
    status = get_vision_model_status()
    st.subheader("视觉模型")
    st.caption(f"模型目录：`{status.model_dir}`")
    if status.size_bytes:
        st.caption(f"占用空间：{_format_size(status.size_bytes)}")
    if status.complete:
        st.success("模型已就绪，可使用截图推测。")
        return True
    if status.missing_files:
        st.warning(
            f"模型下载不完整，仍缺 {len(status.missing_files)} 个文件。"
            "请重新点击下载（约 2.4 GB）。"
        )
    else:
        st.warning("模型尚未下载。体积较大（约 2.4 GB），请先下载后再使用截图推测。")
    if st.button("下载视觉模型", key="paste_download_vision_model"):
        progress_bar = st.progress(0.0)
        status_text = st.empty()

        def on_progress(pct: float, message: str) -> None:
            progress_bar.progress(pct)
            status_text.caption(message)

        try:
            snapshot_path = download_vision_model(on_progress=on_progress)
            progress_bar.empty()
            status_text.empty()
            st.success(f"下载完成：`{snapshot_path}`")
            st.rerun()
        except Exception as exc:
            progress_bar.empty()
            status_text.empty()
            st.error(f"下载失败: {exc}")
    return False


def _image_bytes_from_paste(paste_result) -> bytes | None:
    if paste_result is None or paste_result.image_data is None:
        return None
    buf = io.BytesIO()
    paste_result.image_data.save(buf, format="PNG")
    return buf.getvalue()


def render_paste_mapping_tab(template_id: str, template_headers: list[str]) -> None:
    has_saved = load_paste_parse_config(template_id) is not None
    st.caption(
        f"在此初始化并调校「源数据粘贴 → 模板字段」的 YAML 映射。"
        f"保存路径：`{paste_config_path(template_id)}`"
    )
    if has_saved:
        st.success("已保存映射，可在「数据录入」Tab 粘贴源数据并解析。")
    else:
        st.info("尚未保存映射。可用截图或文本样本推测后，核对 YAML 并保存。")

    model_ready = _render_vision_model_panel()

    st.subheader("截图推测")
    st.caption("先截图（如 Win+Shift+S），点击下方按钮后 **Ctrl+V** 粘贴，再点「截图推测」生成 YAML。")
    paste_key = f"paste_clipboard_{template_id}"
    try:
        paste_result = _paste_image_button("粘贴截图 (Ctrl+V)", key=paste_key)
    except RuntimeError as exc:
        st.error(str(exc))
        paste_result = None
    if paste_result is not None:
        image_bytes = _image_bytes_from_paste(paste_result)
        if image_bytes is not None:
            st.session_state[_paste_image_key(template_id)] = image_bytes
    image_bytes = st.session_state.get(_paste_image_key(template_id))
    if image_bytes:
        st.image(image_bytes, caption="当前剪贴板截图", width=480)
    if st.button("截图推测", key=f"paste_image_infer_{template_id}", disabled=not model_ready):
        if not image_bytes:
            st.warning("请先点击「粘贴截图」并 Ctrl+V 粘贴截图。")
        else:
            with st.spinner("截图推测中（首次加载模型约需 1 分钟）..."):
                try:
                    draft = infer_paste_mapping_from_image(image_bytes, template_headers)
                    st.session_state[_yaml_draft_key(template_id)] = draft
                    st.success("已生成 YAML，请在下方核对后保存。")
                    st.rerun()
                except VisionInferenceError as exc:
                    st.error(str(exc))
                    if exc.raw_response:
                        with st.expander("模型原始输出"):
                            st.code(exc.raw_response)
                except Exception as exc:
                    st.error(str(exc))

    st.subheader("文本推测")
    st.caption("粘贴一行制表符分隔样本，用于无截图时的快速推测。")
    sample_text = st.text_area(
        "文本样本",
        height=100,
        placeholder="10073\tGIN\t...\t6/1\t...",
        key=_paste_sample_key(template_id),
        label_visibility="collapsed",
    )
    if st.button("文本推测", key=f"paste_infer_{template_id}"):
        sample = next((line.strip() for line in sample_text.splitlines() if line.strip()), "")
        if not sample:
            st.warning("请粘贴至少一行样本数据。")
        else:
            try:
                draft = infer_paste_mapping_yaml(sample, template_headers)
                st.session_state[_yaml_draft_key(template_id)] = draft
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    st.subheader("映射 YAML")
    with st.expander("模板字段参考", expanded=False):
        for header in template_headers:
            st.markdown(f"- `{header}`")
    yaml_text = st.text_area(
        "映射 YAML",
        value=_load_yaml_draft(template_id),
        height=320,
        key=_yaml_draft_key(template_id),
    )
    if st.button("保存映射", key=f"paste_save_{template_id}", type="primary"):
        try:
            save_paste_parse_yaml(template_id, yaml_text)
            st.success("映射已保存。")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
