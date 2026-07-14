import base64
from typing import Any
from nicegui import ui

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
        
        def handle_upload(e):
            if not e.content:
                ui.notify('未读取到图片', type='warning')
                return
            image_bytes = e.content.read()
            mime = e.type or 'image/jpeg'
            
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
            label='点击此处或拖拽图片 (手机端支持调用相机)',
            accept='image/*'
        ).props('capture="environment"')  # 'capture' attribute for mobile camera
        
        with ui.row().classes('w-full justify-end mt-4'):
            ui.button('取消', on_click=dialog.close).props('flat')

    dialog.open()


def run_ocr(session, label: str, input_element: Any) -> None:
    """
    函数名: run_ocr
    作用: 对 session.field_images[label] 缓存的图片执行 PaddleOCR 识别，并填充到输入框
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
    
    # 暂时禁用输入框，显示加载状态
    input_element.disable()
    ui.notify(f'正在识别 {label}，请稍候...', type='info')
    
    import asyncio
    from nicegui import run
    
    async def process():
        try:
            from paddle_ocr.main import PaddleOcr
            result = await run.io_bound(PaddleOcr, pic_bytes, None)
            
            if result.get("ok"):
                # PaddleOcr returns string1, string2... and table1, table2...
                texts = []
                for k in sorted(result.keys()):
                    if k.startswith("string") and isinstance(result[k], str):
                        texts.append(result[k])
                
                text = "\n".join(texts)
                if text:
                    input_element.value = text
                    session.draft[label] = text
                    ui.notify('识别成功', type='positive')
                    # 保存 OCR 结果供稍后落库使用
                    session.field_images[label]['ocr_text'] = text
                    session.field_images[label]['ocr_status'] = 'success'
                else:
                    ui.notify('未能识别出有效文字', type='warning')
                    session.field_images[label]['ocr_status'] = 'empty'
            else:
                msg = result.get("message", "识别失败")
                ui.notify(f'OCR 失败: {msg}', type='negative')
                session.field_images[label]['ocr_status'] = 'failed'
        except Exception as e:
            ui.notify(f'系统错误: {str(e)}', type='negative')
        finally:
            input_element.enable()
            
    asyncio.create_task(process())
