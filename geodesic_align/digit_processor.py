"""数字化通道：z = x + yi，ID 集合、行指针、搬运与非平凡代数。"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date


from geodesic_align.month_names import TEXT_MONTH_RE, month_number


@dataclass
class ColumnRoute:
    """一列的物理通道与类型。"""

    label: str
    kind: str
    channel: str
    raw_formula: str = ""


EXCEL_EPOCH = date(1899, 12, 30)
Z_EPS = 1e-9
SENTINEL = complex(0.0, -1.0)
_EMPTY = frozenset({
    "", "null", "none", "n/a", "na", "nan", "暂无", "无", "空", "缺失", "-", "--",
    "#n/a", "#na", "nil", "#div/0!", "#ref!", "#name?", "#num!", "#null!", "#value!"
})
_EMPTY_WORDS = _EMPTY
_CURRENCY_RE = re.compile(r"[¥￥$€£]+")
DISCRETE_KINDS = frozenset({"NUMERIC", "STRUCTURED_CODE", "DATETIME", "ID_CODE"})
KEY_KINDS = DISCRETE_KINDS | {"SHORT_STRING", "LONG_STRING"}
KEY_UNIQUENESS = 0.8



@dataclass
class TableView:
    """一张已载入内存的表。physical 为 excel 或 google。"""

    source_key: str
    physical: str
    headers: list[str]
    rows: list[dict[str, str]]
    header_row: int = 1
    sheet: str = ""




@dataclass
class FunctionalClosure:
    """可对新增行重算的派生态射。"""

    op: str
    left_source: str
    left_field: str
    right_source: str
    right_field: str
    sep: str = ""



    def evaluate(self, left_val: float | str, right_val: float | str) -> str:
        """
        函数名: FunctionalClosure.evaluate
        作用: 对任意一对新值执行这个态射
        输入:
            left_val (float | str): 左操作数
            right_val (float | str): 右操作数
        输出:
            str: 运算结果字面；无法解析时为空串
        """
        if self.op in {"+", "-", "*", "/"}:
            try:
                left_num = float(left_val)
                right_num = float(right_val)
            except (TypeError, ValueError):
                return ""
            if self.op == "+":
                result = left_num + right_num
            elif self.op == "-":
                result = left_num - right_num
            elif self.op == "*":
                result = left_num * right_num
            elif self.op == "/":
                if abs(right_num) < 1e-9:
                    return ""
                result = left_num / right_num
            else:
                return ""
            if abs(result - round(result)) < 1e-9:
                return str(int(round(result)))
            return f"{result:.4f}"
        if self.op == "&":
            return f"{str(left_val).strip()}{self.sep}{str(right_val).strip()}"
        return ""



    def to_descriptor(self) -> str:
        """
        函数名: FunctionalClosure.to_descriptor
        作用: 写成可保存的算子字面，不依赖某一次样本
        输入: 无
        输出:
            str: 例如 {source1.基本工资} + {source2.补贴}
        """
        left = "{" + f"{self.left_source}.{self.left_field}" + "}"
        right = "{" + f"{self.right_source}.{self.right_field}" + "}"
        if self.op == "&" and self.sep:
            return f"{left} & '{self.sep}' & {right}"
        if self.op == "&":
            return f"{left} & {right}"
        return f"{left} {self.op} {right}"




@dataclass
class DigitEnd:
    """模板一列在数字化通道上的判定。"""

    input_label: str
    klass: str
    field: str
    source: str
    contributors: list[tuple[str, str]] = field(default_factory=list)
    formula_op: str = ""
    operand_headers: list[str] = field(default_factory=list)
    operand_cols: list[int] = field(default_factory=list)
    excel_row: int = 2
    physical: str = ""
    is_id: bool = False
    warnings: list[str] = field(default_factory=list)
    pointers: list[tuple[str, int] | None] = field(default_factory=list)
    source_b: str = ""
    filled_values: list[str] = field(default_factory=list)
    closure: FunctionalClosure | None = None



def z_eq(left: complex, right: complex) -> bool:
    """
    函数名: z_eq
    作用: 实部容差、虚部严格相等；任一侧哨兵则不相等
    输入:
        left (complex): z = x + yi
        right (complex): z = x + yi
    输出:
        bool
    """
    if left.imag < 0.0 or right.imag < 0.0:
        return False
    return abs(left.real - right.real) < Z_EPS and left.imag == right.imag



def quantize_z(value: complex) -> complex:
    """
    函数名: quantize_z
    作用: 入集前把实部虚部四舍五入到 8 位，避免原生 complex 哈希
    输入:
        value (complex): z = x + yi
    输出:
        complex
    """
    return complex(round(float(value.real), 8), round(float(value.imag), 8))



def _clean_numeric_str(raw: str) -> str:
    """清理币符、千分位及欧式逗号小数，规范化负数。"""
    clean = _CURRENCY_RE.sub("", raw).strip()
    neg = False
    if clean.startswith("(") and clean.endswith(")"):
        neg = True
        clean = clean[1:-1].strip()
    elif clean.startswith("-"):
        neg = True
        clean = clean[1:].strip()
    clean = _CURRENCY_RE.sub("", clean).strip()
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



def _parse_time_fraction(s: str) -> float | None:
    """提取时间日分数：只要有冒号就是时间，小时<24，分钟<60，秒<60"""
    ap = None
    upper = s.upper()
    if "PM" in upper:
        ap = "PM"
    elif "AM" in upper:
        ap = "AM"
    clean_s = upper.replace("PM", "").replace("AM", "").strip()
    parts = clean_s.split(":")
    if not (2 <= len(parts) <= 3):
        return None
    try:
        h = int(parts[0])
        m = int(parts[1])
        sec = float(parts[2]) if len(parts) == 3 else 0.0
        if ap == "PM" and h < 12:
            h += 12
        elif ap == "AM" and h == 12:
            h = 0
        if 0 <= h <= 23 and 0 <= m <= 59 and 0 <= sec < 60:
            return (h * 3600 + m * 60 + sec) / 86400.0
    except ValueError:
        pass
    return None



def _date_serial(year: int, month: int, day: int, frac: float) -> complex:
    """
    函数名: _date_serial
    作用: 合法日得到 Excel 序列；非法日向下钳位，溢出记在虚部
    输入:
        year (int): 年
        month (int): 月
        day (int): 日
        frac (float): 日分数
    输出:
        complex: z = x + yi
    """
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return SENTINEL
    day_fix = int(day)
    while day_fix >= 1:
        try:
            target = date(year, month, day_fix)
        except ValueError:
            day_fix -= 1
            continue
        serial = float((target - EXCEL_EPOCH).days) + float(frac)
        return complex(serial, float(day - day_fix))
    return SENTINEL



def _parse_date_tuple(s: str) -> tuple[int, int, int] | None:
    """提取日期：有 - / . 或中英文月份，年月日自然消歧"""
    for sep in ("-", "/", "."):
        if sep in s:
            parts = s.split(sep)
            if len(parts) == 3:
                try:
                    nums = [int(p) for p in parts]
                    if nums[0] > 1000:  # YYYY-MM-DD
                        return nums[0], nums[1], nums[2]
                    if nums[2] > 1000:  # DD-MM-YYYY 或 MM-DD-YYYY
                        if nums[1] > 12 and 1 <= nums[0] <= 12:
                            return nums[2], nums[0], nums[1]
                        return nums[2], nums[1], nums[0]
                except ValueError:
                    pass
    m = TEXT_MONTH_RE.search(s)
    if m:
        if m.group("d1") is not None:
            return int(m.group("y1")), month_number(m.group("mon1")), int(m.group("d1"))
        if m.group("mon2") is not None:
            return int(m.group("y2")), month_number(m.group("mon2")), int(m.group("d2"))
        if m.group("y3") is not None:
            return int(m.group("y3")), month_number(m.group("mon3")), int(m.group("d3"))
    return None



def _parse_datetime_z(body: str, negative: bool) -> complex:
    """从字符中提取日期时间，转为 z = x + yi；认不出来安全返回 SENTINEL 降级为 input"""
    if ":" in body and not any(sep in body for sep in ("-", "/", ".", "年")):
        frac = _parse_time_fraction(body)
        if frac is not None:
            return complex(-frac if negative else frac, 0.0)

    frac = 0.0
    date_str = body
    if ":" in body:
        tokens = body.replace("T", " ").split()
        time_tokens: list[str] = []
        date_tokens: list[str] = []
        for i, tok in enumerate(tokens):
            if ":" in tok:
                time_tokens.append(tok)
                if i + 1 < len(tokens) and tokens[i + 1].upper() in ("AM", "PM"):
                    time_tokens.append(tokens[i + 1])
            elif tok.upper() not in ("AM", "PM"):
                date_tokens.append(tok)
        if time_tokens:
            tf = _parse_time_fraction(" ".join(time_tokens))
            if tf is not None:
                frac = tf
            date_str = " ".join(date_tokens)

    d_tuple = _parse_date_tuple(date_str)
    if d_tuple is not None:
        y, m, d = d_tuple
        z = _date_serial(y, m, d, frac)
        if negative and z.imag >= 0.0:
            return complex(-z.real, z.imag)
        return z

    try:
        serial = float(body)
        if not (math.isnan(serial) or math.isinf(serial)):
            if negative and serial > 0:
                serial = -serial
            return complex(serial, 0.0)
    except ValueError:
        pass

    return SENTINEL



def cell_to_z(text: str, *, kind: str) -> complex:
    """
    函数名: cell_to_z
    作用: 把格子编成 z = x + yi；失败为 0 + (-1)i，不抛异常，安全降级为 input
    输入:
        text (str): 格子字面
        kind (str): ID_CODE / NUMERIC / DATETIME
    输出:
        complex
    """
    raw = str(text).strip().replace("\u00a0", " ").strip()
    if not raw or raw.lower() in _EMPTY or raw in {"暂无"}:
        return SENTINEL
    clean = _clean_numeric_str(raw)
    negative = clean.startswith("-")
    body = _CURRENCY_RE.sub("", raw).strip()
    if body.startswith("(") and body.endswith(")"):
        body = body[1:-1].strip()
    body = _CURRENCY_RE.sub("", body).strip()

    if kind == "ID_CODE":
        body = body[1:] if body.startswith("#") else body
        clean = clean[1:] if clean.startswith("#") else clean

    if body.endswith("%") and kind != "ID_CODE":
        try:
            val = float(clean.lstrip("-")) / 100.0
            if not (math.isnan(val) or math.isinf(val)):
                return complex(-val if negative else val, 0.0)
        except ValueError:
            pass
        return SENTINEL

    if kind == "DATETIME":
        return _parse_datetime_z(body, negative)

    try:
        val = float(clean)
        if not (math.isnan(val) or math.isinf(val)):
            return complex(-val if negative and val > 0 else val, 0.0)
    except ValueError:
        pass
    return SENTINEL
    # 得到虚部为 0 的数值 z



def extract_cell_physics(text: str) -> str:
    """
    函数名: extract_cell_physics
    作用: 按字符物理特征判断单格类型，不依赖任何表头关键词字典
    输出:
        str: EMPTY / FORMULA / DATETIME / NUMERIC / STRUCTURED_CODE / NATURAL_TEXT
    """
    raw = str(text).strip().replace("\u00a0", " ").strip()
    if not raw or raw.lower() in _EMPTY or raw in {"暂无"}:
        return "EMPTY"
    if raw.startswith("="):
        return "FORMULA"
    if ":" in raw or _parse_date_tuple(raw) is not None or (TEXT_MONTH_RE.search(raw) and any(c.isdigit() for c in raw)):
        return "DATETIME"
    clean = _clean_numeric_str(raw)
    try:
        val = float(clean)
        if not (math.isnan(val) or math.isinf(val)):
            return "NUMERIC"
    except ValueError:
        pass
    if " " not in raw and any(c.isalpha() for c in raw) and any(c.isdigit() for c in raw):
        return "STRUCTURED_CODE"
    return "NATURAL_TEXT"



def route_column(rows: list[dict[str, str]], label: str) -> ColumnRoute:
    """
    函数名: route_column
    作用: 按单格物理特征统计与单射率给出列通道
    输入:
        rows (list[dict[str, str]]): 数据行
        label (str): 列名
    输出:
        ColumnRoute
    """
    raws: list[str] = []
    physics: list[str] = []
    for row in rows:
        val = str(row.get(label) or "").strip()
        kind = extract_cell_physics(val)
        if kind != "EMPTY":
            physics.append(kind)
            raws.append(val)

    if not physics:
        return ColumnRoute(label, "SHORT_STRING", "text")

    formula_count = sum(1 for p in physics if p == "FORMULA")
    if formula_count / len(physics) > 0.5:
        formula_raws = [r for r in raws if r.startswith("=")]
        raw = formula_raws[0] if formula_raws else ""
        kind = "EXTERNAL_FORMULA" if any("[" in r and "]" in r for r in formula_raws) else "INTERNAL_FORMULA"
        return ColumnRoute(label, kind, "formula", raw)

    types = set(physics)
    if types == {"DATETIME"} or types == {"DATETIME", "NUMERIC"}:
        return ColumnRoute(label, "DATETIME", "digit")

    if types == {"NUMERIC"}:
        unique_ratio = len(set(raws)) / len(raws)
        is_int_like = all(_clean_numeric_str(r).lstrip("-").isdigit() for r in raws)
        if is_int_like and (unique_ratio >= 0.8 or min(len(r) for r in raws) >= 8):
            return ColumnRoute(label, "ID_CODE", "digit")
        return ColumnRoute(label, "NUMERIC", "digit")

    if types == {"STRUCTURED_CODE"}:
        unique_ratio = len(set(raws)) / len(raws)
        if unique_ratio >= 0.8:
            return ColumnRoute(label, "ID_CODE", "digit")
        return ColumnRoute(label, "STRUCTURED_CODE", "digit")

    max_len = max(len(r) for r in raws)
    return ColumnRoute(label, "SHORT_STRING" if max_len < 16 else "LONG_STRING", "text")



def route_columns(headers: list[str], rows: list[dict[str, str]]) -> list[ColumnRoute]:
    """按表头顺序给出每列通道"""
    return [route_column(rows, h) for h in headers]



def column_z(rows: list[dict[str, str]], label: str, kind: str) -> list[complex]:
    """
    函数名: column_z
    作用: 整列编成 z 列表，与行序对齐
    输入:
        rows (list[dict[str, str]]): 数据行
        label (str): 列名
        kind (str): 列类型
    输出:
        list[complex]
    """
    return [cell_to_z(str(item.get(label) or ""), kind=kind) for item in rows]



def set_of_z(values: list[complex]) -> set[complex]:
    """
    函数名: set_of_z
    作用: 丢掉哨兵后用量化键建集合
    输入:
        values (list[complex]): 一列 z
    输出:
        set[complex]
    """
    packed: set[complex] = set()
    for item in values:
        if item.imag < 0.0:
            continue
        packed.add(quantize_z(item))
    return packed



def _header_cos(left: str, right: str) -> float:
    """
    函数名: _header_cos
    作用: 列名字符袋重合度，仅用于已通过值检验的候选打破平局
    输入:
        left (str): 表头
        right (str): 表头
    输出:
        float
    """
    s1 = {ch.lower() for ch in str(left) if ch.strip()}
    s2 = {ch.lower() for ch in str(right) if ch.strip()}
    if not s1 or not s2:
        return 0.0
    return len(s1 & s2) / float(len(s1 | s2))



def _clean_std(values: list[complex]) -> float:
    """
    函数名: _clean_std
    作用: 检查列是否包含有效方差，常数列（全0或全相同值）返回 0.0
    输入:
        values (list[complex]): 列上的 z
    输出:
        float
    """
    reals = [round(float(item.real), 6) for item in values if item.imag == 0.0]
    return 1.0 if len(set(reals)) > 1 else 0.0



def _majority_key(pointers: list[tuple[str, int] | None]) -> str:
    """
    函数名: _majority_key
    作用: 行指针里出现最多的源键
    输入:
        pointers (list): 每行 (source_key, row) 或 None
    输出:
        str
    """
    counts: dict[str, int] = {}
    for item in pointers:
        if item is None:
            continue
        counts[item[0]] = counts.get(item[0], 0) + 1
    if not counts:
        return ""
    return max(counts.items(), key=lambda pair: (pair[1], pair[0]))[0]



def _value_token(text: str, kind: str) -> str | None:
    """
    函数名: _value_token
    作用: 把格子收成可入集合的键；空值和哨兵返回 None
    输入:
        text (str): 格子字面
        kind (str): NUMERIC / DATETIME / STRUCTURED_CODE
    输出:
        str | None
    """
    # 去掉空白和哨兵，准备收成集合键
    raw = str(text).strip()
    # 得到去空白后的格子原文
    if not raw or raw.lower() in {"null", "none", "n/a", "na", "暂无", "-", "--"}:
        return None
    # 得到空键，本格不进集合
    # 结构化代码和文本按原文入集合
    if kind in {"STRUCTURED_CODE", "SHORT_STRING", "LONG_STRING"}:
        return raw
    # ID 代码：纯数值/井号转量化键，字母数字代码保留原文
    if kind == "ID_CODE":
        clean = raw[1:] if raw.startswith("#") else raw
        try:
            val = float(clean)
            if not (math.isnan(val) or math.isinf(val)):
                packed = quantize_z(complex(val, 0.0))
                return f"{packed.real:.8f}|{packed.imag:.8f}"
        except ValueError:
            pass
        return raw
    # 数值与日期先收成 z，再量化成集合键
    z_kind = "DATETIME" if kind == "DATETIME" else "NUMERIC"
    value = cell_to_z(raw, kind=z_kind)
    if value.imag < 0.0:
        return None
    packed = quantize_z(value)
    return f"{packed.real:.8f}|{packed.imag:.8f}"
    # 得到可哈希的集合键



def _token_series(rows: list[dict[str, str]], label: str, kind: str) -> list[str | None]:
    """
    函数名: _token_series
    作用: 整列变成集合键，空格子为 None
    输入:
        rows (list[dict[str, str]]): 数据行
        label (str): 列名
        kind (str): 离散列类型
    输出:
        list[str | None]
    """
    return [_value_token(str(item.get(label) or ""), kind) for item in rows]



def _occupied_rows(rows: list[dict[str, str]]) -> int:
    """
    函数名: _occupied_rows
    作用: 至少有一个非空格子的行数
    输入:
        rows (list[dict[str, str]]): 数据行
    输出:
        int
    """
    count = 0
    for row in rows:
        if any(str(value).strip() for value in row.values()):
            count += 1
    return count



def align_topology(
    dest: TableView,
    sources: list[TableView],
) -> tuple[str, list[tuple[str, int] | None], list[list[tuple[str, int]]], list[tuple[str, str]]]:
    """
    函数名: align_topology
    作用: 用覆盖度和单射率选出主键列，并给出每行的源指针
    输入:
        dest (TableView): 模板
        sources (list[TableView]): 源表
    输出:
        tuple: (目标主键列名, 主指针, 全部命中, 参与的源列)
    """
    # 先给目标和每个源表做物理分流，列名只当键
    dest_routes = {item.label: item for item in route_columns(dest.headers, dest.rows)}
    # 得到目标列路由
    src_routes = {
        table.source_key: {item.label: item for item in route_columns(table.headers, table.rows)}
        for table in sources
    }
    # 得到各源表列路由
    ranked: list[tuple[float, float, int, int, str, str]] = []
    full_cover: list[tuple[str, str, str, str]] = []
    header_at = {name: idx for idx, name in enumerate(dest.headers)}
    # 得到目标列的出现顺序，同分时靠前的列优先
    for dest_label, dest_route in dest_routes.items():
        if dest_route.kind not in KEY_KINDS:
            continue
        # 抽出目标列非空集合
        dest_tokens = _token_series(dest.rows, dest_label, dest_route.kind)
        # 得到按行排列的集合键，空格为 None
        dest_set = {item for item in dest_tokens if item}
        # 得到目标非空集合
        if not dest_set:
            continue
        partial: list[tuple[str, str, set[str]]] = []
        for order, table in enumerate(sources):
            # 用非空行数做分母，不用两表行数相等
            occupied = _occupied_rows(table.rows)
            # 得到源表非空行数
            if occupied <= 0:
                continue
            for src_label, src_route in src_routes[table.source_key].items():
                if src_route.kind != dest_route.kind:
                    continue
                src_tokens = _token_series(table.rows, src_label, src_route.kind)
                src_set = {item for item in src_tokens if item}
                # 得到源列非空集合
                if not src_set:
                    continue
                # 算覆盖度、唯一率和得分
                coverage = len(dest_set & src_set) / len(dest_set)
                # 得到目标集合被源集合盖住的比例
                uniqueness = len(src_set) / occupied
                # 得到源列去重后相对非空行的单射率
                if uniqueness < KEY_UNIQUENESS:
                    continue
                score = coverage * uniqueness
                # 得到覆盖度乘唯一率
                place = -header_at.get(dest_label, 0)
                # 完全覆盖的配对直接进入候选
                if coverage == 1.0:
                    ranked.append((score, uniqueness, -order, place, dest_label, table.source_key))
                    full_cover.append((dest_label, table.source_key, src_label, dest_route.kind))
                    # 得到一条完全覆盖的源列
                elif coverage > 0.0:
                    partial.append((table.source_key, src_label, src_set))
                    # 得到一条只盖住一部分的源列
        # 已有完全覆盖就不再拼并集
        if any(item[0] == dest_label for item in full_cover):
            continue
        # 没有单列盖住时，试多列并集是否盖住目标
        union: set[str] = set()
        members: list[tuple[str, str]] = []
        for source_key, src_label, src_set in partial:
            union |= src_set
            members.append((source_key, src_label))
        # 得到部分列的并集
        if dest_set <= union and len(members) >= 2:
            for source_key, src_label in members:
                full_cover.append((dest_label, source_key, src_label, dest_route.kind))
            place = -header_at.get(dest_label, 0)
            ranked.append((len(members) / (len(members) + 1.0), 1.0, 0, place, dest_label, members[0][0]))
            # 得到一条并集覆盖的主键候选
    empty_ptr: list[tuple[str, int] | None] = [None] * len(dest.rows)
    empty_hits: list[list[tuple[str, int]]] = [[] for _row in dest.rows]
    if not ranked:
        return "", empty_ptr, empty_hits, []
    # 得到没有主键时的空指针
    # 按得分挑出主键列
    ranked.sort(reverse=True)
    key_label = ranked[0][4]
    # 得到目标主键列名
    kind = next(item[3] for item in full_cover if item[0] == key_label)
    # 得到主键的物理类型
    contributors = [(item[1], item[2]) for item in full_cover if item[0] == key_label]
    # 得到参与这把主键的源列
    # 把源列键值登记成行下标
    index: dict[str, list[tuple[str, int]]] = {}
    for source_key, src_label in contributors:
        table = next(item for item in sources if item.source_key == source_key)
        series = _token_series(table.rows, src_label, kind)
        for row_idx, token in enumerate(series):
            if not token:
                continue
            index.setdefault(token, []).append((source_key, row_idx))
    # 得到键值到源行的倒排
    # 用目标主键把每一行指到源行，空格记为 None
    dest_tokens = _token_series(dest.rows, key_label, kind)
    pointers: list[tuple[str, int] | None] = []
    lineage: list[list[tuple[str, int]]] = []
    for token in dest_tokens:
        if not token:
            pointers.append(None)
            lineage.append([])
            # 得到空目标格的空指针
            continue
        hits = list(index.get(token, []))
        # 得到该键在各源表上的行号
        lineage.append(hits)
        pointers.append(hits[0] if hits else None)
        # 得到主指针，多源时取先出现的那张表
    return key_label, pointers, lineage, contributors
    # 得到主键列名、主指针、全部命中和参与源列



def id_lineage(
    dest: TableView,
    sources: list[TableView],
) -> list[list[tuple[str, int]]]:
    """
    函数名: id_lineage
    作用: 返回集合拓扑推出的每行全部源指针
    输入:
        dest (TableView): 模板
        sources (list[TableView]): 源表
    输出:
        list[list[tuple[str, int]]]
    """
    _label, _pointers, lineage, _contributors = align_topology(dest, sources)
    return lineage



def _pick_pointer_rows(
    table: TableView,
    pointers: list[tuple[str, int] | None],
    row_indexes: list[int],
) -> list[int] | None:
    """按行指针提取有效源行下标，指针不在该表或越界则返回 None"""
    picked: list[int] = []
    num_rows = len(table.rows)
    for idx in row_indexes:
        ptr = pointers[idx]
        if ptr is None or ptr[0] != table.source_key or not (0 <= ptr[1] < num_rows):
            return None
        picked.append(ptr[1])
    return picked



def _values_on_pointer(
    table: TableView,
    label: str,
    kind: str,
    pointers: list[tuple[str, int] | None],
    row_indexes: list[int],
) -> list[complex] | None:
    """按行指针取出源列 z；指针不在该表则失败"""
    row_ids = _pick_pointer_rows(table, pointers, row_indexes)
    if row_ids is None:
        return None
    series = column_z(table.rows, label, kind)
    return [series[r] for r in row_ids]



def _match_rows(dest: list[complex], src: list[complex]) -> bool:
    """对齐后的两列是否逐格 z_eq"""
    if len(dest) != len(src) or not dest:
        return False
    return all(z_eq(l, r) for l, r in zip(dest, src))



def _plain_on_pointer(
    table: TableView,
    label: str,
    pointers: list[tuple[str, int] | None],
    row_indexes: list[int],
) -> list[str] | None:
    """按行指针取源列原文，供结构化代码逐字比对"""
    row_ids = _pick_pointer_rows(table, pointers, row_indexes)
    if row_ids is None:
        return None
    return [str(table.rows[r].get(label) or "").strip() for r in row_ids]



def _column_agrees(
    table: TableView,
    name: str,
    kind: str,
    pointers: list[tuple[str, int] | None],
    idxs: list[int],
    dest_z: list[complex],
    dest_plain: list[str],
) -> bool:
    """
    函数名: _column_agrees
    作用: 有效指针行上，源列与模板列是否逐格相同
    输入:
        table (TableView): 源表
        name (str): 源列名
        kind (str): 列类型
        pointers (list): 行指针
        idxs (list[int]): 有效模板行
        dest_z (list[complex]): 模板 z
        dest_plain (list[str]): 模板原文
    输出:
        bool
    """
    # 结构化代码比原文，数值和日期比 z
    if kind == "STRUCTURED_CODE":
        got = _plain_on_pointer(table, name, pointers, idxs)
        # 得到指针所指的源原文
        want = [dest_plain[idx] for idx in idxs]
        # 得到有效目标行的原文
        return got is not None and got == want and all(item for item in want)
    # 得到是否逐字全等
    got_z = _values_on_pointer(table, name, kind, pointers, idxs)
    # 得到指针所指的源 z
    want_z = [dest_z[idx] for idx in idxs]
    # 得到有效目标行的 z
    return got_z is not None and _match_rows(want_z, got_z)
    # 得到是否逐格 z 相等



def _try_carry(
    dest_label: str,
    dest_z: list[complex],
    kind: str,
    pointers: list[tuple[str, int] | None],
    sources: list[TableView],
    routes: dict[str, dict[str, ColumnRoute]],
    active: list[int],
    dest_plain: list[str],
) -> list[tuple[str, str]] | None:
    """
    函数名: _try_carry
    作用: 按有效行指针分组，对单表或多表分别寻找逐格匹配的源列 (len==1 为单源 carry, >=2 为多源 union)
    输入:
        dest_label (str): 模板列名
        dest_z (list[complex]): 模板列 z
        kind (str): 列类型
        pointers (list): 行指针
        sources (list[TableView]): 源表
        routes (dict): 各表列路由
        active (list[int]): 已填行号
        dest_plain (list[str]): 目标原文
    输出:
        list[tuple[str, str]] | None: 匹配到的 [(source_key, field), ...]
    """
    if not active:
        return None
    groups: dict[str, list[int]] = {}
    for idx in active:
        ptr = pointers[idx]
        if ptr is None:
            return None
        groups.setdefault(ptr[0], []).append(idx)
    if not groups:
        return None

    chosen: list[tuple[str, str]] = []
    by_key = {item.source_key: item for item in sources}
    for source_key, idxs in groups.items():
        table = by_key.get(source_key)
        if table is None:
            return None
        headers = [
            name for name, route in routes.get(source_key, {}).items()
            if route.channel == "digit" and route.kind == kind
        ]
        ordered = [dest_label] if dest_label in headers else []
        ordered.extend(name for name in headers if name != dest_label)
        hit: tuple[str, float] | None = None
        for name in ordered:
            if not _column_agrees(table, name, kind, pointers, idxs, dest_z, dest_plain):
                continue
            score = _header_cos(dest_label, name)
            if hit is None or score > hit[1]:
                hit = (name, score)
        if hit is None:
            return None
        chosen.append((source_key, hit[0]))
    return chosen



def _op_value(op: str, left: float, right: float) -> float:
    """
    函数名: _op_value
    作用: 二元运算的实部
    输入:
        op (str): + - * /
        left (float): 左实部
        right (float): 右实部
    输出:
        float
    """
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if op == "/":
        return left / right if abs(right) > Z_EPS else float("inf")
    return left * right



def _formula_holds(
    dest_z: list[complex],
    left_z: list[complex],
    right_z: list[complex],
    op: str,
) -> bool:
    """
    函数名: _formula_holds
    作用: 全部行虚部为 0 且实部满足非平凡公式
    输入:
        dest_z (list[complex]): 目标列
        left_z (list[complex]): 左操作数
        right_z (list[complex]): 右操作数
        op (str): + - * /
    输出:
        bool
    """
    if _clean_std(left_z) <= 0.0 or _clean_std(right_z) <= 0.0:
        return False
    for dest, left, right in zip(dest_z, left_z, right_z):
        if dest.imag != 0.0 or left.imag != 0.0 or right.imag != 0.0:
            return False
        if op == "/" and abs(right.real) < Z_EPS:
            return False
        got = _op_value(op, left.real, right.real)
        if abs(got - dest.real) >= Z_EPS:
            return False
    return True



def _iter_binary_ops(left_item, left_z, right_item, right_z):
    """依次生成 +, *, - (正反), / (正反) 的候选五元组 (a_item, op, b_item, a_z, b_z)"""
    yield left_item, "+", right_item, left_z, right_z
    yield left_item, "*", right_item, left_z, right_z
    yield left_item, "-", right_item, left_z, right_z
    yield right_item, "-", left_item, right_z, left_z
    yield left_item, "/", right_item, left_z, right_z
    yield right_item, "/", left_item, right_z, left_z



def _try_internal_derived(
    dest_label: str,
    dest_z: list[complex],
    kind: str,
    dest_table: TableView,
    dest_routes: dict[str, ColumnRoute],
) -> tuple[str, str, str] | None:
    """
    函数名: _try_internal_derived
    作用: 目标列等于模板上另外两列的运算，视为内部公式
    输入:
        dest_label (str): 模板列名
        dest_z (list[complex]): 目标 z
        kind (str): 列类型
        dest_table (TableView): 模板表
        dest_routes (dict[str, ColumnRoute]): 模板列路由
    输出:
        tuple[str, str, str] | None: (左列, 运算, 右列)
    """
    names = [
        name for name, route in dest_routes.items()
        if name != dest_label and route.channel == "digit" and route.kind == kind
    ]
    best: tuple[float, str, str, str] | None = None
    for i, left_name in enumerate(names):
        left_z = column_z(dest_table.rows, left_name, kind)
        for right_name in names[i + 1:]:
            right_z = column_z(dest_table.rows, right_name, kind)
            for a_name, op, b_name, a_z, b_z in _iter_binary_ops(left_name, left_z, right_name, right_z):
                if not _formula_holds(dest_z, a_z, b_z, op):
                    continue
                score = _header_cos(dest_label, a_name) + _header_cos(dest_label, b_name)
                if best is None or score > best[0]:
                    best = (score, a_name, op, b_name)
    if best is None:
        return None
    return best[1], best[2], best[3]



def _align_active(
    table: TableView,
    label: str,
    kind: str,
    lineage: list[list[tuple[str, int]]],
    active: list[int],
) -> list[complex] | None:
    """
    函数名: _align_active
    作用: 按全部行指针把一列对齐到已填目标行，缺行则失败
    输入:
        table (TableView): 源表
        label (str): 列名
        kind (str): 列类型
        lineage (list): 每行全部源指针
        active (list[int]): 已填目标行
    输出:
        list[complex] | None
    """
    series = column_z(table.rows, label, kind)
    picked: list[complex] = []
    for idx in active:
        hits = lineage[idx] if idx < len(lineage) else []
        row_idx = None
        for key, src_idx in hits:
            if key == table.source_key:
                row_idx = src_idx
                break
        if row_idx is None or row_idx < 0 or row_idx >= len(series):
            return None
        picked.append(series[row_idx])
    return picked



def _try_external_derived(
    dest_label: str,
    dest_z: list[complex],
    kind: str,
    lineage: list[list[tuple[str, int]]],
    active: list[int],
    sources: list[TableView],
    routes: dict[str, dict[str, ColumnRoute]],
) -> tuple[TableView, str, str, TableView, str] | None:
    """
    函数名: _try_external_derived
    作用: 在已填行上搜索二元式，左右操作数可以来自不同源表
    输入:
        dest_label (str): 模板列名
        dest_z (list[complex]): 目标 z，与全部行对齐
        kind (str): 列类型
        lineage (list): 每行全部源指针
        active (list[int]): 已填目标行
        sources (list[TableView]): 源表
        routes (dict): 源列路由
    输出:
        tuple | None: (左表, 左列, 运算, 右表, 右列)
    """
    if not active:
        return None
    want = [dest_z[idx] for idx in active]
    # 得到已填行上的目标 z
    columns: list[tuple[TableView, str, list[complex]]] = []
    for table in sources:
        for name, route in routes[table.source_key].items():
            if route.channel != "digit" or route.kind != kind or route.kind == "ID_CODE":
                continue
            series = _align_active(table, name, kind, lineage, active)
            if series is not None:
                columns.append((table, name, series))
    # 得到每张源表上能对齐的数字列
    best: tuple[float, TableView, str, str, TableView, str] | None = None
    for i, (left_table, left_name, left_z) in enumerate(columns):
        for right_table, right_name, right_z in columns[i + 1:]:
            for (a_tbl, a_name), op, (b_tbl, b_name), a_z, b_z in _iter_binary_ops(
                (left_table, left_name), left_z, (right_table, right_name), right_z
            ):
                if not _formula_holds(want, a_z, b_z, op):
                    continue
                score = _header_cos(dest_label, a_name) + _header_cos(dest_label, b_name)
                if best is None or score > best[0]:
                    best = (score, a_tbl, a_name, op, b_tbl, b_name)
    if best is None:
        return None
    return best[1], best[2], best[3], best[4], best[5]



def _excel_col(index_1based: int) -> str:
    """
    函数名: _excel_col
    作用: 1-based 列号转 Excel 列字母
    输入:
        index_1based (int): 列号
    输出:
        str
    """
    n = int(index_1based)
    letters: list[str] = []
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters.append(chr(65 + rem))
    return "".join(reversed(letters))



def excel_formula_pair(
    source_a: str,
    col_a: int,
    source_b: str,
    col_b: int,
    row: int,
    op: str,
) -> str:
    """两个源的外链公式；同源则简写为单表公式，列绝对、行相对"""
    symbol = " & " if op == "&" else f" {op} "
    b_src = source_b if source_b else source_a
    left = f"='{{{source_a}}}'!${_excel_col(col_a)}{int(row)}"
    right = f"'{{{b_src}}}'!${_excel_col(col_b)}{int(row)}"
    return left + symbol + right



def excel_formula(source_key: str, col_a: int, col_b: int, row: int, op: str) -> str:
    """单源外链公式"""
    return excel_formula_pair(source_key, col_a, source_key, col_b, row, op)




def run_digit_align(
    sources: list[TableView],
    dest: TableView,
) -> list[DigitEnd]:
    """
    函数名: run_digit_align
    作用: 对模板上每个数字化列做规则还原
    输入:
        sources (list[TableView]): 源表
        dest (TableView): 已填模板
    输出:
        list[DigitEnd]
    """
    src_routes = {
        table.source_key: {item.label: item for item in route_columns(table.headers, table.rows)}
        for table in sources
    }
    dest_routes = {item.label: item for item in route_columns(dest.headers, dest.rows)}
    # 先推出主键和行指针
    key_label, pointers, lineage, contributors = align_topology(dest, sources)
    # 得到主键列、主指针和参与源列
    ends: list[DigitEnd] = []
    by_key = {item.source_key: item for item in sources}
    for label, route in dest_routes.items():
        # 只保留本列已填的行，空白占位行不进判定
        active = [idx for idx, row in enumerate(dest.rows) if str(row.get(label) or "").strip()]
        # 得到有效行下标
        # 主键列直接记为行指针，文本主键也记，不走代数
        if label == key_label and contributors:
            source = _majority_key(pointers) or contributors[0][0]
            # 得到占多数的源表
            field_name = next((name for key, name in contributors if key == source), contributors[0][1])
            # 得到该源表上的主键列名
            warnings: list[str] = []
            if len({key for key, _name in contributors}) >= 2:
                warnings.append("multi_source_overlap:" + ",".join(key for key, _name in contributors))
                # 得到多源重叠告警
            ends.append(
                DigitEnd(
                    input_label=label,
                    klass="union" if len({key for key, _name in contributors}) >= 2 else "carry",
                    field=field_name,
                    source=source,
                    contributors=list(contributors),
                    physical=by_key[source].physical if source in by_key else "excel",
                    is_id=True,
                    warnings=warnings,
                    pointers=list(pointers),
                )
            )
            # 得到主键判定，is_id 为真
            continue
        if route.kind not in DISCRETE_KINDS:
            continue
        dest_z = column_z(dest.rows, label, "DATETIME" if route.kind == "DATETIME" else "NUMERIC")
        # 得到本列的 z
        plain = [str(row.get(label) or "").strip() for row in dest.rows]
        # 得到本列原文
        # 逐格搬运 (单源 carry 或多源 union_carry)
        carried = _try_carry(label, dest_z, route.kind, pointers, sources, src_routes, active, plain)
        if carried is not None:
            if len(carried) == 1:
                source_key, field_name = carried[0]
                table = by_key[source_key]
                ends.append(
                    DigitEnd(
                        input_label=label,
                        klass="carry",
                        field=field_name,
                        source=source_key,
                        contributors=list(carried),
                        physical=table.physical,
                        pointers=list(pointers),
                        excel_row=int(table.header_row) + 1 + (pointers[0][1] if pointers and pointers[0] else 0),
                    )
                )
            else:
                source = _majority_key(pointers)
                field_name = next(name for key, name in carried if key == source)
                warnings = ["multi_source_overlap:" + ",".join(key for key, _name in carried)]
                names = {name for _key, name in carried}
                if len(names) > 1:
                    bits = "|".join(f"{key}.{name}" for key, name in carried)
                    warnings.append(f"heterogeneous_headers:{bits}")
                ends.append(
                    DigitEnd(
                        input_label=label,
                        klass="union_carry",
                        field=field_name,
                        source=source,
                        contributors=list(carried),
                        physical=by_key[source].physical if source in by_key else "excel",
                        warnings=warnings,
                        pointers=list(pointers),
                    )
                )
            continue
        internal = _try_internal_derived(label, dest_z, route.kind, dest, dest_routes)
        if internal is not None:
            col_a = dest.headers.index(internal[0]) + 1
            col_b = dest.headers.index(internal[2]) + 1
            row = int(dest.header_row) + 1
            ends.append(
                DigitEnd(
                    input_label=label,
                    klass="derived",
                    field="",
                    source="",
                    formula_op=internal[1],
                    operand_headers=[internal[0], internal[2]],
                    operand_cols=[col_a, col_b],
                    excel_row=row,
                    physical="internal",
                    pointers=list(pointers),
                )
            )
            continue
        external = _try_external_derived(label, dest_z, route.kind, lineage, active, sources, src_routes)
        if external is not None:
            left_table, left_name, op, right_table, right_name = external
            row = int(left_table.header_row) + 1
            if pointers and pointers[0] is not None and pointers[0][0] == left_table.source_key:
                row = int(left_table.header_row) + 1 + int(pointers[0][1])
            warnings: list[str] = []
            source_b = ""
            physical = left_table.physical
            if right_table.source_key != left_table.source_key:
                source_b = right_table.source_key
                warnings.append(f"multi_source_overlap:{left_table.source_key},{right_table.source_key}")
                if left_table.physical == "google" or right_table.physical == "google":
                    physical = "google"
            closure = FunctionalClosure(op, left_table.source_key, left_name, right_table.source_key, right_name)
            filled: list[str] = []
            if physical == "google":
                # 用算子对当前行求值，描述符留给以后的新行
                for idx in range(len(dest.rows)):
                    hits = lineage[idx] if idx < len(lineage) else []
                    left_hit = next((src_idx for key, src_idx in hits if key == left_table.source_key), None)
                    right_hit = next((src_idx for key, src_idx in hits if key == right_table.source_key), None)
                    left_text = ""
                    right_text = ""
                    if left_hit is not None and 0 <= left_hit < len(left_table.rows):
                        left_text = str(left_table.rows[left_hit].get(left_name) or "").strip()
                    if right_hit is not None and 0 <= right_hit < len(right_table.rows):
                        right_text = str(right_table.rows[right_hit].get(right_name) or "").strip()
                    filled.append(closure.evaluate(left_text, right_text))
            ends.append(
                DigitEnd(
                    input_label=label,
                    klass="derived",
                    field="",
                    source=left_table.source_key,
                    formula_op=op,
                    operand_headers=[left_name, right_name],
                    operand_cols=[
                        left_table.headers.index(left_name) + 1,
                        right_table.headers.index(right_name) + 1,
                    ],
                    excel_row=row,
                    physical=physical,
                    pointers=list(pointers),
                    source_b=source_b,
                    filled_values=filled,
                    warnings=warnings,
                    closure=closure if physical == "google" else None,
                )
            )
            continue
        has_ptr = any(item is not None for item in pointers)
        ends.append(
            DigitEnd(
                input_label=label,
                klass="inspan_miss" if has_ptr else "outspan",
                field="",
                source="",
                pointers=list(pointers),
            )
        )
    return ends
