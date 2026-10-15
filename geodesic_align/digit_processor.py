"""数字化通道：z = x + yi，ID 集合、行指针、搬运与非平凡代数。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from geodesic_align.digit_router import ColumnRoute, route_columns


EXCEL_EPOCH = date(1899, 12, 30)
Z_EPS = 1e-9
SENTINEL = complex(0.0, -1.0)
_EMPTY = frozenset({"", "null", "none", "n/a", "na", "暂无", "-", "--"})
_DATE_TIME = re.compile(
    r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?$"
)
_CLOCK = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")
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
        if self.op in {"+", "-", "*"}:
            try:
                left_num = float(left_val)
                right_num = float(right_val)
            except (TypeError, ValueError):
                return ""
            if self.op == "+":
                result = left_num + right_num
            elif self.op == "-":
                result = left_num - right_num
            else:
                result = left_num * right_num
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



def _clock_fraction(hour: int, minute: int, second: int) -> float | None:
    """
    函数名: _clock_fraction
    作用: 时刻折成日的小数；非法时钟返回 None
    输入:
        hour (int): 时
        minute (int): 分
        second (int): 秒
    输出:
        float | None
    """
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        return None
    return (hour * 3600 + minute * 60 + second) / 86400.0



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



def cell_to_z(text: str, *, kind: str) -> complex:
    """
    函数名: cell_to_z
    作用: 把格子编成 z = x + yi；失败为 0 + (-1)i，不抛异常
    输入:
        text (str): 格子字面
        kind (str): ID_CODE / NUMERIC / DATETIME
    输出:
        complex
    """
    # 去掉首尾空白，空值和哨兵直接记为 0+(-1)i
    raw = str(text).strip()
    # 得到去空白后的格子原文
    if raw.lower() in _EMPTY or raw in {"暂无"}:
        return SENTINEL
    # 得到哨兵，两枚哨兵互不相等
    # 会计括号表示负数，并剥掉币符和千分位
    negative = False
    body = raw
    if body.startswith("(") and body.endswith(")"):
        negative = True
        body = body[1:-1].strip()
        # 得到去掉括号后的正文，并记下负号
    body = body.replace("¥", "").replace("￥", "").replace("$", "").replace(",", "").strip()
    # 得到去掉币符和逗号后的正文
    # 井号开头的标识码去掉前缀，再按数值解析
    if kind == "ID_CODE":
        body = body[1:] if body.startswith("#") else body
        # 得到去掉井号后的正文
    # 百分号按百分数除以 100，虚部保持 0
    if body.endswith("%") and kind != "ID_CODE":
        try:
            val = float(body[:-1].strip()) / 100.0
        except ValueError:
            return SENTINEL
            # 得到无法解析的百分数哨兵
        if negative:
            val = -val
        return complex(val, 0.0)
        # 得到百分数的实数 z
    # 纯时刻折成日分数，只在日期列上生效
    clock = _CLOCK.fullmatch(body)
    # 得到是否整格都是时:分:秒
    if clock is not None and kind == "DATETIME":
        sec = int(clock.group(3) or 0)
        frac = _clock_fraction(int(clock.group(1)), int(clock.group(2)), sec)
        # 得到一天中的小数，非法时钟为 None
        if frac is None:
            return SENTINEL
            # 得到非法时刻哨兵
        return complex(-frac if negative else frac, 0.0)
        # 得到只有时刻的实数 z
    # 年月日字面转成 Excel 序列，非法日把溢出记在虚部
    matched = _DATE_TIME.fullmatch(body)
    # 得到是否整格都是日期或日期加时刻
    if matched is not None and kind == "DATETIME":
        hour = int(matched.group(4) or 0)
        minute = int(matched.group(5) or 0)
        sec = int(matched.group(6) or 0)
        frac = 0.0
        if matched.group(4) is not None:
            got = _clock_fraction(hour, minute, sec)
            # 得到日期后面的时刻小数
            if got is None:
                return SENTINEL
                # 得到非法时刻哨兵
            frac = got
        z = _date_serial(int(matched.group(1)), int(matched.group(2)), int(matched.group(3)), frac)
        # 得到序列号在实部、钳位溢出在虚部的 z
        if negative and z.imag >= 0.0:
            return complex(-z.real, z.imag)
            # 得到实部取负、虚部保留的 z
        return z
        # 得到日期 z
    # 日期列上的纯数字按 Excel 序列号收录
    if kind == "DATETIME":
        try:
            serial = float(body)
        except ValueError:
            return SENTINEL
            # 得到无法解析的日期哨兵
        if negative:
            serial = -serial
        return complex(serial, 0.0)
        # 得到虚部为 0 的序列号 z
    # 其余按普通浮点收录，失败仍是哨兵
    try:
        val = float(body)
    except ValueError:
        return SENTINEL
        # 得到无法解析的数值哨兵
    if negative:
        val = -val
    return complex(val, 0.0)
    # 得到虚部为 0 的数值 z



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
    作用: 列名字符袋余弦，仅用于已通过值检验的候选打破平局
    输入:
        left (str): 表头
        right (str): 表头
    输出:
        float
    """
    def bag(text: str) -> dict[str, float]:
        counts: dict[str, float] = {}
        for ch in str(text).lower():
            if ch.strip():
                counts[ch] = counts.get(ch, 0.0) + 1.0
        return counts
    a = bag(left)
    b = bag(right)
    keys = set(a) | set(b)
    if not keys:
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for key in keys:
        dot += a.get(key, 0.0) * b.get(key, 0.0)
        na += a.get(key, 0.0) ** 2
        nb += b.get(key, 0.0) ** 2
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return float(dot / ((na ** 0.5) * (nb ** 0.5)))



