import asyncio
import base64
import json
from typing import Any

from nicegui import run, ui

GHOST_OCR_LABEL = "顶部粘贴"

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
    # 优先收集 string1..N
    for k in sorted(result.keys()):
        if k.startswith("string") and isinstance(result[k], str):
            val = result[k].strip()
            if val:
                texts.append(val)
                
    # 如果有 string，优先返回
    if texts:
        return "\n".join(texts)
        
    # 如果无 string，则回退合并 table 中的 cells
    for k in sorted(result.keys()):
        if k.startswith("table") and isinstance(result[k], list):
            for row in result[k]:
                if isinstance(row, dict) and "cells" in row:
                    cells = row["cells"]
                    if isinstance(cells, list):
                        # 把所有 cells 用空格连接为一行
                        line = " ".join([str(c).strip() for c in cells if str(c).strip()])
                        if line:
                            texts.append(line)
                            
    return "\n".join(texts).strip()

def open_camera_dialog(session, label: str, on_success=None) -> None:
    """
    函数名: open_camera_dialog
    作用: 打开对话框，支持拍照或上传图片，提供截图选区，并存入 session.field_images[label]
    输入:
        session: 当前用户会话
        label (str): 当前字段的 Input_label
        on_success (callable): 成功后的回调函数
    输出: 无
    """
    with ui.dialog() as dialog, ui.card().classes('w-full max-w-4xl p-2 sm:p-4'):
        content_container = ui.column().classes('w-full')
        
        def render_upload():
            content_container.clear()
            with content_container:
                ui.label(f'[{label}] 拍照 / 选图').classes('text-h6 font-bold')
                ui.upload(
                    on_upload=handle_upload,
                    auto_upload=True,
                    max_files=1,
                    label='点击此处或拖拽图片 (手机端支持调用相机)'
                ).props('accept="image/*" capture="environment"').classes('w-full')
                with ui.row().classes('w-full justify-end mt-4'):
                    ui.button('取消', on_click=dialog.close).props('flat')

        def render_preview(image_bytes):
            content_container.clear()
            with content_container:
                ui.label(f'[{label}] 调整识别区域 (拖动角点)').classes('text-h6 font-bold')
                
                from PIL import Image
                import io
                try:
                    img = Image.open(io.BytesIO(image_bytes))
                    img_w, img_h = img.width, img.height
                except Exception:
                    img_w, img_h = 1000, 1000

                b64 = base64.b64encode(image_bytes).decode('utf-8')
                img_src = f"data:image/jpeg;base64,{b64}"
                
                rect_data = {"x": 0, "y": 0, "w": img_w, "h": img_h}
                is_dragging = [False]
                pinned_pt = [0, 0]
                
                def draw():
                    x, y, w, h = rect_data["x"], rect_data["y"], rect_data["w"], rect_data["h"]
                    r = max(img_w, img_h) * 0.02
                    sw = max(img_w, img_h) * 0.005
                    path_d = f"M -10000 -10000 H 20000 V 20000 H -10000 Z M {x} {y} v {h} h {w} v {-h} Z"
                    svg = f'''
                    <path d="{path_d}" fill="rgba(0,0,0,0.5)" fill-rule="evenodd" />
                    <rect x="{x}" y="{y}" width="{w}" height="{h}" fill="none" stroke="#2196F3" stroke-width="{sw*2}"/>
                    <circle cx="{x}" cy="{y}" r="{r}" fill="white" stroke="#2196F3" stroke-width="{sw}"/>
                    <circle cx="{x+w}" cy="{y}" r="{r}" fill="white" stroke="#2196F3" stroke-width="{sw}"/>
                    <circle cx="{x}" cy="{y+h}" r="{r}" fill="white" stroke="#2196F3" stroke-width="{sw}"/>
                    <circle cx="{x+w}" cy="{y+h}" r="{r}" fill="white" stroke="#2196F3" stroke-width="{sw}"/>
                    '''
                    ii.content = svg

                def on_mouse(e):
                    if e.type == 'mousedown':
                        is_dragging[0] = True
                        x, y, w, h = rect_data["x"], rect_data["y"], rect_data["w"], rect_data["h"]
                        corners = [
                            (x, y, (x+w, y+h)),
                            (x+w, y, (x, y+h)),
                            (x, y+h, (x+w, y)),
                            (x+w, y+h, (x, y))
                        ]
                        def dist2(cx, cy): return (cx - e.image_x)**2 + (cy - e.image_y)**2
                        closest = min(corners, key=lambda c: dist2(c[0], c[1]))
                        pinned_pt[0] = closest[2][0]
                        pinned_pt[1] = closest[2][1]
                    elif e.type == 'mousemove' and is_dragging[0]:
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
                    elif e.type == 'mouseup':
                        is_dragging[0] = False

                ii = ui.interactive_image(img_src, on_mouse=on_mouse, events=['mousedown', 'mousemove', 'mouseup'], cross=False).classes('w-full')
                draw()

                def confirm():
                    if rect_data["w"] > 0 and rect_data["h"] > 0 and (rect_data["w"] < img_w or rect_data["h"] < img_h):
                        session.field_images[label]['rectangle'] = (int(rect_data["x"]), int(rect_data["y"]), int(rect_data["w"]), int(rect_data["h"]))
                    else:
                        session.field_images[label].pop('rectangle', None)
                        
                    dialog.close()
                    if on_success:
                        on_success()

                with ui.row().classes('w-full justify-between mt-4'):
                    ui.button('重新上传', on_click=render_upload).props('flat')
                    ui.button('开始 OCR', on_click=confirm).props('color="primary"')

        async def handle_upload(e):
            if not getattr(e, 'file', None):
                ui.notify('未读取到图片', type='warning')
                return
            image_bytes = await e.file.read()
            mime = getattr(e.file, 'content_type', 'image/jpeg')
            
            if not hasattr(session, 'field_images'):
                session.field_images = {}
            session.field_images[label] = {
                'bytes': image_bytes,
                'mime': mime
            }
            render_preview(image_bytes)
            
        render_upload()
    dialog.open()


