"""run_ocr_job: image -> OCR or PP-StructureV3, optional LM similarity scoring.

Compressed from paddle_ocr/job/{runner,events,templates}.py into one module.
No threading lock, no daemon, no Gemma full-page correction.
LM scoring is optional: caller injects vision_fn; if None, scoring is skipped.
"""

from __future__ import annotations

import copy
from typing import Any, Callable

from paddleocr_mcp_controller import config
from paddleocr_mcp_controller.image_decode import (
    CropBoxError,
    ImageDecodeError,
    load_for_ocr,
)
from paddleocr_mcp_controller.lm_similarity import VisionFn, lm_similarity_score
from paddleocr_mcp_controller.mcp_runtime import (
    call_ocr_mcp,
    call_structure_mcp,
    ensure_ocr_mcp,
    start_structure_mcp,
    stop_structure_mcp,
)
from paddleocr_mcp_controller.table_grid import HasTableGrid


PicInput = bytes | Any
Rectangle = tuple[int, int, int, int] | None
StatusCb = Callable[[str], None] | None

JOB_BAG_KEYS = frozenset({"engine_draft", "lm_draft", "lm_scores", "lm_adopted"})

# 中文注释: 状态 kind 常量（与原 paddle_ocr.job.events 对齐，方便 UI 复用）
JOB_DECODE = "job.decode"
JOB_DETECT_TABLE = "job.detect_table"
DAEMON_OCR_ENSURE = "daemon.ocr.ensure"
INFER_OCR = "infer.ocr"
DAEMON_STRUCTURE_ENSURE = "daemon.structure.ensure"
INFER_STRUCTURE = "infer.structure"
SCORE_LM_SIMILARITY = "score.lm_similarity"

_STATUS_KINDS = frozenset({
    DAEMON_OCR_ENSURE,
    INFER_OCR,
    DAEMON_STRUCTURE_ENSURE,
    INFER_STRUCTURE,
    SCORE_LM_SIMILARITY,
})

# 中文注释: UI 进度文案表；与原 paddle_ocr.job.events.STATUS_HINTS 对齐
STATUS_HINTS = {
    DAEMON_OCR_ENSURE: "正在启动 OCR 引擎…",
    INFER_OCR: "文字识别",
    DAEMON_STRUCTURE_ENSURE: "版面/表格识别",
    INFER_STRUCTURE: "版面/表格识别",
    SCORE_LM_SIMILARITY: "多模态校对",
}


def _emit(status_cb: StatusCb, kind: str) -> None:
    """forward kind to status_callback if it is a status kind."""
    if status_cb is None or kind not in _STATUS_KINDS:
        return
    status_cb(kind)


def _remember_engine(payload: Any) -> Any:
    """deep copy engine draft (PaddleOcr / PpStructure return); strip bag fields."""
    if not isinstance(payload, dict):
        return payload
    return copy.deepcopy({k: v for k, v in payload.items() if k not in JOB_BAG_KEYS})


def _attach_job_bag(
    result: Any,
    *,
    engine_draft: Any,
    lm_draft: Any,
    lm_scores: dict[str, int],
    lm_adopted: list[str],
) -> Any:
    """attach engine_draft / lm_draft / scores / adopted to the final result."""
    if not isinstance(result, dict):
        return result
    out = {k: v for k, v in result.items() if k not in JOB_BAG_KEYS}
    engine = engine_draft if engine_draft is not None else copy.deepcopy(out)
    out["engine_draft"] = engine
    out["lm_draft"] = lm_draft
    out["lm_scores"] = dict(lm_scores or {})
    out["lm_adopted"] = list(lm_adopted or [])
    return out


