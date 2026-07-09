"""CLI entry and public facade for the paddle_ocr platform."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

from paddle_ocr import config
from paddle_ocr.models_catalog import catalog_summary, models_dir_nonempty
from paddle_ocr.runtime import HealthReport, OcrResult
from paddle_ocr.runtime.ocr_backend import get_backend
from paddle_ocr.runtime.postprocess import HasContent
from paddle_ocr.runtime.structure_backend import GetStructureBackend


def PaddleOcr(
    pic: bytes | Path | str,
    rectangle: tuple[int, int, int, int] | None = None,
) -> dict[str, Any]:
    """Public OCR API: picture + optional OpenCV ROI → string*/table* JSON.

    Fast path = PPStructureV3. LLM refine is planned when fast is empty/fails;
    not required for the picture→JSON gate.
    """
    try:
        result = GetStructureBackend().Run(pic, rectangle)
    except Exception:
        return {"ok": False, "message": config.MSG_INFER_FAIL, "mode": "fast"}
    # LLM auto-fallback (C3): only when fast ran but produced no content / infer fail
    # and LLM is available. Stub: leave result as-is until llm_refine is wired.
    if result.get("ok") and not HasContent(result):
        # Placeholder for future LlmRefine(pic, rectangle, draft=result)
        pass
    return result



def HealthCheck() -> dict[str, Any]:
    try:
        return GetStructureBackend().HealthCheck()
    except Exception:
        return {"ok": False, "message": config.MSG_NOT_READY, "version": ""}



def recognize(
    image,
    *,
    crop_box: tuple[int, int, int, int] | None = None,
    lang: str = "ch",
    task: str = "field",
) -> OcrResult:
    """Legacy field OCR (debug). Prefer PaddleOcr() for UI."""
    try:
        return get_backend().recognize(
            image,
            crop_box=crop_box,
            lang=lang,
            task=task,
        )
    except Exception:
        return OcrResult(ok=False, message=config.MSG_INFER_FAIL, version="")



def health_check() -> HealthReport:
    """Legacy health wrapper around structure HealthCheck."""
    report = HealthCheck()
    return HealthReport(
        ok=bool(report.get("ok")),
        message=str(report.get("message") or ""),
        version=str(report.get("version") or ""),
    )



def cmd_probe() -> int:
    print("paddle_ocr probe")
    print(f"  python: {sys.version.split()[0]}")
    print(f"  platform_root: {config.PLATFORM_ROOT}")
    print(f"  models_dir: {config.MODELS_DIR}")
    print(f"  sample: {config.SAMPLE_IMAGE} exists={config.SAMPLE_IMAGE.is_file()}")
    try:
        import importlib.metadata
        print(f"  paddle: {importlib.metadata.version('paddlepaddle')}")
        print(f"  paddleocr: {importlib.metadata.version('paddleocr')}")
    except Exception as exc:
        print(f"  packages: MISSING ({exc})")
        return 1
    summary = catalog_summary()
    for k, v in summary.items():
        print(f"  catalog.{k}: {v}")
    print(f"  models_nonempty: {models_dir_nonempty()}")
    report = HealthCheck()
    print(f"  health.ok: {report.get('ok')}")
    print(f"  health.message: {report.get('message')}")
    return 0 if report.get("ok") else 1


def cmd_download() -> int:
    from paddle_ocr.scripts.download_models import download_models
    ok, message = download_models()
    print(message)
    return 0 if ok else 1


def cmd_smoke() -> int:
    from paddle_ocr.scripts.smoke_test import run_smoke
    ok, message = run_smoke()
    print(message)
    return 0 if ok else 1


def cmd_bench() -> int:
    sample = config.SAMPLE_IMAGE
    if not sample.is_file():
        print(f"missing sample: {sample}")
        return 1
    PaddleOcr(sample, None)
    times: list[float] = []
    result: dict[str, Any] = {}
    for _ in range(2):
        t0 = time.perf_counter()
        result = PaddleOcr(sample, None)
        times.append(time.perf_counter() - t0)
        if not result.get("ok"):
            print(result.get("message"))
            return 1
    avg = sum(times) / len(times)
    print(f"bench n=2 avg_s={avg:.3f} mode={result.get('mode')} keys={sorted(k for k in result if k.startswith(('string','table')))}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paddle_ocr.main", description="PaddleOCR platform CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("probe", help="Check Python, paddle, paddleocr, models")
    sub.add_parser("download", help="Pull/verify models into paddle_ocr/models")
    sub.add_parser("smoke", help="PaddleOcr(sample) JSON gate")
    sub.add_parser("bench", help="Optional timing sample")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "probe":
        return cmd_probe()
    if args.command == "download":
        return cmd_download()
    if args.command == "smoke":
        return cmd_smoke()
    if args.command == "bench":
        return cmd_bench()
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    raise SystemExit(main())
