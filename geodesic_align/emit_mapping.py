"""把数字化与文本判定收成 MappingDecision，对齐 TOML 字段契约。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from geodesic_align.digit_processor import (
    DigitEnd,
    FunctionalClosure,
    TableView,
    _excel_col,
    cell_to_z,
    excel_formula_pair,
    id_lineage,
    run_digit_align,
    z_eq,
)
from geodesic_align.digit_router import route_columns
from geodesic_align.regex_deduce import deduce_regex_mapping


_DATE_IN_TEXT = (
    re.compile(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})"),
    re.compile(r"(\d+/\d+/\d+)"),
    re.compile(r"(\d+)/"),
    re.compile(r"\d+/(\d+)"),
)
_SHEET_REF = re.compile(r"'?\[(?P<book>[^\]]+)\](?P<sheet>[^'!]+)'?!")
_TOKEN = re.compile(r"[0-9a-z\u4e00-\u9fff]+", re.IGNORECASE)



@dataclass
class MappingDecision:
    """一条可写入 [[fields]] 的映射。source 只能是单个 [sources] 键。"""

    input_label: str
    field: str
    source: str
    cell_role: str
    regex: str = ""
    formula: str = ""
    is_id: bool = False
    klass: str = ""
    confidence: float = 1.0
    warnings: list[str] = field(default_factory=list)
    values: list[str] = field(default_factory=list)
    closure: FunctionalClosure | None = None



def regex_toml_literal(pattern: str) -> str:
    """
    函数名: regex_toml_literal
    作用: 把正则写成 TOML 单引号字面量；模式含单引号时才退回双引号
    输入:
        pattern (str): Python re 模式
    输出:
        str: 形如 regex = '\\d+'
    """
    if "'" in pattern:
        escaped = pattern.replace("\\", "\\\\").replace('"', '\\"')
        return f'regex = "{escaped}"'
    return f"regex = '{pattern}'"



def _decision_from_digit(end: DigitEnd) -> MappingDecision:
    """
    函数名: _decision_from_digit
    作用: 把 DigitEnd 收成单一 source 的 MappingDecision
    输入:
        end (DigitEnd): 数字化判定
    输出:
        MappingDecision
    """
    warnings = list(end.warnings)
    formula = ""
    role = "input"
    source = end.source
    field_name = end.field
    values: list[str] = []
    closure = None
    if end.klass in {"carry", "union", "union_carry"}:
        role = "data"
    elif end.klass == "derived" and end.physical == "internal":
        role = "formula"
        source = ""
        field_name = ""
        if len(end.operand_cols) == 2:
            col_a, col_b = end.operand_cols[0], end.operand_cols[1]
            op = end.formula_op
            formula = f"=${_excel_col(col_a)}{end.excel_row} {op} ${_excel_col(col_b)}{end.excel_row}"
    elif end.klass == "derived" and end.physical == "google":
        role = "data"
        closure = end.closure
        formula = closure.to_descriptor() if closure is not None else ""
        values = list(end.filled_values)
        # 得到算子字面，以及它对当前行算出的值
    elif end.klass == "derived" and len(end.operand_cols) == 2:
        role = "formula"
        formula = excel_formula_pair(
            end.source,
            end.operand_cols[0],
            end.source_b or end.source,
            end.operand_cols[1],
            end.excel_row,
            end.formula_op,
        )
        field_name = ""
    elif end.klass in {"outspan", "inspan_miss"}:
        role = "input"
        source = ""
        field_name = ""
    if "|" in source or "|" in field_name:
        raise ValueError("source 与 field 禁止管道符")
    return MappingDecision(
        input_label=end.input_label,
        field=field_name,
        source=source,
        cell_role=role,
        formula=formula,
        is_id=bool(end.is_id and role == "data"),
        klass=end.klass,
        warnings=warnings,
        values=values,
        closure=closure,
    )



def macro_formula(raw: str, sheet_to_source: dict[str, str]) -> tuple[str, str]:
    """
    函数名: macro_formula
    作用: 把外链公式里的工作表引用换成 '{source}' 宏
    输入:
        raw (str): Excel 公式原文
        sheet_to_source (dict[str, str]): 工作表名到 source 键
    输出:
        tuple[str, str]: (宏公式, 命中的 source 键)
    """
    source = ""

    def _repl(matched: re.Match[str]) -> str:
        nonlocal source
        key = sheet_to_source.get(matched.group("sheet"), "")
        if key and not source:
            source = key
        if not key:
            return matched.group(0)
        return "'{" + key + "}'!"

    return _SHEET_REF.sub(_repl, raw), source



def _formula_decision(route_label: str, kind: str, raw: str, tables: list[TableView]) -> MappingDecision:
    """
    函数名: _formula_decision
    作用: 内部公式清空 source；外部公式写成宏模板
    输入:
        route_label (str): 模板列名
        kind (str): INTERNAL_FORMULA 或 EXTERNAL_FORMULA
        raw (str): 公式原文
        tables (list[TableView]): 源表，用 sheet 名对齐
    输出:
        MappingDecision
    """
    if kind == "INTERNAL_FORMULA":
        return MappingDecision(route_label, "", "", "formula", formula="", klass="internal_formula")
    sheet_to_source = {table.sheet: table.source_key for table in tables if table.sheet}
    text, source = macro_formula(raw, sheet_to_source)
    return MappingDecision(route_label, "", source, "formula", formula=text, klass="external_formula")



def _tokens(text: str) -> list[str]:
    """
    函数名: _tokens
    作用: 文本切成可比的词
    输入:
        text (str): 格子字面
    输出:
        list[str]
    """
    return [item.lower() for item in _TOKEN.findall(str(text))]



def _text_covers(dest_text: str, src_text: str) -> bool:
    """
    函数名: _text_covers
    作用: 沿指针判断目标文本是否等于源文本，或长文本被源文本词集覆盖
    输入:
        dest_text (str): 模板格子
        src_text (str): 源格子
    输出:
        bool
    """
    dest_tok = _tokens(dest_text)
    src_tok = _tokens(src_text)
    if not dest_tok and not src_tok:
        return True
    if not dest_tok or not src_tok:
        return False
    if dest_tok == src_tok:
        return True
    joined = "".join(dest_tok)
    return len(joined) >= 8 and set(dest_tok) <= set(src_tok)



def _text_at(table: TableView, label: str, hits: list[tuple[str, int]]) -> str | None:
    """
    函数名: _text_at
    作用: 在行指针里取出这张表、这一列的格子
    输入:
        table (TableView): 源表
        label (str): 列名
        hits (list[tuple[str, int]]): 该行的源指针
    输出:
        str | None
    """
    if label not in table.headers:
        return None
    for key, row_idx in hits:
        if key != table.source_key or row_idx < 0 or row_idx >= len(table.rows):
            continue
        return str(table.rows[row_idx].get(label) or "")
    return None



def _table_named(sources: list[TableView], key: str) -> TableView | None:
    """
    函数名: _table_named
    作用: 按 source_key 或工作表名找到源表
    输入:
        sources (list[TableView]): 源表
        key (str): 键或表名
    输出:
        TableView | None
    """
    for table in sources:
        if table.source_key == key or table.sheet == key:
            return table
    return None


def resolve_text_derived_morphism(
    dest: TableView,
    dest_label: str,
    sources: list[TableView],
    lineage: list[list[tuple[str, int]]],
    pairs: list[tuple[str, str]],
) -> tuple[str, str, str, str, list[str]]:
    """
    函数名: resolve_text_derived_morphism
    作用: 多源文本只有在拼接同态成立时才写成公式，否则留给手工，不投影成单列
    输入:
        dest (TableView): 模板
        dest_label (str): 目标列
        sources (list[TableView]): 源表
        lineage (list): 行指针
        pairs (list[tuple[str, str]]): (源键, 列名)
    输出:
        tuple[str, str, str, str, list[str]]: (cell_role, source, field, formula, warnings)
    """
    warnings: list[str] = []
    if len(pairs) < 2:
        warnings.append("unresolved_derived_requires_manual_merge:")
        return "input", "", "", "", warnings
    left_key, left_field = pairs[0]
    right_key, right_field = pairs[1]
    tag = f"{left_key}.{left_field}|{right_key}.{right_field}"
    left_table = _table_named(sources, left_key)
    right_table = _table_named(sources, right_key)
    if left_table is None or right_table is None:
        warnings.append(f"unresolved_derived_requires_manual_merge:{tag}")
        return "input", "", "", "", warnings
    chosen: tuple[bool, str] | None = None
    for swapped, sep in ((False, ""), (False, " "), (True, ""), (True, " "), (False, "-"), (True, "-"), (False, "_"), (True, "_"), (False, "/"), (True, "/")):
        matched = True
        used = 0
        for idx, row in enumerate(dest.rows):
            dest_val = str(row.get(dest_label) or "").strip()
            if not dest_val:
                continue
            hits = lineage[idx] if idx < len(lineage) else []
            left_text = _text_at(left_table, left_field, hits)
            right_text = _text_at(right_table, right_field, hits)
            if left_text is None or right_text is None:
                matched = False
                break
            first, second = (right_text, left_text) if swapped else (left_text, right_text)
            if dest_val != f"{first}{sep}{second}":
                matched = False
                break
            used += 1
        if matched and used > 0:
            chosen = (swapped, sep)
            break
    if chosen is None:
        warnings.append(f"unresolved_derived_requires_manual_merge:{tag}")
        return "input", "", "", "", warnings
    swapped, sep = chosen
    if swapped:
        left_table, right_table = right_table, left_table
        left_field, right_field = right_field, left_field
    warnings.append(f"multi_source_derived_synthesis:{left_table.source_key}.{left_field},{right_table.source_key}.{right_field}")
    # 得到已经在已填行上成立的拼接
    if left_table.physical == "google" or right_table.physical == "google":
        closure = FunctionalClosure("&", left_table.source_key, left_field, right_table.source_key, right_field, sep)
        return "data", "", "", closure.to_descriptor(), warnings
    row = int(left_table.header_row) + 1
    for hits in lineage:
        for key, src_idx in hits:
            if key == left_table.source_key:
                row = int(left_table.header_row) + 1 + int(src_idx)
                break
        else:
            continue
        break
    left_ref = f"='{{{left_table.source_key}}}'!${_excel_col(left_table.headers.index(left_field) + 1)}{row}"
    right_ref = f"'{{{right_table.source_key}}}'!${_excel_col(right_table.headers.index(right_field) + 1)}{row}"
    middle = f' & "{sep}" & ' if sep else " & "
    return "formula", "", "", left_ref + middle + right_ref, warnings



def _try_text_concat_along_lineage(
    dest: TableView,
    sources: list[TableView],
    lineage: list[list[tuple[str, int]]],
    taken: set[str],
) -> dict[str, MappingDecision]:
    """
    函数名: _try_text_concat_along_lineage
    作用: 对未对上的文本列，在源表文本列中搜索二元拼接同态 (A & B)
    输入:
        dest (TableView): 模板
        sources (list[TableView]): 源表
        lineage (list): 行指针
        taken (set[str]): 已定案的列
    输出:
        dict[str, MappingDecision]
    """
    routes = {item.label: item for item in route_columns(dest.headers, dest.rows)}
    packed: dict[str, MappingDecision] = {}
    source_cols: list[tuple[TableView, str]] = []
    for table in sources:
        for item in route_columns(table.headers, table.rows):
            if item.channel != "formula":
                source_cols.append((table, item.label))
    for label, route in routes.items():
        if label in taken or route.channel != "text":
            continue
        found: MappingDecision | None = None
        for i, (left_t, left_f) in enumerate(source_cols):
            for right_t, right_f in source_cols[i + 1:]:
                pairs = [(left_t.source_key, left_f), (right_t.source_key, right_f)]
                role, source, field_name, formula, warnings = resolve_text_derived_morphism(
                    dest, label, sources, lineage, pairs
                )
                if role == "formula" or (role == "data" and formula):
                    found = MappingDecision(
                        input_label=label,
                        field=field_name,
                        source=source,
                        cell_role=role,
                        formula=formula,
                        klass="derived",
                        confidence=1.0,
                        warnings=warnings,
                    )
                    break
            if found is not None:
                break
        if found is not None:
            packed[label] = found
    return packed



def _try_regex(
    dest: TableView,
    sources: list[TableView],
    decision: MappingDecision,
    lineage: list[list[tuple[str, int]]],
) -> MappingDecision:
    """
    函数名: _try_regex
    作用: 先走超集归纳；日期字面对不上时，仍按捕获组的 z 比对
    输入:
        dest (TableView): 模板
        sources (list[TableView]): 源表
        decision (MappingDecision): 当前判定
        lineage (list): 每行全部 (source_key, 源行号)
    输出:
        MappingDecision
    """
    decided = deduce_regex_mapping(dest, sources, lineage, decision)
    if decided.cell_role != "input":
        return decided
    return _try_date_capture(dest, sources, decided, lineage)



def _try_date_capture(
    dest: TableView,
    sources: list[TableView],
    decision: MappingDecision,
    lineage: list[list[tuple[str, int]]],
) -> MappingDecision:
    """
    函数名: _try_date_capture
    作用: 源句里的日期与模板日期 z 相等时收成捕获组正则
    输入:
        dest (TableView): 模板
        sources (list[TableView]): 源表
        decision (MappingDecision): 仍为 input 的判定
        lineage (list): 每行全部 (source_key, 源行号)
    输出:
        MappingDecision
    """
    routes = {item.label: item for item in route_columns(dest.headers, dest.rows)}
    route = routes.get(decision.input_label)
    if route is None or route.kind != "DATETIME":
        return decision
    dest_z = [cell_to_z(str(row.get(decision.input_label) or ""), kind=route.kind) for row in dest.rows]
    for table in sources:
        text_labels = [
            item.label for item in route_columns(table.headers, table.rows) if item.channel != "formula"
        ]
        for label in text_labels:
            for pattern in _DATE_IN_TEXT:
                ok = True
                valid_hits = 0
                # 中文注释: 只核已填的目标格，空白行不计入失败
                for idx, row in enumerate(dest.rows):
                    dest_val = str(row.get(decision.input_label) or "").strip()
                    if not dest_val:
                        continue
                    value = dest_z[idx]
                    hits = [hit for hit in lineage[idx] if hit[0] == table.source_key] if idx < len(lineage) else []
                    if not hits:
                        ok = False
                        break
                    matched = False
                    for _key, row_idx in hits:
                        if row_idx >= len(table.rows):
                            continue
                        for found in pattern.finditer(str(table.rows[row_idx].get(label) or "")):
                            captured = found.group(1)
                            parsed = cell_to_z(captured, kind="DATETIME")
                            if z_eq(parsed, value):
                                matched = True
                                break
                    if not matched:
                        ok = False
                        break
                    valid_hits += 1
                if not ok or valid_hits <= 0:
                    continue
                decision.cell_role = "regex"
                decision.source = table.source_key
                decision.field = label
                decision.regex = pattern.pattern
                decision.klass = "regex"
                return decision
    return decision


def _text_along_lineage(
    dest: TableView,
    sources: list[TableView],
    lineage: list[list[tuple[str, int]]],
    taken: set[str],
) -> dict[str, MappingDecision]:
    """
    函数名: _text_along_lineage
    作用: 文本列沿 ID 行指针做相等或词集覆盖，不看列名特判
    输入:
        dest (TableView): 模板
        sources (list[TableView]): 源表
        lineage (list): 每行全部源指针
        taken (set[str]): 已被公式或数字通道占用的列
    输出:
        dict[str, MappingDecision]
    """
    routes = {item.label: item for item in route_columns(dest.headers, dest.rows)}
    packed: dict[str, MappingDecision] = {}
    for label, route in routes.items():
        if label in taken or route.channel != "text":
            continue
        best: tuple[int, str, str] | None = None
        for table in sources:
            for item in route_columns(table.headers, table.rows):
                if item.channel == "formula":
                    continue
                exact = 0
                ok = True
                valid_hits = 0
                # 只核已填的目标格，空白行不截断整列
                for idx, row in enumerate(dest.rows):
                    dest_text = str(row.get(label) or "").strip()
                    # 得到目标格原文
                    if not dest_text:
                        continue
                    hits = [hit for hit in lineage[idx] if hit[0] == table.source_key] if idx < len(lineage) else []
                    # 得到该行在当前源表上的指针
                    if not hits:
                        ok = False
                        # 得到已填行没有指针，本列失败
                        break
                    covered = False
                    for _key, row_idx in hits:
                        if row_idx >= len(table.rows):
                            continue
                        src_text = str(table.rows[row_idx].get(item.label) or "")
                        # 得到指针所指源格原文
                        if _text_covers(dest_text, src_text):
                            covered = True
                            # 得到目标文本被源格覆盖
                            if _tokens(dest_text) and _tokens(dest_text) == _tokens(src_text):
                                exact += 1
                                # 得到一次词集完全相等
                            break
                    if not covered:
                        ok = False
                        break
                    valid_hits += 1
                # 得到已填样本的命中数
                if not ok or valid_hits <= 0:
                    continue
                if best is None or exact > best[0]:
                    best = (exact, table.source_key, item.label)
        if best is None:
            continue
        packed[label] = MappingDecision(
            label,
            best[2],
            best[1],
            "data",
            klass="carry",
            confidence=1.0 if best[0] else 0.8,
        )
    return packed



def sources_table(tables: list[TableView]) -> dict[str, str | list[str]]:
    """
    函数名: sources_table
    作用: 生成 [sources] 两套物理结构；调用方传入已写好的 locator
    输入:
        tables (list[TableView]): 源表，source_key 为键，rows 不入表
    输出:
        dict: 键到 locator；locator 由 TableView 不携带，这里只占位空串
    """
    packed: dict[str, str | list[str]] = {}
    for table in tables:
        if table.physical == "google":
            packed[table.source_key] = ["", ""]
        else:
            packed[table.source_key] = ""
    return packed



def build_sources(locators: dict[str, str | list[str]]) -> dict[str, str | list[str]]:
    """
    函数名: build_sources
    作用: 校验 [sources] 值是 Excel 单字符串或 Google 二元组
    输入:
        locators (dict): 源键到定位
    输出:
        dict
    """
    packed: dict[str, str | list[str]] = {}
    for key, value in locators.items():
        if "|" in str(key):
            raise ValueError("sources 键禁止管道符")
        if isinstance(value, str):
            packed[key] = value
            continue
        if isinstance(value, (list, tuple)) and len(value) == 2:
            url = str(value[0])
            if "[" in url or "]" in url:
                raise ValueError("Google URL 禁止方括号")
            packed[key] = [url, str(value[1])]
            continue
        raise ValueError("sources 只能是字符串或二元组")
    return packed



def recover_mapping(
    sources: list[TableView],
    dest: TableView,
    *,
    text_ends: list | None = None,
) -> list[MappingDecision]:
    """
    函数名: recover_mapping
    作用: 数字化结果优先，文本列用 GeodesicEnd，合成每条模板列一条决策
    输入:
        sources (list[TableView]): 源表
        dest (TableView): 已填模板
        text_ends (list | None): 文本通道 GeodesicEnd
    输出:
        list[MappingDecision]
    """
    routes = {item.label: item for item in route_columns(dest.headers, dest.rows)}
    by_label: dict[str, MappingDecision] = {}
    for label, route in routes.items():
        if route.channel == "formula":
            by_label[label] = _formula_decision(label, route.kind, route.raw_formula, sources)
    digit_ends = run_digit_align(sources, dest)
    lineage = id_lineage(dest, sources)
    for item in digit_ends:
        if item.input_label in by_label:
            continue
        by_label[item.input_label] = _try_regex(dest, sources, _decision_from_digit(item), lineage)
    for end in text_ends or []:
        if end.input_label in by_label:
            continue
        role = "input"
        source = ""
        field_name = ""
        formula = ""
        warnings: list[str] = []
        confidence = 0.0 if end.klass in {"outspan", "inspan_miss"} else 1.0
        sheets = [bit for bit in str(end.source_sheet).split("|") if bit]
        names = [bit for bit in str(end.field).split("|") if bit]
        if end.klass == "carry":
            role = "data"
            source = sheets[0] if sheets else ""
            field_name = names[0] if names else ""
        elif end.klass == "derived" and len(names) >= 2:
            if len(sheets) == len(names):
                pairs = list(zip(sheets, names))
            elif len(sheets) == 1:
                pairs = [(sheets[0], name) for name in names]
            else:
                pairs = list(zip(sheets, names))
            role, source, field_name, formula, warnings = resolve_text_derived_morphism(
                dest, end.input_label, sources, lineage, pairs,
            )
            confidence = 0.5 if role == "formula" else 0.0
        elif end.klass == "derived":
            role = "data"
            source = sheets[0] if sheets else ""
            field_name = names[0] if names else ""
            confidence = 0.5
        by_label[end.input_label] = MappingDecision(
            input_label=end.input_label,
            field=field_name,
            source=source,
            cell_role=role,
            formula=formula,
            klass=end.klass,
            confidence=confidence,
            warnings=warnings,
        )
    by_label.update(_text_along_lineage(dest, sources, lineage, set(by_label)))
    by_label.update(_try_text_concat_along_lineage(dest, sources, lineage, set(by_label)))
    ordered: list[MappingDecision] = []
    for label in dest.headers:
        if label in by_label:
            ordered.append(by_label[label])
            continue
        ordered.append(MappingDecision(label, "", "", "input", klass="outspan", confidence=0.0))
    return ordered
