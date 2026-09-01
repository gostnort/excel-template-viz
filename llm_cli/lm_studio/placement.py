"""两套及以上权重同时加载时，用 decode 速度对照 DRAM 带宽估指定模型在 VRAM 还是 CPU RAM。"""

from __future__ import annotations

import json
import subprocess
import time
from typing import Any

from llm_cli.lm_studio.complete import complete
from llm_cli.lm_studio.models import model_size_bytes


_PROBE_MAX_TOKENS = 16
_FALLBACK_DRAM_PEAK_GBS = 90.0
_DRAM_PEAK_CACHE: tuple[float] | None = None



def multi_load_notice(current: str, loaded: list[str]) -> str:
    """
    函数名: multi_load_notice
    作用: 多模型并存时列出名单，并对指定模型做带宽位置估计
    输入:
        current (str): 要评估的模型（CLI 默认）
        loaded (list): 当前已加载 key
    输出:
        str: 警告全文；不足两套则为空
    """
    names = [str(item).strip() for item in loaded if str(item).strip()]
    if len(names) < 2:
        return ""
    listed = ", ".join(names)
    want = str(current or "").strip()
    head = f"warning: {len(names)} models loaded at once ({listed})."
    if not want:
        return head + " Specify a model to probe VRAM vs CPU RAM."
    if want not in names:
        return head + f" CLI default {want} is not in the loaded set."
    # 中文注释: 只评估指定模型；不猜测另一套权重占着哪块显存
    body = _assess_bus(want)
    tail = " Unload extras in LM Studio so the model you need stays on GPU."
    return f"{head} {body}{tail}"


def dram_peak_gbs() -> float:
    """
    函数名: dram_peak_gbs
    作用: 估本机 DRAM 理论峰值 GB/s；失败则用保守回退值
    输入: 无
    输出:
        float
    """
    global _DRAM_PEAK_CACHE
    if _DRAM_PEAK_CACHE is not None:
        return _DRAM_PEAK_CACHE[0]
    detected = _detect_dram_peak_gbs()
    peak = detected if detected is not None and detected > 0 else _FALLBACK_DRAM_PEAK_GBS
    _DRAM_PEAK_CACHE = (peak,)
    return peak


def _detect_dram_peak_gbs() -> float | None:
    """
    函数名: _detect_dram_peak_gbs
    作用: 用 Win32_PhysicalMemory 的 MT/s 累加理论带宽
    输入: 无
    输出:
        float | None
    """
    cmd = (
        "Get-CimInstance Win32_PhysicalMemory | "
        "Select-Object Speed,ConfiguredClockSpeed | ConvertTo-Json -Compress"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception:
        return None
    raw = (proc.stdout or "").strip()
    if not raw or proc.returncode != 0:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    rows = parsed if isinstance(parsed, list) else [parsed]
    total = 0.0
    for item in rows:
        if not isinstance(item, dict):
            continue
        speed = item.get("ConfiguredClockSpeed") or item.get("Speed")
        try:
            mts = float(speed)
        except (TypeError, ValueError):
            continue
        if mts <= 0:
            continue
        # 中文注释: 每条 64-bit DIMM 理论 GB/s = MT/s * 8 / 1000
        total += mts * 8.0 / 1000.0
    return total if total > 0 else None


def _assess_bus(model_key: str) -> str:
    """
    函数名: _assess_bus
    作用: 短 decode 测 tok/s，用 体积*速度 对照 DRAM 峰值分类
    输入:
        model_key (str): 指定模型
    输出:
        str: 一段测量说明
    """
    size = model_size_bytes(model_key)
    try:
        t0 = time.perf_counter()
        result = complete(
            [{"role": "user", "content": "Reply with the single word ok."}],
            model=model_key,
            thinking=False,
            max_tokens=_PROBE_MAX_TOKENS,
            temperature=0.0,
        )
        elapsed = time.perf_counter() - t0
    except Exception as exc:
        return f"{model_key} placement probe failed ({exc})."
    out_n = _output_tokens(result)
    if elapsed <= 0 or out_n <= 0:
        return f"{model_key} placement probe returned no decode tokens."
    tok_s = out_n / elapsed
    if not size:
        return (
            f"{model_key} decode ~{tok_s:.2f} tok/s over {elapsed:.1f}s "
            f"({out_n} tokens) but size_bytes is unknown, so bus cannot be classified."
        )
    implied = tok_s * float(size) / 1e9
    peak = dram_peak_gbs()
    gb = size / 1e9
    where = _classify(implied, peak)
    return (
        f"{model_key} decode ~{tok_s:.2f} tok/s, weights ~{gb:.1f} GB, "
        f"implied ~{implied:.0f} GB/s vs DRAM peak ~{peak:.0f} GB/s → {where}."
    )


def _classify(implied_gbs: float, dram_peak_gbs_value: float) -> str:
    """
    函数名: _classify
    作用: 用 DRAM 理论峰值为上限，判断更像 VRAM、CPU RAM 还是混合
    输入:
        implied_gbs (float): tok/s * size
        dram_peak_gbs_value (float): 本机 DRAM 峰值
    输出:
        str
    """
    if dram_peak_gbs_value <= 0:
        return "unclear"
    # 中文注释: 超过 DRAM 理论上限则不可能纯走内存总线；明显低于峰值则像 CPU RAM
    if implied_gbs > dram_peak_gbs_value * 1.2:
        return "likely VRAM (faster than DRAM can supply)"
    if implied_gbs <= dram_peak_gbs_value * 0.7:
        return "likely CPU RAM (decode matches DRAM-class bandwidth)"
    return "hybrid or unclear (partial offload / prefill noise)"


def _output_tokens(result: Any) -> int:
    """
    函数名: _output_tokens
    作用: 从 complete 结果取 completion token 数
    输入:
        result: CompletionResult
    输出:
        int
    """
    raw = getattr(result, "raw", None)
    if isinstance(raw, dict):
        usage = raw.get("usage")
        if isinstance(usage, dict):
            for key in ("completion_tokens", "output_tokens"):
                n = usage.get(key)
                if isinstance(n, (int, float)) and int(n) > 0:
                    return int(n)
    text = str(getattr(result, "text", "") or "").strip()
    if not text:
        return 0
    return max(1, len(text.split()))
