import json
import os
from pathlib import Path

import gspread
import polars as pl
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from app.services.excel_parser import parse_spreadsheet_id

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

GOOGLE_CLOUD_HOME_URL = "https://console.cloud.google.com/"
GOOGLE_SHEETS_API_URL = "https://console.cloud.google.com/flows/enableapi?apiid=sheets.googleapis.com"
GOOGLE_OAUTH_CONSENT_URL = "https://console.cloud.google.com/apis/credentials/consent"
GOOGLE_OAUTH_AUDIENCE_URL = "https://console.cloud.google.com/auth/audience"
GOOGLE_OAUTH_CREATE_CLIENT_URL = "https://console.cloud.google.com/apis/credentials/oauthclient"
GOOGLE_CREDENTIALS_URL = "https://console.cloud.google.com/apis/credentials"
_APP_DIR = Path(__file__).resolve().parents[1]
_OAUTH_DIR = _APP_DIR / "oauth"
_OAUTH_CLIENT_PATH = _OAUTH_DIR / "oauth_client.json"
_OAUTH_TOKEN_PATH = _OAUTH_DIR / "authorized_user.json"
_LEGACY_CLIENT_PATH = Path(__file__).resolve().parents[2] / "credentials" / "oauth_client.json"


class GoogleSheetsError(Exception):
    def __init__(self, message: str, hints: list[str] | None = None):
        super().__init__(message)
        self.hints = hints or []


class OAuthClientNotConfiguredError(GoogleSheetsError):
    pass


def _gspread_credentials_path() -> Path | None:
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        candidate = Path(appdata) / "gspread" / "credentials.json"
        if candidate.is_file():
            return candidate
    candidate = Path.home() / ".config" / "gspread" / "credentials.json"
    if candidate.is_file():
        return candidate
    return None


def find_oauth_client_path() -> Path | None:
    for candidate in (_OAUTH_CLIENT_PATH, _LEGACY_CLIENT_PATH, _gspread_credentials_path()):
        if candidate and candidate.is_file():
            return candidate
    return None


def has_oauth_client() -> bool:
    return find_oauth_client_path() is not None


def stored_oauth_client_path() -> Path | None:
    if _OAUTH_CLIENT_PATH.is_file():
        return _OAUTH_CLIENT_PATH
    if _LEGACY_CLIENT_PATH.is_file():
        return _LEGACY_CLIENT_PATH
    return None


def remove_stored_oauth() -> list[str]:
    removed: list[str] = []
    for path in (_OAUTH_CLIENT_PATH, _OAUTH_TOKEN_PATH, _LEGACY_CLIENT_PATH):
        if path.is_file():
            path.unlink()
            removed.append(str(path))
    return removed


def save_oauth_client_json(raw: bytes) -> Path:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GoogleSheetsError("不是有效的 JSON 文件") from exc
    if "installed" not in payload and "web" not in payload:
        raise GoogleSheetsError(
            "这不是 OAuth 客户端文件",
            ["请在 Google Cloud 创建「桌面应用」OAuth 客户端并下载 JSON"],
        )
    _OAUTH_DIR.mkdir(parents=True, exist_ok=True)
    _OAUTH_CLIENT_PATH.write_bytes(raw)
    return _OAUTH_CLIENT_PATH


def _save_token(credentials: Credentials) -> None:
    _OAUTH_DIR.mkdir(parents=True, exist_ok=True)
    _OAUTH_TOKEN_PATH.write_text(credentials.to_json(), encoding="utf-8")


def _load_cached_credentials() -> Credentials | None:
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
        _save_token(credentials)
        return credentials
    return None


def run_oauth_flow() -> Credentials:
    client_path = find_oauth_client_path()
    if client_path is None:
        raise OAuthClientNotConfiguredError(
            "尚未配置 OAuth 客户端",
            [],
        )

    cached = _load_cached_credentials()
    if cached is not None:
        return cached

    flow = InstalledAppFlow.from_client_secrets_file(str(client_path), SCOPES)
    credentials = flow.run_local_server(port=0, open_browser=True)
    _save_token(credentials)
    return credentials


