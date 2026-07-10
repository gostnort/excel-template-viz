"""CLI entry and public facade for the paddle_ocr platform."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from paddle_ocr import config
from paddle_ocr.models_catalog import models_dir_nonempty
from paddle_ocr.runtime.llm_refine import LlmRefine, ShouldTryLlm
from paddle_ocr.runtime.postprocess import HasContent
from paddle_ocr.runtime.structure_backend import GetStructureBackend


PicInput = bytes | Path | str
Rectangle = tuple[int, int, int, int] | None
OcrTask = tuple[PicInput, Rectangle]


def PaddleOcr(
    pic: PicInput,
    rectangle: Rectangle = None,
) -> dict[str, Any]:
    """One picture + optional OpenCV ROI → string*/table* JSON (no HealthCheck)."""
    try:
        fast = GetStructureBackend().Run(pic, rectangle)
    except Exception:
        fast = {"ok": False, "message": config.MSG_INFER_FAIL, "mode": "fast"}
    if not ShouldTryLlm(fast):
        return fast
    try:
        llm = LlmRefine(pic, rectangle, draft=fast)
    except Exception:
        llm = {"ok": False, "message": config.MSG_INFER_FAIL, "mode": "llm"}
    if llm.get("ok") and HasContent(llm):
        return llm
    if fast.get("ok") and HasContent(fast):
        merged = dict(fast)
        merged["message"] = config.MSG_LLM_PARTIAL
        return merged
    return llm



def PaddleOcrTasks(tasks: list[OcrTask]) -> list[dict[str, Any]]:
    """Run multiple (pic, rectangle) jobs in order; each item is one PaddleOcr result."""
    results: list[dict[str, Any]] = []
    for pic, rectangle in tasks:
        results.append(PaddleOcr(pic, rectangle))
    return results



def HealthCheck() -> dict[str, Any]:
    try:
        return GetStructureBackend().HealthCheck()
    except Exception:
        return {"ok": False, "message": config.MSG_NOT_READY, "version": ""}



def _ensure_models() -> tuple[bool, str]:
    report = HealthCheck()
    if report.get("ok") and models_dir_nonempty():
        return True, str(report.get("message") or config.MSG_HEALTH_OK)
    from paddle_ocr.scripts.download_models import download_models
    ok, message = download_models()
    if not ok:
        return False, message
    report = HealthCheck()
    if not report.get("ok"):
        return False, str(report.get("message") or config.MSG_NOT_READY)
    return True, str(report.get("message") or config.MSG_HEALTH_OK)



def main(argv: list[str] | None = None) -> int:
    """CLI gate: HealthCheck → auto download → one PaddleOcr on sample image."""
    if argv is None:
        argv = sys.argv[1:]
    if argv:
        print(f"usage: python paddle_ocr/main.py  (ignored args: {argv!r})")
    ok, message = _ensure_models()
    print(message)
    if not ok:
        return 1
    sample = config.SAMPLE_IMAGE
    if not sample.is_file():
        print(f"缺少样图: {sample}")
        return 1
    result = PaddleOcr(sample, None)
    print(result.get("message"))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    raise SystemExit(main())
