"""按 example_workflow 的调用顺序前进一步，并画出这一步之后的数据。"""

from __future__ import annotations

import math
import subprocess
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from matplotlib.patches import Rectangle

from geodesic_align.digit_processor import (
    TableView,
    column_z,
    id_lineage,
    route_columns,
    run_digit_align,
)
from geodesic_align.emit_mapping import MappingDecision, recover_mapping
from geodesic_align.example_workflow import (
    _SAMPLE_DIR,
    _apply_text_end,
    load_sample_views,
    render_toml,
)
from geodesic_align.text_processor import (
    GAUSS_SIGMA,
    OVERLAP_TAU,
    cached_text_align,
    named_row_sentence,
    run_text_align,
    spherical_length,
    text_headers,
)


_CHANNEL_COLOR = {
    "digit": "#457b9d",
    "text": "#2a9d8f",
    "formula": "#e76f51",
}
_ROLE_COLOR = {
    "data": "#1d3557",
    "union": "#2a9d8f",
    "regex": "#e9c46a",
    "formula": "#e76f51",
    "derived": "#457b9d",
    "input": "#adb5bd",
}
_FONT_READY = False



def _font() -> None:
    """
    函数名: _font
    作用: 让坐标轴上的中文用微软雅黑
    输入: 无
    输出: 无
    """
    global _FONT_READY
    if _FONT_READY:
        return
    font_file = Path(r"C:\Windows\Fonts\msyh.ttc")
    if font_file.is_file():
        font_manager.fontManager.addfont(str(font_file))
        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.dpi"] = 120
    _FONT_READY = True



def _token_names(engine: object, sentence: str) -> list[str]:
    """
    函数名: _token_names
    作用: 取出与 encode 同一分词顺序的 token 字面，含特殊符号
    输入:
        engine (object): MaskedBert
        sentence (str): 句子
    输出:
        list[str]
    """
    ids = engine.tokenizer(sentence, add_special_tokens=True, truncation=True)["input_ids"]
    return list(engine.tokenizer.convert_ids_to_tokens(ids))



def _token_detail(engine: object, sentence: str, label: str) -> dict[str, object]:
    """
    函数名: _token_detail
    作用: 按列名区间算出每个内容 token 的重叠、高斯权重和隐向量
    输入:
        engine (object): MaskedBert
        sentence (str): 列名与值拼成的句子
        label (str): 列名
    输出:
        dict[str, object]: 列名中心、区间，以及每个 token 的权重和向量
    """
    bundle = engine.encode(sentence)
    offsets = bundle.offsets or engine.content_offsets(sentence)
    names = _token_names(engine, sentence)
    token = f"{label}："
    start = sentence.find(token)
    packed: list[dict[str, object]] = []
    if start < 0:
        return {"center": 0.0, "start": 0, "stop": 0, "tokens": packed, "hidden": bundle.hidden}
    stop = start + len(token)
    center = (float(start) + float(stop)) / 2.0
    label_span = max(float(stop - start), 1.0)
    for tok_idx, a, b in offsets:
        # 重叠比例和高斯权重与 _clouds_for_sheet 使用同一条式子
        overlap = float(min(stop, b) - max(start, a))
        token_span = max(float(b - a), 1.0)
        ratio_token = 0.0 if overlap <= 0.0 else overlap / token_span
        ratio_label = 0.0 if overlap <= 0.0 else overlap / label_span
        kept = overlap > 0.0 and (ratio_token >= OVERLAP_TAU or ratio_label >= OVERLAP_TAU)
        mid = (float(a) + float(b)) / 2.0
        raw_weight = math.exp(-0.5 * ((mid - center) / GAUSS_SIGMA) ** 2)
        weight = raw_weight if kept else 0.0
        piece = names[tok_idx] if tok_idx < len(names) else sentence[a:b]
        packed.append({
            "token": piece,
            "text": sentence[a:b],
            "a": a,
            "b": b,
            "mid": mid,
            "kept": kept,
            "weight": weight,
            "raw_weight": raw_weight,
            "vec": np.asarray(bundle.hidden[tok_idx], dtype=np.float64),
        })
    return {
        "center": center,
        "start": start,
        "stop": stop,
        "tokens": packed,
        "hidden": np.asarray(bundle.hidden, dtype=np.float64),
    }



