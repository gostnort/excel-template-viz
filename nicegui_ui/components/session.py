from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import time

from nicegui import app
from nicegui_ui.components.auth import resolve_principal

@dataclass
class SessionState:
    template_id: str | None = None
    template_path: Path | None = None
    cfg: Any | None = None
    verify_report: dict[str, Any] | None = None
    located: dict[str, dict[str, int]] = field(default_factory=dict)
    
    db_path: Path | None = None
    db: Any | None = None
    ui_provider: Any | None = None
    t2db: Any | None = None
    writer: Any | None = None
    
    input_capacity: int = 0
    current_instance_index: int = 0
    
    draft: dict[str, Any] = field(default_factory=dict)
    template_defaults: dict[str, Any] = field(default_factory=dict)
    session_rows: list[dict[str, Any]] = field(default_factory=list)
    selected_session_index: int | None = None
    
    suppress_id_search: bool = False
    pending_id_value: int | None = None
    
    exported_files: list[Path] = field(default_factory=list)
    last_export_path: Path | None = None
    
    active_db_suffix: str | None = None
    selected_db_row_index: int | None = None
    
    google_connected: bool = False
    google_sheet_rows: list[dict[str, Any]] = field(default_factory=list)
    
    # 心跳时间，用于清理无活动的过期会话
    last_accessed: float = field(default_factory=time.time)

class SessionRegistry:
    _sessions: dict[str, SessionState] = {}

    @classmethod
    def for_current(cls) -> SessionState:
        """
        获取当前操作者的会话状态。
        基于 browser_id 和 principal_id 的双重隔离，防止多标签页串车。
        """
        # browser_id 在 app.py 的 @ui.page('/') 中颁发
        browser_id = app.storage.browser.get('id')
        if not browser_id:
            browser_id = 'system'
            
        principal = resolve_principal(browser_id)
        session_key = f"{principal.principal_id}::{browser_id}"
        
        # 触发过期清理 (2小时无心跳则淘汰)
        cls._cleanup_expired()
        
        session = cls._sessions.setdefault(session_key, SessionState())
        session.last_accessed = time.time()
        return session
        
    @classmethod
    def _cleanup_expired(cls):
        now = time.time()
        # 清理超过 7200 秒 (2小时) 未活跃的 session
        expired_keys = [k for k, v in cls._sessions.items() if now - v.last_accessed > 7200]
        for k in expired_keys:
            del cls._sessions[k]

    @classmethod
    def reset_current(cls):
        """
        清空当前用户的业务会话状态（通常在加载新模板或 TOML 报错时调用）
        """
        browser_id = app.storage.browser.get('id', 'system')
        principal = resolve_principal(browser_id)
        session_key = f"{principal.principal_id}::{browser_id}"
        cls._sessions[session_key] = SessionState()
