"""PP-StructureV3 via paddleocr-mcp HTTP（PpStructure callee；不按网格分流字段 OCR）。"""

from __future__ import annotations

import threading
from typing import Any

from paddle_ocr import config
from paddle_ocr.mcp_runtime import call_structure_mcp, start_mcp, start_structure_mcp, stop_structure_mcp
from paddle_ocr.runtime.image_decode import CropBoxError, ImageDecodeError, load_for_ocr
from paddle_ocr.runtime.infer_lock import INFER_LOCK
from paddle_ocr.runtime.postprocess import HasContent


_lock = threading.Lock()
_instance: "StructureBackend | None" = None



class StructureBackend:
    def __init__(self) -> None:
        self._engine = None
        self._version = ""
        self._init_error: str | None = None


    def _package_version(self) -> str:
        """
        函数名: _package_version
        作用: 读已安装 paddleocr-mcp 版本号。
        输入: 无。
        输出:
            str: 版本；读失败为空串。
        """
        if self._version:
            return self._version
        try:
            import importlib.metadata
            self._version = importlib.metadata.version("paddleocr_mcp")
        except Exception:
            self._version = ""
        return self._version


    def _ensure_engine(self):
        """
        函数名: _ensure_engine
        作用: 经 start_structure_mcp 懒启动 PP-StructureV3 daemon；不拉 OCR。
        输入: 无。
        输出:
            Any: 就绪为 True；失败为 None。
        """
        # 中文注释: 未起则懒启动 Structure 槽；已起则 no-op。callee 不 stop（T5 runner finally 释放）。
        if start_structure_mcp():
            self._engine = True
            return self._engine
        self._init_error = "import"
        return None


    def warm(self) -> None:
        """
        函数名: warm
        作用: 安装/顶栏预热：先占端口再启动 paddleocr-mcp（job 路径不按档常驻 Structure）。
        输入: 无。
        输出: 无。
        """
        # T3/T7：预热不要再默认 start_mcp(include_structure=True) 常驻 Structure。
        start_mcp(include_structure=True)


    def HealthCheck(self) -> dict[str, Any]:
        """
        函数名: HealthCheck
        作用: paddleocr-mcp 可导入即可；权重由 MCP 子进程首次启动时下载。
        输入: 无。
        输出:
            dict: ok / message / version。
        """
        ver = self._package_version()
        try:
            import paddleocr_mcp  # noqa: F401
        except Exception:
            self._init_error = "import"
            return {"ok": False, "message": config.MSG_NOT_READY, "version": ver}
        return {"ok": True, "message": config.MSG_HEALTH_OK, "version": ver}


    def Run(
        self,
        pic,
        rectangle: tuple[int, int, int, int] | None = None,
        *,
        mode: str = "fast",
    ) -> dict[str, Any]:
        """
        函数名: Run
        作用: 解码裁切后只调 PP-StructureV3 MCP；不按 HasTableGrid 分流字段 OCR。
        输入:
            pic: bytes/Path/str/ndarray。
            rectangle (tuple|None): OpenCV ROI (x,y,w,h)。
            mode (str): fast 或 structure（仅写入 JSON，不改引擎）。
        输出:
            dict: §3.3 JSON，engine="structure"。
        """
        ver = self._package_version()
        try:
            img = load_for_ocr(pic, rectangle)
        except ImageDecodeError:
            return {"ok": False, "message": config.MSG_BAD_IMAGE, "version": ver, "mode": mode, "engine": "structure"}
        except CropBoxError:
            return {"ok": False, "message": config.MSG_BAD_CROP, "version": ver, "mode": mode, "engine": "structure"}
        except Exception:
            return {"ok": False, "message": config.MSG_BAD_IMAGE, "version": ver, "mode": mode, "engine": "structure"}
        # 中文注释: 一律 Structure MCP；网格分流由 T5 list runner BOOT 负责
        with INFER_LOCK:
            engine = self._ensure_engine()
            if engine is None:
                return {"ok": False, "message": config.MSG_NOT_READY, "version": ver, "mode": mode, "engine": "structure"}
            try:
                result = call_structure_mcp(img, mode=mode)
            except Exception:
                return {"ok": False, "message": config.MSG_INFER_FAIL, "version": ver, "mode": mode, "engine": "structure"}
        result["version"] = ver
        result["engine"] = "structure"
        if result.get("ok") and not HasContent(result):
            result["message"] = config.MSG_EMPTY
        return result



def GetStructureBackend() -> StructureBackend:
    """
    函数名: GetStructureBackend
    作用: 返回进程内 StructureBackend 单例。
    输入: 无。
    输出:
        StructureBackend: 单例。
    """
    global _instance
    with _lock:
        if _instance is None:
            _instance = StructureBackend()
        return _instance



def ResetStructureBackend() -> None:
    """
    函数名: ResetStructureBackend
    作用: 结束 Structure MCP 子进程并清空单例（不停 OCR）。
    输入: 无。
    输出: 无。
    """
    global _instance
    stop_structure_mcp()
    with _lock:
        _instance = None



def StructureRefine(
    pic,
    rectangle: tuple[int, int, int, int] | None = None,
    *,
    draft: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    函数名: StructureRefine
    作用: 用 PP-StructureV3 MCP 做精修。空结果时保留 fast 草稿。
    输入:
        pic: 原图（bytes/Path/str）。
        rectangle (tuple|None): OpenCV ROI (x,y,w,h)。
        draft (dict|None): fast 草稿；Structure 无内容时回退。
    输出:
        dict: §3.3 JSON，mode="structure"。
    """
    result = GetStructureBackend().Run(pic, rectangle, mode="structure")
    if result.get("ok") and HasContent(result):
        return result
    ver = result.get("version") or ""
    if draft and HasContent(draft):
        out = dict(draft)
        out["mode"] = "structure"
        out["engine"] = "structure"
        out["message"] = config.MSG_LLM_PARTIAL
        out["version"] = ver
        return out
    if not result.get("ok"):
        return result
    result["message"] = config.MSG_EMPTY
    return result