def _weight_axis(ax, detail: dict[str, object], sentence: str, label: str) -> None:
    """
    函数名: _weight_axis
    作用: 在字符轴上画高斯钟形、列名区间，以及每个 token 的权重
    输入:
        ax: 坐标轴
        detail (dict[str, object]): _token_detail 的结果
        sentence (str): 句子
        label (str): 列名
    输出: 无
    """
    center = float(detail["center"])
    xs = np.linspace(-0.5, len(sentence) - 0.5, 400)
    ys = np.exp(-0.5 * ((xs - center) / GAUSS_SIGMA) ** 2)
    ax.axvspan(float(detail["start"]), float(detail["stop"]), color="#a8dadc", alpha=0.45)
    ax.axvline(center, color="#e76f51", ls="--", lw=0.8)
    ax.plot(xs, ys, color="#1d3557", lw=1.4)
    for item in detail["tokens"]:
        color = "#e76f51" if item["kept"] else "#adb5bd"
        height = float(item["weight"] if item["kept"] else item["raw_weight"])
        width = max(float(item["b"]) - float(item["a"]), 0.4) * 0.7
        ax.bar(float(item["mid"]), height, width=width, color=color, alpha=0.9 if item["kept"] else 0.35)
    ax.set_xticks(np.arange(len(sentence)))
    ax.set_xticklabels(list(sentence), fontsize=8)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("权重")
    ax.set_title(f"{label}    σ = {GAUSS_SIGMA:g}    τ = {OVERLAP_TAU:g}", fontsize=11)



def _memory_table(
    source_key: str,
    headers: list[str],
    records: list[dict[str, str]],
    sheet: str,
) -> TableView:
    """
    函数名: _memory_table
    作用: 工作簿缺失时用字面行做一张内存表
    输入:
        source_key (str): 源键
        headers (list[str]): 表头
        records (list[dict[str, str]]): 每行的列字面
        sheet (str): 工作表名
    输出:
        TableView
    """
    rows = [{name: str(item.get(name, "")) for name in headers} for item in records]
    return TableView(source_key, "excel", list(headers), rows, sheet=sheet)



def zhifa_views() -> tuple[list[TableView], TableView]:
    """
    函数名: zhifa_views
    作用: 样本工作簿不在时，按 toml 的十列做同形状的源表和模板
    输入: 无
    输出:
        tuple[list[TableView], TableView]
    """
    source1 = _memory_table(
        "source1",
        ["ID", "Last name", "First name"],
        [
            {"ID": "10001", "Last name": "张", "First name": "伟"},
            {"ID": "10002", "Last name": "李", "First name": "娜"},
            {"ID": "10003", "Last name": "王", "First name": "强"},
        ],
        "sheet1",
    )
    source2 = _memory_table(
        "source2",
        ["ID", "issues"],
        [
            {"ID": "10001", "issues": "现场巡查 2026/3/1 已归档"},
            {"ID": "10002", "issues": "现场复查 2026/4/2 已归档"},
            {"ID": "10003", "issues": "现场抽查 2026/5/3 已归档"},
        ],
        "sheet2",
    )
    dest = _memory_table(
        "dest",
        [
            "ID#",
            "Last name",
            "First name",
            "name combination",
            "Name",
            "Recent Issue",
            "Report Date",
            "Discipline",
            "Effective_Date",
            "Sign",
        ],
        [
            {
                "ID#": "10001",
                "Last name": "张",
                "First name": "伟",
                "name combination": "='{source1}'!$C$4 & '{source1}'!$B$4",
                "Name": "=C2&B2",
                "Recent Issue": "现场巡查 2026/3/1 已归档",
                "Report Date": "2026-03-01",
            },
            {
                "ID#": "10002",
                "Last name": "李",
                "First name": "娜",
                "name combination": "='{source1}'!$C$4 & '{source1}'!$B$4",
                "Name": "=C2&B2",
                "Recent Issue": "现场复查 2026/4/2 已归档",
                "Report Date": "2026-04-02",
            },
            {
                "ID#": "10003",
                "Last name": "王",
                "First name": "强",
                "name combination": "='{source1}'!$C$4 & '{source1}'!$B$4",
                "Name": "=C2&B2",
                "Recent Issue": "现场抽查 2026/5/3 已归档",
                "Report Date": "2026-05-03",
            },
        ],
        "Input_sheet",
    )
    return [source1, source2], dest



