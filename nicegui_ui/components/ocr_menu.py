import asyncio
import base64
import json
from typing import Any

from nicegui import run, ui

from nicegui_ui.components.buttons import AppBtn

GHOST_OCR_LABEL = "顶部粘贴"

IMAGE_ACCEPT = (
    "image/jpeg,image/jpg,image/png,image/heic,image/heif,.jpg,.jpeg,.png,.heic,.heif"
)


def ocr_result_to_field_text(result: dict) -> str:
    """
    函数名: ocr_result_to_field_text
    作用: 从 PaddleOcr JSON 提取单字段展示用纯文本（非 JSON）
    输入:
        result (dict): PaddleOcr 返回值（含 ok/string*/table*）
    输出:
        str: 合并后的可读文本；无内容返回 ""
    """
    if not result.get("ok"):
        return ""
    texts = []
    for k in sorted(result.keys()):
        if k.startswith("string") and isinstance(result[k], str):
            val = result[k].strip()
            if val:
                texts.append(val)
    if texts:
        return "\n".join(texts)
    for k in sorted(result.keys()):
        if k.startswith("table") and isinstance(result[k], list):
            for row in result[k]:
                if isinstance(row, dict) and "cells" in row:
                    cells = row["cells"]
                    if isinstance(cells, list):
                        line = " ".join(
                            [str(c).strip() for c in cells if str(c).strip()]
                        )
                        if line:
                            texts.append(line)
    return "\n".join(texts).strip()


def _ensure_field_images(session) -> dict:
    """
    函数名: _ensure_field_images
    作用: 确保 session 上有 field_images 字典并返回
    输入:
        session: 当前会话
    输出:
        dict: field_images 引用
    """
    if not hasattr(session, "field_images") or session.field_images is None:
        session.field_images = {}
    return session.field_images


def _store_image_bytes(session, label: str, image_bytes: bytes, mime: str) -> None:
    """
    函数名: _store_image_bytes
    作用: 将图片字节写入 session.field_images[label]（覆盖同字段旧图）
    输入:
        session: 当前会话
        label (str): Input_label
        image_bytes (bytes): 图片数据
        mime (str): MIME 类型
    输出: 无
    """
    images = _ensure_field_images(session)
    prev = images.get(label, {})
    images[label] = {
        "bytes": image_bytes,
        "mime": mime or "image/jpeg",
    }
    if "rectangle" in prev:
        images[label]["rectangle"] = prev["rectangle"]
    for key in ("ocr_text", "ocr_status"):
        if key in prev:
            images[label].pop(key, None)


def _preview_data_url(image_bytes: bytes) -> tuple[str, int, int]:
    """
    函数名: _preview_data_url
    作用: 将任意图片字节转为浏览器可显示的 JPEG data URL 及宽高
    输入:
        image_bytes (bytes): 原始图片（含 HEIC/HEIF）
    输出:
        tuple[str, int, int]: data_url, width, height
    """
    import cv2
    from paddle_ocr.runtime.image_decode import decode_image

    try:
        bgr = decode_image(image_bytes)
        img_h, img_w = bgr.shape[:2]
        ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        if not ok:
            raise ValueError("jpeg encode failed")
        b64 = base64.b64encode(buf.tobytes()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}", img_w, img_h
    except Exception:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        return f"data:image/jpeg;base64,{b64}", 1000, 1000


def _trigger_pick_files(uploader) -> None:
    """
    函数名: _trigger_pick_files
    作用: 程序化唤起 Quasar QUploader 文件选择（须在用户点击回调内同步调用）
    输入:
        uploader: ui.upload 实例
    输出: 无
    """
    uploader.run_method("pickFiles")


async def _handle_image_upload(e, session, label: str, input_element) -> None:
    """
    函数名: _handle_image_upload
    作用: upload 回调：读图并打开裁切预览
    输入:
        e: upload 事件
        session: 当前会话
        label (str): 字段名
        input_element: OCR 回填控件
    输出: 无
    """
    if not getattr(e, "file", None):
        ui.notify("未读取到图片", type="warning")
        return
    image_bytes = await e.file.read()
    mime = getattr(e.file, "content_type", None) or "image/jpeg"
    _store_image_bytes(session, label, image_bytes, mime)
    _show_preview_dialog(session, label, image_bytes, input_element)


