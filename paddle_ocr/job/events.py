"""job.ocr.request 事件 kind 常量；kind 与 callee 函数名不必相同。"""

from __future__ import annotations

# job.ocr.request BOOT
JOB_OCR_REQUEST = "job.ocr.request"
JOB_DECODE = "job.decode"
JOB_DETECT_TABLE = "job.detect_table"
JOB_DETECT_LM = "job.detect_lm"
JOB_PICK_TEMPLATE = "job.pick_template"

# 模板步骤
DAEMON_OCR_ENSURE = "daemon.ocr.ensure"
INFER_OCR = "infer.ocr"
JUDGE_SEMANTIC = "judge.semantic"
DAEMON_STRUCTURE_ENSURE = "daemon.structure.ensure"
INFER_STRUCTURE = "infer.structure"
SCORE_LM_SIMILARITY = "score.lm_similarity"
DAEMON_STRUCTURE_RELEASE = "daemon.structure.release"

# when 缺省 always；lm_loaded 才跑第 3 步；finally 在 runner finally
WHEN_ALWAYS = "always"
WHEN_NOT_FLUENT = "not_fluent"
WHEN_LM_LOADED = "lm_loaded"
WHEN_FINALLY = "finally"

# T8/T10 按 kind 拼 UI 文案；无 Gemma 整页纠错
STATUS_HINTS = {
    DAEMON_OCR_ENSURE: "正在启动 OCR 引擎…",
    INFER_OCR: "文字识别",
    DAEMON_STRUCTURE_ENSURE: "版面/表格识别",
    INFER_STRUCTURE: "版面/表格识别",
    SCORE_LM_SIMILARITY: "多模态校对",
}