def load_chinese_bert() -> object | None:
    """
    函数名: load_chinese_bert
    作用: 权重就绪时载入 bert-base-chinese；缺失时按文档下载一次
    输入: 无
    输出:
        object | None: MaskedBert 或 None
    """
    try:
        from geodesic_align.mlm_tokens import MODEL_ROOT, ZH_MODEL_ID, load_masked_bert, weights_ready
    except ImportError:
        return None
    if not weights_ready(ZH_MODEL_ID):
        dest = Path(MODEL_ROOT) / ZH_MODEL_ID
        dest.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["hf", "download", "google-bert/bert-base-chinese", "--local-dir", str(dest)],
            check=False,
        )
    if not weights_ready(ZH_MODEL_ID):
        return None
    return load_masked_bert(ZH_MODEL_ID)



def _short(text: str, limit: int = 8) -> str:
    """
    函数名: _short
    作用: 格子字面太长时只留前几个字符，避免色块里的字叠在一起
    输入:
        text (str): 格子字面
        limit (int): 保留的字符数
    输出:
        str
    """
    raw = str(text).replace("\n", " ")
    if len(raw) <= limit:
        return raw
    return raw[: limit - 1] + "…"



def _fig_tables(sources: list[TableView], dest: TableView, title: str):
    """
    函数名: _fig_tables
    作用: 把每张表画成色块，颜色是这一列的通道
    输入:
        sources (list[TableView]): 源表
        dest (TableView): 模板表
        title (str): 图标题
    输出:
        matplotlib.figure.Figure
    """
    _font()
    tables = list(sources) + [dest]
    fig, axes = plt.subplots(1, len(tables), figsize=(4.4 * len(tables), 4.2), squeeze=False)
    for ax, table in zip(axes[0], tables):
        routes = {item.label: item for item in route_columns(table.headers, table.rows)}
        headers = list(table.headers)
        ax.set_xlim(-0.5, max(len(headers), 1) - 0.5)
        ax.set_ylim(-0.6, max(len(table.rows), 1) - 0.4)
        ax.set_xticks(range(len(headers)))
        ax.set_xticklabels(headers, rotation=40, ha="right", fontsize=8)
        y_ticks = [len(table.rows) - idx - 1 for idx in range(len(table.rows))]
        ax.set_yticks(y_ticks)
        ax.set_yticklabels([str(idx) for idx in range(len(table.rows))], fontsize=8)
        ax.set_title(table.sheet or table.source_key, fontsize=11)
        for col, name in enumerate(headers):
            route = routes.get(name)
            color = _CHANNEL_COLOR.get(route.channel if route is not None else "", "#dee2e6")
            for row_idx, row in enumerate(table.rows):
                y_val = len(table.rows) - row_idx - 1
                ax.add_patch(Rectangle((col - 0.46, y_val - 0.38), 0.92, 0.76, facecolor=color, edgecolor="white"))
                ax.text(col, y_val, _short(row.get(name) or ""), ha="center", va="center", fontsize=7, color="white")
    fig.suptitle(title, fontsize=13)
    fig.tight_layout()
    return fig



