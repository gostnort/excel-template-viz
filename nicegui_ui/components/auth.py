from dataclasses import dataclass
from nicegui import app

@dataclass(frozen=True)
class Principal:
    principal_id: str
    display_name: str | None = None

def known_usernames() -> list[str]:
    # 预留给未来多用户扩展
    return ["admin"]

def login_required() -> bool:
    return len(known_usernames()) > 1

def resolve_principal(browser_id: str | None = None) -> Principal:
    """
    解析当前操作者的身份 (Principal)
    """
    if login_required():
        username = app.storage.user.get('username')
        if username and username in known_usernames():
            return Principal(principal_id=f'user:{username}', display_name=username)
        return Principal(principal_id='user:unauthenticated', display_name=None)
    
    return Principal(principal_id='user:admin', display_name='admin')

def pref_key(name: str) -> str:
    """
    获取带用户前缀的持久化偏好键名
    """
    principal = resolve_principal()
    return f"{principal.principal_id}:{name}"
