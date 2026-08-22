"""PP-OCRv6 field OCR via paddleocr-mcp HTTP（细条裁剪）。"""

from __future__ import annotations

import threading
from typing import Any

from paddle_ocr import config
from paddle_ocr.mcp_runtime import call_ocr_mcp, ensure_ocr_mcp
from paddle_ocr.runtime.infer_lock import INFER_LOCK


_lock = threading.Lock()
_instance: "FieldStripBackend | None" = None



class FieldStripBackend:
    def __init__(self) -> None:
        self._engine = None
        self._init_error: str | None = None


    def _ensure_engine(self):
        """
        函数名: _ensure_engine
        作用: 经 ensure_ocr_mcp 懒启动 PP-OCRv6 daemon（已运行则直接就绪）；不拉 Structure。
        输入: 无。
        输出:
            Any: 就绪为 True；失败为 None。
        """
        # 中文注释: 未起则懒启动 OCR 槽；已起则 no-op。不 stop。
        if ensure_ocr_mcp():
            self._engine = True
            return self._engine
        self._init_error = "import"
        return None


    def Run(self, img) -> dict[str, Any]:
        """
        函数名: Run
        作用: 对已裁剪细条图调用 PP-OCRv6 MCP。
        输入:
            img: BGR ndarray。
        输出:
            dict: §3.3 fast JSON。
        """
        with INFER_LOCK:
            engine = self._ensure_engine()
            if engine is None:
                msg = config.MSG_NOT_READY if self._init_error == "import" else config.MSG_MODEL_MISSING
                return {"ok": False, "message": msg, "mode": "fast", "engine": "ocr"}
            try:
                return call_ocr_mcp(img)
            except Exception:
                return {"ok": False, "message": config.MSG_INFER_FAIL, "mode": "fast", "engine": "ocr"}



def GetFieldStripBackend() -> FieldStripBackend:
    """
    函数名: GetFieldStripBackend
    作用: 返回进程内 FieldStripBackend 单例。
    输入: 无。
    输出:
        FieldStripBackend: 单例。
    """
    global _instance
    with _lock:
        if _instance is None:
            _instance = FieldStripBackend()
        return _instance



def ResetFieldStripBackend() -> None:
    """
    函数名: ResetFieldStripBackend
    作用: 清空字段 OCR 单例（不停止 MCP；OCR 由 stop_ocr_mcp/stop_mcp 停，Structure 由 ResetStructureBackend）。
    输入: 无。
    输出: 无。
    """
    global _instance
    with _lock:
        _instance = None