def _fig_lineage(sources: list[TableView], dest: TableView, lineage: list[list[tuple[str, int]]]):
    """
    函数名: _fig_lineage
    作用: 把每一条行指针画成从源行指向模板行的箭头
    输入:
        sources (list[TableView]): 源表
        dest (TableView): 模板表
        lineage (list): id_lineage 的结果
    输出:
        matplotlib.figure.Figure
    """
    _font()
    left: list[tuple[str, int, str]] = []
    for table in sources:
        for idx, row in enumerate(table.rows):
            tag = ""
            for name in table.headers:
                if "id" in name.lower():
                    tag = str(row.get(name) or "")
                    break
            left.append((table.source_key, idx, tag or str(idx)))
    fig, ax = plt.subplots(figsize=(8, 0.55 * max(len(left), len(dest.rows), 1) + 1.4))
    ax.set_axis_off()
    ax.set_xlim(-0.2, 1.2)
    ax.set_ylim(-1, max(len(left), len(dest.rows)))
    left_y = {key: len(left) - idx - 1 for idx, key in enumerate((item[0], item[1]) for item in left)}
    right_y = {idx: len(dest.rows) - idx - 1 for idx in range(len(dest.rows))}
    for key, idx, tag in left:
        y_val = left_y[(key, idx)]
        ax.scatter([0], [y_val], s=36, color="#1d3557")
        ax.text(-0.03, y_val, f"{key}[{idx}] {tag}", ha="right", va="center", fontsize=9)
    for idx, row in enumerate(dest.rows):
        y_val = right_y[idx]
        tag = ""
        for name in dest.headers:
            if "id" in name.lower():
                tag = str(row.get(name) or "")
                break
        ax.scatter([1], [y_val], s=36, color="#457b9d")
        ax.text(1.03, y_val, f"{dest.sheet}[{idx}] {tag}", ha="left", va="center", fontsize=9)
    for dest_idx, hits in enumerate(lineage):
        for key, src_idx in hits:
            if (key, src_idx) not in left_y or dest_idx not in right_y:
                continue
            ax.annotate(
                "",
                xy=(0.98, right_y[dest_idx]),
                xytext=(0.02, left_y[(key, src_idx)]),
                arrowprops={"arrowstyle": "->", "color": "#1d3557", "lw": 1.4},
            )
    ax.set_title("id_lineage：行指针", fontsize=13)
    fig.tight_layout()
    return fig



def _fig_digit(sources: list[TableView], dest: TableView):
    """
    函数名: _fig_digit
    作用: 把数字通道各列的 z 画在复平面上，日期序列和普通数值分开
    输入:
        sources (list[TableView]): 源表
        dest (TableView): 模板表
    输出:
        matplotlib.figure.Figure
    """
    _font()
    near: list[tuple[float, float, str]] = []
    far: list[tuple[float, float, str]] = []
    for table in list(sources) + [dest]:
        for route in route_columns(table.headers, table.rows):
            if route.channel != "digit" and route.kind not in {"NUMERIC", "DATETIME", "ID_CODE"}:
                continue
            kind = "DATETIME" if route.kind == "DATETIME" else "NUMERIC"
            for value in column_z(table.rows, route.label, kind):
                if value.imag < 0.0 and value.real == 0.0:
                    continue
                bucket = far if abs(value.real) >= 10000.0 else near
                bucket.append((value.real, value.imag, f"{table.sheet}.{route.label}"))
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4))
    for ax, group, title in (
        (axes[0], near, "普通数值"),
        (axes[1], far, "日期序列"),
    ):
        if not group:
            ax.set_axis_off()
            ax.set_title(title + "：这一步没有点")
            continue
        for real, imag, name in group:
            color = "#e76f51" if imag != 0.0 else "#1d3557"
            ax.scatter([real], [imag], s=60, color=color, zorder=3)
            ax.annotate(name, (real, imag), textcoords="offset points", xytext=(6, 6), fontsize=8)
        reals = [item[0] for item in group]
        imags = [item[1] for item in group]
        span_x = max(reals) - min(reals)
        span_y = max(imags) - min(imags)
        pad_x = span_x * 0.45 if span_x > 0.0 else 0.5
        pad_y = span_y * 0.55 if span_y > 0.0 else 0.35
        ax.set_xlim(min(reals) - pad_x, max(reals) + pad_x)
        ax.set_ylim(min(imags) - pad_y, max(imags) + pad_y)
        ax.axhline(0.0, color="0.85", lw=0.8, zorder=0)
        ax.axvline(0.0, color="0.85", lw=0.8, zorder=0)
        ax.set_xlabel("实部")
        ax.set_ylabel("虚部")
        ax.set_title(title, fontsize=11)
    fig.suptitle("run_digit_align 之前，各格已经编成 z = x + yi", fontsize=13)
    fig.tight_layout()
    return fig



