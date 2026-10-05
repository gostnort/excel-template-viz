"""用 MLM 事件特征对齐两表列；不用表头字符串，不用 LLM。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import numpy as np
from openpyxl import load_workbook

from fisher_groupoid.mlm_tokens import pick_model_id, pooled_vector


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_BOOK = PROJECT_ROOT / "docs" / "sample" / "执法堂业绩.xlsx"
TEMPLATE_BOOK = PROJECT_ROOT / "docs" / "sample" / "sample_template.xlsx"
_EMPTY = frozenset({"", "null", "none", "n/a"})
_DATE_PATTERNS = (
    re.compile(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:\s+\d{1,2}:\d{2}:\d{2})?$"),
    re.compile(r"^(\d{4})(\d{2})(\d{2})$"),
)
_CANON_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATE_VALUE_WEIGHT = 0.7
DATE_LOO_WEIGHT = 0.3
SDE_GAMMA = 0.25
SDE_BETA = 0.45
_TEMPORAL_AXIS_CACHE: dict[str, np.ndarray] = {}



def _floats(vector: np.ndarray) -> list[float]:
    """
    函数名: _floats
    作用: 向量写成浮点列表
    输入:
        vector (np.ndarray)
    输出:
        list[float]
    """
    return [float(x) for x in np.asarray(vector, dtype=np.float64).reshape(-1)]



def _cosine(left: np.ndarray, right: np.ndarray) -> float:
    """
    函数名: _cosine
    作用: 两向量余弦；零向量为 0
    输入:
        left (np.ndarray)
        right (np.ndarray)
    输出:
        float
    """
    a = np.asarray(left, dtype=np.float64).reshape(-1)
    b = np.asarray(right, dtype=np.float64).reshape(-1)
    n1 = float(np.linalg.norm(a))
    n2 = float(np.linalg.norm(b))
    if n1 < 1e-12 or n2 < 1e-12:
        return 0.0
    return float(np.clip(np.dot(a, b) / (n1 * n2), -1.0, 1.0))



def normalize_date_str(text: str) -> str:
    """
    函数名: normalize_date_str
    作用: 把各类日期字面改写成 YYYY-MM-DD；非法日不经 datetime 构造
    输入:
        text (str): 单元格字面
    输出:
        str: 标准日期或原文本
    """
    s = str(text).strip()
    for pat in _DATE_PATTERNS:
        matched = pat.match(s)
        if matched is None:
            continue
        year_s, month_s, day_s = matched.group(1), matched.group(2), matched.group(3)
        year_n = int(year_s)
        month_n = int(month_s)
        day_n = int(day_s)
        # 中文注释: 只查范围，不校验闰年，保留 1978-02-29 这类用户字面
        if 1900 <= year_n <= 2100 and 1 <= month_n <= 12 and 1 <= day_n <= 31:
            return f"{year_n:04d}-{month_n:02d}-{day_n:02d}"
    return s



def _cell_text(value: object) -> str:
    """
    函数名: _cell_text
    作用: 单元格转字面；Excel 日期去时间尾巴，字符串日期统一格式
    输入:
        value (object)
    输出:
        str
    """
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return normalize_date_str(str(value).strip())



def _is_empty(text: str) -> bool:
    """
    函数名: _is_empty
    作用: 空值或 NULL 不算观测
    输入:
        text (str)
    输出:
        bool
    """
    return str(text).strip().casefold() in _EMPTY



def _unit(vector: np.ndarray) -> np.ndarray:
    """
    函数名: _unit
    作用: 单位化；零向量原样返回
    输入:
        vector (np.ndarray)
    输出:
        np.ndarray
    """
    vec = np.asarray(vector, dtype=np.float64).reshape(-1)
    nrm = float(np.linalg.norm(vec))
    if nrm < 1e-12:
        return vec
    return vec / nrm



def _is_date_column(rows: list[dict[str, str]], label: str) -> bool:
    """
    函数名: _is_date_column
    作用: 非空格中过半已是 YYYY-MM-DD 则视为日期列
    输入:
        rows (list[dict[str, str]])
        label (str)
    输出:
        bool
    """
    dates_count = 0
    total = 0
    for item in rows:
        val = str(item.get(label) or "").strip()
        if _is_empty(val):
            continue
        total += 1
        if _CANON_DATE.match(val):
            dates_count += 1
    return total > 0 and (dates_count / total) >= 0.5



def _feat_is_date(feat: dict[str, list[float]]) -> bool:
    """
    函数名: _feat_is_date
    作用: 特征包里的日期列标记
    输入:
        feat (dict[str, list[float]])
    输出:
        bool
    """
    flag = feat.get("is_date") or []
    if not flag:
        return False
    return float(flag[0]) >= 0.5



def temporal_epoch_axis(model_id: str) -> np.ndarray:
    """
    函数名: temporal_epoch_axis
    作用: BERT 空间里历史年到现代年的方向基底
    输入:
        model_id (str)
    输出:
        np.ndarray
    """
    cached = _TEMPORAL_AXIS_CACHE.get(model_id)
    if cached is not None:
        return cached
    v_hist = _unit(pooled_vector("1978年", model_id=model_id))
    v_curr = _unit(pooled_vector("2026年", model_id=model_id))
    axis = _unit(v_hist - v_curr)
    _TEMPORAL_AXIS_CACHE[model_id] = axis
    return axis



def sde_renormalize_date_vector(
    raw_vec: np.ndarray,
    rows: list[dict[str, str]],
    label: str,
    *,
    model_id: str,
    gamma: float = SDE_GAMMA,
) -> np.ndarray:
    """
    函数名: sde_renormalize_date_vector
    作用: 用该列年份的平均值和标准差，沿与列向量垂直的时间方向挪一小步，再单位化
    输入:
        raw_vec (np.ndarray): 该列格子字面的平均向量
        rows (list[dict[str, str]]): 该表的所有数据行
        label (str): 列名
        model_id (str): BERT 模型名
        gamma (float): 年份平均值的步长系数，默认 SDE_GAMMA
    输出:
        np.ndarray: 挪步后的单位向量
    """
    v0 = _unit(raw_vec)
    # 列内容向量单位化，后面只改方向不改名字
    e_raw = temporal_epoch_axis(model_id)
    # 1978年减2026年，得到「更早相对更晚」的方向
    proj = float(np.dot(e_raw, v0)) * v0
    # e_raw 落在 v0 上的平行分量，内积乘 v0
    e_orth = _unit(e_raw - proj)
    # 减去平行分量，剩下与列向量垂直的时间方向
    if float(np.linalg.norm(e_orth)) < 1e-12:
        # 垂直分量几乎是零，时间方向与列向量共线，挪了等于没挪
        return v0
    year_deltas: list[float] = []
    # 收集该列每个非空日期相对 2000 年的缩放年份
    for item in rows:
        val = str(item.get(label) or "").strip()
        # label 这一格的字面，空则跳过
        if _is_empty(val):
            continue
        matched = re.match(r"^(\d{4})", val)
        # 只取开头四位当作年份
        if matched is None:
            continue
        year_n = float(matched.group(1))
        year_deltas.append((year_n - 2000.0) / 30.0)
        # 减 2000 再除 30，把年份压到大约 [-1, 1]
    if not year_deltas:
        # 这一列没有读出任何年份，原样返回
        return v0
    mean_tau = float(np.mean(year_deltas))
    # 该列年份的平均值
    std_tau = float(np.std(year_deltas))
    # 该列年份的标准差：两行同一天则为 0，跨几十年则较大
    coeff = float(SDE_BETA) * std_tau - float(gamma) * mean_tau
    # 跨度大则沿垂直时间方向多走；平均值把整列往早或晚微移
    return _unit(v0 + coeff * e_orth)
    # 走一步再单位化，得到新的列方向



def load_header_rows(path: Path, sheet: str, *, header_row: int = 1) -> tuple[list[str], list[dict[str, str]]]:
    """
    函数名: load_header_rows
    作用: 读表头与数据行；表头只当列键
    输入:
        path (Path)
        sheet (str)
        header_row (int): 1-based
    输出:
        tuple[list[str], list[dict[str, str]]]
    """
    book = load_workbook(path, data_only=True)
    try:
        if sheet not in book.sheetnames:
            raise KeyError(sheet)
        ws = book[sheet]
        max_col = int(ws.max_column or 1)
        max_row = int(ws.max_row or 1)
        headers: list[str] = []
        for col in range(1, max_col + 1):
            name = _cell_text(ws.cell(int(header_row), col).value)
            if name:
                headers.append(name)
        rows: list[dict[str, str]] = []
        for row_idx in range(int(header_row) + 1, max_row + 1):
            item: dict[str, str] = {}
            for col, name in enumerate(headers, start=1):
                item[name] = _cell_text(ws.cell(row_idx, col).value)
            if any(not _is_empty(text) for text in item.values()):
                rows.append(item)
        return headers, rows
    finally:
        book.close()



def values_only_row(values: dict[str, str], *, skip: str | None = None) -> str:
    """
    函数名: values_only_row
    作用: 只串单元格字面，不含表头
    输入:
        values (dict[str, str])
        skip (str | None): 要拿掉的列键
    输出:
        str
    """
    parts: list[str] = []
    for key, text in values.items():
        if skip is not None and key == skip:
            continue
        if _is_empty(text):
            continue
        parts.append(str(text).strip())
    return "，".join(parts)



def column_value_feature(rows: list[dict[str, str]], label: str, *, model_id: str) -> np.ndarray | None:
    """
    函数名: column_value_feature
    作用: 一列非空字面的单位向量均值
    输入:
        rows (list[dict[str, str]])
        label (str)
        model_id (str)
    输出:
        np.ndarray | None
    """
    acc: list[np.ndarray] = []
    for item in rows:
        text = str(item.get(label) or "").strip()
        if _is_empty(text):
            continue
        acc.append(_unit(pooled_vector(text, model_id=model_id)))
    if not acc:
        return None
    return _unit(np.mean(np.stack(acc, axis=0), axis=0))



def column_loo_feature(rows: list[dict[str, str]], label: str, *, model_id: str) -> np.ndarray | None:
    """
    函数名: column_loo_feature
    作用: 完整事件句减去去掉该列后的句向量，再跨行平均
    输入:
        rows (list[dict[str, str]])
        label (str)
        model_id (str)
    输出:
        np.ndarray | None
    """
    acc: list[np.ndarray] = []
    for item in rows:
        if label not in item or _is_empty(item.get(label) or ""):
            continue
        full_text = values_only_row(item)
        miss_text = values_only_row(item, skip=label)
        if not full_text or not miss_text or full_text == miss_text:
            continue
        full = pooled_vector(full_text, model_id=model_id)
        miss = pooled_vector(miss_text, model_id=model_id)
        # 中文注释: 按行单位化差分，避免长短字面主导模长
        acc.append(_unit(full - miss))
    if not acc:
        return None
    return _unit(np.mean(np.stack(acc, axis=0), axis=0))



def table_column_features(
    headers: list[str],
    rows: list[dict[str, str]],
    *,
    model_id: str,
) -> dict[str, dict[str, list[float]]]:
    """
    函数名: table_column_features
    作用: 每列的值云与留一列贡献；日期列值云做时间尺度穿衣
    输入:
        headers (list[str])
        rows (list[dict[str, str]])
        model_id (str)
    输出:
        dict[str, dict[str, list[float]]]
    """
    packed: dict[str, dict[str, list[float]]] = {}
    for name in headers:
        value_vec = column_value_feature(rows, name, model_id=model_id)
        loo_vec = column_loo_feature(rows, name, model_id=model_id)
        is_date = _is_date_column(rows, name)
        # 中文注释: 日期列值云走朗之万时间穿衣，LOO 保持原差分
        if is_date and value_vec is not None:
            value_vec = sde_renormalize_date_vector(
                value_vec, rows, name, model_id=model_id, gamma=SDE_GAMMA
            )
        packed[name] = {
            "value": _floats(value_vec) if value_vec is not None else [],
            "loo": _floats(loo_vec) if loo_vec is not None else [],
            "is_date": [1.0] if is_date else [0.0],
        }
    return packed



def _channel_cosine(src: dict[str, list[float]], dst: dict[str, list[float]], channel: str) -> float | None:
    """
    函数名: _channel_cosine
    作用: 同一通道余弦；缺则 None
    输入:
        src (dict[str, list[float]])
        dst (dict[str, list[float]])
        channel (str)
    输出:
        float | None
    """
    left = src.get(channel)
    right = dst.get(channel)
    if not left or not right:
        return None
    return _cosine(np.array(left, dtype=np.float64), np.array(right, dtype=np.float64))



def pair_score(src: dict[str, list[float]], dst: dict[str, list[float]]) -> float:
    """
    函数名: pair_score
    作用: 值云与留一列余弦；日期对日期加重值云
    输入:
        src (dict[str, list[float]])
        dst (dict[str, list[float]])
    输出:
        float
    """
    val = _channel_cosine(src, dst, "value")
    loo = _channel_cosine(src, dst, "loo")
    if _feat_is_date(src) and _feat_is_date(dst) and val is not None and loo is not None:
        return float(DATE_VALUE_WEIGHT * val + DATE_LOO_WEIGHT * loo)
    scores: list[float] = []
    if val is not None:
        scores.append(val)
    if loo is not None:
        scores.append(loo)
    if not scores:
        return 0.0
    return float(sum(scores) / len(scores))



def cosine_table(
    src_feats: dict[str, dict[str, list[float]]],
    dst_feats: dict[str, dict[str, list[float]]],
) -> dict[str, dict[str, float]]:
    """
    函数名: cosine_table
    作用: 源列 × 输出列分数表
    输入:
        src_feats (dict)
        dst_feats (dict)
    输出:
        dict[str, dict[str, float]]
    """
    table: dict[str, dict[str, float]] = {}
    for src_name, src_vec in src_feats.items():
        row: dict[str, float] = {}
        for dst_name, dst_vec in dst_feats.items():
            row[dst_name] = pair_score(src_vec, dst_vec)
        table[src_name] = row
    return table



def greedy_phi(
    table: dict[str, dict[str, float]],
    *,
    floor: float = 0.5,
    margin: float = 0.08,
    type_floor: float = 0.5,
) -> dict[str, str]:
    """
    函数名: greedy_phi
    作用: 只配显著胜出的槽；与最优分差小于裕度的同类高分则不配
    输入:
        table (dict[str, dict[str, float]])
        floor (float)
        margin (float)
        type_floor (float)
    输出:
        dict[str, str]
    """
    taken_src: set[str] = set()
    taken_dst: set[str] = set()
    phi: dict[str, str] = {}
    sources = list(table.keys())
    def _best(src: str) -> float:
        """
        函数名: _best
        作用: 该源列最高分
        输入:
            src (str)
        输出:
            float
        """
        row = table.get(src) or {}
        if not row:
            return -1.0
        return max(float(val) for val in row.values())
    ordered = sorted(sources, key=_best, reverse=True)
    for src in ordered:
        if src in taken_src:
            continue
        row = table.get(src) or {}
        ranked = sorted(row.items(), key=lambda item: float(item[1]), reverse=True)
        if not ranked:
            continue
        dst, score = ranked[0]
        if dst in taken_dst:
            continue
        if float(score) < float(floor):
            continue
        # 中文注释: 只有与最高分难以区分的高分竞争者，才算真歧义
        rivals = [
            name
            for name, val in row.items()
            if name != dst and float(val) >= float(type_floor) and (float(score) - float(val)) < float(margin)
        ]
        if rivals:
            continue
        second = float(ranked[1][1]) if len(ranked) > 1 else -1.0
        if second >= 0.0 and (float(score) - second) < float(margin):
            continue
        back_best = None
        back_score = -1.0
        back_second = -1.0
        for other in sources:
            if other in taken_src and other != src:
                continue
            val = float((table.get(other) or {}).get(dst, -1.0))
            if val > back_score:
                back_second = back_score
                back_score = val
                back_best = other
            elif val > back_second:
                back_second = val
        if back_best != src:
            continue
        if back_second >= 0.0 and (back_score - back_second) < float(margin):
            continue
        phi[src] = dst
        taken_src.add(src)
        taken_dst.add(dst)
    return phi



def char_header_equiv(left: str, right: str) -> bool:
    """
    函数名: char_header_equiv
    作用: 验收用字符等价，不参与配对
    输入:
        left (str)
        right (str)
    输出:
        bool
    """
    def _norm(text: str) -> str:
        """
        函数名: _norm
        作用: 去掉 # _ 空白
        输入:
            text (str)
        输出:
            str
        """
        out: list[str] = []
        for ch in str(text).casefold():
            if ch in "#_ \t":
                continue
            out.append(ch)
        return "".join(out)
    a = _norm(left)
    b = _norm(right)
    if not a or not b:
        return False
    return a == b



def verify_phi(phi: dict[str, str]) -> dict[str, dict]:
    """
    函数名: verify_phi
    作用: 事后字符验收
    输入:
        phi (dict[str, str])
    输出:
        dict[str, dict]
    """
    report: dict[str, dict] = {}
    for src, dst in phi.items():
        report[src] = {
            "dst": dst,
            "char_equiv": char_header_equiv(src, dst),
        }
    return report



@dataclass(frozen=True)
class SheetColumnMatch:
    """MLM 列对齐结果。"""

    src_sheet: str
    dst_sheet: str
    model: str
    src_headers: tuple[str, ...]
    dst_headers: tuple[str, ...]
    table: dict[str, dict[str, float]]
    phi: dict[str, str]
    verify: dict[str, dict]


    def unmatched_src(self) -> list[str]:
        """
        函数名: SheetColumnMatch.unmatched_src
        作用: 源表未配上的列
        输入: 无
        输出:
            list[str]
        """
        return [name for name in self.src_headers if name not in self.phi]


    def unmatched_dst(self) -> list[str]:
        """
        函数名: SheetColumnMatch.unmatched_dst
        作用: 模板未配上的列
        输入: 无
        输出:
            list[str]
        """
        taken = set(self.phi.values())
        return [name for name in self.dst_headers if name not in taken]


    def as_dict(self) -> dict:
        """
        函数名: SheetColumnMatch.as_dict
        作用: 序列化
        输入: 无
        输出:
            dict
        """
        return {
            "src_sheet": self.src_sheet,
            "dst_sheet": self.dst_sheet,
            "model": self.model,
            "src_headers": list(self.src_headers),
            "dst_headers": list(self.dst_headers),
            "table": self.table,
            "phi": dict(self.phi),
            "verify": self.verify,
            "unmatched_src": self.unmatched_src(),
            "unmatched_dst": self.unmatched_dst(),
        }



def match_source_to_template(
    *,
    src_path: Path | None = None,
    dst_path: Path | None = None,
    src_sheet: str = "sheet1",
    dst_sheet: str = "Input_sheet",
    floor: float = 0.5,
    margin: float = 0.08,
    type_floor: float = 0.5,
) -> SheetColumnMatch:
    """
    函数名: match_source_to_template
    作用: 只用 MLM 把源表列对齐到模板列
    输入:
        src_path (Path | None)
        dst_path (Path | None)
        src_sheet (str)
        dst_sheet (str)
        floor (float)
        margin (float)
        type_floor (float)
    输出:
        SheetColumnMatch
    """
    source = Path(src_path) if src_path is not None else SOURCE_BOOK
    dest = Path(dst_path) if dst_path is not None else TEMPLATE_BOOK
    src_headers, src_rows = load_header_rows(source, src_sheet)
    dst_headers, dst_rows = load_header_rows(dest, dst_sheet)
    blobs = list(src_headers) + list(dst_headers)
    for item in src_rows + dst_rows:
        blobs.extend(item.values())
    model_id = pick_model_id(*blobs)
    src_feats = table_column_features(src_headers, src_rows, model_id=model_id)
    dst_feats = table_column_features(dst_headers, dst_rows, model_id=model_id)
    table = cosine_table(src_feats, dst_feats)
    phi = greedy_phi(table, floor=floor, margin=margin, type_floor=type_floor)
    return SheetColumnMatch(
        src_sheet=src_sheet,
        dst_sheet=dst_sheet,
        model=model_id,
        src_headers=tuple(src_headers),
        dst_headers=tuple(dst_headers),
        table=table,
        phi=phi,
        verify=verify_phi(phi),
    )
