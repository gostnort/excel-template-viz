import json
from pathlib import Path

import gspread
import pandas as pd
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow

from app.services.excel_parser import parse_spreadsheet_id

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
OAUTH_CLIENT_PATH = Path(__file__).resolve().parents[2] / "credentials" / "oauth_client.json"


class GoogleSheetsError(Exception):
    # Google Sheets 操作失败时携带用户可读说明
    def __init__(self, message: str, hints: list[str] | None = None):
        super().__init__(message)
        self.hints = hints or []


def credentials_from_service_account_json(raw_json: str) -> ServiceAccountCredentials:
    # 从上传的 JSON 字符串构建服务账号凭证
    try:
        info = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise GoogleSheetsError("服务账号 JSON 格式无效", ["请上传 Google Cloud 控制台下载的完整 JSON 密钥"]) from exc
    email = info.get("client_email", "")
    creds = ServiceAccountCredentials.from_service_account_info(info, scopes=SCOPES)
    creds.extra = {"service_account_email": email}
    return creds


def run_oauth_flow() -> Credentials:
    # 使用本地 oauth_client.json 启动 OAuth 浏览器授权
    if not OAUTH_CLIENT_PATH.exists():
        raise GoogleSheetsError(
            "未找到 OAuth 客户端配置文件",
            [
                f"请将 Google Cloud OAuth 客户端 JSON 放到: {OAUTH_CLIENT_PATH}",
                "API 控制台需启用 Google Sheets API",
            ],
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(OAUTH_CLIENT_PATH), SCOPES)
    return flow.run_local_server(port=0)


def open_gspread_client(credentials) -> gspread.Client:
    # 统一打开 gspread 客户端
    return gspread.authorize(credentials)


def fetch_sheet_preview(
    credentials,
    spreadsheet_id_or_url: str,
    worksheet_name: str | None,
    max_rows: int = 10,
) -> tuple[pd.DataFrame, dict]:
    # 读取表格前几行，返回 DataFrame 与元信息
    spreadsheet_id = parse_spreadsheet_id(spreadsheet_id_or_url)
    try:
        client = open_gspread_client(credentials)
        spreadsheet = client.open_by_key(spreadsheet_id)
    except gspread.exceptions.SpreadsheetNotFound as exc:
        raise GoogleSheetsError(
            "找不到该 Spreadsheet（404）",
            ["确认 Sheet ID 正确", "确认已将该表格共享给服务账号邮箱或当前 OAuth 用户"],
        ) from exc
    except PermissionError as exc:
        raise GoogleSheetsError(
            "无权限访问该 Spreadsheet（403）",
            ["服务账号：在 Google Sheet 共享中添加 client_email", "OAuth：使用有权限的 Google 账号登录"],
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
        dataframe = pd.DataFrame()
    else:
        header = values[0]
        rows = values[1 : max_rows + 1] if len(values) > 1 else []
        dataframe = pd.DataFrame(rows, columns=header)
    meta = {
        "spreadsheet_title": spreadsheet.title,
        "worksheet_title": worksheet.title,
        "spreadsheet_id": spreadsheet_id,
        "row_count": len(values),
    }
    return dataframe, meta