def _fig_links(decisions: list[MappingDecision], dest: TableView, title: str):
    """
    函数名: _fig_links
    作用: 把当前决策画成从源列指向模板列的箭头
    输入:
        decisions (list[MappingDecision]): 目前已有的映射
        dest (TableView): 模板表
        title (str): 图标题
    输出:
        matplotlib.figure.Figure
    """
    _font()
    left_names: list[str] = []
    edges: list[tuple[str, str, str]] = []
    for item in decisions:
        if not item.source or not item.field:
            continue
        name = f"{item.source}.{item.field}"
        if name not in left_names:
            left_names.append(name)
        edges.append((name, item.input_label, item.cell_role or item.klass or "input"))
    right_names = list(dest.headers)
    fig, ax = plt.subplots(figsize=(10, 0.46 * max(len(right_names), len(left_names), 1) + 1.5))
    ax.set_axis_off()
    ax.set_xlim(-0.15, 1.15)
    ax.set_ylim(-1, max(len(right_names), len(left_names), 1))
    left_y = {name: len(left_names) - idx - 1 for idx, name in enumerate(left_names)}
    right_y = {name: len(right_names) - idx - 1 for idx, name in enumerate(right_names)}
    for name, y_val in left_y.items():
        ax.scatter([0], [y_val], s=36, color="#1d3557")
        ax.text(-0.03, y_val, name, ha="right", va="center", fontsize=9)
    for name, y_val in right_y.items():
        ax.scatter([1], [y_val], s=36, color="#457b9d")
        ax.text(1.03, y_val, name, ha="left", va="center", fontsize=9)
    seen: set[str] = set()
    for src_name, dst_name, role in edges:
        color = _ROLE_COLOR.get(role, "#6c757d")
        ax.annotate(
            "",
            xy=(0.98, right_y[dst_name]),
            xytext=(0.02, left_y[src_name]),
            arrowprops={"arrowstyle": "->", "color": color, "lw": 1.6},
        )
        if role not in seen:
            seen.add(role)
            ax.plot([], [], color=color, lw=2, label=role)
    if seen:
        ax.legend(loc="lower center", ncol=max(len(seen), 1), fontsize=8, frameon=False, bbox_to_anchor=(0.5, -0.06))
    ax.set_title(title, fontsize=13)
    fig.tight_layout()
    return fig



def _first_sentence(sources: list[TableView]) -> tuple[str, list[str]]:
    """
    函数名: _first_sentence
    作用: 取第一句非空的列名句子，以及这句所用的文本列
    输入:
        sources (list[TableView]): 源表
    输出:
        tuple[str, list[str]]: 句子和列名
    """
    for table in sources:
        names = text_headers(table.headers, table.rows)
        for row in table.rows:
            sentence = named_row_sentence(names, row)
            if sentence:
                return sentence, names
    return "", []



