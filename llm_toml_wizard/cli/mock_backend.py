"""可脚本化的 LlmBackend：离线跑通 dialog 循环，不连接 LM Studio。"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from llm_lmstudio.backend import GenerateResult, HealthReport, SessionOptions


class ScriptedSession:
    """
    类名: ScriptedSession
    作用: 把 send_turn 转交给 ScriptedBackend 按 session_id 生成回复
    """

    def __init__(self, backend: "ScriptedBackend", session_id: str, thinking: bool) -> None:
        self._backend = backend
        self.session_id = session_id
        self.thinking = thinking
        self._closed = False

    def send_turn(self, message: Mapping[str, Any], *, max_output_tokens: int | None = None) -> GenerateResult:
        """
        函数名: send_turn
        作用: 记录调用并返回脚本回复
        输入:
            message (Mapping): 须含 content
            max_output_tokens (int | None): 忽略
        输出:
            GenerateResult: 文本回复
        """
        content = str(message.get("content") or "")
        return self._backend.script_reply(self.session_id, content, thinking=self.thinking)

    def close(self) -> None:
        """
        函数名: close
        作用: 标记会话关闭
        输入: 无
        输出: 无
        """
        self._closed = True

    @property
    def token_count(self) -> int:
        return 0


def _intake_status_map(content: str) -> dict[str, str]:
    """
    函数名: _intake_status_map
    作用: 从 toml decide 提示的 IntakePlan 段解析 key→status（忽略 catalog 正文）
    输入:
        content (str): 决策提示全文
    输出:
        dict[str, str]: intake key → pending/done/skip
    """
    statuses: dict[str, str] = {}
    chunk = content
    marker = "## IntakePlan"
    if marker in content:
        chunk = content.split(marker, 1)[-1]
        nxt = chunk.find("\n## ")
        if nxt >= 0:
            chunk = chunk[:nxt]
    for line in chunk.splitlines():
        text = line.strip()
        if not text.startswith("- ") or ":" not in text:
            continue
        rest = text[2:]
        key, after = rest.split(":", 1)
        key = key.strip()
        status = after.strip().split()[0] if after.strip() else ""
        if key and status:
            statuses[key] = status
    return statuses



class ScriptedBackend:
    """
    类名: ScriptedBackend
    作用: 不加载权重的后端；用于展示/测试 dialog 运行时
    """

    def __init__(self, *, force_thinking_retry: bool = False) -> None:
        self.force_thinking_retry = force_thinking_retry
        self.calls: list[dict[str, Any]] = []

    def health_check(self) -> HealthReport:
        """
        函数名: health_check
        作用: 返回 mock 健康报告（不探测硬件）
        输入: 无
        输出:
            HealthReport: profile=cpu
        """
        return HealthReport(
            ok=True,
            profile="cpu",
            litert_backend="cpu",
            mtp=False,
            model_path="(scripted)",
            message="scripted backend",
        )

    def warm(self) -> None:
        """
        函数名: warm
        作用: mock 空操作
        输入: 无
        输出: 无
        """
        return None

    def close(self) -> None:
        """
        函数名: close
        作用: mock 空操作
        输入: 无
        输出: 无
        """
        return None

    def generate(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        thinking: bool = False,
        max_tokens: int | None = None,
        temperature: float = 0.0,
        judgment_tool=None,
    ) -> GenerateResult:
        """
        函数名: generate
        作用: 无状态脚本回复
        输入:
            messages: 对话消息
            thinking / max_tokens / temperature / judgment_tool: 记录用
        输出:
            GenerateResult
        """
        content = ""
        if messages:
            content = str(messages[-1].get("content") or "")
        return self.script_reply("generate", content, thinking=thinking)

    def generate_vision(
        self,
        image,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> GenerateResult:
        """
        函数名: generate_vision
        作用: 返回占位视觉文本
        输入:
            image: 忽略
            prompt (str): 提示
        输出:
            GenerateResult
        """
        return GenerateResult(text=f"(scripted vision) {prompt[:80]}")

    def open_session(self, session_id: str, *, options: SessionOptions | None = None) -> ScriptedSession:
        """
        函数名: open_session
        作用: 打开脚本会话
        输入:
            session_id (str): 会话 id
            options (SessionOptions | None): 含 thinking 标志
        输出:
            ScriptedSession
        """
        thinking = bool(options.thinking) if options is not None else False
        return ScriptedSession(self, session_id, thinking)

    def script_reply(self, session_id: str, content: str, *, thinking: bool) -> GenerateResult:
        """
        函数名: script_reply
        作用: 按 session 前缀生成可解析的 JSON / 综合文本
        输入:
            session_id (str): 会话 id
            content (str): 用户正文
            thinking (bool): 是否 thinking 会话
        输出:
            GenerateResult
        """
        self.calls.append({"session_id": session_id, "thinking": thinking, "chars": len(content)})
        if session_id.startswith("dialog_decision_") or session_id.startswith("wizard_decision_"):
            text = self._decision_json(content)
        elif session_id in ("dialog_main", "wizard_main"):
            text = self._main_reply(content)
        elif "determiner" in session_id:
            text = "**Determiners**: [\\t, \\n]\\n\\n**Cleaned String**: `LotID\\t10034\\tProduct\\tGinger\\tQty\\t12`"
        elif "_pass1" in session_id and self.force_thinking_retry and not thinking:
            text = "not-json (force pass2)"
        elif "extract_points" in session_id:
            text = (
                '{"items":['
                '{"point":"上线支付回调并对账失败发邮件","complete":false},'
                '{"point":"给值班同学一份检查清单","complete":true}'
                "]}"
            )
        elif "gap_check" in session_id:
            text = '{"gaps":["收件人未指定","重试次数未指定","是否覆盖退款未说明"]}'
        elif session_id.startswith("field_") or "ghost_" in session_id or "sheet_" in session_id:
            text = '{"index": 1, "match_type": "exact", "column_name": "LotID", "reason": "scripted"}'
        elif "regex_" in session_id:
            text = '{"regex": "(\\\\d+)", "reason": "scripted"}'
        else:
            text = '{"ok":true,"note":"scripted"}'
        thought = "retry with structure" if thinking else None
        return GenerateResult(text=text, thought=thought)

    def _decision_json(self, content: str) -> str:
        lower = content.lower()
        if "capture_sources" in lower and "finalize_toml" in lower:
            return self._toml_decision_json(content)
        if "summary_ready" in lower and "true" in content.split("## summary_ready")[-1][:20].lower():
            return '{"next_action":"finalize","action_id":"finish","reason":"scripted finish"}'
        if "artifacts" in lower and "(none)" not in content.split("## artifacts")[-1][:40]:
            if "extract_points" in content or "gap_check" in content:
                return '{"next_action":"compute","action_id":"synthesize","reason":"scripted synthesize"}'
        if "captured keys" in lower and "material" in content:
            return '{"next_action":"compute","action_id":"dispatch_subagents","reason":"scripted dispatch"}'
        if "intake list missing" in lower or "(none)" in content.split("## Intake")[-1][:20]:
            return '{"next_action":"compute","action_id":"plan_intake","reason":"scripted plan"}'
        return '{"next_action":"ask_user","action_id":"ask_user","reason":"scripted ask"}'


    def _toml_decision_json(self, content: str) -> str:
        """
        函数名: _toml_decision_json
        作用: 按 IntakePlan 状态给出可解析的 TOML 九动作决策（非 stub 时）
        输入:
            content (str): decide 提示全文
        输出:
            str: JSON 文本
        """
        status = _intake_status_map(content)
        order = (
            ("data_sources", "ask_user", "capture_sources", "scripted sources"),
            ("input_section", "ask_user", "capture_layout", "scripted layout"),
            ("ghost_sample", "ask_user", "capture_sample", "scripted sample"),
            ("ghost_preprocess", "compute", "preprocess_sample", "scripted preprocess"),
            ("field_match", "compute", "match_ghost_fields", "scripted ghost"),
            ("sheet_match", "compute", "match_sheet_columns", "scripted sheet"),
            ("regex_infer", "compute", "infer_regex", "scripted regex"),
            ("db_id", "ask_user", "finalize_toml", "scripted db_id"),
        )
        for key, next_action, action_id, reason in order:
            if status.get(key, "pending") == "pending":
                return (
                    '{"next_action":"' + next_action + '","action_id":"'
                    + action_id + '","reason":"' + reason + '"}'
                )
        return '{"next_action":"finalize","action_id":"finalize_toml","reason":"scripted finalize"}'


    def _main_reply(self, content: str) -> str:
        if "needs" in content and "JSON" in content:
            return (
                '{"needs":['
                '{"key":"material","question":"请贴上材料原文","required":true},'
                '{"key":"constraints","question":"有哪些约束？","required":true}'
                "]}"
            )
        return "【脚本综合】要点已抽出；缺收件人、重试次数与退款覆盖范围。请业务方补齐后再上线。"
