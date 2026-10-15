"""列级分流：整格日期正则优先，整数再用表头和唯一率区分 ID 与数量。"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from geodesic_align.month_names import TEXT_MONTH_RE


_EXTERNAL_REF = re.compile(r"\[[^\]]+\]")
_CODE = re.compile(r"^[A-Za-z0-9_#-]+$")
_LETTER = re.compile(r"[A-Za-z]")
_DIGIT = re.compile(r"\d")
_DATETIME_CELL = re.compile(r"^(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{4})[ T]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:\s*[AaPp][Mm])?$")
_DATE_CELL = re.compile(r"^(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{4})$")
_TIME_CELL = re.compile(r"^\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:\s*[AaPp][Mm])?$")
_INT_CELL = re.compile(r"[+-]?\d+")
_ID_HEADER = re.compile(r"(?i)(?<![A-Za-z])(?:id|no|po|code|number)(?![A-Za-z])|编号|单号|工号")
SHORT_CHAR = 16
ID_UNIQUENESS = 0.8
LONG_ID_UNIQUENESS = 0.95
LONG_ID_CHARS = 8
_EMPTY_WORDS = frozenset({
    "", "null", "none", "n/a", "na", "nan", "暂无", "无", "空", "缺失", "-", "--",
    "#n/a", "#na", "nil", "#div/0!", "#ref!", "#name?", "#num!", "#null!", "#value!"
})
_DATE_FAMILY = frozenset({"DATETIME_LITERAL", "DATE_LITERAL", "TIME_LITERAL"})



_DATE_HEADER = re.compile(r"(?i)(?<![A-Za-z])(?:date|time|datetime|timestamp|day|enrollment|trial)(?![A-Za-z])|日期|时间")



def _clean_numeric_str(raw: str) -> str:
    """清理币符、千分位及欧式逗号小数，规范化负数。"""
    clean = raw.replace("\u00a0", " ").strip()
    clean = clean.replace("¥", "").replace("￥", "").replace("$", "").replace("€", "").replace("£", "").strip()
    neg = False
    if clean.startswith("(") and clean.endswith(")"):
        neg = True
        clean = clean[1:-1].strip()
    elif clean.startswith("-"):
        neg = True
        clean = clean[1:].strip()
    clean = clean.replace("¥", "").replace("￥", "").replace("$", "").replace("€", "").replace("£", "").strip()
    if clean.startswith("(") and clean.endswith(")"):
        neg = True
        clean = clean[1:-1].strip()
    if clean.endswith("%"):
        clean = clean[:-1].strip()
    if "." in clean and "," in clean:
        if clean.rfind(",") > clean.rfind("."):
            clean = clean.replace(".", "").replace(",", ".")
        else:
            clean = clean.replace(",", "")
    elif "," in clean:
        parts = clean.split(",")
        if len(parts) == 2:
            if parts[0] in ("0", "-0", "+0", "") or len(parts[1]) != 3:
                clean = clean.replace(",", ".")
            else:
                clean = clean.replace(",", "")
        else:
            clean = clean.replace(",", "")
    elif clean.count(".") > 1:
        dot_parts = clean.split(".")
        if all(len(p) == 3 for p in dot_parts[1:]):
            clean = clean.replace(".", "")
    if neg:
        clean = "-" + clean
    return clean



@dataclass
class ColumnRoute:
    """一列的类型与通道。公式列带原始公式文本。"""

    label: str
    kind: str
    channel: str
    raw_formula: str = ""



def extract_cell_physics(text: str) -> str:
    """
    函数名: extract_cell_physics
    作用: 按字符和符号判断单格物理类型，不看列名
    输入:
        text (str): 单元格字面
    输出:
        str: EMPTY / FORMULA / DATETIME_LITERAL / DATE_LITERAL / TIME_LITERAL / NUMERIC_SCALAR / STRUCTURED_CODE / NATURAL_TEXT
    """
    # 去掉首尾空白，准备按字符和符号判别
    raw = str(text).strip().replace("\u00a0", " ").strip()
    # 得到待判别的格子原文
    # 空字面和哨兵词记为空，不再往下判
    if not raw or raw.lower() in _EMPTY_WORDS:
        return "EMPTY"
    # 得到 EMPTY
    # 等号开头记为公式
    if raw.startswith("="):
        return "FORMULA"
    # 得到 FORMULA
    # 整格必须是日期或时刻，子串里的减号和斜杠不算
    if _DATETIME_CELL.fullmatch(raw):
        return "DATETIME_LITERAL"
    # 得到带时刻的日期字面
    txt_m = TEXT_MONTH_RE.fullmatch(raw)
    if txt_m:
        if ":" in raw:
            return "DATETIME_LITERAL"
        return "DATE_LITERAL"
    if _DATE_CELL.fullmatch(raw):
        return "DATE_LITERAL"
    # 得到纯日期字面
    if _TIME_CELL.fullmatch(raw):
        return "TIME_LITERAL"
    # 得到纯时刻字面
    clean = _clean_numeric_str(raw)
    try:
        val = float(clean)
        if math.isnan(val) or math.isinf(val):
            return "EMPTY"
    except ValueError:
        pass
    else:
        return "NUMERIC_SCALAR"
    # 无空格且同时含字母和数字，记为结构化代码
    if _CODE.fullmatch(raw) and _LETTER.search(raw) and _DIGIT.search(raw):
        return "STRUCTURED_CODE"
    # 得到 STRUCTURED_CODE
    return "NATURAL_TEXT"
    # 得到自然语言文本



def _samples(rows: list[dict[str, str]], label: str) -> tuple[list[str], list[str]]:
    """
    函数名: _samples
    作用: 收集一列非空格子的物理特征和原文
    输入:
        rows (list[dict[str, str]]): 数据行
        label (str): 列名，只作键
    输出:
        tuple[list[str], list[str]]: (物理特征, 原文)
    """
    physics: list[str] = []
    raws: list[str] = []
    for item in rows:
        raw = str(item.get(label) or "").strip()
        kind = extract_cell_physics(raw)
        if kind == "EMPTY":
            continue
        physics.append(kind)
        raws.append(raw)
    return physics, raws



def _freq(physics: list[str], names: set[str]) -> float:
    """
    函数名: _freq
    作用: 物理特征落在给定集合里的频率
    输入:
        physics (list[str]): 非空样本特征
        names (set[str]): 要计数的特征名
    输出:
        float
    """
    if not physics:
        return 0.0
    hits = 0
    for item in physics:
        if item in names:
            hits += 1
    return hits / len(physics)



def _family(kind: str) -> str:
    """
    函数名: _family
    作用: 把日期、时刻收成同一族，便于判断一列是否混杂
    输入:
        kind (str): 单格物理特征
    输出:
        str
    """
    if kind in _DATE_FAMILY:
        return "DATETIME"
    if kind == "NUMERIC_SCALAR":
        return "NUMERIC"
    return kind



def _as_id(label: str, raws: list[str]) -> bool:
    """
    函数名: _as_id
    作用: 用表头词和唯一率把整数列从数量里分成 ID
    输入:
        label (str): 列名
        raws (list[str]): 非空原文
    输出:
        bool
    """
    unique = len(set(raws)) / len(raws)
    # 得到非空值的唯一率
    if _ID_HEADER.search(label) and unique >= ID_UNIQUENESS:
        return True
    # 得到表头像 ID 且足够单射
    long_ints = all(_INT_CELL.fullmatch(item) for item in raws) and min(len(item) for item in raws) >= LONG_ID_CHARS
    return long_ints and unique >= LONG_ID_UNIQUENESS



def route_column(rows: list[dict[str, str]], label: str) -> ColumnRoute:
    """
    函数名: route_column
    作用: 纯日期进数字通道；混杂列留在文本；整数再用表头和唯一率分 ID
    输入:
        rows (list[dict[str, str]]): 数据行
        label (str): 列名，参与 ID 与数量的区分
    输出:
        ColumnRoute
    """
    # 收集本列非空格子的物理特征
    physics, raws = _samples(rows, label)
    # 得到特征序列和对应原文
    if not physics:
        return ColumnRoute(label, "SHORT_STRING", "text")
    # 得到空列，落成短文本
    # 公式占比过半时，再区分外链和本表公式
    if _freq(physics, {"FORMULA"}) > 0.5:
        external = any(_EXTERNAL_REF.search(item) for item in raws if item.startswith("="))
        # 得到是否含方括号外链
        kind = "EXTERNAL_FORMULA" if external else "INTERNAL_FORMULA"
        # 得到公式种类
        raw = next(item for item in raws if item.startswith("="))
        # 得到第一条公式原文
        return ColumnRoute(label, kind, "formula", raw)
    # 得到公式通道
    # 出现两种以上物理族就留在文本，不用过半表决切进数字
    families = {_family(item) for item in physics}
    # 当出现日期字面与纯数字 (Excel 日期序列号) 混杂时，若日期族占多数或列名具备日期特征，判定为日期列
    if families <= {"DATETIME", "NUMERIC"}:
        date_freq = _freq(physics, _DATE_FAMILY)
        if date_freq >= 0.5 or (date_freq > 0.0 and _DATE_HEADER.search(label)):
            families = {"DATETIME"}
    # 得到这一列出现过的物理族
    if len(families) != 1:
        longest = max(len(item) for item in raws)
        if longest < SHORT_CHAR:
            return ColumnRoute(label, "SHORT_STRING", "text")
        return ColumnRoute(label, "LONG_STRING", "text")
    # 得到混杂列的文本通道
    family = next(iter(families))
    # 得到唯一的物理族
    if family == "DATETIME":
        return ColumnRoute(label, "DATETIME", "digit")
    # 得到整列日期
    if family == "NUMERIC":
        if _as_id(label, raws):
            return ColumnRoute(label, "ID_CODE", "digit")
        # 得到由唯一率或表头判定的 ID
        return ColumnRoute(label, "NUMERIC", "digit")
    # 得到普通数量
    if family == "STRUCTURED_CODE":
        if _as_id(label, raws):
            return ColumnRoute(label, "ID_CODE", "digit")
        return ColumnRoute(label, "STRUCTURED_CODE", "digit")
    # 得到结构化代码，或表头把它提升成 ID
    longest = max(len(item) for item in raws)
    # 得到本列最长原文的字符数
    if longest < SHORT_CHAR:
        return ColumnRoute(label, "SHORT_STRING", "text")
    # 得到短文本通道
    return ColumnRoute(label, "LONG_STRING", "text")
    # 得到长文本通道



def route_columns(headers: list[str], rows: list[dict[str, str]]) -> list[ColumnRoute]:
    """
    函数名: route_columns
    作用: 按表头顺序给出每列通道
    输入:
        headers (list[str]): 表头
        rows (list[dict[str, str]]): 数据行
    输出:
        list[ColumnRoute]
    """
    return [route_column(rows, label) for label in headers]