def _fig_bert(engine: object, sentence: str):
    """
    函数名: _fig_bert
    作用: 画出这一句的最后一层隐状态和 token 余弦
    输入:
        engine (object): MaskedBert
        sentence (str): 列名句子
    输出:
        matplotlib.figure.Figure
    """
    if engine is None or not sentence:
        _font()
        fig, ax = plt.subplots(figsize=(8, 2))
        ax.set_axis_off()
        ax.set_title("没有中文 BERT 权重，或没有文本列")
        return fig
    _font()
    bundle = engine.encode(sentence)
    hidden = np.asarray(bundle.hidden, dtype=np.float64)
    labels = _token_names(engine, sentence)
    if len(labels) != hidden.shape[0]:
        labels = [str(idx) for idx in range(hidden.shape[0])]
    norms = np.linalg.norm(hidden, axis=1, keepdims=True)
    units = hidden / np.maximum(norms, 1e-12)
    cosine = units @ units.T
    limit = float(np.quantile(np.abs(hidden), 0.98))
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.4), gridspec_kw={"width_ratios": [2.4, 1]})
    image = axes[0].imshow(hidden, aspect="auto", cmap="coolwarm", vmin=-limit, vmax=limit, interpolation="nearest")
    axes[0].set_yticks(np.arange(len(labels)))
    axes[0].set_yticklabels(labels, fontsize=8)
    axes[0].set_xlabel("隐层的 768 维")
    axes[0].set_title(sentence, fontsize=10)
    fig.colorbar(image, ax=axes[0], fraction=0.02, pad=0.02)
    heat = axes[1].imshow(cosine, vmin=-1, vmax=1, cmap="coolwarm", interpolation="nearest")
    axes[1].set_xticks(np.arange(len(labels)))
    axes[1].set_yticks(np.arange(len(labels)))
    axes[1].set_xticklabels(labels, rotation=90, fontsize=7)
    axes[1].set_yticklabels(labels, fontsize=7)
    axes[1].set_title("token 余弦")
    fig.colorbar(heat, ax=axes[1], fraction=0.046, pad=0.04)
    fig.suptitle("encode：BERT 最后一层", fontsize=13)
    fig.tight_layout()
    return fig



def _fig_gaussian(engine: object, sentence: str, names: list[str]):
    """
    函数名: _fig_gaussian
    作用: 画出这句里前两个列名的高斯权重
    输入:
        engine (object): MaskedBert
        sentence (str): 列名句子
        names (list[str]): 文本列名
    输出:
        matplotlib.figure.Figure
    """
    if engine is None or not sentence or not names:
        _font()
        fig, ax = plt.subplots(figsize=(8, 2))
        ax.set_axis_off()
        ax.set_title("没有向量可做高斯平滑")
        return fig
    _font()
    picked = names[:2]
    fig, axes = plt.subplots(len(picked), 1, figsize=(13, 3.1 * len(picked)), squeeze=False)
    for ax, label in zip(axes[0], picked):
        _weight_axis(ax, _token_detail(engine, sentence, label), sentence, label)
    fig.suptitle("高斯平滑：橙色柱进入平均，虚线是列名中心", fontsize=13)
    fig.tight_layout()
    return fig