def add_image_pick_menu_items(session, label: str, input_element: Any = None) -> None:
    """
    函数名: add_image_pick_menu_items
    作用: 在 ui.menu / ui.context_menu 内加入「相机」按钮与「相册」上传区
    输入:
        session: 当前会话
        label (str): Input_label
        input_element: 可选 OCR 回填控件
    输出: 无
    """

    async def on_upload(e):
        await _handle_image_upload(e, session, label, input_element)

    cam_upload = (
        ui.upload(
            on_upload=on_upload,
            auto_upload=True,
            max_files=1,
        )
        .props(
            f'accept="{IMAGE_ACCEPT}" capture="environment" '
            "no-thumbnails auto-hide-upload-progress"
        )
        .style(
            "position:fixed;left:-9999px;width:1px;height:1px;opacity:0;overflow:hidden"
        )
    )
    ui.menu_item("相机", on_click=lambda: cam_upload.run_method("pickFiles"))
    ui.upload(
        on_upload=on_upload,
        auto_upload=True,
        max_files=1,
        label="相册",
    ).props(
        f'accept="{IMAGE_ACCEPT}" flat dense no-thumbnails auto-hide-upload-progress'
    ).classes("ocr-menu-pick w-full")


_pick_ctx: dict[str, Any] = {"session": None, "label": None, "input_element": None}
_pick_uploads_ready = False
_camera_uploader = None
_gallery_uploader = None


def _ensure_hidden_pick_uploads() -> tuple[Any, Any]:
    """
    函数名: _ensure_hidden_pick_uploads
    作用: 挂载全局隐藏 upload（桌面标签触发 pickFiles 用）
    输入: 无
    输出:
        tuple: (camera_uploader, gallery_uploader)
    """
    global _pick_uploads_ready, _camera_uploader, _gallery_uploader
    if _pick_uploads_ready:
        return _camera_uploader, _gallery_uploader

    async def on_upload(e):
        session = _pick_ctx.get("session")
        label = _pick_ctx.get("label")
        if not session or not label:
            return
        await _handle_image_upload(
            e,
            session,
            label,
            _pick_ctx.get("input_element"),
        )

    _camera_uploader = (
        ui.upload(
            on_upload=on_upload,
            auto_upload=True,
            max_files=1,
        )
        .props(
            f'accept="{IMAGE_ACCEPT}" capture="environment" no-thumbnails auto-hide-upload-progress'
        )
        .style(
            "position:fixed;left:-9999px;width:1px;height:1px;opacity:0;overflow:hidden"
        )
    )
    _gallery_uploader = (
        ui.upload(
            on_upload=on_upload,
            auto_upload=True,
            max_files=1,
        )
        .props(f'accept="{IMAGE_ACCEPT}" no-thumbnails auto-hide-upload-progress')
        .style(
            "position:fixed;left:-9999px;width:1px;height:1px;opacity:0;overflow:hidden"
        )
    )
    _pick_uploads_ready = True
    return _camera_uploader, _gallery_uploader


def pick_camera(session, label: str, input_element: Any = None) -> None:
    """
    函数名: pick_camera
    作用: 桌面回退：隐藏 upload + 同步 pickFiles（须在点击回调内调用）
    输入:
        session: 当前会话
        label (str): Input_label
        input_element: 可选 OCR 回填控件
    输出: 无
    """
    _pick_ctx["session"] = session
    _pick_ctx["label"] = label
    _pick_ctx["input_element"] = input_element
    cam, _ = _ensure_hidden_pick_uploads()
    _trigger_pick_files(cam)


def pick_gallery(session, label: str, input_element: Any = None) -> None:
    """
    函数名: pick_gallery
    作用: 桌面回退：隐藏 upload + 同步 pickFiles（须在点击回调内调用）
    输入:
        session: 当前会话
        label (str): Input_label
        input_element: 可选 OCR 回填控件
    输出: 无
    """
    _pick_ctx["session"] = session
    _pick_ctx["label"] = label
    _pick_ctx["input_element"] = input_element
    _, gal = _ensure_hidden_pick_uploads()
    _trigger_pick_files(gal)


