"""超集正则归纳：符号快速轨，以及 gemma-4-e4b 沙箱闭环。"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from geodesic_align.digit_processor import TableView


if TYPE_CHECKING:
    from geodesic_align.emit_mapping import MappingDecision


_SUPERSET_SENTINELS = frozenset({"N/A", "暂无", "-", "null"})



@dataclass(frozen=True)
class LineageSample:
    """拓扑行指针锚定的 (源文本, 目标字面) 有效配对样本。"""

    dest_row_idx: int
    source_row_idx: int
    source_text: str
    target_value: str



@dataclass(frozen=True)
class RegexCandidate:
    """通过编译与结构校验的正则表达式候选。"""

    pattern: str
    capture_group: int = 1
    source_key: str = ""
    source_field: str = ""
    origin: Literal["symbolic", "gemma4_verified"] = "symbolic"



@dataclass
class ValidationReport:
    """本地沙箱 100% 全量回测结果报告。"""

    is_valid: bool
    total_samples: int
    matched_samples: int
    mismatches: list[tuple[LineageSample, str]]
    latency_ms: float



def detect_superset_columns(
    dest: TableView,
    sources: list[TableView],
    lineage: list[list[tuple[str, int]]],
    target_label: str,
) -> list[tuple[TableView, str, list[LineageSample]]]:
    """
    函数名: detect_superset_columns
    作用: 找出目标字面恒为源列连续子串的 (源表, 源列, 样本) 组合
    输入:
        dest (TableView): 模板表
        sources (list[TableView]): 源表池
        lineage (list[list[tuple[str, int]]]): 每行的 (source_key, 源行号) 指针
        target_label (str): 模板列名
    输出:
        list[tuple[TableView, str, list[LineageSample]]]: 超集成立且至少两条有效样本的列
    """
    candidates: list[tuple[TableView, str, list[LineageSample]]] = []
    for table in sources:
        for src_label in table.headers:
            samples: list[LineageSample] = []
            superset_holds = True
            # 中文注释: 沿拓扑指针逐行核对，禁止按物理行号硬对齐
            for d_idx, row in enumerate(dest.rows):
                dest_val = str(row.get(target_label) or "").strip()
                if not dest_val or dest_val in _SUPERSET_SENTINELS:
                    continue
                target = dest_val[1:] if dest_val.startswith("#") else dest_val
                hits = [hit for hit in lineage[d_idx] if hit[0] == table.source_key] if d_idx < len(lineage) else []
                if not hits:
                    superset_holds = False
                    break
                src_row_idx = hits[0][1]
                if src_row_idx >= len(table.rows):
                    superset_holds = False
                    break
                src_text = str(table.rows[src_row_idx].get(src_label) or "")
                if target not in src_text:
                    superset_holds = False
                    break
                samples.append(LineageSample(d_idx, src_row_idx, src_text, target))
            if superset_holds and len(samples) >= 2:
                candidates.append((table, src_label, samples))
    return candidates



def _core_token(samples: list[LineageSample]) -> str:
    """
    函数名: _core_token
    作用: 按目标字面的字符集选择唯一捕获组，避免无边界的 (.*)
    输入:
        samples (list[LineageSample]): 已确认的超集样本
    输出:
        str: 带一对圆括号的捕获组
    """
    all_targets = "".join(item.target_value for item in samples)
    if all_targets.isdigit():
        return r"(\d+)"
    if re.fullmatch(r"[A-Za-z0-9_#-]+", all_targets):
        return r"([A-Za-z0-9_#-]+)"
    return r"([^,\s\]\}\)\>]+)"



def symbolic_anchored_synthesizer(samples: list[LineageSample]) -> str | None:
    """
    函数名: symbolic_anchored_synthesizer
    作用: 用目标前后 24 字的公共锚点合成正则，并要求全量样本闭环
    输入:
        samples (list[LineageSample]): (源文本, 目标字面) 样本
    输出:
        str | None: 沙箱通过的模式；否则放弃
    """
    if not samples:
        return None
    prefixes: list[str] = []
    suffixes: list[str] = []
    for item in samples:
        pos = item.source_text.find(item.target_value)
        prefixes.append(item.source_text[max(0, pos - 24):pos])
        end_pos = pos + len(item.target_value)
        suffixes.append(item.source_text[end_pos:min(len(item.source_text), end_pos + 24)])
    core_token = _core_token(samples)
    candidates: list[str] = []
    # 中文注释: 具名引导词，例如 SensorRef: / Code#
    word_anchors: list[str] = []
    for prefix in prefixes:
        matched = re.search(r"([A-Za-z0-9_]+[:#=\-]|\[[A-Za-z0-9_]+[:\s])\s*$", prefix)
        if matched:
            word_anchors.append(matched.group(1).strip())
    if len(word_anchors) == len(samples) and len(set(word_anchors)) == 1:
        candidates.append(re.escape(word_anchors[0]) + r"\s*" + core_token)
    # 中文注释: 成对定界符，左右括号本身必须 re.escape
    for left, right in (("[", "]"), ("(", ")"), ("<", ">"), ("{", "}")):
        if all(prefix.rstrip().endswith(left) for prefix in prefixes) and all(suffix.lstrip().startswith(right) for suffix in suffixes):
            candidates.append(re.escape(left) + r"\s*" + core_token + r"\s*" + re.escape(right))
    # 中文注释: 常见分隔标点，模式本身已是正则，不再 escape
    for sep in (r":\s*", r"#\s*", r"-\s*", r"\s+"):
        if all(re.search(sep + r"$", prefix) for prefix in prefixes):
            candidates.append(sep + core_token)
    candidates.append(rf"\b{core_token}\b")
    for pattern in candidates:
        report = verify_regex_across_lineage(pattern, samples)
        if report.is_valid:
            return pattern
    return None



def verify_regex_across_lineage(
    pattern: str,
    samples: list[LineageSample],
    timeout_ms: float = 200.0,
) -> ValidationReport:
    """
    函数名: verify_regex_across_lineage
    作用: 用本地 re 对全部行指针样本回测，超时或捕获组不对即作废
    输入:
        pattern (str): 待测正则，必须含至少一组捕获
        samples (list[LineageSample]): 全量样本，不只是送进提示词的三条
        timeout_ms (float): 累计耗时上限，默认 200 毫秒
    输出:
        ValidationReport: 是否全量命中、反例与耗时
    """
    t0 = time.perf_counter()
    try:
        compiled = re.compile(pattern)
    except re.error:
        return ValidationReport(False, len(samples), 0, [], 0.0)
    if compiled.groups < 1:
        return ValidationReport(False, len(samples), 0, [], 0.0)
    mismatches: list[tuple[LineageSample, str]] = []
    matched_count = 0
    for item in samples:
        if (time.perf_counter() - t0) * 1000 > timeout_ms:
            return ValidationReport(False, len(samples), matched_count, mismatches, timeout_ms)
        found = compiled.search(item.source_text)
        if found is None:
            mismatches.append((item, "<NO_MATCH>"))
            continue
        captured = found.group(1)
        if captured is None:
            mismatches.append((item, "<NO_MATCH>"))
            continue
        got = captured.strip()
        if got != item.target_value:
            mismatches.append((item, got))
            continue
        matched_count += 1
    latency = (time.perf_counter() - t0) * 1000
    is_valid = matched_count == len(samples) and len(mismatches) == 0
    return ValidationReport(is_valid, len(samples), matched_count, mismatches, latency)



def _clean_gemma_regex_output(raw_text: str) -> str:
    """
    函数名: _clean_gemma_regex_output
    作用: 去掉 Gemma 4 E4B 附带的代码块、前缀和引号，只留一行正则
    输入:
        raw_text (str): 模型原文
    输出:
        str: 单行模式；空串表示没抽出
    """
    text = raw_text.strip()
    text = re.sub(r"</?turn.*?>", "", text, flags=re.IGNORECASE)
    block_match = re.search(r"```(?:regex|python)?\s*([\s\S]*?)(?:```|$)", text)
    if block_match and block_match.group(1).strip():
        text = block_match.group(1).strip()
    text = re.sub(r"^(?:PATTERN|REGEX|正则)\s*[:=]\s*", "", text, flags=re.IGNORECASE)
    text = text.strip().strip("'\"`")
    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("```")]
    return lines[0] if lines else ""



def _select_few_shots(samples: list[LineageSample]) -> list[LineageSample]:
    """
    函数名: _select_few_shots
    作用: 只留最长、最短、含特殊符号三条，避免把整表灌进 4B 上下文
    输入:
        samples (list[LineageSample]): 全量超集样本
    输出:
        list[LineageSample]: 至多 3 条
    """
    if len(samples) <= 3:
        return list(samples)
    ranked = sorted(samples, key=lambda item: (len(item.source_text), item.dest_row_idx))
    shortest = ranked[0]
    longest = ranked[-1]
    special: LineageSample | None = None
    for item in samples:
        if item == shortest or item == longest:
            continue
        if re.search(r"[^\w\s]", item.source_text):
            special = item
            break
    chosen: list[LineageSample] = []
    for item in (longest, shortest, special):
        if item is None or item in chosen:
            continue
        chosen.append(item)
    if len(chosen) < 3:
        for item in samples:
            if item not in chosen:
                chosen.append(item)
            if len(chosen) >= 3:
                break
    return chosen[:3]



def is_lm_studio_ready() -> bool:
    """
    函数名: is_lm_studio_ready
    作用: 确认 LM Studio 在线，且 user.toml 里的 gemma-4-e4b 已加载
    输入: 无
    输出:
        bool: 可以调用神经轨时为 True
    """
    try:
        from llm_lmstudio import get_backend
        health = get_backend().health_check()
    except Exception:
        return False
    if not getattr(health, "ok", False):
        return False
    model = str(getattr(health, "model", "") or "").lower()
    if "gemma-4-e4b" not in model:
        return False
    if str(getattr(health, "message", "") or "") == "model not loaded":
        return False
    return True



def gemma4_e4b_synthesizer(
    samples: list[LineageSample],
    max_retries: int = 3,
) -> str | None:
    """
    函数名: gemma4_e4b_synthesizer
    作用: 用本地 gemma-4-e4b 出一条单捕获组正则，再由沙箱对全量样本回测
    输入:
        samples (list[LineageSample]): 全量样本；提示词只用其中至多 3 条
        max_retries (int): 含首次在内的尝试次数，默认 3
    输出:
        str | None: 沙箱 100% 通过的模式；探活失败或重试耗尽则为 None
    """
    from llm_lmstudio import conversation_once
    # 中文注释: 未连接或模型未加载时立刻降级，不阻塞映射流水线
    if not is_lm_studio_ready():
        return None
    few_shots = _select_few_shots(samples)
    reflection_note = ""
    for _attempt in range(max_retries):
        prompt_lines = [
            "You are a regex generator. Given Source strings and Expected target values, produce a Python regex with EXACTLY ONE capture group () that extracts the target.",
            "Rules:",
            "1. Output ONLY the regex inside ```regex ... ``` block. No explanation.",
            "2. The target must be captured inside parentheses (), e.g. anchor\\s+([A-Za-z0-9_-]+).",
            "3. Do not use lookaround or non-capturing groups. Put the target in group 1.",
            "",
            "Demonstration:",
            'Example input: "Status code: ERR-404 in system" -> Expected: "ERR-404"',
            "Regex:",
            "```regex",
            r"code:\s+([A-Za-z0-9_-]+)",
            "```",
            "",
            "Examples for your task:",
        ]
        for item in few_shots:
            prompt_lines.append(f'Source: "{item.source_text}" -> Target: "{item.target_value}"')
        if reflection_note:
            prompt_lines.append("")
            prompt_lines.append(f"Correction Notice: {reflection_note}")
        prompt_lines.append("\nGenerate regex:")
        full_prompt = "\n".join(prompt_lines)
        try:
            # 中文注释: 4B 关闭发散思考，温度压到 0
            resp = conversation_once(
                full_prompt,
                system="You are an expert PCRE regular expression synthesizer. Reply only with the regex.",
                thinking=False,
                temperature=0.0,
            )
        except Exception:
            return None
        candidate_pattern = _clean_gemma_regex_output(resp)
        if not candidate_pattern:
            reflection_note = "Your previous output did not contain a valid single-line regex."
            continue
        report = verify_regex_across_lineage(candidate_pattern, samples)
        if report.is_valid:
            return candidate_pattern
        if not report.mismatches:
            reflection_note = "Pattern was rejected by the sandbox before any capture."
            continue
        bad_sample, actual_extracted = report.mismatches[0]
        reflection_note = (
            f"Pattern '{candidate_pattern}' failed on \"{bad_sample.source_text}\". "
            f"It extracted \"{actual_extracted}\", but expected was \"{bad_sample.target_value}\"."
        )
    return None



def deduce_regex_mapping(
    dest: TableView,
    sources: list[TableView],
    lineage: list[list[tuple[str, int]]],
    decision: MappingDecision,
) -> MappingDecision:
    """
    函数名: deduce_regex_mapping
    作用: 先走符号轨，失败再问 gemma-4-e4b；两条都不闭环则保持手工输入
    输入:
        dest (TableView): 模板表
        sources (list[TableView]): 源表池
        lineage (list[list[tuple[str, int]]]): 行指针
        decision (MappingDecision): 当前列判定，仅 cell_role 为 input 时尝试
    输出:
        MappingDecision: 闭环成功时 cell_role 改为 regex，否则原样返回并记下未解析
    """
    if decision.cell_role != "input":
        return decision
    superset_list = detect_superset_columns(dest, sources, lineage, decision.input_label)
    if not superset_list:
        return decision
    for table, src_field, samples in superset_list:
        pattern = symbolic_anchored_synthesizer(samples)
        origin: Literal["symbolic", "gemma4_verified"] = "symbolic"
        if pattern is None:
            pattern = gemma4_e4b_synthesizer(samples)
            origin = "gemma4_verified"
        if pattern is None:
            continue
        picked = RegexCandidate(
            pattern=pattern,
            capture_group=1,
            source_key=table.source_key,
            source_field=src_field,
            origin=origin,
        )
        decision.cell_role = "regex"
        decision.source = picked.source_key
        decision.field = picked.source_field
        decision.regex = picked.pattern
        decision.klass = "regex"
        decision.confidence = 1.0 if picked.origin == "symbolic" else 0.95
        return decision
    decision.warnings.append("regex_unresolved:")
    return decision