def _fig_clouds(src_clouds: list, dst_clouds: list, ends: list):
    """
    函数名: _fig_clouds
    作用: 画出 run_text_align 得到的大圆距离和切空间能量
    输入:
        src_clouds (list): 源列云
        dst_clouds (list): 模板列云
        ends (list): GeodesicEnd
    输出:
        matplotlib.figure.Figure
    """
    _font()
    left = [cloud for cloud in src_clouds if cloud.mu is not None]
    right = [cloud for cloud in dst_clouds if cloud.mu is not None]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2), gridspec_kw={"width_ratios": [1.3, 1]})
    if not left or not right:
        axes[0].set_axis_off()
        axes[0].set_title("没有列云")
    else:
        matrix = np.zeros((len(left), len(right)), dtype=np.float64)
        for i, src in enumerate(left):
            for j, dst in enumerate(right):
                matrix[i, j] = spherical_length(src.mu, dst.mu)
        image = axes[0].imshow(matrix, cmap="YlOrRd", interpolation="nearest")
        axes[0].set_xticks(np.arange(len(right)))
        axes[0].set_yticks(np.arange(len(left)))
        axes[0].set_xticklabels([cloud.label for cloud in right], rotation=40, ha="right", fontsize=8)
        axes[0].set_yticklabels([cloud.label for cloud in left], fontsize=8)
        peak = float(np.max(matrix)) if matrix.size else 1.0
        for i in range(matrix.shape[0]):
            for j in range(matrix.shape[1]):
                ink = "white" if matrix[i, j] >= peak * 0.72 else "#1d3557"
                axes[0].text(j, i, f"{matrix[i, j]:.2f}", ha="center", va="center", fontsize=7, color=ink)
        axes[0].set_title("列云之间的大圆距离", fontsize=11)
        fig.colorbar(image, ax=axes[0], fraction=0.046, pad=0.04)
    labels = [item.input_label for item in ends]
    xpos = np.arange(len(labels))
    axes[1].bar(xpos, [item.E_in for item in ends], color="#457b9d", label="E_in")
    axes[1].bar(xpos, [item.E_out for item in ends], bottom=[item.E_in for item in ends], color="#e76f51", label="E_out")
    axes[1].set_xticks(xpos)
    axes[1].set_xticklabels(labels, rotation=40, ha="right", fontsize=8)
    axes[1].set_ylabel("能量")
    axes[1].legend(fontsize=8)
    axes[1].set_title("run_text_align 的能量", fontsize=11)
    fig.suptitle("run_text_align", fontsize=13)
    fig.tight_layout()
    return fig



