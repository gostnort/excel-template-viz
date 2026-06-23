"""UI 纯字符串入 DB 与 Gradio 数据供给（路径 A）。见 docs/data_flow_design.md。"""

from __future__ import annotations

import datetime
import json
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from app.services.core_registry import PROJECT_ROOT
from app.services.core_toml import GetTomlValues


TEMP_DIR = PROJECT_ROOT / "temp"
_ACTIVE_POINTER_SUFFIX = ".active"
_FORBIDDEN_DB_SUFFIXES = (".db", ".sqlite", ".sql")
_SUFFIX_TOKEN_PATTERN = re.compile(r"^[A-Z]\d{4}$")


def _current_year() -> int:
    return datetime.date.today().year


def _is_valid_suffix_token(token: str) -> bool:
    return bool(_SUFFIX_TOKEN_PATTERN.fullmatch(token))


def _suffix_token_from_path(db_path: Path) -> str | None:
    suffix = db_path.suffix
    if not suffix or len(suffix) < 2:
        return None
    token = suffix[1:]
    if not _is_valid_suffix_token(token):
        return None
    return token


def _parse_suffix_token(token: str) -> tuple[str, int] | None:
    if not _is_valid_suffix_token(token):
        return None
    return token[0], int(token[1:])


def _active_pointer_path(template_id: str) -> Path:
    return TEMP_DIR / f"{template_id}{_ACTIVE_POINTER_SUFFIX}"


def _read_active_suffix_token(template_id: str) -> str | None:
    pointer = _active_pointer_path(template_id)
    if not pointer.is_file():
        return None
    token = pointer.read_text(encoding="utf-8").strip()
    if _is_valid_suffix_token(token):
        return token
    return None


def _write_active_suffix_token(template_id: str, suffix_token: str) -> None:
    if not _is_valid_suffix_token(suffix_token):
        raise ValueError(f"invalid suffix token: {suffix_token!r}")
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    _active_pointer_path(template_id).write_text(suffix_token, encoding="utf-8")


def _db_path_for_suffix_token(template_id: str, suffix_token: str) -> Path:
    return TEMP_DIR / f"{template_id}.{suffix_token}"


def list_db_paths(template_id: str, year: int | None = None) -> list[Path]:
    """
    函数名: list_db_paths
    作用: 列出 temp 下某模板在指定年份的全部数据库文件
    输入:
        template_id (str) - 模板 ID（与 xlsx stem 规范化后一致）
        year (int | None) - 年份，默认当前年
    输出:
        list[Path] - 按字母序排序的路径列表
    """
    if year is None:
        year = _current_year()
    if not TEMP_DIR.is_dir():
        return []
    paths: list[Path] = []
    for candidate in TEMP_DIR.glob(f"{template_id}.*"):
        if candidate.name.endswith(_ACTIVE_POINTER_SUFFIX):
            continue
        token = _suffix_token_from_path(candidate)
        if token is None:
            continue
        parsed = _parse_suffix_token(token)
        if parsed is None or parsed[1] != year:
            continue
        paths.append(candidate)
    paths.sort(key=lambda item: _parse_suffix_token(_suffix_token_from_path(item) or "A0000")[0])
    return paths


def default_db_path(template_id: str) -> Path:
    """
    函数名: default_db_path
    作用: 返回当前应写入的数据库路径；扩展名在内部按 A2026 规则生成或解析
    输入:
        template_id (str) - 模板唯一 ID
    输出:
        Path - temp/{template_id}.{Letter}{Year}
    """
    year = _current_year()
    active = _read_active_suffix_token(template_id)
    if active is not None:
        parsed = _parse_suffix_token(active)
        if parsed is not None and parsed[1] == year:
            return _db_path_for_suffix_token(template_id, active)
    existing = list_db_paths(template_id, year)
    if existing:
        latest = existing[-1]
        token = _suffix_token_from_path(latest)
        if token is not None:
            _write_active_suffix_token(template_id, token)
        return latest
    suffix_token = f"A{year}"
    _write_active_suffix_token(template_id, suffix_token)
    return _db_path_for_suffix_token(template_id, suffix_token)


def allocate_next_db_path(template_id: str) -> Path:
    """
    函数名: allocate_next_db_path
    作用: 同年创建下一个字母扩展名的库（A2026→B2026），并设为当前写入目标
    输入:
        template_id (str) - 模板唯一 ID
    输出:
        Path - 新库路径（文件尚未存在，由 SecureSQLite 创建）
    """
    year = _current_year()
    existing = list_db_paths(template_id, year)
    if not existing:
        suffix_token = f"A{year}"
    else:
        last_token = _suffix_token_from_path(existing[-1])
        if last_token is None:
            raise ValueError("existing database path has invalid suffix")
        letter = last_token[0]
        if letter >= "Z":
            raise ValueError(f"no database slot left for {template_id} in {year}")
        suffix_token = f"{chr(ord(letter) + 1)}{year}"
    _write_active_suffix_token(template_id, suffix_token)
    return _db_path_for_suffix_token(template_id, suffix_token)


def _normalize_id(value: Any) -> int:
    """
    函数名: _normalize_id
    作用: 将 ID 规范为整数主键（拒绝布尔与空值）
    输入:
        value (Any) - 原始 ID 值
    输出:
        int - 规范化后的整数 ID
    """
    if isinstance(value, bool):
        raise ValueError("ID cannot be boolean")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip()
    if not text:
        raise ValueError("ID cannot be empty")
    if "." in text:
        return int(float(text))
    return int(text)


