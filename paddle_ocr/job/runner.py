"""job.ocr.request list runner：BOOT 选模板，dispatch 调 callee，finally 只释放 Structure。"""

from __future__ import annotations

import copy
from typing import Any, Callable

from llm_lmstudio.models import is_model_loaded
from paddle_ocr import config
from paddle_ocr.gate.memory_guard import warn_if_structure_low_memory
from paddle_ocr.job.events import (
    DAEMON_OCR_ENSURE,
    DAEMON_STRUCTURE_ENSURE,
    DAEMON_STRUCTURE_RELEASE,
    INFER_OCR,
    INFER_STRUCTURE,
    JOB_DECODE,
    JOB_DETECT_LM,
    JOB_DETECT_TABLE,
    JOB_PICK_TEMPLATE,
    SCORE_LM_SIMILARITY,
    WHEN_ALWAYS,
    WHEN_FINALLY,
    WHEN_LM_LOADED,
    WHEN_NOT_FLUENT,
)
from paddle_ocr.job.templates import BOOT, TEMPLATES, pick_template_name
from paddle_ocr.mcp_runtime import ensure_ocr_mcp, start_structure_mcp, stop_structure_mcp
from paddle_ocr.runtime.image_decode import CropBoxError, ImageDecodeError, load_for_ocr
from paddle_ocr.runtime.table_grid import HasTableGrid
import paddle_ocr.main as ocr_main

PicInput = bytes | Any
Rectangle = tuple[int, int, int, int] | None
StatusCb = Callable[[str], None] | None
# 中文注释: 挂在终稿旁的对照袋；不得写进 engine_draft 副本里以免自引用
JOB_BAG_KEYS = frozenset({"engine_draft", "lm_draft", "lm_scores", "lm_adopted"})

_STATUS_KINDS = frozenset({
    DAEMON_OCR_ENSURE,
    INFER_OCR,
    DAEMON_STRUCTURE_ENSURE,
    INFER_STRUCTURE,
    SCORE_LM_SIMILARITY,
})


def _emit(ctx: dict[str, Any], kind: str) -> None:
    """
    函数名: _emit
    作用: 把事件 kind 交给 status_callback；BOOT 探测步骤不回调。
    输入:
        ctx (dict): job 上下文。
        kind (str): 事件 kind。
    输出: 无。
    """
    cb = ctx.get("status_cb")
    if cb is None:
        return
    if kind not in _STATUS_KINDS:
        return
    cb(kind)


def _should_run(event: dict[str, str], ctx: dict[str, Any]) -> bool:
    """
    函数名: _should_run
    作用: 按 when 决定本事件是否在主循环执行；finally 不在此跑；lm_loaded 才跑第 3 步。
    输入:
        event (dict): kind + 可选 when。
        ctx (dict): job 上下文（读 lm_loaded）。
    输出:
        bool: True=主循环应 dispatch。
    """
    when = str(event.get("when") or WHEN_ALWAYS)
    if when == WHEN_FINALLY:
        return False
    if when == WHEN_LM_LOADED:
        return bool(ctx.get("lm_loaded"))
    if when in (WHEN_NOT_FLUENT, "not fluent"):
        return not bool(ctx.get("fluent", True))
    return True


def _decode(ctx: dict[str, Any]) -> None:
    """
    函数名: _decode
    作用: 解码裁切写入 ctx['img']；失败则 job fail、不选模板。
    输入:
        ctx (dict): 含 pic / rectangle。
    输出: 无。
    """
    try:
        ctx["img"] = load_for_ocr(ctx["pic"], ctx["rectangle"])
    except CropBoxError:
        ctx["failed"] = True
        ctx["result"] = {"ok": False, "message": config.MSG_BAD_CROP, "mode": "fast", "engine": "ocr"}
    except (ImageDecodeError, Exception):
        ctx["failed"] = True
        ctx["result"] = {"ok": False, "message": config.MSG_BAD_IMAGE, "mode": "fast", "engine": "ocr"}


def _detect_table(ctx: dict[str, Any]) -> None:
    """
    函数名: _detect_table
    作用: HasTableGrid 启发式；图表 v1 视同有表。
    输入:
        ctx (dict): 含 img。
    输出: 无。
    """
    ctx["has_table"] = bool(HasTableGrid(ctx["img"]))


