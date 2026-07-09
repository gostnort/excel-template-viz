"""Self-contained PaddleOCR platform (no UI, no SQLite)."""

from paddle_ocr.main import HealthCheck, PaddleOcr, health_check, recognize


__all__ = ["PaddleOcr", "HealthCheck", "recognize", "health_check"]
