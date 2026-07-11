"""Download the Gemma 4 .litertlm weight; async-kickoff on backend init.

`ensure_model_async()` is called from `backends/factory.py` as soon as the
LlmBackend is being constructed (i.e. "gemma4 API 已初始化"). It never blocks:
if the weight is missing it starts a background thread and returns a Future,
which the LiteRT backend only awaits lazily, right before it actually needs
the file (first real `generate`/`open_session` call), not at construction time.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future

from llm_gemma4 import config


_log = logging.getLogger(__name__)
_download_lock = threading.Lock()
_download_future: Future[tuple[bool, str]] | None = None


def download_litert() -> tuple[bool, str]:
    """Blocking fetch of the .litertlm weight via huggingface_hub.

    Safe to call repeatedly: huggingface_hub checks existing local files by
    hash/etag instead of re-downloading them.
    """
    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    config.INSTALL_LOG.parent.mkdir(parents=True, exist_ok=True)
    try:
        from huggingface_hub import hf_hub_download
        path = hf_hub_download(
            repo_id=config.HF_REPO_ID,
            filename=config.MODEL_FILENAME,
            local_dir=config.MODELS_DIR,
        )
        ok_msg = f"model ready at {path}"
        _append_log(ok_msg)
        return True, ok_msg
    except Exception as exc:
        _log.exception("download_litert failed")
        msg = f"download failed: {exc}"
        _append_log(msg)
        return False, msg


def ensure_model_async() -> Future[tuple[bool, str]] | None:
    """Start a background download if the weight is missing; never blocks.

    Returns the shared Future so a caller that truly needs the model (e.g. the
    LiteRT backend right before `Engine(...)`) can await it lazily. Returns
    `None` when the file already exists — nothing to wait on.
    """
    global _download_future
    if config.model_exists():
        return None
    with _download_lock:
        stale = _download_future is not None and _download_future.done() and not config.model_exists()
        if _download_future is None or stale:
            future: Future[tuple[bool, str]] = Future()
            _download_future = future
            thread = threading.Thread(target=_run_download, args=(future,), name="gemma4-hf-download", daemon=True)
            thread.start()
        return _download_future


def wait_for_model(pending: Future[tuple[bool, str]] | None, timeout: float | None = None) -> tuple[bool, str]:
    """Block on the Future returned by `ensure_model_async`; `None` means already-ready."""
    if pending is None:
        return True, "model already present"
    return pending.result(timeout=timeout)


def _run_download(future: Future[tuple[bool, str]]) -> None:
    # download_litert() already catches its own exceptions and returns (False, msg);
    # this outer guard only protects against something escaping that contract.
    try:
        result = download_litert()
    except Exception as exc:  # pragma: no cover - defensive
        future.set_exception(exc)
        return
    future.set_result(result)


def _append_log(line: str) -> None:
    try:
        with config.INSTALL_LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


if __name__ == "__main__":
    ok, message = download_litert()
    print(message)
    raise SystemExit(0 if ok else 1)