def run_ocr_job(
    pic: PicInput,
    rectangle: Rectangle = None,
    status_callback: StatusCb = None,
    *,
    vision_fn: VisionFn | None = None,
) -> dict[str, Any]:
    """
    函数名: run_ocr_job
    作用: 处理一张图：解码 -> HasTableGrid 路由 -> PaddleOcr 或 PpStructure；
        若 vision_fn 不为 None 则跑 LM 相似度校对（分低于阈值才采纳 proposed）。
        Structure 子进程在本 job 结束时停止；OCR 子进程按需懒启动。
    输入:
        pic (bytes|Path|str|ndarray): 图片。
        rectangle (tuple|None): OpenCV ROI (x, y, w, h)；None 表示整图。
        status_callback (Callable|None): 按事件 kind 字符串回调。
        vision_fn (VisionFn|None): (image_bytes, prompt, system) -> str；None 跳过 LM 校对。
    输出:
        dict: OCR 或 Structure JSON，并带 engine_draft / lm_draft / lm_scores / lm_adopted；
            解码失败 ok=False。
    """
    # 中文注释: 1) 解码裁切
    _emit(status_callback, JOB_DECODE)
    try:
        img = load_for_ocr(pic, rectangle)
    except CropBoxError:
        return _attach_job_bag(
            {"ok": False, "message": config.MSG_BAD_CROP, "mode": "fast", "engine": "ocr"},
            engine_draft=None, lm_draft=None, lm_scores={}, lm_adopted=[],
        )
    except (ImageDecodeError, Exception):
        return _attach_job_bag(
            {"ok": False, "message": config.MSG_BAD_IMAGE, "mode": "fast", "engine": "ocr"},
            engine_draft=None, lm_draft=None, lm_scores={}, lm_adopted=[],
        )
    # 中文注释: 2) 表格启发式路由
    _emit(status_callback, JOB_DETECT_TABLE)
    has_table = bool(HasTableGrid(img))
    structure_started = False
    result: dict[str, Any] = {}
    engine_draft: Any = None
    lm_draft: Any = None
    lm_scores: dict[str, int] = {}
    lm_adopted: list[str] = []
    try:
        if has_table:
            # 中文注释: 有表 -> PP-StructureV3
            _emit(status_callback, DAEMON_STRUCTURE_ENSURE)
            if not start_structure_mcp():
                return _attach_job_bag(
                    {"ok": False, "message": config.MSG_NOT_READY, "mode": "structure", "engine": "structure"},
                    engine_draft=None, lm_draft=None, lm_scores={}, lm_adopted=[],
                )
            structure_started = True
            _emit(status_callback, INFER_STRUCTURE)
            result = call_structure_mcp(img, mode="structure")
        else:
            # 中文注释: 无表 -> PP-OCRv6
            _emit(status_callback, DAEMON_OCR_ENSURE)
            if not ensure_ocr_mcp():
                return _attach_job_bag(
                    {"ok": False, "message": config.MSG_NOT_READY, "mode": "fast", "engine": "ocr"},
                    engine_draft=None, lm_draft=None, lm_scores={}, lm_adopted=[],
                )
            _emit(status_callback, INFER_OCR)
            result = call_ocr_mcp(img)
        engine_draft = _remember_engine(result)
        # 中文注释: 3) LM 相似度校对（可选）
        if vision_fn is not None and isinstance(engine_draft, dict):
            _emit(status_callback, SCORE_LM_SIMILARITY)
            scored = lm_similarity_score(pic, rectangle, engine_draft, vision_fn=vision_fn)
            if isinstance(scored, dict):
                lm_draft = scored.get("lm_draft")
                lm_scores = dict(scored.get("lm_scores") or {})
                lm_adopted = list(scored.get("lm_adopted") or [])
                merged = scored.get("result")
                if isinstance(merged, dict):
                    result = merged
        return _attach_job_bag(
            result,
            engine_draft=engine_draft,
            lm_draft=lm_draft,
            lm_scores=lm_scores,
            lm_adopted=lm_adopted,
        )
    finally:
        # 中文注释: 本 job 若拉起过 Structure 则只 stop_structure_mcp；OCR 按需懒启动
        if structure_started:
            stop_structure_mcp()
