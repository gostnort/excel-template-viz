"""步骤 7：试跑样本拆分并写盘 sidecar TOML。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import tomlkit

from app.core_connect import _apply_regex
from app.core_split import indexed_dict_to_parts, is_brace_json, json_to_indexed_dict, split_by_determiner
from app.core_toml import _config_from_dict, verify_toml
from llm_gemma4.wizard.state import WizardState
from llm_gemma4.wizard.toml_patcher import generate_toml, persist_wizard_toml


def _parts_from_sample(cfg: Any, state: WizardState) -> tuple[list[str] | None, str | None]:
    """
    函数名: _parts_from_sample
    作用: 从 ghost 样本按与向导相同的规则拆分为段列表
    输入:
        cfg (Any): 解析后的 TOML 配置
        state (WizardState): 向导状态
    输出:
        tuple[list[str] | None, str | None]: (段列表, 错误信息)
    """
    raw = state.normalized_sample or state.ghost_text_sample
    if state.indexed_segments:
        return indexed_dict_to_parts(state.indexed_segments), None
    if is_brace_json(raw):
        indexed = json_to_indexed_dict(raw)
        return indexed_dict_to_parts(indexed), None
    try:
        parts = split_by_determiner(raw, cfg.determiner)
    except Exception as exc:
        return None, str(exc)
    return parts, None


def _extract_from_sample(cfg: Any, state: WizardState) -> tuple[dict[str, Any] | None, str | None]:
    parts, split_err = _parts_from_sample(cfg, state)
    if split_err:
        return None, split_err
    if parts is None:
        return None, "failed to split sample"
    fields: dict[str, Any] = {}
    max_index = max((rule.index for rule in cfg.field_rules if rule.index >= 0), default=-1)
    if max_index >= 0 and len(parts) <= max_index:
        return None, f"split into {len(parts)} part(s), need at least {max_index + 1}"
    for rule in cfg.field_rules:
        if rule.index < 0:
            continue
        try:
            fields[rule.Input_label] = _apply_regex(parts[rule.index], rule.regex)
        except IndexError:
            return None, f"{rule.Input_label}: index {rule.index} out of range"
    for label, fs in state.fields.items():
        if fs.needs_regex and fs.regex:
            haystack = state.ghost_text_sample
            if state.indexed_segments:
                haystack = "\n".join(
                    f"{k}: {v}" for k, v in sorted(state.indexed_segments.items())
                )
            try:
                match = re.search(fs.regex, haystack)
                if match:
                    fields[label] = match.group(1) if match.lastindex else match.group(0)
            except re.error:
                pass
    return fields, None


def run_trial(state: WizardState, template_path: Path | None) -> dict[str, Any]:
    """
    函数名: run_trial
    作用: 用生成的 TOML 对 ghost 样本试跑拆分并收集 mismatch
    输入:
        state (WizardState): 向导状态
        template_path (Path | None): 模板 xlsx 路径
    输出:
        dict: {ok, mismatches, structural_errors}
    """
    mismatches: list[dict[str, str]] = []
    structural: list[str] = []
    toml_str = generate_toml(state)
    try:
        raw_dict = dict(tomlkit.loads(toml_str))
    except Exception as exc:
        return {"ok": False, "mismatches": [], "structural_errors": [str(exc)]}
    cfg = _config_from_dict(raw_dict)
    if cfg is None:
        return {"ok": False, "mismatches": [], "structural_errors": ["TOML structure invalid"]}
    if template_path and template_path.is_file():
        report = verify_toml(template_path, cfg)
        if not report.get("ok"):
            structural.extend(report.get("errors") or [])
            for key in ("missing_labels", "duplicate_labels", "out_of_area_labels"):
                for item in report.get(key) or []:
                    structural.append(f"{key}: {item}")
    sample = state.ghost_text_sample.strip()
    if not sample:
        structural.append("ghost sample is empty")
        return {"ok": False, "mismatches": mismatches, "structural_errors": structural}
    extracted, split_err = _extract_from_sample(cfg, state)
    if split_err:
        structural.append(split_err)
        return {"ok": False, "mismatches": mismatches, "structural_errors": structural}
    for label, fs in state.fields.items():
        if fs.error:
            mismatches.append({"label": label, "expected": "no error", "got": fs.error})
            continue
        if fs.match_type == "none" and not fs.needs_regex and not fs.column_name:
            continue
        if fs.index < 0 and not fs.column_name and not fs.needs_regex:
            continue
        val = extracted.get(label) if extracted else None
        if val is None or str(val).strip() == "":
            mismatches.append({"label": label, "expected": "non-empty value", "got": str(val)})
    ok = not structural and not mismatches
    return {"ok": ok, "mismatches": mismatches, "structural_errors": structural}


def run_trial_and_write(
    state: WizardState,
    template_id: str,
    template_path: Path | None,
) -> dict[str, Any]:
    """
    函数名: run_trial_and_write
    作用: 试跑通过后写入 templates/{id}/{id}.toml
    输入:
        state (WizardState): 向导状态
        template_id (str): 模板 ID
        template_path (Path | None): xlsx 路径（verify 用）
    输出:
        dict: 试跑报告 + written_path
    """
    report = run_trial(state, template_path)
    if not report.get("ok"):
        return report
    if not template_id:
        report["structural_errors"] = list(report.get("structural_errors") or []) + ["missing template_id"]
        report["ok"] = False
        return report
    path = persist_wizard_toml(state, template_id)
    report["written_path"] = str(path)
    return report