def _clean_std(values: list[complex]) -> float:
    """
    函数名: _clean_std
    作用: 干净实部的标准差；常数列（含全 0、全 1）为 0
    输入:
        values (list[complex]): 列上的 z
    输出:
        float
    """
    reals = [float(item.real) for item in values if item.imag == 0.0]
    if len(reals) < 2:
        return 0.0
    return float(np.std(np.asarray(reals, dtype=np.float64)))



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



def _build_pointers(
    dest_ids: list[complex],
    sources: list[TableView],
    id_cols: dict[str, str],
) -> list[tuple[str, int] | None]:
    """
    函数名: _build_pointers
    作用: 用量化后的 ID z 把模板行指到源表行
    输入:
        dest_ids (list[complex]): 模板 ID 列
        sources (list[TableView]): 源表
        id_cols (dict[str, str]): source_key → ID 列名
    输出:
        list[tuple[str, int] | None]
    """
    index: dict[complex, list[tuple[str, int]]] = {}
    for table in sources:
        label = id_cols.get(table.source_key)
        if not label:
            continue
        series = column_z(table.rows, label, "ID_CODE")
        for row_idx, value in enumerate(series):
            if value.imag < 0.0:
                continue
            index.setdefault(quantize_z(value), []).append((table.source_key, row_idx))
    pointers: list[tuple[str, int] | None] = []
    for value in dest_ids:
        if value.imag < 0.0:
            pointers.append(None)
            continue
        hits = index.get(quantize_z(value), [])
        if not hits:
            pointers.append(None)
            continue
        pointers.append(hits[0])
    return pointers



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
    # 结构化代码按原文入集合
    if kind in {"STRUCTURED_CODE", "SHORT_STRING", "LONG_STRING"}:
        return raw
    # 得到原文键
    # 数值、日期和 ID 先收成 z，再量化成集合键
    if kind == "DATETIME":
        z_kind = "DATETIME"
    elif kind == "ID_CODE":
        z_kind = "ID_CODE"
    else:
        z_kind = "NUMERIC"
    value = cell_to_z(raw, kind=z_kind)
    # 得到 z = x + yi
    if value.imag < 0.0:
        return None
    # 得到哨兵，本格不进集合
    packed = quantize_z(value)
    # 得到四舍五入后的 z
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



