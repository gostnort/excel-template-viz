import os
import subprocess
import sys
import threading
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PID_FILE = PROJECT_ROOT / ".run.pid"
CLOSE_TAB_HTML = "<script>window.close();</script>"


def write_pid_file(pid: int | None = None) -> None:
    # 写入 PID 文件，供 run.bat 启动与关闭功能共用
    target = pid if pid is not None else os.getpid()
    PID_FILE.write_text(str(target), encoding="ascii")


def read_pid_from_file() -> int | None:
    if not PID_FILE.exists():
        return None
    text = PID_FILE.read_text(encoding="ascii").strip()
    if not text.isdigit():
        return None
    return int(text)


def shutdown_server() -> bool:
    # 终止 Streamlit 后台进程（Windows 使用 taskkill 结束进程树）
    pid = read_pid_from_file()
    if pid is None:
        pid = os.getpid()
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F", "/T"],
            capture_output=True,
            check=False,
        )
    else:
        os.kill(pid, 9)
    PID_FILE.unlink(missing_ok=True)
    return True


def schedule_shutdown(delay_seconds: float = 0.3) -> None:
    # 延迟关闭，给浏览器执行 window.close() 留出时间
    def _run() -> None:
        time.sleep(delay_seconds)
        shutdown_server()
    threading.Thread(target=_run, daemon=True).start()