def open_gspread_client(credentials) -> gspread.Client:
    return gspread.authorize(credentials)


def fetch_sheet_preview(
    credentials,
    spreadsheet_id_or_url: str,
    worksheet_name: str | None,
    max_rows: int = 10,
) -> tuple[pl.DataFrame, dict]:
    """
    Fetch preview of Google Sheet data using polars
    
    Args:
        credentials: Google OAuth credentials
        spreadsheet_id_or_url: Sheet ID or full URL
        worksheet_name: Optional worksheet name (defaults to first sheet)
        max_rows: Maximum number of rows to preview
    
    Returns:
        Tuple of (polars DataFrame, metadata dict)
    """
    spreadsheet_id = parse_spreadsheet_id(spreadsheet_id_or_url)
    try:
        client = open_gspread_client(credentials)
        spreadsheet = client.open_by_key(spreadsheet_id)
    except gspread.exceptions.SpreadsheetNotFound as exc:
        raise GoogleSheetsError(
            "找不到该 Spreadsheet（404）",
            ["确认 Sheet ID 正确", "确认当前 Google 账号有权访问该表格"],
        ) from exc
    except PermissionError as exc:
        raise GoogleSheetsError(
            "无权限访问该 Spreadsheet（403）",
            ["使用有权限的 Google 账号重新连接", "确认该表格已共享给你的账号"],
        ) from exc
    except Exception as exc:
        message = str(exc)
        if "403" in message or "permission" in message.lower():
            raise GoogleSheetsError(
                "无权限访问该 Spreadsheet",
                ["检查表格是否已共享", "检查 API 是否已在 Google Cloud 启用"],
            ) from exc
        raise GoogleSheetsError(f"连接失败: {message}") from exc
    if worksheet_name:
        try:
            worksheet = spreadsheet.worksheet(worksheet_name)
        except gspread.exceptions.WorksheetNotFound as exc:
            titles = [ws.title for ws in spreadsheet.worksheets()]
            raise GoogleSheetsError(
                f"工作表 '{worksheet_name}' 不存在",
                [f"可用工作表: {', '.join(titles)}"],
            ) from exc
    else:
        worksheet = spreadsheet.sheet1
    
    values = worksheet.get_all_values()
    if not values:
        dataframe = pl.DataFrame()
    else:
        header = values[0]
        rows = values[1 : max_rows + 1] if len(values) > 1 else []
        if rows:
            # Create polars DataFrame with explicit schema
            dataframe = pl.DataFrame(rows, schema=header, orient="row")
        else:
            # Empty DataFrame with column names
            dataframe = pl.DataFrame({col: [] for col in header})
    
    meta = {
        "spreadsheet_title": spreadsheet.title,
        "worksheet_title": worksheet.title,
        "spreadsheet_id": spreadsheet_id,
        "row_count": len(values),
    }
    return dataframe, meta


def fetch_all_rows(
    credentials,
    spreadsheet_id_or_url: str,
    worksheet_name: str | None
) -> pl.DataFrame:
    """
    Fetch all rows from Google Sheet using polars (for bulk import)
    
    Args:
        credentials: Google OAuth credentials
        spreadsheet_id_or_url: Sheet ID or full URL
        worksheet_name: Optional worksheet name (defaults to first sheet)
    
    Returns:
        polars DataFrame with all rows
    """
    spreadsheet_id = parse_spreadsheet_id(spreadsheet_id_or_url)
    try:
        client = open_gspread_client(credentials)
        spreadsheet = client.open_by_key(spreadsheet_id)
    except gspread.exceptions.SpreadsheetNotFound as exc:
        raise GoogleSheetsError("找不到该 Spreadsheet（404）") from exc
    except Exception as exc:
        message = str(exc)
        if "403" in message or "permission" in message.lower():
            raise GoogleSheetsError("无权限访问该 Spreadsheet") from exc
        raise GoogleSheetsError(f"连接失败: {message}") from exc
    
    worksheet = _resolve_worksheet(spreadsheet, worksheet_name)
    values = worksheet.get_all_values()
    
    if not values:
        return pl.DataFrame()
    
    header = values[0]
    rows = values[1:]
    
    if rows:
        return pl.DataFrame(rows, schema=header, orient="row")
    else:
        return pl.DataFrame({col: [] for col in header})


