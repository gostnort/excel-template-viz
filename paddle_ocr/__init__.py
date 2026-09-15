"""Self-contained PaddleOCR platform (no UI, no SQLite)."""

from paddle_ocr.main import EnsureModels, HealthCheck, PaddleOcr, PaddleOcrTasks, PaddleOcr_PDF2MDs, PpStructure, lm_similarity_score, run_ocr_job, semantic_judge

__all__ = ["PaddleOcr", "PaddleOcrTasks", "PaddleOcr_PDF2MDs", "PpStructure", "lm_similarity_score", "run_ocr_job", "semantic_judge", "HealthCheck", "EnsureModels"]