def _detect_lm(ctx: dict[str, Any]) -> None:
    """
    函数名: _detect_lm
    作用: 只查询 is_model_loaded；禁止 load_model。
    输入:
        ctx (dict): job 上下文。
    输出: 无。
    """
    try:
        ctx["lm_loaded"] = bool(is_model_loaded())
    except Exception:
        ctx["lm_loaded"] = False


def _pick_template(ctx: dict[str, Any]) -> None:
    """
    函数名: _pick_template
    作用: 只按 has_table 写入模板名；lm_loaded 留给 when=lm_loaded。
    输入:
        ctx (dict): BOOT 探测结果。
    输出: 无。
    """
    ctx["template"] = pick_template_name(bool(ctx.get("has_table")), bool(ctx.get("lm_loaded")))


def _remember_engine(ctx: dict[str, Any], payload: Any) -> None:
    """
    函数名: _remember_engine
    作用: 深拷贝 paddleocr-mcp 引擎草稿（PaddleOcr / PpStructure 实返回值）；后续 LM 不得覆盖这份副本。
    输入:
        ctx (dict): job 上下文。
        payload (dict|Any): 引擎 JSON。
    输出: 无。
    """
    if not isinstance(payload, dict):
        ctx["engine_draft"] = payload
        return
    # 中文注释: 去掉袋字段再拷贝，避免 engine_draft 嵌套自己
    ctx["engine_draft"] = copy.deepcopy({k: v for k, v in payload.items() if k not in JOB_BAG_KEYS})


def _attach_job_bag(ctx: dict[str, Any]) -> Any:
    """
    函数名: _attach_job_bag
    作用: 终稿旁挂 engine_draft / lm_draft / 分数 / 已采纳字段，UI 与测试可 diff；LM 未跑时 lm_* 为空。
    输入:
        ctx (dict): job 上下文。
    输出:
        dict|Any: 带对照袋的返回值；非 dict 原样返回。
    """
    result = ctx.get("result")
    if not isinstance(result, dict):
        return result
    out = {k: v for k, v in result.items() if k not in JOB_BAG_KEYS}
    engine = ctx.get("engine_draft")
    if engine is None:
        engine = copy.deepcopy(out)
    out["engine_draft"] = engine
    out["lm_draft"] = ctx.get("lm_draft")
    out["lm_scores"] = dict(ctx.get("lm_scores") or {})
    out["lm_adopted"] = list(ctx.get("lm_adopted") or [])
    return out


def _ensure_ocr(ctx: dict[str, Any]) -> None:
    """
    函数名: _ensure_ocr
    作用: 懒启动 PP-OCRv6 daemon（常驻）；不拉 Structure。
    输入:
        ctx (dict): job 上下文（本步不读写标志）。
    输出: 无。
    """
    ensure_ocr_mcp()


def _infer_ocr(ctx: dict[str, Any]) -> None:
    """
    函数名: _infer_ocr
    作用: 只调 PaddleOcr callee；不 judge、不 Structure。
    输入:
        ctx (dict): 含 pic / rectangle。
    输出: 无。
    """
    draft = ocr_main.PaddleOcr(ctx["pic"], ctx["rectangle"])
    ctx["draft"] = draft
    ctx["result"] = draft
    _remember_engine(ctx, draft)


def _ensure_structure(ctx: dict[str, Any]) -> None:
    """
    函数名: _ensure_structure
    作用: 仅本 job 拉起 Structure daemon；标记 structure_started 供 finally 释放。低内存只 warn，不分档。
    输入:
        ctx (dict): job 上下文。
    输出: 无。
    """
    ctx["structure_started"] = True
    # 中文注释: 低内存 Structure 只 warn，仍按事件表启动，不分档跳过
    warn_if_structure_low_memory()
    start_structure_mcp()


def _infer_structure(ctx: dict[str, Any]) -> None:
    """
    函数名: _infer_structure
    作用: 只调 PpStructure callee；写入 engine_draft 深拷贝；不调 OCR、不 score。
    输入:
        ctx (dict): 含 pic / rectangle。
    输出: 无。
    """
    structured = ocr_main.PpStructure(ctx["pic"], ctx["rectangle"])
    ctx["draft"] = structured
    ctx["result"] = structured
    _remember_engine(ctx, structured)


