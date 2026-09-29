"""desktop-commander：Wikipedia 与本地文件。失败返回错误字符串。"""

from mcp_desktop.session import close_session
from mcp_desktop.tools import read_local_file, wikipedia_lookup

__all__ = ["close_session", "read_local_file", "wikipedia_lookup"]
