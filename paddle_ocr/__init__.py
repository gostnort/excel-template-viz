"""Self-contained PaddleOCR platform (no UI, no SQLite)."""

from paddle_ocr.main import EnsureModels, HealthCheck, PaddleOcr, PaddleOcrTasks

# 启动时测一次可用内存，缓存精修路径开关；psutil 失败默认关闭（保守）。
try:
    from paddle_ocr.gate.memory_guard import init_refine_path
    init_refine_path()
except Exception:
    pass


__all__ = ["PaddleOcr", "PaddleOcrTasks", "HealthCheck", "EnsureModels"]
