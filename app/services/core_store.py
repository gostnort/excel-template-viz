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
from app.services.core_toml import GetTomlValues, resolve_db_id


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
    paths.sort(
        key=lambda item: _parse_suffix_token(_suffix_token_from_path(item) or "A0000")[
            0
        ]
    )
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


def _has_valid_id_value(value: Any) -> bool:
    """业务 ID 列非空且非纯空白时视为有效。"""
    if value is None:
        return False
    if isinstance(value, str) and value.strip() == "":
        return False
    return True


def _build_payload_from_toml(
    cfg: GetTomlValues, incoming: dict[str, Any]
) -> dict[str, Any]:
    """
    函数名: _build_payload_from_toml
    作用: 按当前 TOML 全体 Input_label 生成落库 JSON；incoming 无则填空串
    输入:
        cfg (GetTomlValues) - 当前 TOML
        incoming (dict[str, Any]) - 调用方传入的局部 Input_label 值（可含无关键，忽略）
    输出:
        dict[str, Any] - 完整 payload，键 = 全部 Input_label
    """
    payload: dict[str, Any] = {}
    for rule in cfg.field_rules:
        label = rule.Input_label
        if label in incoming and _has_valid_id_value(incoming[label]):
            payload[label] = _json_safe_value(incoming[label])
        else:
            payload[label] = ""
    return payload


def _resolve_records_id(cfg: GetTomlValues, incoming: dict[str, Any]) -> int:
    """
    函数名: _resolve_records_id
    作用: 由 resolve_db_id 指定的 Input_label 在 incoming 中的值推导 records.id，否则自动生成
    输入:
        cfg (GetTomlValues) - TOML 配置
        incoming (dict[str, Any]) - 本次写入的原始字段 dict
    输出:
        int - SQLite 行主键
    """
    label = resolve_db_id(cfg)
    if label is not None and label in incoming and _has_valid_id_value(incoming[label]):
        return _normalize_id(incoming[label])
    return uuid.uuid4().int >> 64


def _json_safe_value(value: Any) -> Any:
    """datetime 等类型转为可 JSON 序列化的值。"""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _row_from_db(row_id: int, data_text: str) -> dict[str, Any]:
    """SQLite 行 → 对外 dict：顶层 id + data 内各 Input_label。"""
    parsed = json.loads(data_text)
    if not isinstance(parsed, dict):
        parsed = {}
    return {"id": row_id, **parsed}


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
    """非常规扩展名 SQLite；records.data 以 JSON 存各 Input_label 登记内容。"""

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

    def insert_or_update(self, incoming: dict[str, Any], cfg: GetTomlValues) -> int:
        """
        函数名: insert_or_update
        作用: 以 TOML 骨架覆盖 data JSON；不读、不合并旧 data
        输入:
            incoming (dict[str, Any]) - 本次登记值（可缺键）
            cfg (GetTomlValues) - 当前 TOML 列定义
        输出:
            int - 写入后的 records.id
        """
        rid = _resolve_records_id(cfg, incoming)
        payload = _build_payload_from_toml(cfg, incoming)
        cur = self.conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO records (id, data) VALUES (?, ?)",
            (rid, json.dumps(payload, ensure_ascii=False)),
        )
        self.conn.commit()
        return rid

    def query_by_id(self, rid: int) -> dict[str, Any] | None:
        """
        函数名: query_by_id
        作用: 按主键读取一条记录（顶层 id + data 内 Input_label）
        输入:
            rid (int) - 记录主键
        输出:
            dict[str, Any] | None - 当前落库记录或 None
        """
        cur = self.conn.cursor()
        cur.execute("SELECT id, data FROM records WHERE id=?", (_normalize_id(rid),))
        row = cur.fetchone()
        if not row:
            return None
        return _row_from_db(row[0], row[1])

    def query_all(self) -> list[dict[str, Any]]:
        """
        函数名: query_all
        作用: 读取全部记录，供 UiProvider.get_data 使用
        输入: 无
        输出:
            list[dict[str, Any]] - 每行含 id 与各 Input_label
        """
        cur = self.conn.cursor()
        cur.execute("SELECT id, data FROM records ORDER BY id")
        return [_row_from_db(row_id, data_text) for row_id, data_text in cur.fetchall()]

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
        作用: 从 DB 读取全部行（records.id + 各 Input_label）
        输入: 无
        输出:
            list[dict[str, Any]] - 与 query_all 一致
        """
        return self.db.query_all()

    def persist_fields(self, incoming: dict[str, Any]) -> int:
        """
        函数名: persist_fields
        作用: incoming 按 TOML 骨架覆盖写入 DB
        输入:
            incoming (dict[str, Any]) - 本次登记值（可缺键）
        输出:
            int - records.id
        """
        return self.db.insert_or_update(incoming, self.cfg)

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
        作用: 路径 A：determiner 拆分后按 index 映射为 dict[Input_label]
        输入:
            raw (str) - textbox 纯字符串
        输出:
            dict[str, Any] - 仅含参与拆分的 Input_label 键
        """
        parts = self.split_by_determiner(raw)
        fields: dict[str, Any] = {}
        max_index = max(
            (rule.index for rule in self.cfg.field_rules if rule.index >= 0), default=-1
        )
        if max_index >= 0 and len(parts) <= max_index:
            raise ValueError(
                f"textbox split into {len(parts)} part(s), need at least {max_index + 1}"
            )
        # 仅 index>=0 的 rule 参与拆分；index=-1 由其它路径补全
        for rule in self.cfg.field_rules:
            if rule.index < 0:
                continue
            fields[rule.Input_label] = parts[rule.index]
        return fields