def run_ocr(session, label: str, input_element: Any = None) -> None:
    """
    函数名: run_ocr
    作用: 对 session.field_images[label] 缓存的图片执行 PaddleOCR 识别。支持多阶段提示反馈，并将结果回填。
    输入:
        session: 当前用户会话
        label (str): 当前字段的 Input_label
        input_element: 默认回填控件
    输出: 无
    """
    if label not in getattr(session, 'field_images', {}):
        open_camera_dialog(session, label, on_success=lambda: run_ocr(session, label, input_element))
        return
        
    image_data = session.field_images[label]
    pic_bytes = image_data['bytes']
    rectangle = image_data.get('rectangle', None)
    
    if input_element and hasattr(input_element, 'disable'):
        input_element.disable()
        
    client = input_element.client if input_element else ui.context.client
    is_ghost = (label == GHOST_OCR_LABEL)

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
            OcrStage.FAST_OCR: f'正在识别 {label}: 快速 OCR 特征提取',
            OcrStage.SEMANTIC_CHECK: f'正在识别 {label}: 语义检查中…',
            OcrStage.GEMMA_REFINE: f'正在识别 {label}: Gemma 视觉纠错',
            OcrStage.VL_REFINE: f'正在识别 {label}: Paddle-VL 最终纠错',
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
                    progress_notify[0] = ui.notification(message, spinner=True, type='ongoing')
                else:
                    progress_notify[0].message = message

        def on_status(code: OcrStage) -> None:
            loop.call_soon_threadsafe(show_stage, code)

        try:
            with client:
                progress_notify[0] = ui.notification(
                    f'正在识别 {label}…',
                    spinner=True,
                    type='ongoing',
                )
            result = await run.io_bound(
                lambda: PaddleOcr(pic_bytes, rectangle, status_callback=on_status),
            )
            dismiss_progress()
            with client:
                if not result.get('ok'):
                    ui.notify(result.get('message', '识别失败'), type='negative')
                    session.field_images[label]['ocr_status'] = 'failed'
                    return
                if is_ghost:
                    import re
                    display_text = json.dumps(result, ensure_ascii=False, indent=2)
                    display_text = re.sub(r'(?<![}\]])\s*,\n\s+', ', ', display_text)
                    hint = '识别完成，请在输入框确认或修改后点击空白处填入'
                else:
                    display_text = ocr_result_to_field_text(result)
                    hint = '识别成功'
                if not display_text.strip():
                    ui.notify('未能识别出有效文字', type='warning')
                    session.field_images[label]['ocr_status'] = 'empty'
                    return
                if input_element and hasattr(input_element, 'value'):
                    input_element.value = display_text
                if not is_ghost:
                    session.draft[label] = display_text
                session.field_images[label]['ocr_text'] = json.dumps(
                    result, ensure_ascii=False,
                )
                session.field_images[label]['ocr_status'] = 'success'
                ui.notify(hint, type='positive')
        except Exception as exc:
            dismiss_progress()
            with client:
                ui.notify(f'系统错误: {str(exc)}', type='negative')
        finally:
            if input_element and hasattr(input_element, 'enable'):
                try:
                    with client:
                        input_element.enable()
                except Exception:
                    pass

    asyncio.create_task(process())
