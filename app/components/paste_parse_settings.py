import io

import streamlit as st
from streamlit.components.v1 import html as st_html

from app.components.paste_image_button import paste_image_button
from app.services.paste_parse_config import (
    build_empty_mapping_yaml,
    paste_config_path,
    save_paste_parse_yaml,
)
from app.services.phi35_vision_model import (
    download_vision_model,
    get_vision_model_status,
)
from app.services.phi35_vision_paste_infer import (
    VisionInferenceError,
    infer_paste_mapping_from_image,
)


def _yaml_draft_key(template_id: str) -> str:
    return f"paste_yaml_draft_{template_id}"


def _yaml_mtime_key(template_id: str) -> str:
    return f"paste_yaml_mtime_{template_id}"


def _yaml_force_reload_key(template_id: str) -> str:
    return f"paste_yaml_force_reload_{template_id}"


def _paste_image_key(template_id: str) -> str:
    return f"paste_image_bytes_{template_id}"


def _prepare_yaml_draft(template_id: str, template_headers: list[str]) -> None:
    """Load YAML into session state before the text_area widget is created."""
    key = _yaml_draft_key(template_id)
    mtime_key = _yaml_mtime_key(template_id)
    force_reload = st.session_state.pop(_yaml_force_reload_key(template_id), False)
    path = paste_config_path(template_id)

    if path.exists():
        mtime = path.stat().st_mtime_ns
        cached_mtime = st.session_state.get(mtime_key)
        if force_reload or cached_mtime is None or cached_mtime != mtime:
            st.session_state[key] = path.read_text(encoding="utf-8")
            st.session_state[mtime_key] = mtime
            return

    if key not in st.session_state:
        st.session_state[key] = build_empty_mapping_yaml(template_headers)


def _render_vision_model_panel() -> bool:
    status = get_vision_model_status()
    if status.complete:
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
            download_vision_model(on_progress=on_progress)
            progress_bar.empty()
            status_text.empty()
            st.success("下载完成。")
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
    st_html(
        """
        <script>
        window.addEventListener("keydown", (event) => {
          const isCtrlC = (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "c";
          if (!isCtrlC) {
            return;
          }
          const target = event.target;
          const tag = target ? target.tagName : "";
          const editable = target && (target.isContentEditable || tag === "INPUT" || tag === "TEXTAREA");
          if (!editable) {
            event.stopPropagation();
          }
        }, true);
        </script>
        """,
        height=0,
    )
    _prepare_yaml_draft(template_id, template_headers)

    model_ready = _render_vision_model_panel()

    st.subheader("截图推测")
    st.caption(
        "先截图（如 Win+Shift+S），点击「粘贴截图」后按 Ctrl+V，再点「截图推测」。"
        "无需按 Ctrl+C，避免触发清缓存提示。"
    )
    paste_key = f"paste_clipboard_{template_id}"
    paste_col, infer_col = st.columns(2, gap="small", vertical_alignment="center")
    with paste_col:
        paste_result = paste_image_button(
            "粘贴截图",
            key=paste_key,
            background_color="#FF4B4B",
            hover_background_color="#E02020",
            text_color="#FFFFFF",
        )
    with infer_col:
        infer_clicked = st.button(
            "截图推测",
            key=f"paste_image_infer_{template_id}",
            disabled=not model_ready,
            type="primary",
            use_container_width=True,
        )
    if paste_result is not None:
        image_bytes = _image_bytes_from_paste(paste_result)
        if image_bytes is not None:
            st.session_state[_paste_image_key(template_id)] = image_bytes
    image_bytes = st.session_state.get(_paste_image_key(template_id))
    if image_bytes:
        st.image(image_bytes, caption="当前剪贴板截图", width=480)
    if infer_clicked:
        if not image_bytes:
            st.warning("请先点击「粘贴截图」，再用 Ctrl+V 粘贴截图。")
        else:
            with st.spinner("截图推测中（首次加载模型约需 1 分钟）..."):
                try:
                    draft = infer_paste_mapping_from_image(
                        image_bytes, template_headers
                    )
                    st.session_state[_yaml_draft_key(template_id)] = draft
                    st.rerun()
                except VisionInferenceError as exc:
                    st.error(str(exc))
                    if exc.raw_response:
                        with st.expander("模型原始输出"):
                            st.code(exc.raw_response)
                except Exception as exc:
                    st.error(str(exc))

    st.subheader("映射 YAML")
    st.text_area(
        "映射 YAML",
        height=320,
        key=_yaml_draft_key(template_id),
    )
    if st.button("保存映射", key=f"paste_save_{template_id}", type="primary"):
        try:
            yaml_text = st.session_state[_yaml_draft_key(template_id)]
            save_paste_parse_yaml(template_id, yaml_text, template_headers)
            st.session_state[_yaml_force_reload_key(template_id)] = True
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