def _apply_rectangle(
    session, label: str, rect_data: dict, img_w: int, img_h: int
) -> None:
    """
    函数名: _apply_rectangle
    作用: 将预览框选区域写入 field_images[label].rectangle
    输入:
        session: 当前会话
        label (str): 字段名
        rect_data (dict): 含 x,y,w,h
        img_w (int): 原图宽
        img_h (int): 原图高
    输出: 无
    """
    if (
        rect_data["w"] > 0
        and rect_data["h"] > 0
        and (rect_data["w"] < img_w or rect_data["h"] < img_h)
    ):
        session.field_images[label]["rectangle"] = (
            int(rect_data["x"]),
            int(rect_data["y"]),
            int(rect_data["w"]),
            int(rect_data["h"]),
        )
    else:
        session.field_images[label].pop("rectangle", None)


def _show_preview_dialog(
    session,
    label: str,
    image_bytes: bytes,
    input_element: Any = None,
) -> None:
    """
    函数名: _show_preview_dialog
    作用: 显示裁切预览；可保存截取区域或执行 OCR
    输入:
        session: 当前会话
        label (str): Input_label
        image_bytes (bytes): 已选图片
        input_element: 可选 OCR 回填控件
    输出: 无
    """
    img_src, img_w, img_h = _preview_data_url(image_bytes)
    rect_data = {"x": 0, "y": 0, "w": img_w, "h": img_h}
    is_dragging = [False]
    pinned_pt = [0, 0]
    with ui.dialog() as dialog, ui.card().classes("w-full max-w-4xl p-2 sm:p-4"):
        ui.label(f"[{label}] 调整区域（拖动角点）").classes("text-h6 font-bold")

        def draw():
            x, y, w, h = rect_data["x"], rect_data["y"], rect_data["w"], rect_data["h"]
            r = max(img_w, img_h) * 0.02
            sw = max(img_w, img_h) * 0.005
            path_d = (
                f"M -10000 -10000 H 20000 V 20000 H -10000 Z "
                f"M {x} {y} v {h} h {w} v {-h} Z"
            )
            svg = f'''
            <path d="{path_d}" fill="rgba(0,0,0,0.5)" fill-rule="evenodd" />
            <rect x="{x}" y="{y}" width="{w}" height="{h}" fill="none" stroke="#2196F3" stroke-width="{sw * 2}"/>
            <circle cx="{x}" cy="{y}" r="{r}" fill="white" stroke="#2196F3" stroke-width="{sw}"/>
            <circle cx="{x + w}" cy="{y}" r="{r}" fill="white" stroke="#2196F3" stroke-width="{sw}"/>
            <circle cx="{x}" cy="{y + h}" r="{r}" fill="white" stroke="#2196F3" stroke-width="{sw}"/>
            <circle cx="{x + w}" cy="{y + h}" r="{r}" fill="white" stroke="#2196F3" stroke-width="{sw}"/>
            '''
            ii.content = svg

        def on_mouse(e):
            if e.type == "mousedown":
                is_dragging[0] = True
                x, y, w, h = (
                    rect_data["x"],
                    rect_data["y"],
                    rect_data["w"],
                    rect_data["h"],
                )
                corners = [
                    (x, y, (x + w, y + h)),
                    (x + w, y, (x, y + h)),
                    (x, y + h, (x + w, y)),
                    (x + w, y + h, (x, y)),
                ]

                def dist2(cx, cy):
                    return (cx - e.image_x) ** 2 + (cy - e.image_y) ** 2

                closest = min(corners, key=lambda c: dist2(c[0], c[1]))
                pinned_pt[0] = closest[2][0]
                pinned_pt[1] = closest[2][1]
            elif e.type == "mousemove" and is_dragging[0]:
                x1 = min(pinned_pt[0], e.image_x)
                y1 = min(pinned_pt[1], e.image_y)
                x2 = max(pinned_pt[0], e.image_x)
                y2 = max(pinned_pt[1], e.image_y)
                x1 = max(0, min(img_w, x1))
                y1 = max(0, min(img_h, y1))
                x2 = max(0, min(img_w, x2))
                y2 = max(0, min(img_h, y2))
                rect_data["x"] = x1
                rect_data["y"] = y1
                rect_data["w"] = x2 - x1
                rect_data["h"] = y2 - y1
                draw()
            elif e.type == "mouseup":
                is_dragging[0] = False

        ii = ui.interactive_image(
            img_src,
            on_mouse=on_mouse,
            events=["mousedown", "mousemove", "mouseup"],
            cross=False,
        ).classes("w-full")
        draw()

        def save_crop():
            _apply_rectangle(session, label, rect_data, img_w, img_h)
            dialog.close()
            ui.notify(
                f"已保存 [{label}] 截取区域；添加数据/保存时写入数据库",
                type="positive",
            )

        def start_ocr():
            _apply_rectangle(session, label, rect_data, img_w, img_h)
            dialog.close()
            run_ocr(session, label, input_element)

        with ui.row().classes("w-full items-center mt-4 flex-wrap gap-2"):
            AppBtn("取消", on_click=dialog.close).props("flat")
            ui.space()
            with ui.row().classes("gap-2"):
                AppBtn("保存", variant="db", on_click=save_crop)
                AppBtn("OCR", on_click=start_ocr)
    dialog.open()


