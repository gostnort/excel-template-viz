"""Global lock: one OCR task (PP-OCRv6 or PP-StructureV3) at a time."""

from __future__ import annotations

import threading


INFER_LOCK = threading.Lock()
