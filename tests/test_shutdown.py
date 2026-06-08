from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services import shutdown


@pytest.fixture
def pid_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / ".run.pid"
    monkeypatch.setattr(shutdown, "PID_FILE", path)
    return path


def test_write_and_read_pid_file(pid_file: Path) -> None:
    shutdown.write_pid_file(12345)
    assert pid_file.read_text(encoding="ascii") == "12345"
    assert shutdown.read_pid_from_file() == 12345


def test_read_pid_from_file_missing(pid_file: Path) -> None:
    assert shutdown.read_pid_from_file() is None


def test_read_pid_from_file_invalid(pid_file: Path) -> None:
    pid_file.write_text("not-a-pid", encoding="ascii")
    assert shutdown.read_pid_from_file() is None


@patch("app.services.shutdown.subprocess.run")
def test_shutdown_server_uses_pid_file(mock_run: MagicMock, pid_file: Path) -> None:
    pid_file.write_text("9999", encoding="ascii")
    with patch.object(shutdown.sys, "platform", "win32"):
        result = shutdown.shutdown_server()
    assert result is True
    mock_run.assert_called_once_with(
        ["taskkill", "/PID", "9999", "/F", "/T"],
        capture_output=True,
        check=False,
    )
    assert not pid_file.exists()


@patch("app.services.shutdown.os.kill")
def test_shutdown_server_fallback_to_current_pid(
    mock_kill: MagicMock, pid_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutdown.os, "getpid", lambda: 4321)
    with patch.object(shutdown.sys, "platform", "linux"):
        shutdown.shutdown_server()
    mock_kill.assert_called_once_with(4321, 9)


def test_close_tab_html_contains_window_close() -> None:
    assert "window.close()" in shutdown.CLOSE_TAB_HTML