def run_ocr(session, label: str, input_element: Any = None) -> None:
    """
    函数名: run_ocr
    作用: 对 field_images 中已缓存并裁切的图片执行 PaddleOCR
    输入:
        session: 当前用户会话
        label (str): 当前字段的 Input_label
        input_element: 默认回填控件
    输出: 无
    """
    if label not in _ensure_field_images(session):
        ui.notify("请先通过「相机」或「相册」选择图片", type="warning")
        return
    image_data = session.field_images[label]
    pic_bytes = image_data["bytes"]
    rectangle = image_data.get("rectangle", None)
    if input_element and hasattr(input_element, "disable"):
        input_element.disable()
    client = input_element.client if input_element else ui.context.client
    is_ghost = label == GHOST_OCR_LABEL

    async def process():
        """
        函数名: process
        作用: 后台执行 OCR；单条 ongoing 通知随 OcrStage 更新，完成后 dismiss
        输入: 无
        输出: 无
        """
        from paddle_ocr.main import OcrStage, PaddleOcr

        loop = asyncio.get_running_loop()
        progress_notify = [None]
        last_stage = [None]
        stage_messages = {
            OcrStage.FAST_OCR: f"正在识别 {label}: 快速 OCR 特征提取",
            OcrStage.SEMANTIC_CHECK: f"正在识别 {label}: 语义检查中…",
            OcrStage.GEMMA_REFINE: f"正在识别 {label}: Gemma 视觉纠错",
            OcrStage.VL_REFINE: f"正在识别 {label}: Paddle-VL 最终纠错",
        }

        def dismiss_progress() -> None:
            with client:
                if progress_notify[0] is not None:
                    progress_notify[0].dismiss()
                    progress_notify[0] = None

        def show_stage(code: OcrStage) -> None:
            message = stage_messages.get(code)
            if not message or last_stage[0] == code:
                return
            last_stage[0] = code
            with client:
                if progress_notify[0] is None:
                    progress_notify[0] = ui.notification(
                        message, spinner=True, type="ongoing"
                    )
                else:
                    progress_notify[0].message = message

        def on_status(code: OcrStage) -> None:
            loop.call_soon_threadsafe(show_stage, code)

        try:
            with client:
                progress_notify[0] = ui.notification(
                    f"正在识别 {label}…",
                    spinner=True,
                    type="ongoing",
                )
            result = await run.io_bound(
                lambda: PaddleOcr(pic_bytes, rectangle, status_callback=on_status),
            )
            dismiss_progress()
            with client:
                if not result.get("ok"):
                    ui.notify(result.get("message", "识别失败"), type="negative")
                    session.field_images[label]["ocr_status"] = "failed"
                    return
                if is_ghost:
                    import re

                    display_text = json.dumps(result, ensure_ascii=False, indent=2)
                    display_text = re.sub(r"(?<![}\]])\s*,\n\s+", ", ", display_text)
                    hint = "识别完成，请在输入框确认或修改后点击空白处填入"
                else:
                    display_text = ocr_result_to_field_text(result)
                    hint = "识别成功"
                if not display_text.strip():
                    ui.notify("未能识别出有效文字", type="warning")
                    session.field_images[label]["ocr_status"] = "empty"
                    return
                if input_element and hasattr(input_element, "value"):
                    input_element.value = display_text
                if not is_ghost:
                    session.draft[label] = display_text
                session.field_images[label]["ocr_text"] = json.dumps(
                    result,
                    ensure_ascii=False,
                )
                session.field_images[label]["ocr_status"] = "success"
                ui.notify(hint, type="positive")
        except Exception as exc:
            dismiss_progress()
            with client:
                ui.notify(f"系统错误: {str(exc)}", type="negative")
        finally:
            if input_element and hasattr(input_element, "enable"):
                try:
                    with client:
                        input_element.enable()
                except Exception:
                    pass

    asyncio.create_task(process())
