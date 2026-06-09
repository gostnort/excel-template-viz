import io

import streamlit as st
from streamlit.components.v1 import html as st_html

from app.services.paste_mapping_infer import (
    extract_sample_line,
    infer_paste_mapping_yaml,
)
from app.services.paste_parse_config import (
    load_paste_parse_config,
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


def _paste_image_key(template_id: str) -> str:
    return f"paste_image_bytes_{template_id}"


def _paste_sample_key(template_id: str) -> str:
    return f"paste_sample_text_{template_id}"


def _paste_init_notice_key(template_id: str) -> str:
    return f"paste_init_notice_{template_id}"


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
        raise RuntimeError(
            "请安装 streamlit-paste-button: pip install -r requirements.txt"
        ) from exc
    return paste_image_button(label=label, key=key)


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
    has_saved = load_paste_parse_config(template_id) is not None
    st.caption(
        "Configure how pasted source rows (Data entry tab) map to template fields. "
        "Save YAML here before using Parse & fill."
    )
    if not has_saved and not st.session_state.get(_paste_init_notice_key(template_id)):
        st.info(f"首次使用请初始化并保存 YAML：`templates/{template_id}.paste.yaml`。")
        st.session_state[_paste_init_notice_key(template_id)] = True
    if has_saved:
        st.success("Mapping saved. Paste source rows in Data entry and click Parse & fill.")
    else:
        st.info("No mapping saved yet. Use screenshot or text sample inference, review YAML, then save.")

    model_ready = _render_vision_model_panel()

    st.subheader("截图推测")
    st.caption(
        "先截图（如 Win+Shift+S），点击「粘贴截图」后按 Ctrl+V，再点「截图推测」。"
        "无需按 Ctrl+C，避免触发清缓存提示。"
    )
    paste_key = f"paste_clipboard_{template_id}"
    paste_col, infer_col, spacer_col = st.columns(
        [1, 1, 3], vertical_alignment="bottom"
    )
    try:
        with paste_col:
            paste_result = _paste_image_button("粘贴截图", key=paste_key)
    except RuntimeError as exc:
        st.error(str(exc))
        paste_result = None
    with infer_col:
        infer_clicked = st.button(
            "截图推测",
            key=f"paste_image_infer_{template_id}",
            disabled=not model_ready,
            use_container_width=True,
        )
    with spacer_col:
        st.empty()
    st.markdown(
        """
        <script>
        const syncPasteInferButtons = () => {
          const labels = ["粘贴截图", "截图推测"];
          const buttons = Array.from(window.parent.document.querySelectorAll("button"))
            .filter((btn) => labels.includes(btn.innerText.trim()));
          if (buttons.length !== 2) {
            return;
          }
          const targetWidth = Math.max(
            ...buttons.map((btn) => btn.parentElement.getBoundingClientRect().width)
          );
          buttons.forEach((btn) => {
            btn.style.width = `${Math.ceil(targetWidth)}px`;
          });
        };
        setTimeout(syncPasteInferButtons, 0);
        window.parent.addEventListener("resize", syncPasteInferButtons);
        </script>
        """,
        unsafe_allow_html=True,
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
    st.caption("Paste a tab-separated row or HTML/Markdown table to infer mapping rules for Data entry.")
    sample_text = st.text_area(
        "文本样本",
        height=100,
        placeholder="粘贴原始数据...",
        key=_paste_sample_key(template_id),
        label_visibility="collapsed",
    )
    if st.button("文本推测", key=f"paste_infer_{template_id}"):
        sample = extract_sample_line(sample_text)
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
    yaml_text = st.text_area(
        "映射 YAML",
        value=_load_yaml_draft(template_id),
        height=320,
        key=_yaml_draft_key(template_id),
    )
    if st.button("保存映射", key=f"paste_save_{template_id}", type="primary"):
        try:
            save_paste_parse_yaml(template_id, yaml_text, template_headers)
            st.success("映射已保存。")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
