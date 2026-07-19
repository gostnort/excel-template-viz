"""UI 纯字符串入 DB 与 Gradio 数据供给（路径 A）。见 docs/data_flow_design.md。"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import sqlite3
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from app.core_connect import _apply_regex
from app.core_registry import TEMPLATES_DIR
from app.core_toml import GetTomlValues, resolve_db_id


_ACTIVE_POINTER_SUFFIX = ".active"
_FORBIDDEN_DB_SUFFIXES = (".db", ".sqlite", ".sql")
_SUFFIX_TOKEN_PATTERN = re.compile(r"^[A-Z]\d{4}$")
_SQLITE_INT_MIN = -9223372036854775808
_SQLITE_INT_MAX = 9223372036854775807


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


def _template_dir(template_id: str) -> Path:
    """模板 sidecar 目录：与 {template_id}.toml 同级。"""
    return TEMPLATES_DIR / template_id


def _active_pointer_path(template_id: str) -> Path:
    return _template_dir(template_id) / f"{template_id}{_ACTIVE_POINTER_SUFFIX}"


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
    sidecar = _template_dir(template_id)
    sidecar.mkdir(parents=True, exist_ok=True)
    _active_pointer_path(template_id).write_text(suffix_token, encoding="utf-8")


def _db_path_for_suffix_token(template_id: str, suffix_token: str) -> Path:
    return _template_dir(template_id) / f"{template_id}.{suffix_token}"


def list_db_paths(template_id: str, year: int | None = None) -> list[Path]:
    """
    函数名: list_db_paths
    作用: 列出 templates/{template_id}/ 下某模板在指定年份的全部数据库文件
    输入:
        template_id (str) - 模板 ID（与 xlsx stem 规范化后一致）
        year (int | None) - 年份，默认当前年
    输出:
        list[Path] - 按字母序排序的路径列表
    """
    if year is None:
        year = _current_year()
    sidecar = _template_dir(template_id)
    if not sidecar.is_dir():
        return []
    paths: list[Path] = []
    for candidate in sidecar.glob(f"{template_id}.*"):
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
        Path - templates/{template_id}/{template_id}.{Letter}{Year}
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


def _sqlite_safe_int(value: int) -> int:
    """拒绝超出 SQLite INTEGER 有符号 64 位范围的值。"""
    if value < _SQLITE_INT_MIN or value > _SQLITE_INT_MAX:
        raise ValueError(
            f"ID {value} exceeds SQLite INTEGER range "
            f"[{_SQLITE_INT_MIN}, {_SQLITE_INT_MAX}]"
        )
    return value


def _auto_records_id() -> int:
    # uuid 高 64 位常超过有符号 INTEGER 上限；保留低 63 位正整数
    rid = uuid.uuid4().int & _SQLITE_INT_MAX
    return rid or 1


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
        return _sqlite_safe_int(value)
    if isinstance(value, float):
        return _sqlite_safe_int(int(value))
    text = str(value).strip()
    if not text:
        raise ValueError("ID cannot be empty")
    if "." in text:
        return _sqlite_safe_int(int(float(text)))
    return _sqlite_safe_int(int(text))


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
            raw = incoming[label]
            payload[label] = _json_safe_value(_apply_regex(raw, rule.regex))
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
    return _auto_records_id()


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
        作用: 打开或创建 templates/{template_id}/ 下 {template_id}.{Letter}{Year} 并确保表结构存在
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
        作用: 创建 records(id, data) 表与 record_images 表（若不存在）
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
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS record_images (
                image_id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id TEXT NOT NULL,
                record_id INTEGER NOT NULL,
                input_label TEXT NOT NULL,
                image_path TEXT NOT NULL,
                mime TEXT NOT NULL,
                width INTEGER,
                height INTEGER,
                file_size INTEGER,
                content_hash TEXT,
                crop_box TEXT,
                ocr_text TEXT,
                ocr_engine TEXT,
                ocr_version TEXT,
                ocr_status TEXT,
                excel_sheet_name TEXT,
                excel_anchor TEXT,
                excel_target_cell TEXT,
                excel_offset_x INTEGER DEFAULT 0,
                excel_offset_y INTEGER DEFAULT 0,
                excel_scale_x REAL DEFAULT 1.0,
                excel_scale_y REAL DEFAULT 1.0,
                excel_fit_strategy TEXT DEFAULT 'none',
                excel_render_order INTEGER DEFAULT 0,
                excel_render_mode TEXT DEFAULT 'overlay',
                created_at TEXT NOT NULL,
                updated_at TEXT,
                is_deleted INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        # 增加查询索引
        cur.execute("CREATE INDEX IF NOT EXISTS idx_record_images_history ON record_images(template_id, record_id, input_label, created_at DESC)")
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

    def save_image(
        self,
        cfg: GetTomlValues,
        template_id: str,
        record_id: int,
        input_label: str,
        image_bytes: bytes,
        mime: str,
        crop_box: tuple[int, int, int, int] | None = None
    ) -> dict[str, Any]:
        """
        函数名: save_image
        作用: 持久化原图并写入 record_images 元数据
        输入:
            cfg (GetTomlValues): TOML 配置
            template_id (str): 模板 ID
            record_id (int): 记录 ID
            input_label (str): 字段标签
            image_bytes (bytes): 图片二进制内容
            mime (str): MIME 类型
            crop_box (tuple | None): (x, y, w, h) 截图框
        输出:
            dict: 成功含 image_id 和 ok=True，失败含 ok=False 和 message
        """
        # 校验 label 是否属于配置
        valid_labels = {rule.Input_label for rule in cfg.field_rules}
        if input_label not in valid_labels:
            return {"ok": False, "message": "字段标签无效，无法保存图片。"}

        if not image_bytes:
            return {"ok": False, "message": "无法读取图片，请重新拍照或选择文件。"}

        try:
            img = Image.open(BytesIO(image_bytes))
            width, height = img.size
        except Exception:
            return {"ok": False, "message": "无法识别图片格式，请重新拍照。"}
        
        file_size = len(image_bytes)
        content_hash = hashlib.sha256(image_bytes).hexdigest()
        
        # 构造存储路径 templates/{template_id}/images/{record_id}/{uuid}.{ext}
        ext = mime.split("/")[-1] if "/" in mime else "jpg"
        if ext == "jpeg":
            ext = "jpg"
        unique_name = f"{uuid.uuid4().hex}.{ext}"
        rel_path = f"images/{record_id}/{unique_name}"
        
        # 物理路径
        template_dir = _template_dir(template_id)
        abs_path = template_dir / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 保存文件
        try:
            abs_path.write_bytes(image_bytes)
        except Exception:
            return {"ok": False, "message": "存储不可用，图片未能保存。"}
            
        crop_box_str = json.dumps(list(crop_box)) if crop_box else None
        created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        cur = self.conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO record_images (
                    template_id, record_id, input_label, image_path, mime,
                    width, height, file_size, content_hash, crop_box, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    template_id, record_id, input_label, rel_path, mime,
                    width, height, file_size, content_hash, crop_box_str, created_at
                )
            )
            self.conn.commit()
            image_id = cur.lastrowid
            return {"ok": True, "message": "图片已保存。", "image_id": image_id, "image_path": rel_path}
        except Exception:
            self.conn.rollback()
            try:
                abs_path.unlink(missing_ok=True)
            except Exception:
                pass
            return {"ok": False, "message": "图片保存失败，请稍后重试。"}

    def get_latest_image(self, template_id: str, record_id: int, input_label: str) -> dict[str, Any] | None:
        """
        函数名: get_latest_image
        作用: 查询指定维度下未删除的最新一张图片记录
        输入:
            template_id (str): 模板 ID
            record_id (int): 记录 ID
            input_label (str): 字段标签
        输出:
            dict | None: 图片元数据记录或 None
        """
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT image_id, image_path, mime, width, height, ocr_text, ocr_status, crop_box
            FROM record_images 
            WHERE template_id=? AND record_id=? AND input_label=? AND is_deleted=0
            ORDER BY created_at DESC LIMIT 1
            """,
            (template_id, record_id, input_label)
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "image_id": row[0],
            "image_path": row[1],
            "mime": row[2],
            "width": row[3],
            "height": row[4],
            "ocr_text": row[5],
            "ocr_status": row[6],
            "crop_box": json.loads(row[7]) if row[7] else None
        }

    def list_images_by_label(self, template_id: str, record_id: int, input_label: str) -> list[dict[str, Any]]:
        """
        函数名: list_images_by_label
        作用: 查询指定字段标签下的所有图片历史（按时间倒序）
        输入:
            template_id (str): 模板 ID
            record_id (int): 记录 ID
            input_label (str): 字段标签
        输出:
            list[dict]: 图片元数据记录列表
        """
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT image_id, image_path, mime, width, height, ocr_text, ocr_status, created_at
            FROM record_images 
            WHERE template_id=? AND record_id=? AND input_label=? AND is_deleted=0
            ORDER BY created_at DESC
            """,
            (template_id, record_id, input_label)
        )
        return [
            {
                "image_id": r[0], "image_path": r[1], "mime": r[2], 
                "width": r[3], "height": r[4], "ocr_text": r[5], 
                "ocr_status": r[6], "created_at": r[7]
            }
            for r in cur.fetchall()
        ]

    def update_image_ocr(
        self,
        image_id: int,
        ocr_text: str | None,
        ocr_engine: str | None = None,
        ocr_version: str | None = None,
        ocr_status: str | None = None,
        crop_box: tuple[int, int, int, int] | None = None
    ) -> dict[str, Any]:
        """
        函数名: update_image_ocr
        作用: 回写图像的 OCR 识别结果，不改动图片内容
        输入:
            image_id (int): 图片记录主键
            ocr_text (str | None): 识别结果原文
            ocr_engine (str | None): 引擎名
            ocr_version (str | None): 版本名
            ocr_status (str | None): 识别状态
            crop_box (tuple | None): 用于此次识别的截取区域
        输出:
            dict: {ok: bool, message: str}
        """
        cur = self.conn.cursor()
        cur.execute("SELECT image_id FROM record_images WHERE image_id=? AND is_deleted=0", (image_id,))
        if not cur.fetchone():
            return {"ok": False, "message": "未找到对应图片，无法保存识别结果。"}
            
        updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        updates = []
        params = []
        if ocr_text is not None:  # We'll allow empty string to clear it
            updates.append("ocr_text=?")
            params.append(ocr_text)
        if ocr_engine is not None:
            updates.append("ocr_engine=?")
            params.append(ocr_engine)
        if ocr_version is not None:
            updates.append("ocr_version=?")
            params.append(ocr_version)
        if ocr_status is not None:
            updates.append("ocr_status=?")
            params.append(ocr_status)
        if crop_box is not None:
            updates.append("crop_box=?")
            params.append(json.dumps(list(crop_box)))
            
        if not updates:
            return {"ok": True, "message": "无更新内容。"}
            
        updates.append("updated_at=?")
        params.append(updated_at)
        params.append(image_id)
        
        try:
            cur.execute(
                f"UPDATE record_images SET {', '.join(updates)} WHERE image_id=?",
                tuple(params)
            )
            self.conn.commit()
            return {"ok": True, "message": "识别结果已保存。"}
        except Exception:
            self.conn.rollback()
            return {"ok": False, "message": "识别结果保存失败，请稍后重试。"}

    def close(self) -> None:
        """
        函数名: close
        作用: 关闭数据库连接
        输入: 无
        输出: 无
        """
        self.conn.close()

def _ocr_json_to_flat_kv(data: dict) -> dict[str, str]:
    """从 PaddleOcr result dict 提取扁平 key->value（string* + table cells 交替对）"""
    flat = {}
    # 1. table1..N
    for k in sorted(data.keys()):
        if k.startswith("table") and isinstance(data[k], list):
            for row in data[k]:
                if isinstance(row, dict) and "cells" in row:
                    cells = row["cells"]
                    if not isinstance(cells, list):
                        continue
                    for i in range(0, len(cells) - 1, 2):
                        key = str(cells[i]).strip()
                        val = str(cells[i+1]).strip()
                        if key:
                            flat[key] = val

    # 2. string1..N (会覆盖同名的 table 提取结果，优先级由字典遍历顺序决定，这里 string1..N 提取的是单行键值)
    pattern = re.compile(r"^([^：:]+)[：:](.*)$")
    for k in sorted(data.keys()):
        if k.startswith("string") and isinstance(data[k], str):
            line = data[k].strip()
            match = pattern.fullmatch(line)
            if match:
                key = match.group(1).strip()
                val = match.group(2).strip()
                if key:
                    flat[key] = val

    return flat

def _map_flat_kv_to_fields(flat: dict[str, str], field_rules: list) -> dict[str, Any]:
    """Input_label 精确匹配 -> 规范化 -> 唯一模糊匹配；值经 _apply_regex"""
    fields = {}
    
    def normalize_key(k: str) -> str:
        return k.replace(" ", "").replace("　", "")
        
    for rule in field_rules:
        target_label = rule.Input_label
        norm_target = normalize_key(target_label)
        
        # 1. 精确匹配
        if target_label in flat:
            fields[target_label] = _apply_regex(flat[target_label], getattr(rule, "regex", ""))
            continue
            
        # 2. 规范化精确匹配
        matched = False
        for k, v in flat.items():
            if normalize_key(k) == norm_target:
                fields[target_label] = _apply_regex(v, getattr(rule, "regex", ""))
                matched = True
                break
        if matched:
            continue
            
        # 3. 模糊匹配（仅当唯一命中）
        candidates = []
        for k, v in flat.items():
            norm_k = normalize_key(k)
            if target_label in k or k in target_label or norm_target in norm_k or norm_k in norm_target:
                candidates.append(v)
        if len(candidates) == 1:
            fields[target_label] = _apply_regex(candidates[0], getattr(rule, "regex", ""))

    return fields

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
        作用: 路径 A：determiner 拆分后按 index 映射为 dict[Input_label]。若输入为合法 OCR JSON，则按字段名进行匹配填充。
        输入:
            raw (str) - textbox 纯字符串
        输出:
            dict[str, Any] - 仅含参与拆分的 Input_label 键
        """
        stripped = raw.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                data = json.loads(stripped)
                if isinstance(data, dict) and data.get("ok") is not False:
                    flat = _ocr_json_to_flat_kv(data)
                    if flat:
                        return _map_flat_kv_to_fields(flat, self.cfg.field_rules)
            except (json.JSONDecodeError, TypeError):
                pass
                
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
            fields[rule.Input_label] = _apply_regex(parts[rule.index], rule.regex)
        return fields