def _score_lm_similarity(ctx: dict[str, Any]) -> None:
    """
    函数名: _score_lm_similarity
    作用: 只调 lm_similarity_score；异常则 keep 引擎草稿，job 不失败；不改 engine_draft。
    输入:
        ctx (dict): 含 pic / rectangle / engine_draft。
    输出: 无。
    """
    engine = ctx.get("engine_draft")
    if not isinstance(engine, dict):
        result = ctx.get("result")
        engine = result if isinstance(result, dict) else {}
    try:
        scored = ocr_main.lm_similarity_score(ctx["pic"], ctx["rectangle"], engine)
    except Exception:
        ctx["lm_draft"] = None
        ctx["lm_scores"] = {}
        ctx["lm_adopted"] = []
        return
    if not isinstance(scored, dict):
        ctx["lm_draft"] = None
        ctx["lm_scores"] = {}
        ctx["lm_adopted"] = []
        return
    ctx["lm_draft"] = scored.get("lm_draft")
    ctx["lm_scores"] = dict(scored.get("lm_scores") or {})
    ctx["lm_adopted"] = list(scored.get("lm_adopted") or [])
    merged = scored.get("result")
    if isinstance(merged, dict):
        ctx["result"] = merged
        ctx["draft"] = merged


def _release_structure(ctx: dict[str, Any]) -> None:
    """
    函数名: _release_structure
    作用: 只停 Structure MCP；OCR 常驻不动。主循环不调用（when=finally）。
    输入:
        ctx (dict): job 上下文。
    输出: 无。
    """
    stop_structure_mcp()
    ctx["structure_started"] = False


DISPATCH: dict[str, Callable[[dict[str, Any]], None]] = {
    JOB_DECODE: _decode,
    JOB_DETECT_TABLE: _detect_table,
    JOB_DETECT_LM: _detect_lm,
    JOB_PICK_TEMPLATE: _pick_template,
    DAEMON_OCR_ENSURE: _ensure_ocr,
    INFER_OCR: _infer_ocr,
    DAEMON_STRUCTURE_ENSURE: _ensure_structure,
    INFER_STRUCTURE: _infer_structure,
    SCORE_LM_SIMILARITY: _score_lm_similarity,
    DAEMON_STRUCTURE_RELEASE: _release_structure,
}


def _run_event_list(ctx: dict[str, Any], events: list[dict[str, str]]) -> None:
    """
    函数名: _run_event_list
    作用: 按表 dispatch；when 不成立则跳过；callee 禁止再入队下一事件。
    输入:
        ctx (dict): job 上下文。
        events (list): 模板或 BOOT 事件表。
    输出: 无。
    """
    for event in events:
        if not _should_run(event, ctx):
            continue
        kind = str(event.get("kind") or "")
        handler = DISPATCH.get(kind)
        if handler is None:
            continue
        _emit(ctx, kind)
        handler(ctx)
        if ctx.get("failed"):
            return


def run_ocr_job(
    pic: PicInput,
    rectangle: Rectangle = None,
    status_callback: StatusCb = None,
) -> dict[str, Any]:
    """
    函数名: run_ocr_job
    作用: 处理 job.ocr.request：BOOT 后按模板跑事件表；Structure 在 finally 释放，从不 stop OCR。
    输入:
        pic (bytes|Path|str|ndarray): 图片。
        rectangle (tuple|None): OpenCV ROI (x, y, w, h)；None 表示整图。
        status_callback (Callable|None): 按事件 kind 字符串回调（无 Gemma）。
    输出:
        dict: OCR 或 Structure JSON，并带 engine_draft / lm_draft / lm_scores / lm_adopted；解码失败 ok=False。
    """
    ctx: dict[str, Any] = {
        "pic": pic,
        "rectangle": rectangle,
        "status_cb": status_callback,
        "img": None,
        "has_table": False,
        "lm_loaded": False,
        "template": None,
        "draft": None,
        "engine_draft": None,
        "lm_draft": None,
        "lm_scores": {},
        "lm_adopted": [],
        "fluent": True,
        "structure_started": False,
        "result": None,
        "failed": False,
    }
    try:
        # 中文注释: BOOT 解码 / 有表 / LM 是否已加载 / 选模板；失败不启动 daemon
        _run_event_list(ctx, BOOT)
        if ctx["failed"]:
            return _attach_job_bag(ctx)
        # 中文注释: runner 选模板并逐事件 invoke；when=finally 的 release 不在此循环
        template_events = TEMPLATES[ctx["template"]]
        _run_event_list(ctx, template_events)
        return _attach_job_bag(ctx)
    finally:
        # 中文注释: 本 job 若拉起过 Structure 则只 stop_structure_mcp；OCR 常驻
        if ctx.get("structure_started"):
            stop_structure_mcp()