def _reject_forbidden_db_suffix(db_path: Path) -> None:
    """
    函数名: _reject_forbidden_db_suffix
    作用: 拒绝 .db/.sqlite/.sql，并要求扩展名为 {Letter}{Year} 五字符形式
    输入:
        db_path (Path) - 数据库文件路径
    输出:
        无；非法后缀时抛出 ValueError
    """
    lower = db_path.suffix.lower()
    if lower in _FORBIDDEN_DB_SUFFIXES:
        raise ValueError(f"Forbidden database suffix: {lower}")
    token = _suffix_token_from_path(db_path)
    if token is None:
        raise ValueError(f"Invalid database suffix: {db_path.suffix!r}")


class SecureSQLite:
    """非常规扩展名 SQLite；records 表以 JSON 存整条标准记录。"""

    def __init__(self, db_path: Path) -> None:
        """
        函数名: __init__
        作用: 打开或创建 temp 下 {template_id}.{Letter}{Year} 并确保表结构存在
        输入:
            db_path (Path) - 数据库文件路径
        输出:
            无
        """
        _reject_forbidden_db_suffix(db_path)
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.ensure_table()


    def ensure_table(self) -> None:
        """
        函数名: ensure_table
        作用: 创建 records(id, data) 表（若不存在）
        输入: 无
        输出: 无
        """
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY,
                data TEXT NOT NULL
            )
            """
        )
        self.conn.commit()


    def insert_or_update(self, record: dict[str, Any]) -> None:
        """
        函数名: insert_or_update
        作用: 按 record["id"] 插入或更新整条 JSON 记录
        输入:
            record (dict[str, Any]) - 须含 id 键的标准记录
        输出: 无
        """
        if "id" not in record:
            raise ValueError("record must contain id")
        rid = _normalize_id(record["id"])
        payload = json.dumps(record, ensure_ascii=False)
        cur = self.conn.cursor()
        cur.execute("SELECT id FROM records WHERE id=?", (rid,))
        exists = cur.fetchone()
        if exists:
            cur.execute("UPDATE records SET data=? WHERE id=?", (payload, rid))
        else:
            cur.execute("INSERT INTO records (id, data) VALUES (?, ?)", (rid, payload))
        self.conn.commit()


    def query_by_id(self, rid: int) -> dict[str, Any] | None:
        """
        函数名: query_by_id
        作用: 按主键读取一条记录
        输入:
            rid (int) - 记录主键
        输出:
            dict[str, Any] | None - 解析后的记录或 None
        """
        cur = self.conn.cursor()
        cur.execute("SELECT data FROM records WHERE id=?", (_normalize_id(rid),))
        row = cur.fetchone()
        if not row:
            return None
        return json.loads(row[0])


    def query_all(self) -> list[dict[str, Any]]:
        """
        函数名: query_all
        作用: 读取全部记录，供 UiProvider.get_data 使用
        输入: 无
        输出:
            list[dict[str, Any]] - 按 id 排序的记录列表
        """
        cur = self.conn.cursor()
        cur.execute("SELECT data FROM records ORDER BY id")
        return [json.loads(row[0]) for row in cur.fetchall()]


    def close(self) -> None:
        """
        函数名: close
        作用: 关闭数据库连接
        输入: 无
        输出: 无
        """
        self.conn.close()



class UiProvider:
    """Gradio labels + data；数据一律来自 SecureSQLite。"""

    def __init__(self, cfg: GetTomlValues, db: SecureSQLite) -> None:
        """
        函数名: __init__
        作用: 绑定 TOML 配置与数据库实例
        输入:
            cfg (GetTomlValues) - 已加载的 TOML
            db (SecureSQLite) - 持久化层
        输出: 无
        """
        self.cfg = cfg
        self.db = db


    def get_labels(self) -> list[str]:
        """
        函数名: get_labels
        作用: 返回表单列标题（Input_label 顺序）
        输入: 无
        输出:
            list[str] - Gradio 列名列表
        """
        return [rule.Input_label for rule in self.cfg.field_rules]


    def get_data(self) -> list[dict[str, Any]]:
        """
        函数名: get_data
        作用: 从 DB 读取全部行数据，不直读 Excel
        输入: 无
        输出:
            list[dict[str, Any]] - 与 query_all 一致
        """
        return self.db.query_all()


    def split_by_determiner(self, raw: str) -> list[str]:
        """
        函数名: split_by_determiner
        作用: 用 cfg.determiner 拆分 UI textbox 纯字符串
        输入:
            raw (str) - 用户输入的整段字符串
        输出:
            list[str] - 拆分后的段列表
        """
        return raw.split(self.cfg.determiner)


    def record_from_textbox(self, raw: str) -> dict[str, Any]:
        """
        函数名: record_from_textbox
        作用: 路径 A：determiner 拆分后按 index 映射为标准记录
        输入:
            raw (str) - textbox 纯字符串
        输出:
            dict[str, Any] - 含 id、field、Input_label 键的记录
        """
        parts = self.split_by_determiner(raw)
        record: dict[str, Any] = {}
        has_id_field = False
        max_index = max((rule.index for rule in self.cfg.field_rules if rule.index >= 0), default=-1)
        if max_index >= 0 and len(parts) <= max_index:
            raise ValueError(
                f"textbox split into {len(parts)} part(s), need at least {max_index + 1}"
            )
        # 仅 index>=0 的 rule 参与拆分；index=-1 仅 Input_sheet 或数据源路径
        for rule in self.cfg.field_rules:
            if rule.index < 0:
                continue
            segment = parts[rule.index]
            if rule.field:
                record[rule.field] = segment
            record[rule.Input_label] = segment
            if rule.id:
                has_id_field = True
                record["id"] = _normalize_id(segment)
        if not has_id_field:
            record["id"] = uuid.uuid4().int >> 64
        return record
