"""Global lock: one OCR task (fast or VL) at a time."""

from __future__ import annotations

import threading


INFER_LOCK = threading.Lock()
