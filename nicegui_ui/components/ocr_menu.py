import base64
from typing import Any
import json
from nicegui import ui

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
    作用: 打开对话框，支持拍照或上传图片，并存入 session.field_images[label]
    输入:
        session: 当前用户会话
        label (str): 当前字段的 Input_label
        on_success (callable): 成功后的回调函数
    输出: 无
    """
    with ui.dialog() as dialog, ui.card().classes('w-full max-w-md'):
        ui.label(f'[{label}] 拍照 / 选图').classes('text-h6 font-bold')
        
        async def handle_upload(e):
            if not getattr(e, 'file', None):
                ui.notify('未读取到图片', type='warning')
                return
            image_bytes = await e.file.read()
            mime = getattr(e.file, 'content_type', 'image/jpeg')
            
            # 存入 session.field_images
            if not hasattr(session, 'field_images'):
                session.field_images = {}
            session.field_images[label] = {
                'bytes': image_bytes,
                'mime': mime
            }
            ui.notify(f'已缓存 {label} 的图片，提交时将存入数据库', type='positive')
            dialog.close()
            if on_success:
                on_success()

        ui.upload(
            on_upload=handle_upload,
            auto_upload=True,
            max_files=1,
            label='点击此处或拖拽图片 (手机端支持调用相机)'
        ).props('accept="image/*" capture="environment"')
        
        with ui.row().classes('w-full justify-end mt-4'):
            ui.button('取消', on_click=dialog.close).props('flat')

    dialog.open()

def run_ocr(session, label: str, input_element: Any) -> None:
    """
    函数名: run_ocr
    作用: 对 session.field_images[label] 缓存的图片执行 PaddleOCR 识别，并在相应输入框中回填 JSON 格式或纯文本。
    输入:
        session: 当前用户会话
        label (str): 当前字段的 Input_label
        input_element: ui.input 或其他输入控件实例，用于回填文本
    输出: 无
    """
    if label not in getattr(session, 'field_images', {}):
        open_camera_dialog(session, label, on_success=lambda: run_ocr(session, label, input_element))
        return
    image_data = session.field_images[label]
    pic_bytes = image_data['bytes']
    # 中文注释：暂时禁用输入框，显示加载状态
    input_element.disable()
    ui.notify(f'正在识别 {label}，请稍候... (预计需 5~15 秒)', type='info', timeout=15000)
    # 中文注释：在启动后台任务前，捕获当前的 NiceGUI 页面 client 实例
    client = input_element.client
    is_ghost = (label == GHOST_OCR_LABEL)

    import asyncio
    from nicegui import run
    async def process():
        """
        函数名: process
        作用: 后台执行 OCR 识别任务并更新 UI 与会话状态
        输入: 无
        输出: 无
        """
        try:
            from paddle_ocr.main import PaddleOcr
            result = await run.io_bound(PaddleOcr, pic_bytes, None)
            with client:
                if not result.get("ok"):
                    ui.notify(result.get("message", "识别失败"), type="negative")
                    session.field_images[label]["ocr_status"] = "failed"
                    return

                if is_ghost:
                    display_text = json.dumps(result, ensure_ascii=False, indent=2)
                    hint = "识别完成，请点击其它区域以拆分填入各字段"
                else:
                    display_text = ocr_result_to_field_text(result)
                    hint = "识别成功"

                if not display_text.strip():
                    ui.notify("未能识别出有效文字", type="warning")
                    session.field_images[label]["ocr_status"] = "empty"
                    return

                input_element.value = display_text

                # FIELD：同步 draft 仅此字段；GHOST：不写 draft（等 blur）
                if not is_ghost:
                    session.draft[label] = display_text

                session.field_images[label]["ocr_text"] = json.dumps(
                    result, ensure_ascii=False
                )  # 落库用完整 JSON
                session.field_images[label]["ocr_status"] = "success"
                ui.notify(hint, type="positive")
        except Exception as e:
            with client:
                ui.notify(f'系统错误: {str(e)}', type='negative')
        finally:
            try:
                with client:
                    input_element.enable()
            except Exception:
                pass
    asyncio.create_task(process())
