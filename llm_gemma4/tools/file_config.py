"""Whitelisted file reads for chat mode (embed_gemma4.md §9)."""

from __future__ import annotations

from pathlib import Path

from llm_gemma4.models_catalog import repo_root


_FORBIDDEN_PARTS = {"credentials"}
_READ_ONLY_ROOTS = ("docs", "nicegui_ui", "app", "exports", "temp", "templates", "plans")
_DEFAULT_MAX_CHARS = 4000


def resolve_repo_path(rel_path: str) -> Path:
    """Resolve a repo-relative path; reject escapes outside repo root."""
    root = repo_root().resolve()
    raw = (rel_path or "").strip().replace("\\", "/").lstrip("/")
    if not raw:
        raise ValueError("path required")
    target = (root / raw).resolve()
    if not str(target).startswith(str(root)):
        raise ValueError("path escapes repository root")
    return target


def path_permission(rel_path: str, *, write: bool = False) -> tuple[bool, str | None]:
    """Return (allowed, reason) for a repo-relative path."""
    try:
        target = resolve_repo_path(rel_path)
    except ValueError as exc:
        return False, str(exc)
    parts = set(target.relative_to(repo_root().resolve()).parts)
    if parts & _FORBIDDEN_PARTS:
        return False, "credentials/** is forbidden"
    if write:
        rel_parts = target.relative_to(repo_root().resolve()).parts
        if not rel_parts or rel_parts[0] != "templates":
            return False, "writes allowed only under templates/**"
        if not str(target).endswith(".toml"):
            return False, "template writes must use toml_io"
        return True, None
    rel_parts = target.relative_to(repo_root().resolve()).parts
    if not rel_parts:
        return False, "repository root is not readable"
    root_name = rel_parts[0]
    if root_name in _READ_ONLY_ROOTS:
        return True, None
    if root_name == "templates":
        return True, None
    return False, f"path not in read whitelist: {root_name}"


def read_file(rel_path: str, *, max_chars: int = _DEFAULT_MAX_CHARS) -> dict:
    """Read a whitelisted file with truncation."""
    allowed, reason = path_permission(rel_path, write=False)
    if not allowed:
        return {"ok": False, "error": reason}
    target = resolve_repo_path(rel_path)
    if not target.is_file():
        return {"ok": False, "error": f"not a file: {rel_path}"}
    text = target.read_text(encoding="utf-8", errors="replace")
    clipped = text[:max_chars]
    payload: dict = {
        "ok": True,
        "path": rel_path,
        "size": len(text),
        "content": clipped,
    }
    if len(text) > max_chars:
        payload["truncated"] = True
    return payload


def list_files(rel_path: str = ".", *, max_entries: int = 80) -> dict:
    """List entries under a whitelisted directory."""
    allowed, reason = path_permission(rel_path, write=False)
    if not allowed:
        return {"ok": False, "error": reason}
    target = resolve_repo_path(rel_path)
    if not target.is_dir():
        return {"ok": False, "error": f"not a directory: {rel_path}"}
    entries: list[str] = []
    for child in sorted(target.iterdir()):
        name = child.name + ("/" if child.is_dir() else "")
        entries.append(name)
        if len(entries) >= max_entries:
            break
    return {
        "ok": True,
        "path": rel_path,
        "entries": entries,
        "truncated": len(entries) >= max_entries,
    }
