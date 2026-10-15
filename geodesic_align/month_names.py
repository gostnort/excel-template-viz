"""月份别名。三字母、四字母、全称和中文月份都在这里增补。"""

from __future__ import annotations

import re


# 键用小写。新的写法只加在这张表里。
MONTH_MAP: dict[str, int] = {
    "jan": 1,
    "january": 1,
    "一月": 1,
    "1月": 1,
    "01月": 1,
    "正月": 1,
    "壹月": 1,
    "feb": 2,
    "february": 2,
    "二月": 2,
    "2月": 2,
    "02月": 2,
    "贰月": 2,
    "mar": 3,
    "march": 3,
    "三月": 3,
    "3月": 3,
    "03月": 3,
    "叁月": 3,
    "apr": 4,
    "april": 4,
    "四月": 4,
    "4月": 4,
    "04月": 4,
    "肆月": 4,
    "may": 5,
    "五月": 5,
    "5月": 5,
    "05月": 5,
    "伍月": 5,
    "jun": 6,
    "june": 6,
    "六月": 6,
    "6月": 6,
    "06月": 6,
    "陆月": 6,
    "jul": 7,
    "july": 7,
    "七月": 7,
    "7月": 7,
    "07月": 7,
    "柒月": 7,
    "aug": 8,
    "august": 8,
    "八月": 8,
    "8月": 8,
    "08月": 8,
    "捌月": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "九月": 9,
    "9月": 9,
    "09月": 9,
    "玖月": 9,
    "oct": 10,
    "october": 10,
    "十月": 10,
    "10月": 10,
    "拾月": 10,
    "nov": 11,
    "november": 11,
    "十一月": 11,
    "11月": 11,
    "拾壹月": 11,
    "dec": 12,
    "december": 12,
    "十二月": 12,
    "12月": 12,
    "腊月": 12,
    "臘月": 12,
    "拾贰月": 12,
}



def month_number(token: str) -> int:
    """
    函数名: month_number
    作用: 把月份别名收成 1 到 12
    输入:
        token (str): 月份写法，含三字母、四字母、全称或中文
    输出:
        int: 1 到 12；认不出为 0
    """
    key = str(token).strip().strip(".").casefold().replace(" ", "")
    return MONTH_MAP.get(key, 0)



def _alt(tokens: list[str]) -> str:
    """
    函数名: _alt
    作用: 按长度从长到短拼成正则分支，避免短别名截断长别名
    输入:
        tokens (list[str]): 月份写法
    输出:
        str: 用竖线连接的转义分支
    """
    ordered = sorted(set(tokens), key=len, reverse=True)
    return "|".join(re.escape(tok) for tok in ordered)



def _text_month_pattern() -> re.Pattern[str]:
    """
    函数名: _text_month_pattern
    作用: 编译带月份别名的整格日期正则
    输入:
        无
    输出:
        re.Pattern[str]: 命名组 d1/mon1/y1、mon2/d2/y2、y3/mon3/d3，以及 hour/minute/sec/ampm
    """
    en_tokens = [key for key in MONTH_MAP if key.isascii()]
    zh_tokens = [key for key in MONTH_MAP if not key.isascii()]
    en = _alt(en_tokens)
    zh = _alt(zh_tokens)
    # 日-月-年、月 日 年，以及年月日里的中文月份
    body = (
        rf"^(?:(?P<d1>\d{{1,2}})[-/. ](?P<mon1>{en})[-/. ,]+(?P<y1>\d{{4}})"
        rf"|(?P<mon2>{en})\s+(?P<d2>\d{{1,2}})[-/. ,]+(?P<y2>\d{{4}})"
        rf"|(?P<y3>\d{{4}})年(?P<mon3>{zh})(?P<d3>\d{{1,2}})日)"
        rf"(?:[ T](?P<hour>\d{{1,2}}):(?P<minute>\d{{2}})(?::(?P<sec>\d{{2}}(?:\.\d+)?))?(?:\s*(?P<ampm>[AaPp][Mm]))?)?$"
    )
    return re.compile(body, re.IGNORECASE)


TEXT_MONTH_RE = _text_month_pattern()