def list_worksheet_titles(credentials, spreadsheet_id_or_url: str) -> list[str]:
    spreadsheet_id = parse_spreadsheet_id(spreadsheet_id_or_url)
    try:
        client = open_gspread_client(credentials)
        spreadsheet = client.open_by_key(spreadsheet_id)
    except gspread.exceptions.SpreadsheetNotFound as exc:
        raise GoogleSheetsError(
            "找不到该 Spreadsheet（404）",
            ["确认 Sheet ID 正确", "确认当前 Google 账号有权访问该表格"],
        ) from exc
    except Exception as exc:
        message = str(exc)
        if "403" in message or "permission" in message.lower():
            raise GoogleSheetsError(
                "无权限访问该 Spreadsheet",
                ["使用有权限的 Google 账号重新连接"],
            ) from exc
        raise GoogleSheetsError(f"连接失败: {message}") from exc
    return [worksheet.title for worksheet in spreadsheet.worksheets()]


def _resolve_worksheet(spreadsheet, worksheet_name: str | None):
    if worksheet_name:
        try:
            return spreadsheet.worksheet(worksheet_name)
        except gspread.exceptions.WorksheetNotFound as exc:
            titles = [ws.title for ws in spreadsheet.worksheets()]
            raise GoogleSheetsError(
                f"工作表 '{worksheet_name}' 不存在",
                [f"可用工作表: {', '.join(titles)}"],
            ) from exc
    return spreadsheet.sheet1


def fetch_row_by_id(
    credentials,
    spreadsheet_id_or_url: str,
    worksheet_name: str | None,
    id_column: str,
    id_value: str,
) -> dict[str, str] | None:
    """
    Fetch a single row by ID using polars for query, return as dict
    
    Args:
        credentials: Google OAuth credentials
        spreadsheet_id_or_url: Sheet ID or full URL
        worksheet_name: Optional worksheet name
        id_column: Column name containing ID
        id_value: ID value to search for
    
    Returns:
        Dict of column_name: value, or None if not found
    """
    spreadsheet_id = parse_spreadsheet_id(spreadsheet_id_or_url)
    search_value = id_value.strip()
    if not search_value:
        raise GoogleSheetsError("ID 值不能为空")
    
    try:
        client = open_gspread_client(credentials)
        spreadsheet = client.open_by_key(spreadsheet_id)
    except gspread.exceptions.SpreadsheetNotFound as exc:
        raise GoogleSheetsError("找不到该 Spreadsheet（404）") from exc
    except Exception as exc:
        message = str(exc)
        if "403" in message or "permission" in message.lower():
            raise GoogleSheetsError("无权限访问该 Spreadsheet") from exc
        raise GoogleSheetsError(f"连接失败: {message}") from exc
    
    worksheet = _resolve_worksheet(spreadsheet, worksheet_name)
    values = worksheet.get_all_values()
    
    if not values:
        return None
    
    header = values[0]
    rows = values[1:]
    
    if not rows:
        return None
    
    # Use polars for efficient filtering
    df = pl.DataFrame(rows, schema=header, orient="row")
    
    id_col = id_column.strip()
    if id_col not in df.columns:
        raise GoogleSheetsError(
            f"未找到 ID 列「{id_col}」",
            [f"可用列: {', '.join(df.columns)}"],
        )
    
    # Filter by ID value
    result = df.filter(pl.col(id_col).str.strip_chars() == search_value)
    
    if result.height == 0:
        return None
    
    # Return first matching row as dict
    return result.row(0, named=True)
