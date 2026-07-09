"""Result types shared by the paddle_ocr facade."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class OcrLine:
    text: str
    confidence: float = 0.0
    box: list[Any] = field(default_factory=list)



@dataclass
class OcrResult:
    ok: bool
    text: str = ""
    lines: list[OcrLine] = field(default_factory=list)
    engine: str = "paddleocr"
    version: str = ""
    message: str = ""



@dataclass
class HealthReport:
    ok: bool
    message: str = ""
    version: str = ""
