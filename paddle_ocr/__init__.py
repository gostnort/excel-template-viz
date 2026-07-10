"""Self-contained PaddleOCR platform (no UI, no SQLite)."""

from paddle_ocr.main import HealthCheck, PaddleOcr, PaddleOcrTasks


__all__ = ["PaddleOcr", "PaddleOcrTasks", "HealthCheck"]