def _values_on_pointer(
    table: TableView,
    label: str,
    kind: str,
    pointers: list[tuple[str, int] | None],
    row_indexes: list[int],
) -> list[complex] | None:
    """
    函数名: _values_on_pointer
    作用: 按行指针取出源列 z；指针不在该表则失败
    输入:
        table (TableView): 源表
        label (str): 源列名
        kind (str): 列类型
        pointers (list): 行指针
        row_indexes (list[int]): 要用的模板行号
    输出:
        list[complex] | None
    """
    series = column_z(table.rows, label, kind)
    picked: list[complex] = []
    for idx in row_indexes:
        ptr = pointers[idx]
        if ptr is None or ptr[0] != table.source_key:
            return None
        if ptr[1] < 0 or ptr[1] >= len(series):
            return None
        picked.append(series[ptr[1]])
    return picked



def _match_rows(dest: list[complex], src: list[complex]) -> bool:
    """
    函数名: _match_rows
    作用: 对齐后的两列是否逐格 z_eq
    输入:
        dest (list[complex]): 模板 z
        src (list[complex]): 源 z
    输出:
        bool
    """
    if len(dest) != len(src) or not dest:
        return False
    for left, right in zip(dest, src):
        if not z_eq(left, right):
            return False
    return True



def _plain_on_pointer(
    table: TableView,
    label: str,
    pointers: list[tuple[str, int] | None],
    row_indexes: list[int],
) -> list[str] | None:
    """
    函数名: _plain_on_pointer
    作用: 按行指针取源列原文，供结构化代码逐字比对
    输入:
        table (TableView): 源表
        label (str): 源列名
        pointers (list): 行指针
        row_indexes (list[int]): 模板行号
    输出:
        list[str] | None
    """
    picked: list[str] = []
    for idx in row_indexes:
        ptr = pointers[idx]
        if ptr is None or ptr[0] != table.source_key:
            return None
        if ptr[1] < 0 or ptr[1] >= len(table.rows):
            return None
        picked.append(str(table.rows[ptr[1]].get(label) or "").strip())
    return picked



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
) -> tuple[str, str] | None:
    """
    函数名: _try_carry
    作用: 全部行指针落在同一源且该源有一列逐格相等
    输入:
        dest_label (str): 模板列名
        dest_z (list[complex]): 模板列 z
        kind (str): 列类型
        pointers (list): 行指针
        sources (list[TableView]): 源表
        routes (dict): 各表列路由
    输出:
        tuple[str, str] | None: (source_key, field)
    """
    # 只看已填目标行的指针，空行不参与
    keys = {pointers[idx][0] for idx in active if pointers[idx] is not None}
    # 得到有效行落到哪些源表
    if not active or len(keys) != 1 or any(pointers[idx] is None for idx in active):
        return None
    # 得到无法单源搬运
    source_key = next(iter(keys))
    # 得到唯一源表键
    table = next(item for item in sources if item.source_key == source_key)
    # 得到该源表
    # 只在同物理类型的数字列里找逐格相等的列
    headers = [
        name for name, route in routes[source_key].items()
        if route.channel == "digit" and route.kind == kind
    ]
    # 得到候选源列名
    ordered = [dest_label] if dest_label in headers else []
    ordered.extend(name for name in headers if name != dest_label)
    best: tuple[str, float] | None = None
    idxs = list(active)
    for name in ordered:
        if not _column_agrees(table, name, kind, pointers, idxs, dest_z, dest_plain):
            continue
        score = _header_cos(dest_label, name)
        # 得到表头字符余弦，只用于同分挑选
        if best is None or score > best[1]:
            best = (name, score)
            # 得到当前最优源列
    if best is None:
        return None
    # 得到没有全等列
    return source_key, best[0]
    # 得到源表键和搬运列名



