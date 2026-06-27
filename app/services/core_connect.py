"""Google Sheets connection and in-memory query (TOML-only).

See docs/connect_google.md for the full contract. Two public classes:
- ConnectGoogle: OAuth authorize / connect / disconnect; loads all TOML sources.
- SheetOperation: read-only view over loaded memory; ID list + field lookup for UI.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import gspread
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from app.services.core_toml import GetTomlValues, TomlDefault


SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
_APP_DIR = Path(__file__).resolve().parents[1]
_OAUTH_DIR = _APP_DIR / "oauth"
_OAUTH_CLIENT_PATH = _OAUTH_DIR / "oauth_client.json"
_OAUTH_TOKEN_PATH = _OAUTH_DIR / "authorized_user.json"
_SPREADSHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")
_BARE_ID_RE = re.compile(r"^[a-zA-Z0-9-_]+$")


class ConnectGoogleError(Exception):
    """Any failure in OAuth, connect, or memory access."""

    def __init__(self, message: str, hints: list[str] | None = None) -> None:
        super().__init__(message)
        self.hints = hints or []



@dataclass
class SpreadsheetMeta:
    """One opened spreadsheet bound to a TOML source alias."""

    source_alias: str
    url: str
    spreadsheet_id: str
    title: str
    handle: gspread.Spreadsheet



@dataclass
class IdRow:
    """One selectable ID row for the UI multi-select list."""

    id_value: str
    source_alias: str
    source_sheet: str
    row_index: int



@dataclass
class FieldRecord:
    """TOML-mapped field values for one requested ID."""

    id_value: str
    found: bool
    source_alias: str
    source_sheet: str
    row_index: int | None
    data: dict[str, Any] = field(default_factory=dict)



@dataclass
class FetchFieldsResult:
    """Payload for the UI: primary id sheet snapshot plus per-ID records."""

    sheet_rows: list[dict[str, str]]
    source_alias: str
    source_sheet: str
    records: list[FieldRecord] = field(default_factory=list)



def _parse_spreadsheet_id(url_or_id: str) -> str:
    """Extract spreadsheet id from a full URL or accept a bare id."""
    text = (url_or_id or "").strip()
    if not text:
        raise ConnectGoogleError("数据源 URL 为空")
    match = _SPREADSHEET_ID_RE.search(text)
    if match:
        return match.group(1)
    if _BARE_ID_RE.match(text):
        return text
    raise ConnectGoogleError(f"无法解析 Google Sheet 链接: {text}")


def _resolve_source_url(cfg: GetTomlValues, source_alias: str) -> str:
    """Look up an alias in cfg.sources; raise if missing or empty."""
    for item in cfg.sources:
        if source_alias not in item:
            continue
        raw = item[source_alias]
        if raw is None or str(raw).strip() == "":
            raise ConnectGoogleError(
                f"数据源「{source_alias}」未配置链接",
                ["在 TOML [[sources]] 中填入完整 Google Sheet URL"],
            )
        return str(raw).strip()
    raise ConnectGoogleError(f"TOML 未定义数据源别名「{source_alias}」")


def _id_column_for_rule(rule: TomlDefault) -> str:
    """ID column name on an id=true rule: field if mapped, else Input_label."""
    if rule.field and str(rule.field).strip():
        return str(rule.field).strip()
    return rule.Input_label


def _column_names_for_rule(rule: TomlDefault) -> list[str]:
    """Data column lookup order: field first, then Input_label."""
    names: list[str] = []
    if rule.field and str(rule.field).strip():
        names.append(str(rule.field).strip())
    if rule.Input_label not in names:
        names.append(rule.Input_label)
    return names


def _apply_regex(value: Any, pattern: str | None) -> Any:
    """Extract via regex when pattern set; group(1) if a capture group exists."""
    if pattern is None or str(pattern).strip() == "":
        return value
    if value is None:
        return value
    match = re.search(pattern, str(value))
    if not match:
        return value
    if match.lastindex:
        return match.group(1)
    return match.group(0)


def _id_equals(cell: Any, target: str) -> bool:
    """Compare a cell to an ID value as strings, with numeric fallback."""
    if cell is None:
        return False
    if str(cell).strip() == target:
        return True
    # Excel/Sheets numeric ids may render as "123.0" while target is "123"
    try:
        if str(int(float(cell))) == target:
            return True
    except (ValueError, TypeError):
        pass
    return False


def _find_row_by_id_columns(
    rows: list[dict[str, str]],
    id_columns: list[str],
    id_value: str,
) -> tuple[int, dict[str, str]] | None:
    """OR-match a row across id_columns; first matching row wins."""
    target = str(id_value).strip()
    if not target:
        return None
    for index, row in enumerate(rows):
        for column in id_columns:
            if column in row and _id_equals(row[column], target):
                return index, row
    return None



class ConnectGoogle:
    """Owns credentials, per-source spreadsheets, and loaded worksheet tables."""

    def __init__(self) -> None:
        self._credentials: Credentials | None = None
        self._cfg: GetTomlValues | None = None
        self._spreadsheets: dict[str, SpreadsheetMeta] = {}
        self._tables: dict[tuple[str, str], list[dict[str, str]]] = {}
        self._id_columns_by_sheet: dict[tuple[str, str], list[str]] = {}
        self._primary_id_sheet: tuple[str, str] | None = None
        self._connected = False


    def authorize(self) -> None:
        """
        函数名: ConnectGoogle.authorize
        作用: 确保拥有可用 OAuth 凭据；首次走浏览器授权，之后复用 token 文件
        输入:
            无
        输出:
            无（凭据存入 self._credentials）
        """
        if not _OAUTH_CLIENT_PATH.is_file():
            raise ConnectGoogleError(
                "尚未配置 OAuth 客户端",
                [f"请将桌面应用 OAuth 客户端 JSON 放到 {_OAUTH_CLIENT_PATH}"],
            )
        credentials = self._load_cached_credentials()
        if credentials is None:
            # No valid cached token: run the desktop browser flow once
            flow = InstalledAppFlow.from_client_secrets_file(str(_OAUTH_CLIENT_PATH), SCOPES)
            credentials = flow.run_local_server(port=0, open_browser=True)
            self._save_token(credentials)
        self._credentials = credentials


    def connect(self, cfg: GetTomlValues) -> None:
        """
        函数名: ConnectGoogle.connect
        作用: 按 TOML 打开所有被引用的数据源并把工作表载入内存
        输入:
            cfg (GetTomlValues) - 已解析的 TOML 配置；URL 仅来自 cfg.sources
        输出:
            无（结果存入 self._tables 等）
        """
        if self._credentials is None:
            self.authorize()
        self._validate_and_build_id_map(cfg)
        # Open one spreadsheet per distinct source alias referenced by fields
        client = gspread.authorize(self._credentials)
        aliases = self._referenced_aliases(cfg)
        spreadsheets: dict[str, SpreadsheetMeta] = {}
        for alias in aliases:
            url = _resolve_source_url(cfg, alias)
            spreadsheets[alias] = self._open_spreadsheet(client, alias, url)
        # Load every distinct (alias, worksheet) pair into memory tables
        tables: dict[tuple[str, str], list[dict[str, str]]] = {}
        for alias, sheet_name in self._referenced_sheets(cfg):
            meta = spreadsheets[alias]
            tables[(alias, sheet_name)] = self._load_worksheet(meta, sheet_name)
        self._spreadsheets = spreadsheets
        self._tables = tables
        self._cfg = cfg
        self._connected = True


    def disconnect(self) -> None:
        """
        函数名: ConnectGoogle.disconnect
        作用: 清空本次连接的内存数据；保留凭据与 token 文件
        输入:
            无
        输出:
            无
        """
        self._tables = {}
        self._spreadsheets = {}
        self._id_columns_by_sheet = {}
        self._primary_id_sheet = None
        self._cfg = None
        self._connected = False


    def _load_cached_credentials(self) -> Credentials | None:
        """Load token file; refresh when expired and refreshable."""
        if not _OAUTH_TOKEN_PATH.is_file():
            return None
        try:
            credentials = Credentials.from_authorized_user_file(str(_OAUTH_TOKEN_PATH), SCOPES)
        except (ValueError, json.JSONDecodeError):
            return None
        if credentials and credentials.valid:
            return credentials
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            self._save_token(credentials)
            return credentials
        return None


    def _save_token(self, credentials: Credentials) -> None:
        """Persist the authorized user token under app/oauth/."""
        _OAUTH_DIR.mkdir(parents=True, exist_ok=True)
        _OAUTH_TOKEN_PATH.write_text(credentials.to_json(), encoding="utf-8")


    def _validate_and_build_id_map(self, cfg: GetTomlValues) -> None:
        """
        函数名: ConnectGoogle._validate_and_build_id_map
        作用: 校验每表至多一个 id=true、至少一个 id；构建 ID 列表与主 ID 表
        输入:
            cfg (GetTomlValues) - TOML 配置
        输出:
            无（写入 _id_columns_by_sheet 与 _primary_id_sheet）
        """
        own_id_columns: dict[tuple[str, str], str] = {}
        primary: tuple[str, str] | None = None
        # First pass: each sheet may declare at most one id=true column
        for rule in cfg.field_rules:
            if not rule.id:
                continue
            if not rule.source_file or not rule.source_sheet:
                raise ConnectGoogleError(
                    f"id=true 字段「{rule.Input_label}」缺少 source_file / source_sheet",
                )
            key = (rule.source_file, rule.source_sheet)
            if key in own_id_columns:
                raise ConnectGoogleError(
                    f"工作表 {key[0]}/{key[1]} 配置了多个 id=true",
                    ["每个工作表只能有一个 id=true 字段"],
                )
            own_id_columns[key] = _id_column_for_rule(rule)
            if primary is None:
                primary = key
        if primary is None:
            raise ConnectGoogleError(
                "TOML 未配置任何 id=true 字段",
                ["至少一个工作表需要标记 id=true"],
            )
        # Second pass: sheets without own id inherit all declared id columns (OR)
        inherited = list(own_id_columns.values())
        id_columns_by_sheet: dict[tuple[str, str], list[str]] = {}
        for key in self._referenced_sheets(cfg):
            if key in own_id_columns:
                id_columns_by_sheet[key] = [own_id_columns[key]]
            else:
                id_columns_by_sheet[key] = list(inherited)
        self._id_columns_by_sheet = id_columns_by_sheet
        self._primary_id_sheet = primary


    def _open_spreadsheet(self, client: gspread.Client, alias: str, url: str) -> SpreadsheetMeta:
        """Parse id, open spreadsheet, wrap as SpreadsheetMeta with friendly errors."""
        spreadsheet_id = _parse_spreadsheet_id(url)
        try:
            handle = client.open_by_key(spreadsheet_id)
        except gspread.exceptions.SpreadsheetNotFound as exc:
            raise ConnectGoogleError(
                f"找不到数据源「{alias}」对应的 Spreadsheet（404）",
                ["确认链接正确", "确认当前 Google 账号有权访问该表格"],
            ) from exc
        except Exception as exc:
            message = str(exc)
            if "403" in message or "permission" in message.lower():
                raise ConnectGoogleError(
                    f"无权限访问数据源「{alias}」对应的 Spreadsheet",
                    ["使用有权限的 Google 账号重新连接", "确认该表格已共享给你的账号"],
                ) from exc
            raise ConnectGoogleError(f"连接数据源「{alias}」失败: {message}") from exc
        return SpreadsheetMeta(
            source_alias=alias,
            url=url,
            spreadsheet_id=spreadsheet_id,
            title=handle.title,
            handle=handle,
        )


    def _load_worksheet(self, meta: SpreadsheetMeta, sheet_name: str) -> list[dict[str, str]]:
        """
        函数名: ConnectGoogle._load_worksheet
        作用: 读取某工作表全部值，首行作表头，组装行字典列表
        输入:
            meta (SpreadsheetMeta) - 已打开的 spreadsheet
            sheet_name (str) - 工作表 tab 名
        输出:
            list[dict[str, str]] - 每行 {表头: 值}
        """
        try:
            worksheet = meta.handle.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound as exc:
            titles = [ws.title for ws in meta.handle.worksheets()]
            raise ConnectGoogleError(
                f"数据源「{meta.source_alias}」中找不到工作表「{sheet_name}」",
                [f"可用工作表: {', '.join(titles)}"],
            ) from exc
        values = worksheet.get_all_values()
        if not values:
            return []
        header = [str(col).strip() for col in values[0]]
        rows: list[dict[str, str]] = []
        # Map each data row onto header keys; ignore cells past the header width
        for raw_row in values[1:]:
            item: dict[str, str] = {}
            for col_index, column in enumerate(header):
                if not column or col_index >= len(raw_row):
                    continue
                item[column] = raw_row[col_index]
            rows.append(item)
        return rows


    @staticmethod
    def _referenced_aliases(cfg: GetTomlValues) -> list[str]:
        """Distinct source aliases referenced by fully-mapped field rules."""
        aliases: list[str] = []
        for rule in cfg.field_rules:
            if not rule.source_file or not rule.source_sheet:
                continue
            if rule.source_file not in aliases:
                aliases.append(rule.source_file)
        return aliases


    @staticmethod
    def _referenced_sheets(cfg: GetTomlValues) -> list[tuple[str, str]]:
        """Distinct (source_file, source_sheet) pairs from field rules, in order."""
        sheets: list[tuple[str, str]] = []
        for rule in cfg.field_rules:
            if not rule.source_file or not rule.source_sheet:
                continue
            key = (rule.source_file, rule.source_sheet)
            if key not in sheets:
                sheets.append(key)
        return sheets



class SheetOperation:
    """Read-only view over ConnectGoogle memory. No file I/O. No network."""

    def __init__(self, conn: ConnectGoogle) -> None:
        if not conn._connected or conn._cfg is None:
            raise ConnectGoogleError("尚未连接，无法创建 SheetOperation")
        if conn._primary_id_sheet is None:
            raise ConnectGoogleError("连接缺少主 ID 工作表")
        self._conn = conn
        self._cfg = conn._cfg
        self._primary = conn._primary_id_sheet


    def list_ids(self) -> list[IdRow]:
        """
        函数名: SheetOperation.list_ids
        作用: 从主 ID 工作表产出供 UI 多选的 ID 列表
        输入:
            无
        输出:
            list[IdRow] - 每个非空 ID 一行
        """
        alias, sheet_name = self._primary
        rows = self._conn._tables.get(self._primary, [])
        id_columns = self._conn._id_columns_by_sheet.get(self._primary, [])
        id_column = id_columns[0] if id_columns else None
        if id_column is None:
            return []
        result: list[IdRow] = []
        # One IdRow per data row with a non-empty primary ID cell
        for index, row in enumerate(rows):
            raw = row.get(id_column, "")
            value = str(raw).strip() if raw is not None else ""
            if not value:
                continue
            result.append(IdRow(value, alias, sheet_name, index))
        return result


    def fetch_fields(self, id_values: list[str]) -> FetchFieldsResult:
        """
        函数名: SheetOperation.fetch_fields
        作用: 主 ID 表浅拷贝供 UI 展示；按选中的 ID 跨表取 TOML 字段
        输入:
            id_values (list[str]) - 用户多选的 ID
        输出:
            FetchFieldsResult - 含主表浅拷贝与逐 ID 的字段记录
        """
        alias, sheet_name = self._primary
        primary_rows = self._conn._tables.get(self._primary, [])
        sheet_rows = list(primary_rows)
        primary_id_columns = self._conn._id_columns_by_sheet.get(self._primary, [])
        records: list[FieldRecord] = []
        for id_value in id_values:
            records.append(self._build_record(id_value, alias, sheet_name, primary_id_columns))
        return FetchFieldsResult(
            sheet_rows=sheet_rows,
            source_alias=alias,
            source_sheet=sheet_name,
            records=records,
        )


    def _build_record(
        self,
        id_value: str,
        alias: str,
        sheet_name: str,
        primary_id_columns: list[str],
    ) -> FieldRecord:
        """
        函数名: SheetOperation._build_record
        作用: 为单个 ID 在主表定位行，再跨各表按 TOML 字段取值
        输入:
            id_value (str) - 待查 ID
            alias (str) - 主表 source 别名
            sheet_name (str) - 主表工作表名
            primary_id_columns (list[str]) - 主表 ID 列（OR）
        输出:
            FieldRecord - found 与 data 已填充
        """
        primary_rows = self._conn._tables.get(self._primary, [])
        primary_match = _find_row_by_id_columns(primary_rows, primary_id_columns, id_value)
        if primary_match is None:
            return FieldRecord(id_value, False, alias, sheet_name, None, {})
        row_index = primary_match[0]
        # Per-sheet row cache so each (alias, sheet) is matched once per ID
        row_cache: dict[tuple[str, str], dict[str, str] | None] = {}
        data: dict[str, Any] = {}
        for rule in self._cfg.field_rules:
            if not rule.source_file or not rule.source_sheet:
                continue
            key = (rule.source_file, rule.source_sheet)
            matched_row = self._match_row_for_sheet(key, id_value, row_cache)
            if matched_row is None:
                data[rule.Input_label] = ""
                continue
            raw_value = _lookup_value(matched_row, rule)
            data[rule.Input_label] = _apply_regex(raw_value, rule.regex)
        return FieldRecord(id_value, True, alias, sheet_name, row_index, data)


    def _match_row_for_sheet(
        self,
        key: tuple[str, str],
        id_value: str,
        row_cache: dict[tuple[str, str], dict[str, str] | None],
    ) -> dict[str, str] | None:
        """Find (and cache) the row matching id_value on one sheet via OR columns."""
        if key in row_cache:
            return row_cache[key]
        rows = self._conn._tables.get(key, [])
        id_columns = self._conn._id_columns_by_sheet.get(key, [])
        match = _find_row_by_id_columns(rows, id_columns, id_value)
        matched_row = match[1] if match is not None else None
        row_cache[key] = matched_row
        return matched_row


def _lookup_value(row: dict[str, str], rule: TomlDefault) -> Any:
    """Read a field value from a matched row: field column first, then Input_label."""
    for column in _column_names_for_rule(rule):
        if column in row:
            return row[column]
    return None