class WorkflowPlayer:
    """一次 example_workflow，按按钮往前走。"""

    def __init__(self) -> None:
        """
        函数名: WorkflowPlayer.__init__
        作用: 记下还没开始，以及这一趟要调用的函数顺序
        输入: 无
        输出: 无
        """
        self.index = -1
        self.sources: list[TableView] = []
        self.dest: TableView | None = None
        self.source_path = _SAMPLE_DIR / "执法堂业绩.xlsx"
        self.dest_path = _SAMPLE_DIR / "sample_template.xlsx"
        self.used_memory = False
        self.lineage: list = []
        self.decisions: list[MappingDecision] = []
        self.engine: object | None = None
        self.sentence = ""
        self.sentence_names: list[str] = []
        self.ends: list = []
        self.steps = [
            self._load,
            self._lineage,
            self._digit,
            self._recover,
            self._bert,
            self._gaussian,
            self._text,
            self._apply,
            self._render,
        ]


    @property
    def finished(self) -> bool:
        """
        函数名: WorkflowPlayer.finished
        作用: 最后一步是否已经跑过
        输入: 无
        输出:
            bool
        """
        return self.index >= len(self.steps) - 1


    def advance(self):
        """
        函数名: WorkflowPlayer.advance
        作用: 调用顺序里的下一个函数，返回标题和这一步的图
        输入: 无
        输出:
            tuple[str, matplotlib.figure.Figure] | None: 走完则为空
        """
        nxt = self.index + 1
        if nxt >= len(self.steps):
            return None
        title, fig = self.steps[nxt]()
        self.index = nxt
        return f"{nxt + 1}/{len(self.steps)}  {title}", fig


    def _load(self):
        """
        函数名: WorkflowPlayer._load
        作用: 调用 load_sample_views；工作簿不在时用同形状的内存表
        输入: 无
        输出:
            tuple[str, matplotlib.figure.Figure]
        """
        try:
            self.source_path, self.dest_path, self.sources, self.dest = load_sample_views()
            self.used_memory = False
            title = "load_sample_views"
        except FileNotFoundError:
            self.sources, self.dest = zhifa_views()
            self.used_memory = True
            title = "load_sample_views：工作簿不在，用了同形状的内存表"
        assert self.dest is not None
        return title, _fig_tables(self.sources, self.dest, title)


    def _lineage(self):
        """
        函数名: WorkflowPlayer._lineage
        作用: 调用 id_lineage 并画出指针
        输入: 无
        输出:
            tuple[str, matplotlib.figure.Figure]
        """
        assert self.dest is not None
        self.lineage = id_lineage(self.dest, self.sources)
        return "id_lineage", _fig_lineage(self.sources, self.dest, self.lineage)


    def _digit(self):
        """
        函数名: WorkflowPlayer._digit
        作用: 调用 run_digit_align，图上是这一步所用的 z
        输入: 无
        输出:
            tuple[str, matplotlib.figure.Figure]
        """
        assert self.dest is not None
        run_digit_align(self.sources, self.dest)
        return "run_digit_align", _fig_digit(self.sources, self.dest)


    def _recover(self):
        """
        函数名: WorkflowPlayer._recover
        作用: 调用 recover_mapping，此时还没有测地线
        输入: 无
        输出:
            tuple[str, matplotlib.figure.Figure]
        """
        assert self.dest is not None
        self.decisions = recover_mapping(self.sources, self.dest)
        return "recover_mapping", _fig_links(self.decisions, self.dest, "recover_mapping：还没有测地线")


    def _bert(self):
        """
        函数名: WorkflowPlayer._bert
        作用: 载入中文 BERT，对工作流即将编码的第一句做前向
        输入: 无
        输出:
            tuple[str, matplotlib.figure.Figure]
        """
        self.sentence, self.sentence_names = _first_sentence(self.sources)
        self.engine = load_chinese_bert()
        return "encode", _fig_bert(self.engine, self.sentence)


    def _gaussian(self):
        """
        函数名: WorkflowPlayer._gaussian
        作用: 对刚才那一句做列名高斯平滑
        输入: 无
        输出:
            tuple[str, matplotlib.figure.Figure]
        """
        return "gaussian", _fig_gaussian(self.engine, self.sentence, self.sentence_names)


    def _text(self):
        """
        函数名: WorkflowPlayer._text
        作用: 调用 run_text_align，并用它留下的列云作图
        输入: 无
        输出:
            tuple[str, matplotlib.figure.Figure]
        """
        assert self.dest is not None
        tuples = [(table.sheet, table.headers, table.rows) for table in self.sources]
        self.ends = run_text_align(tuples, self.dest.sheet, self.dest.headers, self.dest.rows)
        cached = cached_text_align(tuple(table.sheet for table in self.sources), self.dest.sheet)
        if cached is None:
            return "run_text_align", _fig_clouds([], [], self.ends)
        src_clouds, dst_clouds, ends = cached
        self.ends = list(ends)
        return "run_text_align", _fig_clouds(src_clouds, dst_clouds, self.ends)


    def _apply(self):
        """
        函数名: WorkflowPlayer._apply
        作用: 只对仍是手工输入的列调用 _apply_text_end
        输入: 无
        输出:
            tuple[str, matplotlib.figure.Figure]
        """
        assert self.dest is not None
        by_label = {item.input_label: item for item in self.decisions}
        for end in self.ends:
            current = by_label.get(str(getattr(end, "input_label", "")))
            if current is None or current.cell_role != "input":
                continue
            _apply_text_end(self.dest, self.sources, self.lineage, current, end)
        return "_apply_text_end", _fig_links(self.decisions, self.dest, "_apply_text_end")


    def _render(self):
        """
        函数名: WorkflowPlayer._render
        作用: 调用 render_toml，图上仍是定下来的箭头
        输入: 无
        输出:
            tuple[str, matplotlib.figure.Figure]
        """
        assert self.dest is not None
        title = "render_toml"
        try:
            render_toml(self.source_path, self.dest_path, self.sources, self.dest, self.decisions)
        except FileNotFoundError:
            title = "render_toml：工作簿不在，文本没写成"
        return title, _fig_links(self.decisions, self.dest, title)