def _try_union_carry(
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
    函数名: _try_union_carry
    作用: 指针跨多表时，每张表只核对自己名下的行
    输入:
        dest_label (str): 模板列名
        dest_z (list[complex]): 模板列 z
        kind (str): 列类型
        pointers (list): 行指针
        sources (list[TableView]): 源表
        routes (dict): 各表列路由
    输出:
        list[tuple[str, str]] | None
    """
    # 按已填行把指针分组，空目标格不进组
    groups: dict[str, list[int]] = {}
    for idx in active:
        ptr = pointers[idx]
        if ptr is None:
            return None
        groups.setdefault(ptr[0], []).append(idx)
    # 得到每个源表名下的有效行号
    if len(groups) < 2:
        return None
    # 得到不是跨表搬运
    chosen: list[tuple[str, str]] = []
    by_key = {item.source_key: item for item in sources}
    for source_key, idxs in groups.items():
        table = by_key[source_key]
        headers = [
            name for name, route in routes[source_key].items()
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
        op (str): + - *
        left (float): 左实部
        right (float): 右实部
    输出:
        float
    """
    if op == "+":
        return left + right
    if op == "-":
        return left - right
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
        op (str): + - *
    输出:
        bool
    """
    if _clean_std(left_z) <= 0.0 or _clean_std(right_z) <= 0.0:
        return False
    for dest, left, right in zip(dest_z, left_z, right_z):
        if dest.imag != 0.0 or left.imag != 0.0 or right.imag != 0.0:
            return False
        got = _op_value(op, left.real, right.real)
        if abs(got - dest.real) >= Z_EPS:
            return False
    return True



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
            for op in ("+", "-", "*"):
                if not _formula_holds(dest_z, left_z, right_z, op):
                    continue
                score = _header_cos(dest_label, left_name) + _header_cos(dest_label, right_name)
                if best is None or score > best[0]:
                    best = (score, left_name, op, right_name)
            if _formula_holds(dest_z, right_z, left_z, "-"):
                score = _header_cos(dest_label, right_name) + _header_cos(dest_label, left_name)
                if best is None or score > best[0]:
                    best = (score, right_name, "-", left_name)
    if best is None:
        return None
    return best[1], best[2], best[3]



def _aligned_source_series(
    table: TableView,
    label: str,
    kind: str,
    pointers: list[tuple[str, int] | None],
) -> list[complex] | None:
    """
    函数名: _aligned_source_series
    作用: 每个模板行都从同一张源表取出该列；跨表则失败
    输入:
        table (TableView): 源表
        label (str): 列名
        kind (str): 列类型
        pointers (list): 行指针
    输出:
        list[complex] | None
    """
    return _values_on_pointer(table, label, kind, pointers, list(range(len(pointers))))



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
            for op in ("+", "-", "*"):
                if not _formula_holds(want, left_z, right_z, op):
                    continue
                score = _header_cos(dest_label, left_name) + _header_cos(dest_label, right_name)
                if best is None or score > best[0]:
                    best = (score, left_table, left_name, op, right_table, right_name)
            if _formula_holds(want, right_z, left_z, "-"):
                score = _header_cos(dest_label, right_name) + _header_cos(dest_label, left_name)
                if best is None or score > best[0]:
                    best = (score, right_table, right_name, "-", left_table, left_name)
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



def excel_formula(source_key: str, col_a: int, col_b: int, row: int, op: str) -> str:
    """
    函数名: excel_formula
    作用: 列绝对、行相对的外链公式，禁止锁死行号
    输入:
        source_key (str): [sources] 键
        col_a (int): 左列 1-based
        col_b (int): 右列 1-based
        row (int): instance 0 的源行号，不加 $
        op (str): + - *
    输出:
        str
    """
    left = f"='{{{source_key}}}'!${_excel_col(col_a)}{int(row)}"
    right = f"'{{{source_key}}}'!${_excel_col(col_b)}{int(row)}"
    symbol = " & " if op == "&" else f" {op} "
    return left + symbol + right



def excel_formula_pair(
    source_a: str,
    col_a: int,
    source_b: str,
    col_b: int,
    row: int,
    op: str,
) -> str:
    """
    函数名: excel_formula_pair
    作用: 两个源可以不同；列绝对、行相对，禁止锁死行号
    输入:
        source_a (str): 左源键
        col_a (int): 左列 1-based
        source_b (str): 右源键
        col_b (int): 右列 1-based
        row (int): 行号，不加 $
        op (str): + - *
    输出:
        str
    """
    if source_a == source_b or not source_b:
        return excel_formula(source_a, col_a, col_b, row, op)
    left = f"='{{{source_a}}}'!${_excel_col(col_a)}{int(row)}"
    right = f"'{{{source_b}}}'!${_excel_col(col_b)}{int(row)}"
    symbol = " & " if op == "&" else f" {op} "
    return left + symbol + right



def _id_end(
    label: str,
    dest_z: list[complex],
    sources: list[TableView],
    id_cols: dict[str, str],
    pointers: list[tuple[str, int] | None],
) -> DigitEnd:
    """
    函数名: _id_end
    作用: ID 列按集合覆盖判 union 或 carry，禁止 derived
    输入:
        label (str): 模板 ID 列名
        dest_z (list[complex]): 模板 ID 的 z
        sources (list[TableView]): 源表
        id_cols (dict[str, str]): 源 ID 列
        pointers (list): 行指针
    输出:
        DigitEnd
    """
    dest_set = set_of_z(dest_z)
    contributors: list[tuple[str, str]] = []
    for table in sources:
        src_label = id_cols.get(table.source_key)
        if not src_label:
            continue
        src_set = set_of_z(column_z(table.rows, src_label, "ID_CODE"))
        if dest_set & src_set:
            contributors.append((table.source_key, src_label))
    covered = set()
    for table in sources:
        src_label = id_cols.get(table.source_key)
        if not src_label:
            continue
        covered |= set_of_z(column_z(table.rows, src_label, "ID_CODE"))
    if dest_set and dest_set <= covered and len(contributors) >= 2:
        klass = "union"
    elif dest_set and dest_set <= covered and len(contributors) == 1:
        klass = "carry"
    elif dest_set and dest_set <= covered and len(contributors) == 0:
        klass = "outspan"
    elif not dest_set:
        klass = "outspan"
    else:
        klass = "outspan" if not contributors else "inspan_miss"
    if dest_set and not (dest_set <= covered):
        klass = "outspan"
    source = _majority_key(pointers) or (contributors[0][0] if contributors else "")
    field_name = ""
    for key, name in contributors:
        if key == source:
            field_name = name
            break
    if not field_name and contributors:
        field_name = contributors[0][1]
        source = contributors[0][0]
    warnings: list[str] = []
    if len(contributors) >= 2:
        keys = ",".join(item[0] for item in contributors)
        warnings.append(f"multi_source_overlap:{keys}")
        names = {item[1] for item in contributors}
        if len(names) > 1:
            bits = "|".join(f"{key}.{name}" for key, name in contributors)
            warnings.append(f"heterogeneous_headers:{bits}")
    return DigitEnd(
        input_label=label,
        klass=klass,
        field=field_name,
        source=source,
        contributors=contributors,
        physical="excel",
        is_id=True,
        warnings=warnings,
        pointers=list(pointers),
    )



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
        # 先试单源逐格搬运
        carried = _try_carry(label, dest_z, route.kind, pointers, sources, src_routes, active, plain)
        # 得到搬运到的源列，失败为 None
        if carried is not None:
            table = by_key[carried[0]]
            ends.append(
                DigitEnd(
                    input_label=label,
                    klass="carry",
                    field=carried[1],
                    source=carried[0],
                    contributors=[carried],
                    physical=table.physical,
                    pointers=list(pointers),
                    excel_row=int(table.header_row) + 1 + (pointers[0][1] if pointers and pointers[0] else 0),
                )
            )
            continue
        unioned = _try_union_carry(label, dest_z, route.kind, pointers, sources, src_routes, active, plain)
        if unioned is not None:
            source = _majority_key(pointers)
            field_name = next(name for key, name in unioned if key == source)
            warnings = ["multi_source_overlap:" + ",".join(key for key, _name in unioned)]
            names = {name for _key, name in unioned}
            if len(names) > 1:
                bits = "|".join(f"{key}.{name}" for key, name in unioned)
                warnings.append(f"heterogeneous_headers:{bits}")
            ends.append(
                DigitEnd(
                    input_label=label,
                    klass="union_carry",
                    field=field_name,
                    source=source,
                    contributors=unioned,
                    physical=by_key[source].physical,
                    warnings=warnings,
                    pointers=list(pointers),
                )
            )
            continue
        internal = _try_internal_derived(label, dest_z, route.kind, dest, dest_routes)
        if internal is not None:
            ends.append(
                DigitEnd(
                    input_label=label,
                    klass="derived",
                    field="",
                    source="",
                    formula_op=internal[1],
                    operand_headers=[internal[0], internal[2]],
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
