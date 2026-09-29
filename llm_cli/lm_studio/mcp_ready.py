"""检测 LM Studio 里 desktop-commander / playwright 是否配齐，并把结果记到 mcp_ready.json。"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED = ("desktop-commander", "playwright")
PLUGIN_IDS = ("mcp/desktop-commander", "mcp/playwright")
BIN_NAMES = {
    "desktop-commander": ("desktop-commander", "desktop-commander.cmd"),
    "playwright": ("playwright-mcp", "playwright-mcp.cmd"),
}
STATE_NAME = "mcp_ready.json"


def lm_studio_dir() -> Path:
    """
    函数名: lm_studio_dir
    作用: LM Studio 用户目录
    输入: 无
    输出:
        Path
    """
    return Path.home() / ".lmstudio"


def state_path() -> Path:
    """
    函数名: state_path
    作用: 检测结果缓存路径（gitignore）
    输入: 无
    输出:
        Path
    """
    return Path(__file__).resolve().parent / STATE_NAME


def _which_bin(key: str) -> str:
    """
    函数名: _which_bin
    作用: PATH 上找 MCP 命令
    输入:
        key (str): desktop-commander 或 playwright
    输出:
        str: 找到的路径，没有则为空
    """
    for name in BIN_NAMES.get(key) or ():
        found = shutil.which(name)
        if found:
            return found
    return ""


def _load_json(path: Path) -> Any:
    """
    函数名: _load_json
    作用: 读 JSON，失败为 None
    输入:
        path (Path): 文件
    输出:
        Any
    """
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _mcp_json_ok(data: Any) -> dict[str, bool]:
    """
    函数名: _mcp_json_ok
    作用: mcp.json 是否登记了两个服务器
    输入:
        data: 解析后的 mcp.json
    输出:
        dict[str, bool]
    """
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        return {name: False for name in REQUIRED}
    found = {name: False for name in REQUIRED}
    for key, spec in servers.items():
        blob = f"{key} {json.dumps(spec, ensure_ascii=False)}".lower()
        for name in REQUIRED:
            if name in blob or name.replace("-", "") in blob.replace("-", ""):
                found[name] = True
    return found


def _plugin_dir_ok(root: Path) -> dict[str, bool]:
    """
    函数名: _plugin_dir_ok
    作用: 扩展目录里是否已桥接两个 MCP
    输入:
        root (Path): ~/.lmstudio
    输出:
        dict[str, bool]
    """
    base = root / "extensions" / "plugins" / "mcp"
    return {
        "desktop-commander": (base / "desktop-commander" / "manifest.json").is_file(),
        "playwright": (base / "playwright" / "manifest.json").is_file(),
    }


def _pinned_ok(settings: Any) -> bool:
    """
    函数名: _pinned_ok
    作用: 新对话是否钉住两个 MCP
    输入:
        settings: settings.json
    输出:
        bool
    """
    chat = settings.get("chat") if isinstance(settings, dict) else None
    pinned = chat.get("pinnedPlugins") if isinstance(chat, dict) else None
    if not isinstance(pinned, list):
        return False
    have = {str(item).strip() for item in pinned}
    return all(pid in have for pid in PLUGIN_IDS)


def _allow_all_ok(settings: Any) -> bool:
    """
    函数名: _allow_all_ok
    作用: 是否同意两个 MCP 的全部工具免确认
    输入:
        settings: settings.json
    输出:
        bool
    """
    chat = settings.get("chat") if isinstance(settings, dict) else None
    if not isinstance(chat, dict):
        return False
    if chat.get("neverAskForToolConfirmation") is True:
        return True
    patterns = chat.get("skipToolConfirmationPatterns") or []
    if not isinstance(patterns, list):
        return False
    have = {str(item).strip() for item in patterns}
    return all(f"{pid}:*" in have for pid in PLUGIN_IDS)


def _selected_plugins(root: Path) -> list[str]:
    """
    函数名: _selected_plugins
    作用: 当前选中对话启用的 plugin id
    输入:
        root (Path): ~/.lmstudio
    输出:
        list[str]
    """
    cfg = _load_json(root / ".internal" / "conversation-config.json")
    if not isinstance(cfg, dict):
        return []
    name = str(cfg.get("selectedConversation") or "").strip()
    if not name:
        return []
    conv = _load_json(root / "conversations" / name)
    if not isinstance(conv, dict):
        return []
    plugins = conv.get("plugins") or []
    if not isinstance(plugins, list):
        return []
    return [str(item).strip() for item in plugins if str(item).strip()]


def _conversation_ok(plugins: list[str]) -> bool:
    """
    函数名: _conversation_ok
    作用: 当前对话是否启用了两个 MCP
    输入:
        plugins (list): plugin id
    输出:
        bool
    """
    have = set(plugins)
    return all(pid in have for pid in PLUGIN_IDS)


def _fingerprint(root: Path) -> str:
    """
    函数名: _fingerprint
    作用: 配置指纹，变了就要重测
    输入:
        root (Path): ~/.lmstudio
    输出:
        str
    """
    h = hashlib.sha256()
    for rel in ("mcp.json", "settings.json", ".internal/conversation-config.json"):
        path = root / rel
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        if path.is_file():
            h.update(path.read_bytes())
        h.update(b"\n")
    sel = _load_json(root / ".internal" / "conversation-config.json")
    name = ""
    if isinstance(sel, dict):
        name = str(sel.get("selectedConversation") or "")
    conv = root / "conversations" / name if name else None
    if conv is not None and conv.is_file():
        data = _load_json(conv)
        plugins = data.get("plugins") if isinstance(data, dict) else None
        h.update(json.dumps(plugins or [], ensure_ascii=False).encode("utf-8"))
    return h.hexdigest()[:24]


def _check_row(ok: bool, detail: str) -> dict[str, Any]:
    """
    函数名: _check_row
    作用: 一条检测结果
    输入:
        ok (bool): 是否通过
        detail (str): 说明
    输出:
        dict
    """
    return {"ok": bool(ok), "detail": detail}


def probe_mcp_ready(*, force: bool = False) -> dict[str, Any]:
    """
    函数名: probe_mcp_ready
    作用: 检测两个 MCP 的安装、mcp.json、默认对话、允许全部；写状态文件
    输入:
        force (bool): True 则忽略缓存，始终重测
    输出:
        dict: all_ok / warnings / checks / skipped
    """
    root = lm_studio_dir()
    fp = _fingerprint(root)
    prev = _load_json(state_path())
    if (
        not force
        and isinstance(prev, dict)
        and prev.get("all_ok") is True
        and prev.get("fingerprint") == fp
    ):
        out = dict(prev)
        out["skipped"] = True
        return out
    mcp_path = root / "mcp.json"
    settings_path = root / "settings.json"
    mcp_data = _load_json(mcp_path)
    settings = _load_json(settings_path)
    in_json = _mcp_json_ok(mcp_data)
    in_plugin = _plugin_dir_ok(root)
    bins = {name: _which_bin(name) for name in REQUIRED}
    pinned = _pinned_ok(settings)
    allow = _allow_all_ok(settings)
    plugins = _selected_plugins(root)
    conv_ok = _conversation_ok(plugins)
    checks: dict[str, Any] = {}
    warnings: list[str] = []
    for name in REQUIRED:
        path = bins[name]
        checks[f"bin:{name}"] = _check_row(bool(path), path or "not on PATH")
        if not path:
            warnings.append(f"{name} binary not on PATH. Install the MCP and reopen the terminal.")
        checks[f"mcp.json:{name}"] = _check_row(
            in_json.get(name, False),
            "registered" if in_json.get(name) else f"missing in {mcp_path}",
        )
        if not in_json.get(name):
            warnings.append(f"Add mcpServers.{name} to {mcp_path}")
        checks[f"plugin:{name}"] = _check_row(
            in_plugin.get(name, False),
            "bridged" if in_plugin.get(name) else "LM Studio plugin folder missing",
        )
        if not in_plugin.get(name):
            warnings.append(f"Enable {name} once in LM Studio so ~/.lmstudio/extensions/plugins/mcp/{name} exists.")
    checks["pinnedPlugins"] = _check_row(
        pinned,
        "chat.pinnedPlugins has both" if pinned else "pin mcp/desktop-commander and mcp/playwright for new chats",
    )
    if not pinned:
        warnings.append(
            "LM Studio Settings → Chat → pin plugins mcp/desktop-commander and mcp/playwright "
            "(settings.json chat.pinnedPlugins)."
        )
    checks["selectedConversation"] = _check_row(
        conv_ok,
        "current chat plugins has both" if conv_ok else f"current plugins={plugins or []}",
    )
    if not conv_ok:
        warnings.append(
            "Enable desktop-commander and playwright on the current / default LM Studio chat (conversation plugins)."
        )
    checks["allowAll"] = _check_row(
        allow,
        "skipToolConfirmationPatterns * or neverAsk" if allow else "not allowed to run all tools",
    )
    if not allow:
        warnings.append(
            "In LM Studio, allow all tools for mcp/desktop-commander and mcp/playwright "
            "(skipToolConfirmationPatterns mcp/desktop-commander:* and mcp/playwright:*, "
            "or neverAskForToolConfirmation)."
        )
    all_ok = not warnings
    report = {
        "all_ok": all_ok,
        "skipped": False,
        "fingerprint": fp,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "warnings": warnings,
    }
    try:
        state_path().write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass
    return report


def format_mcp_warnings(report: dict[str, Any]) -> list[str]:
    """
    函数名: format_mcp_warnings
    作用: 启动时要打印的警告行；就绪且可跳过则为空
    输入:
        report (dict): probe_mcp_ready 结果
    输出:
        list[str]
    """
    if report.get("all_ok") and report.get("skipped"):
        return []
    if report.get("all_ok"):
        return []
    lines = ["mcp ready: incomplete — will re-check every CLI start until all items pass."]
    for item in report.get("warnings") or []:
        lines.append(f"warning: {item}")
    return [str(item) for item in lines]
