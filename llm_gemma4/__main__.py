"""llm_gemma4 最简入口：一次性问答，字符串进、字符串出。

不需要 JudgmentSpec/JudgmentResult（结构化判定）或 LlmSession（多轮会话状态）
的调用方，直接用 ConversationOnce 即可。仍然遵守底座解耦原则：本文件不含任何
业务域 prompt（见 docs/embed_gemma4.md §0.1）。`python -m llm_gemma4 "问题"`
也走这一个文件，不额外拆 main.py。
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from llm_gemma4.backends.base import LlmBackend

# 单一单例：Engine 构造时恒带 vision_backend（实测 2026-07-12，见
# docs/embed_gemma4.md §3.1d——带 vision_backend 的 Engine 相比纯文本 Engine
# 显存涨幅 ~0.4GB(4.0GB vs 3.6GB)，可忽略；不值得为省这点显存维护两个
# Engine（此前的 _vision_backend 双单例设计已废弃，ConversationOnce/Pic2Str
# 现在共用同一个 Engine，StartGemma() 一次预热两者都受益）。
_backend: LlmBackend | None = None
_backend_lock = threading.Lock()


def ConversationOnce(
    input_string: str,
    *,
    system: str | None = None,
    thinking: bool = False,
    temperature: float = 0.0,
) -> str:
    """
    函数名: ConversationOnce
    作用: 一次性问答；把 input_string 包成一条 user 消息发给模型，只取最终回答文本。
        不做 JSON 解析或结构化判定；需要稳定三态判定的场景改用 run_judgment。
        输出长度上限（max_tokens）不对外暴露，由 LlmBackend 按实际探测到的硬件
        （CPU/GPU/NPU，见 docs/embed_gemma4.md §3.1a）自行决定，调用方所在机器
        与实际运行机器硬件可能不同，不应由调用方猜一个固定值。
    输入:
        input_string (str): 用户的问题/指令原文。
        system (str | None): 可选的系统提示词，用来设定模型的角色/口吻/回答规则
            （例如"你是一个只用一句话回答的助手"），跟 input_string 分开传是因为
            system 通常是调用方固定不变的设定，input_string 才是每次变化的问题。
        thinking (bool): 是否开启 Gemma 4 的 reasoning 通道，默认关闭。
        temperature (float): 采样温度，默认 0（确定性输出）。
    输出:
        str: 模型的最终回答文本（thought 通道已剥离）。
    """
    messages: list[dict[str, str]] = []
    # system 与 input_string 分开拼装：system 在前，作为整段对话的角色设定
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": input_string})
    result = _get_backend().generate(
        messages, thinking=thinking, temperature=temperature
    )
    return result.text


def Pic2Str(
    image: str | Path | bytes,
    prompt: str,
    *,
    system: str | None = None,
    max_tokens: int | None = None,
    temperature: float = 0.0,
) -> str:
    """
    函数名: Pic2Str
    作用: 通用图片→文本接口。给 Gemma4 喂一张图片 + 一段文本提示，原样返回模型
        生成的文本。与 ConversationOnce 共用同一个模块级单例 _backend（见
        _get_backend；Engine 构造时恒带 vision_backend，已实测：真实
        gemma-4-E4B-it.litertlm + Backend.CPU() 可以正常读图，2026-07-12）。
        本函数不做任何业务语义解析——是否要求模型输出 JSON/TOML 等结构化文本、
        拿到文本后怎么解析/校验，由调用方自己决定，不属于本平台职责（同
        ConversationOnce 不含业务域 prompt 的原则）。识别质量、要不要用这个
        接口替代/辅助现有 OCR 流程，也是调用方的判断，本函数只保证接口能通。
    输入:
        image (str | Path | bytes): 图片文件路径，或已编码的原始图片字节
            （jpg/png 等，非解码后的像素数组）。
        prompt (str): 提示词，可在其中要求模型输出特定格式（如 JSON/TOML）。
        system (str | None): 可选系统提示词，同 ConversationOnce 的 system。
        max_tokens (int | None): 不传时按硬件自决默认值（同 ConversationOnce）。
        temperature (float): 采样温度，默认 0（确定性输出）。
    输出:
        str: 模型生成的文本。Gemma4 不可用、模型不支持视觉、或推理失败时抛异常。
    """
    result = _get_backend().generate_vision(
        image, prompt, system=system, max_tokens=max_tokens, temperature=temperature
    )
    return result.text


def _get_backend() -> LlmBackend:
    """
    函数名: _get_backend
    作用: 取模块级单例 backend，首次调用才真正构建；后续调用直接复用同一个
        Engine（GPU 加载成本一次性，复用才划算，见 docs/embed_gemma4.md §1.1）。
        Engine 构造时恒带 vision_backend（enable_vision=True）——实测显存涨幅
        只有 ~0.4GB（4.0GB vs 纯文本 3.6GB，2026-07-12），不值得为此再维护一个
        独立的视觉单例；ConversationOnce 与 Pic2Str 共用这一个 Engine。这个单例
        只在当前进程存活期间有效，不会跨进程持久化——见 §3.1b 末段。
    输入: 无。
    输出:
        LlmBackend: 已初始化（或已缓存）的底座 backend 实例。
    """
    global _backend
    if _backend is None:
        with _backend_lock:
            if _backend is None:
                # 延迟到函数内部 import，避免 llm_gemma4 包顶层 __init__ 与
                # backends.factory 之间出现循环导入。
                from llm_gemma4.backends.factory import create_backend

                _backend = create_backend(enable_vision=True)
    return _backend


def StartGemma() -> None:
    """
    函数名: StartGemma
    作用: 主动加载并常驻 Gemma4——按当前探测到的硬件能力选 NPU/GPU/CPU
        （复用 _get_backend 的同一套单例、同一套探测逻辑，见 §1.1/§1.3），
        不等到第一次 ConversationOnce()/Pic2Str() 调用才隐式触发冷启动。给想
        自己控制"冷启动成本在什么时候扛"的调用方用（例如服务进程启动阶段提前
        加载），跟 ConversationOnce()/Pic2Str() 共用同一个模块级单例：调用顺序
        不影响后续复用，StartGemma() 之后两者都直接吃现成的 Engine，不会重复
        加载。已加载时重复调用是空操作（幂等）。这一份 Engine 恒带
        vision_backend（见 _get_backend），所以 StartGemma() 一次预热同时覆盖
        文本与视觉两条路径。
        `_get_backend()` 本身只构造轻量的 LiteRtBackend 包装对象，真正重的
        Engine 构造是惰性的、原本要等第一次 generate() 才触发（见
        backends/litert/backend.py `_ensure_engine`）——所以这里必须显式调
        `.warm()` 把那次构造提前逼出来，只调 `_get_backend()` 不够（已实测
        验证：不调 warm() 时 StartGemma() 本身几乎瞬间返回，冷启动成本原样
        转嫁到了下一次 ConversationOnce()，没有起到"提前扛"的效果）。
    输入: 无。
    输出: 无（副作用：填充模块级 _backend 单例，且其 Engine 已构造完毕）。
    """
    _get_backend().warm()


def ResetBackend() -> None:
    """
    函数名: ResetBackend
    作用: 关闭并清空缓存的单例 backend；主要用于测试隔离或进程退出前的清理。
    输入: 无。
    输出: 无。
    """
    global _backend
    with _backend_lock:
        if _backend is not None:
            _backend.close()
            _backend = None


def EndGemma() -> None:
    """
    函数名: EndGemma
    作用: 卸载 StartGemma()（或任意一次 ConversationOnce()）加载的 Gemma4，
        释放其占用的常驻内存/显存。是 ResetBackend 的对外别名——同一份实现，
        只是名字跟 StartGemma 成对，方便调用方按"启动/关闭"这套心智模型使用，
        不用记 Reset 这个偏内部测试向的名字。未加载时调用是空操作。
    输入: 无。
    输出: 无。
    """
    ResetBackend()


def _run_from_cli() -> None:
    """
    函数名: _run_from_cli
    作用: 只取第一个位置参数当问题，其余用 ConversationOnce 的默认值，避免
        缺参数时按位置下标取值直接崩溃。每次 `python -m llm_gemma4` 都是一个
        全新进程，跑完就退出——引擎不会跨进程保留，这是 CLI 单发调用的固有
        代价，不是没做缓存（同一进程内多次调用 ConversationOnce 才会复用
        Engine，见 docs/embed_gemma4.md §3.1b 末段）。
    输入: 无（从 sys.argv 读取）。
    输出: 无（直接打印到标准输出）。
    """
    if len(sys.argv) < 2:
        print('usage: python -m llm_gemma4 "your question"')
        raise SystemExit(1)
    print(ConversationOnce(sys.argv[1]))


if __name__ == "__main__":
    _run_from_cli()
