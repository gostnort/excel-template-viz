"""GOP 引擎：底流形、纤维实例化、截面相干。不读表、不指定文件。"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from fisher_groupoid.meaning import (
    VectorLabelOperator,
    coordinate_keys,
    cosine_similarity,
    embed_label,
    ensure_labels_resolved,
    gauge_transport_matrix,
    homomorphism_distance,
    meaning_of_label,
    operator_matrix,
)


HOLONOMY_GATE = 1e-4


@dataclass(frozen=True)
class BaseLabel:
    """底流形上的一个 Label；sources 只是调用方标记来源，引擎不当坐标。"""

    name: str
    sources: tuple[str, ...] = ()



@dataclass(frozen=True)
class ObjectRecord:
    """一个对象在部分 Label 上的取值；缺的键表示截面未覆盖该底点。"""

    object_id: str
    values: dict[str, str]



@dataclass(frozen=True)
class FiberSeries:
    """一条纤维上的稀疏取值。位置键不必连续，缺的位置不是该纤维上的点。"""

    label: str
    source: str
    at: dict[int, str]




@dataclass(frozen=True)
class ChartAtlas:
    """输入侧一张源图：独立底流形与按 ID 索引的局域截面。"""

    name: str
    labels: tuple[BaseLabel, ...]
    records: tuple[ObjectRecord, ...]



@dataclass(frozen=True)
class FieldAnchor:
    """输出卡片内一个 Label 相对原点的锚点；纤维在 Label 旁。"""

    label: str
    delta_row: int
    delta_col: int
    fiber_delta_row: int
    fiber_delta_col: int



@dataclass(frozen=True)
class OutputGroup:
    """输出群：一个对象 D_block，G 由步长生成。"""

    origin_row: int
    origin_col: int
    stride: tuple[int, int]
    right_stride: tuple[int, int] | None
    anchors: tuple[FieldAnchor, ...]


def _sphere_parallel_transport(
    start: np.ndarray,
    end: np.ndarray,
    tangent: np.ndarray,
) -> np.ndarray:
    """
    函数名: _sphere_parallel_transport
    作用: 单位球上沿测地线把切向量从 start 平移到 end
    输入:
        start (np.ndarray): 单位点
        end (np.ndarray): 单位点
        tangent (np.ndarray): start 处切向量
    输出:
        np.ndarray: end 处切向量
    """
    carried = tangent - start * float(np.dot(tangent, start))
    cosine = float(np.clip(np.dot(start, end), -1.0, 1.0))
    sine = math.sqrt(max(0.0, 1.0 - cosine * cosine))
    if sine < 1e-12:
        return carried - end * float(np.dot(carried, end))
    # 在 span{start, end} 内旋转，正交补不动
    axis = (end - cosine * start) / sine
    along = float(np.dot(carried, axis))
    perp = carried - along * axis
    rotated = along * (-sine * start + cosine * axis) + perp
    return rotated - end * float(np.dot(rotated, end))


def section_holonomy(orbits: list[dict]) -> dict:
    """
    函数名: section_holonomy
    作用: 把实例化环连成闭多边形，在意义球上做规范平移
    输入:
        orbits (list[dict]): 截面上的实例化环
    输出:
        dict: 相干残差；不判断字面对错
    """
    path = [item["orbit"] for item in orbits]
    ground = [item["orbit"] for item in orbits if item.get("ground")]
    units: list[np.ndarray] = []
    for item in orbits:
        if item.get("ground"):
            continue
        vec = np.array(item["state"], dtype=np.float64)
        norm = float(np.linalg.norm(vec))
        if norm < 1e-12:
            ground.append(item["orbit"])
            continue
        units.append(vec / norm)
    if len(units) < 2:
        return {
            "connection": "levi_civita_sphere",
            "path": path,
            "ground_orbits": ground,
            "defined": False,
            "reason": "非原点轨道不足，无法围成球面多边形",
        }
    loop = units + [units[0]]
    tangent = loop[1] - loop[0]
    tangent = tangent - loop[0] * float(np.dot(tangent, loop[0]))
    tnorm = float(np.linalg.norm(tangent))
    if tnorm < 1e-12:
        return {
            "connection": "levi_civita_sphere",
            "path": path,
            "ground_orbits": ground,
            "defined": True,
            "residue_norm": 0.0,
            "closed": True,
            "note": "截面上非原点状态指向同一方向",
        }
    tangent = tangent / tnorm
    carried = tangent.copy()
    for idx in range(len(loop) - 1):
        carried = _sphere_parallel_transport(loop[idx], loop[idx + 1], carried)
    residue = carried - tangent
    return {
        "connection": "levi_civita_sphere",
        "path": path,
        "ground_orbits": ground,
        "defined": True,
        "initial_tangent": [float(x) for x in tangent],
        "transported_tangent": [float(x) for x in carried],
        "residue_norm": float(np.linalg.norm(residue)),
        "cosine": float(np.clip(np.dot(carried, tangent), -1.0, 1.0)),
        "closed": float(np.linalg.norm(residue)) < 1e-6,
    }


def holonomy_passes(holonomy: dict, threshold: float = HOLONOMY_GATE) -> bool:
    """
    函数名: holonomy_passes
    作用: 相干残差门禁：闭合或 residue_norm 低于阈值
    输入:
        holonomy (dict): section_holonomy 结果
        threshold (float): 残差上限
    输出:
        bool
    """
    if not holonomy.get("defined"):
        return False
    if holonomy.get("closed"):
        return True
    return float(holonomy.get("residue_norm") or 1.0) < float(threshold)


def key_digest(object_id: str) -> str:
    """
    函数名: key_digest
    作用: 对象键的 sha256 前 16 位十六进制
    输入:
        object_id (str)
    输出:
        str
    """
    return hashlib.sha256(str(object_id).encode("utf-8")).hexdigest()[:16]


def slot_from_key(object_id: str, roster: Sequence[str], n_right: int = 1) -> tuple[int, int]:
    """
    函数名: slot_from_key
    作用: 用对象键在已排序名册中的秩绑定 (k, m)，与读表顺序无关
    输入:
        object_id (str)
        roster (Sequence[str]): 允许推前的对象键全集
        n_right (int): 向右卡片份数
    输出:
        tuple[int, int]
    """
    ranked = sorted({str(item) for item in roster})
    if object_id not in ranked:
        raise KeyError(object_id)
    idx = ranked.index(str(object_id))
    copies = int(n_right) if int(n_right) > 1 else 1
    if copies <= 1:
        return idx, 0
    return idx // copies, idx % copies


def infer_object_key(labels: Sequence[str]) -> str:
    """
    函数名: infer_object_key
    作用: 对象键取声明顺序中的第一个 Label，对所有表同一规则
    输入:
        labels (Sequence[str])
    输出:
        str
    """
    names = [str(item) for item in labels if str(item).strip()]
    if not names:
        raise ValueError("没有 Label 可推断对象键")
    return names[0]


def _phi_pair_cost(source: str, dest: str) -> float:
    """
    函数名: _phi_pair_cost
    作用: 一对 Label 的余弦偏离加 L 同态距离
    输入:
        source (str)
        dest (str)
    输出:
        float
    """
    cosine = cosine_similarity(embed_label(source), embed_label(dest))
    homo = homomorphism_distance(operator_matrix(source), operator_matrix(dest))
    return (1.0 - cosine) + homo


def _phi_residue(
    phi: dict[str, str],
    sample_sections: Sequence[dict[str, str]],
) -> float:
    """
    函数名: _phi_residue
    作用: 给定 φ 时样本截面经 T 平移后的残差和
    输入:
        phi (dict[str, str])
        sample_sections (Sequence[dict[str, str]])
    输出:
        float
    """
    total = 0.0
    for sigma in sample_sections:
        orbits: list[dict] = []
        for src, dst in phi.items():
            if src not in sigma:
                continue
            inst = VectorLabelOperator(src).instantiate(sigma[src])
            transported = gauge_transport_matrix(operator_matrix(src), operator_matrix(dst)) @ np.array(
                inst["state"],
                dtype=np.float64,
            )
            orbits.append(
                {
                    "orbit": f"{inst['literal']} of {dst}" if not inst["ground"] else f"NULL of {dst}",
                    "state": transported,
                    "ground": inst["ground"],
                }
            )
        holonomy = section_holonomy(orbits)
        if not holonomy.get("defined"):
            total += 1.0
            continue
        total += float(holonomy.get("residue_norm") or 0.0)
    return total


def infer_morphism_phi(
    source_labels: Sequence[str],
    target_labels: Sequence[str],
    sample_sections: Sequence[dict[str, str]] | None = None,
) -> dict[str, str]:
    """
    函数名: infer_morphism_phi
    作用: 只保留双向最近的 Label 箭头；输出底点不在输入群胚内则不映射，不补列
    输入:
        source_labels (Sequence[str])
        target_labels (Sequence[str])
        sample_sections (Sequence[dict[str, str]] | None): 保留参数，不用于把缺列填满
    输出:
        dict[str, str]: 源 Label -> 输出 Label，允许两边都有未覆盖点
    """
    _ = sample_sections
    sources = [str(item) for item in source_labels if str(item).strip()]
    targets = [str(item) for item in target_labels if str(item).strip()]
    if not sources or not targets:
        return {}
    phi: dict[str, str] = {}
    taken: set[str] = set()
    for src in sources:
        best_dst = None
        best_c = float("inf")
        second_c = float("inf")
        for dst in targets:
            cost = _phi_pair_cost(src, dst)
            if cost < best_c:
                second_c = best_c
                best_c = cost
                best_dst = dst
            elif cost < second_c:
                second_c = cost
        if best_dst is None:
            continue
        if best_c >= 1.0:
            continue
        if math.isfinite(second_c) and second_c <= best_c:
            continue
        back_src = None
        back_c = float("inf")
        back_second = float("inf")
        for other in sources:
            cost = _phi_pair_cost(other, best_dst)
            if cost < back_c:
                back_second = back_c
                back_c = cost
                back_src = other
            elif cost < back_second:
                back_second = cost
        if back_src != src or best_dst in taken:
            continue
        if back_c >= 1.0:
            continue
        if math.isfinite(back_second) and back_second <= back_c:
            continue
        phi[src] = best_dst
        taken.add(best_dst)
    return phi


def records_from_fibers(
    fibers: Sequence[FiberSeries],
    object_key: str,
) -> tuple[list[BaseLabel], list[ObjectRecord]]:
    """
    函数名: records_from_fibers
    作用: 把稀疏纤维按共享位置对齐；空列/隔行只表现为缺位置，不要求矩形表头
    输入:
        fibers (Sequence[FiberSeries]): 每条纤维自己的位置→字面
        object_key (str): 哪个 Label 的字面当对象名
    输出:
        tuple[list[BaseLabel], list[ObjectRecord]]
    """
    merged: dict[str, dict[int, str]] = {}
    sources: dict[str, list[str]] = {}
    order: list[str] = []
    for fiber in fibers:
        if fiber.label not in merged:
            merged[fiber.label] = dict(fiber.at)
            sources[fiber.label] = [fiber.source]
            order.append(fiber.label)
            continue
        merged[fiber.label].update(fiber.at)
        if fiber.source not in sources[fiber.label]:
            sources[fiber.label].append(fiber.source)
    if object_key not in merged:
        raise ValueError(f"纤维里没有 object_key {object_key!r}")
    labels = [BaseLabel(name, tuple(sources[name])) for name in order]
    records: list[ObjectRecord] = []
    seen_ids: set[str] = set()
    key_slots = merged[object_key]
    for pos in sorted(key_slots):
        object_id = key_slots[pos]
        if not object_id or object_id in seen_ids:
            continue
        seen_ids.add(object_id)
        values: dict[str, str] = {}
        for name in order:
            slots = merged[name]
            if pos in slots:
                values[name] = slots[pos]
        records.append(ObjectRecord(object_id=object_id, values=values))
    return labels, records


def glue_records(
    groups: Sequence[tuple[Sequence[BaseLabel], Sequence[ObjectRecord]]],
) -> tuple[list[BaseLabel], list[ObjectRecord]]:
    """
    函数名: glue_records
    作用: 多张图按对象名粘合；某图没有该对象则那些 Label 缺席
    输入:
        groups (Sequence[tuple[Sequence[BaseLabel], Sequence[ObjectRecord]]])
    输出:
        tuple[list[BaseLabel], list[ObjectRecord]]
    """
    base: list[BaseLabel] = []
    seen: dict[str, int] = {}
    for labels, _records in groups:
        for item in labels:
            if item.name in seen:
                idx = seen[item.name]
                old = base[idx]
                extra = tuple(src for src in item.sources if src not in old.sources)
                if extra:
                    base[idx] = BaseLabel(old.name, old.sources + extra)
                continue
            seen[item.name] = len(base)
            base.append(item)
    order: list[str] = []
    known: set[str] = set()
    indexes: list[dict[str, ObjectRecord]] = []
    for _labels, recs in groups:
        index = {rec.object_id: rec for rec in recs}
        indexes.append(index)
        for rec in recs:
            if rec.object_id not in known:
                known.add(rec.object_id)
                order.append(rec.object_id)
    records: list[ObjectRecord] = []
    for object_id in order:
        values: dict[str, str] = {}
        for index in indexes:
            rec = index.get(object_id)
            if rec is None:
                continue
            for key, text in rec.values.items():
                if key not in values:
                    values[key] = text
        records.append(ObjectRecord(object_id=object_id, values=values))
    return base, records


def chart_index(atlas: ChartAtlas) -> dict[str, ObjectRecord]:
    """
    函数名: chart_index
    作用: 一张源图上 ID -> 局域截面
    输入:
        atlas (ChartAtlas)
    输出:
        dict[str, ObjectRecord]
    """
    return {record.object_id: record for record in atlas.records}


def morphism_on_id(source: ChartAtlas, target: ChartAtlas, object_id: str) -> int:
    """
    函数名: morphism_on_id
    作用: 转移态射 g_source->target 在该 ID 处取值；缺一侧则为 0
    输入:
        source (ChartAtlas)
        target (ChartAtlas)
        object_id (str)
    输出:
        int: 1 或 0
    """
    if object_id in chart_index(source) and object_id in chart_index(target):
        return 1
    return 0



def excel_coord(row: int, col: int) -> str:
    """
    函数名: excel_coord
    作用: 1-based 行列换成 A1
    输入:
        row (int)
        col (int)
    输出:
        str
    """
    n = int(col)
    if n < 1 or int(row) < 1:
        raise ValueError((row, col))
    chars: list[str] = []
    while n:
        n, rem = divmod(n - 1, 26)
        chars.append(chr(65 + rem))
    return "".join(reversed(chars)) + str(int(row))



def period_of_row(names: Sequence[str]) -> int:
    """
    函数名: period_of_row
    作用: 第一行 Label 的最小重复周期；无法整块重复则整行一张卡片
    输入:
        names (Sequence[str]): 从左到右的 Label 名
    输出:
        int: 一块卡片占用的 Label 个数
    """
    items = [str(name) for name in names]
    n = len(items)
    if n == 0:
        return 0
    if len(set(items)) == n:
        return n
    for p in range(1, n):
        if n % p != 0:
            continue
        block = items[:p]
        if len(set(block)) != p:
            continue
        if items == block * (n // p):
            return p
    return n



def output_group_from_header(
    label_row: int,
    columns: Sequence[tuple[int, str]],
    *,
    fiber_down: int = 1,
) -> OutputGroup:
    """
    函数名: output_group_from_header
    作用: 由第一行 Label 列构造 D_block 与 G 的生成元
    输入:
        label_row (int): Label 所在行（1-based）
        columns (Sequence[tuple[int, str]]): (列号, Label 名) 从左到右
        fiber_down (int): 填写相对 Label 的行偏移
    输出:
        OutputGroup
    """
    cols = [(int(col), str(name)) for col, name in columns if str(name).strip()]
    if not cols:
        raise ValueError("输出第一行没有 Label")
    names = [name for _col, name in cols]
    period = period_of_row(names)
    origin_col = cols[0][0]
    anchors: list[FieldAnchor] = []
    for idx in range(period):
        col, name = cols[idx]
        anchors.append(
            FieldAnchor(
                label=name,
                delta_row=0,
                delta_col=col - origin_col,
                fiber_delta_row=int(fiber_down),
                fiber_delta_col=0,
            )
        )
    right: tuple[int, int] | None = None
    if len(cols) > period:
        right = (0, cols[period][0] - origin_col)
    return OutputGroup(
        origin_row=int(label_row),
        origin_col=origin_col,
        stride=(int(fiber_down), 0),
        right_stride=right,
        anchors=tuple(anchors),
    )


def slot_cell(group: OutputGroup, anchor: FieldAnchor, k: int, m: int, *, fiber: bool) -> tuple[int, int]:
    """
    函数名: slot_cell
    作用: 群元素 (k, m) 处 Label 或纤维的绝对格点
    输入:
        group (OutputGroup)
        anchor (FieldAnchor)
        k (int): 向下槽
        m (int): 向右卡片份
        fiber (bool): True 为填写格，False 为 Label 格
    输出:
        tuple[int, int]: (row, col)
    """
    extra_r = 0
    extra_c = 0
    if group.right_stride is not None:
        extra_r = m * group.right_stride[0]
        extra_c = m * group.right_stride[1]
    if fiber:
        row = group.origin_row + anchor.fiber_delta_row + k * group.stride[0] + extra_r
        col = group.origin_col + anchor.fiber_delta_col + anchor.delta_col + k * group.stride[1] + extra_c
        return row, col
    row = group.origin_row + anchor.delta_row + extra_r
    col = group.origin_col + anchor.delta_col + extra_c
    return row, col



class GeodesicEngine:
    """测地线引擎：先钉 B，再对每个对象拉截面。"""

    def __init__(self) -> None:
        """
        函数名: GeodesicEngine.__init__
        作用: 按 Label 缓存算子 L
        输入: 无
        输出: 无
        """
        self._operators: dict[str, VectorLabelOperator] = {}


    def operator(self, label: str) -> VectorLabelOperator:
        """
        函数名: GeodesicEngine.operator
        作用: 每个 Label 只构造一次 L
        输入:
            label (str)
        输出:
            VectorLabelOperator
        """
        found = self._operators.get(label)
        if found is None:
            found = VectorLabelOperator(label)
            self._operators[label] = found
        return found


    def base_manifold(self, labels: Sequence[BaseLabel]) -> list[dict]:
        """
        函数名: GeodesicEngine.base_manifold
        作用: 填数之前固定底流形 B
        输入:
            labels (Sequence[BaseLabel]): 有序 Label
        输出:
            list[dict]
        """
        order: list[dict] = []
        seen: set[str] = set()
        for item in labels:
            name = item.name
            if name in seen:
                continue
            seen.add(name)
            op = self.operator(name)
            order.append(
                {
                    "label": name,
                    "fiber": f"F_{name}",
                    "sources": list(item.sources),
                    "L": [[float(x) for x in row] for row in op.L_matrix],
                    "meaning": meaning_of_label(name).as_dict(),
                }
            )
        return order


    def make_section(self, record: ObjectRecord, base: list[dict]) -> dict:
        """
        函数名: GeodesicEngine.make_section
        作用: values 里有的 Label 实例化；没有的是截面缺口，不是字面错误
        输入:
            record (ObjectRecord)
            base (list[dict]): 已钉死的 B
        输出:
            dict
        """
        orbits: list[dict] = []
        missing: list[str] = []
        for point in base:
            label = str(point["label"])
            if label not in record.values:
                missing.append(label)
                continue
            orbits.append(self.operator(label).instantiate(record.values[label]))
        defined = len(missing) == 0
        if defined:
            holonomy = section_holonomy(orbits)
        else:
            holonomy = {
                "defined": False,
                "reason": "截面未覆盖全部底流形，不能做环路平移",
                "missing_labels": missing,
            }
        return {
            "object_id": record.object_id,
            "map": "sigma: B -> E",
            "defined_on_base": defined,
            "missing_labels": missing,
            "instantiated_orbits": orbits,
            "holonomy": holonomy,
        }


    def report(
        self,
        labels: Sequence[BaseLabel],
        records: Sequence[ObjectRecord],
    ) -> dict:
        """
        函数名: GeodesicEngine.report
        作用: 先固定 B，再对每个对象拉截面并算相干
        输入:
            labels (Sequence[BaseLabel])
            records (Sequence[ObjectRecord])
        输出:
            dict: 纤维丛报告，不含采集路径
        """
        base = self.base_manifold(labels)
        return {
            "geometry": "fiber_bundle",
            "typical_fiber": coordinate_keys(),
            "base_manifold": {"B": base},
            "sections": [self.make_section(record, base) for record in records],
        }


    def input_groupoid(self, atlases: Sequence[ChartAtlas]) -> dict:
        """
        函数名: GeodesicEngine.input_groupoid
        作用: 构建输入侧群胚 U_in：各源图独立，ID 为转移，复合得到 σ_in
        输入:
            atlases (Sequence[ChartAtlas]): 有序源图（不含输出 template）
        输出:
            dict: 局域毯 + 对象截面 σ_in；pushforward_ready 表示可进后续 g_in→template
        """
        pending: list[str] = []
        for atlas in atlases:
            pending.extend(item.name for item in atlas.labels)
        ensure_labels_resolved(pending)
        chart_reports: list[dict] = []
        for atlas in atlases:
            base = self.base_manifold(atlas.labels)
            local_sections: list[dict] = []
            for record in atlas.records:
                section = self.make_section(record, base)
                holonomy = section["holonomy"]
                local_sections.append(
                    {
                        "object_id": record.object_id,
                        "sigma_local": dict(record.values),
                        "instantiated_orbits": section["instantiated_orbits"],
                        "defined_on_base": section["defined_on_base"],
                        "holonomy": holonomy,
                        "markov_blanket": {
                            "sensory_labels": [point["label"] for point in base],
                            "active_residue": holonomy.get("residue_norm"),
                            "active_closed": holonomy.get("closed"),
                        },
                    }
                )
            chart_reports.append(
                {
                    "chart": atlas.name,
                    "base_manifold": {"B": base},
                    "local_sections": local_sections,
                }
            )
        # 对象序：按源图出现顺序并集
        object_ids: list[str] = []
        seen: set[str] = set()
        for atlas in atlases:
            for record in atlas.records:
                if record.object_id not in seen:
                    seen.add(record.object_id)
                    object_ids.append(record.object_id)
        objects: list[dict] = []
        for object_id in object_ids:
            arrows: list[dict] = []
            product = 1
            for idx in range(len(atlases) - 1):
                source = atlases[idx]
                target = atlases[idx + 1]
                value = morphism_on_id(source, target, object_id)
                arrows.append(
                    {
                        "morphism": f"g_{source.name}->{target.name}",
                        "object_id": object_id,
                        "value": value,
                    }
                )
                product *= value
            sigma_in: dict[str, str] = {}
            charts_present: list[str] = []
            for atlas in atlases:
                record = chart_index(atlas).get(object_id)
                if record is None:
                    continue
                charts_present.append(atlas.name)
                for label, text in record.values.items():
                    if label not in sigma_in:
                        sigma_in[label] = text
            orbits = [
                self.operator(label).instantiate(text)
                for label, text in sigma_in.items()
            ]
            glued = section_holonomy(orbits)
            gate_ok = holonomy_passes(glued)
            objects.append(
                {
                    "object_id": object_id,
                    "sigma_in": sigma_in,
                    "charts_present": charts_present,
                    "morphism_product": product,
                    "morphisms": arrows,
                    "instantiated_orbits": orbits,
                    "holonomy": glued,
                    "holonomy_gate": gate_ok,
                    "pushforward_ready": product == 1 and gate_ok,
                }
            )
        return {
            "atlas": "U_in",
            "writes_excel": False,
            "typical_fiber": coordinate_keys(),
            "charts": chart_reports,
            "objects": objects,
        }


    def push_to_output_group(
        self,
        group: OutputGroup,
        sample_sections: Sequence[dict],
        ready: Sequence[dict],
        phi: dict[str, str],
        isolated: Sequence[dict] | None = None,
    ) -> dict:
        """
        函数名: GeodesicEngine.push_to_output_group
        作用: 用 T=L_dst L_src^{-1} 等变平移状态；槽位由对象键绑定
        输入:
            group (OutputGroup): 由 Label 行/列得到的 D_block 与步长
            sample_sections (Sequence[dict]): 已填表上的样本截面，只作分析
            ready (Sequence[dict]): 已过匹配与相干门禁的对象
            isolated (Sequence[dict] | None): 未过门禁的对象
            phi (dict[str, str]): 源 Label -> 输出 Label
        输出:
            dict: 输出群、T、残差、拦截统计、推前格子
        """
        base_labels = [BaseLabel(anchor.label) for anchor in group.anchors]
        base = self.base_manifold(base_labels)
        by_label = {anchor.label: anchor for anchor in group.anchors}
        unmatched_phi = [src for src, dst in phi.items() if dst not in by_label]
        unfilled = [anchor.label for anchor in group.anchors if anchor.label not in set(phi.values())]
        unpushed = []
        seen_src: set[str] = set()
        for item in list(ready) + list(isolated or []):
            for name in item.get("sigma_in") or {}:
                text = str(name)
                if text in seen_src:
                    continue
                seen_src.add(text)
                if text not in phi:
                    unpushed.append(text)
        identity = {"k": 0, "m": 0, "role": "empty_card_at_origin"}
        generators = [{"name": "down", "vector": list(group.stride), "inverse": [-group.stride[0], -group.stride[1]]}]
        if group.right_stride is not None:
            generators.append(
                {
                    "name": "right",
                    "vector": list(group.right_stride),
                    "inverse": [-group.right_stride[0], -group.right_stride[1]],
                }
            )
        transport_matrices: dict[str, dict] = {}
        for src, dst in phi.items():
            if dst not in by_label:
                continue
            matrix = gauge_transport_matrix(self.operator(src).L_matrix, self.operator(dst).L_matrix)
            transport_matrices[src] = {
                "output_label": dst,
                "T": [[float(x) for x in row] for row in matrix],
            }
        roster = [str(item["object_id"]) for item in ready]
        n_right = 1
        placed: list[dict] = []
        residual_sum = 0.0
        for item in ready:
            object_id = str(item["object_id"])
            sigma = dict(item.get("sigma_in") or {})
            orbits_in = {str(orb.get("base")): orb for orb in item.get("instantiated_orbits") or []}
            k, m = slot_from_key(object_id, roster, n_right)
            cells: list[dict] = []
            sigma_out: dict[str, str] = {}
            out_orbits: list[dict] = []
            for src, dst in phi.items():
                anchor = by_label.get(dst)
                if anchor is None:
                    continue
                src_orb = orbits_in.get(src)
                if src_orb is None:
                    text = str(sigma.get(src, ""))
                    src_orb = self.operator(src).instantiate(text)
                text = str(src_orb.get("literal") or "")
                sigma_out[dst] = text
                packed = transport_matrices.get(src)
                if packed is None:
                    continue
                T = np.array(packed["T"], dtype=np.float64)
                v_in = np.array(src_orb["state"], dtype=np.float64)
                v_out = T @ v_in
                ground = bool(src_orb.get("ground"))
                orbit_name = f"NULL of {dst}" if ground else f"{text} of {dst}"
                out_orbits.append({"orbit": orbit_name, "state": v_out, "ground": ground})
                row, col = slot_cell(group, anchor, k, m, fiber=True)
                cells.append(
                    {
                        "cell": excel_coord(row, col),
                        "row": row,
                        "col": col,
                        "source_label": src,
                        "output_label": dst,
                        "literal": text,
                        "orbit": orbit_name,
                        "fiber": f"F_{dst}",
                        "state": [float(x) for x in v_out],
                        "formula": "T · v_in",
                    }
                )
            final_h = section_holonomy(out_orbits)
            residual_sum += float(final_h.get("residue_norm") or 0.0) if final_h.get("defined") else 1.0
            placed.append(
                {
                    "object_id": object_id,
                    "g": {"k": k, "m": m, "key_digest": key_digest(object_id)},
                    "sigma_out": sigma_out,
                    "cells": cells,
                    "holonomy": {
                        "defined": final_h.get("defined"),
                        "residue_norm": final_h.get("residue_norm"),
                        "closed": final_h.get("closed"),
                    },
                }
            )
        label_cells = []
        for anchor in group.anchors:
            row, col = slot_cell(group, anchor, 0, 0, fiber=False)
            label_cells.append(
                {
                    "cell": excel_coord(row, col),
                    "label": anchor.label,
                    "delta": [anchor.delta_row, anchor.delta_col],
                    "fiber_delta": [anchor.fiber_delta_row, anchor.fiber_delta_col],
                }
            )
        rejected = []
        for item in isolated or []:
            holonomy = item.get("holonomy") or {}
            rejected.append(
                {
                    "object_id": str(item.get("object_id")),
                    "residue_norm": holonomy.get("residue_norm"),
                    "closed": holonomy.get("closed"),
                    "defined": holonomy.get("defined"),
                    "morphism_product": item.get("morphism_product"),
                    "reason": "holonomy_gate" if item.get("morphism_product") == 1 else "morphism_zero",
                }
            )
        return {
            "atlas": "G_out",
            "one_object": "D_block",
            "writes_excel": False,
            "identity": identity,
            "generators": generators,
            "haar": {"type": "counting", "on": "G", "unique_up_to_scale": True},
            "phi": dict(phi),
            "unmatched_phi": unmatched_phi,
            "unfilled_output_labels": unfilled,
            "unpushed_source_labels": unpushed,
            "section_broken": bool(unfilled),
            "transport_matrices": transport_matrices,
            "holonomy_gate": {
                "threshold": HOLONOMY_GATE,
                "accepted": len(placed),
                "isolated": len(rejected),
            },
            "final_residue_sum": residual_sum,
            "base_manifold": {"B": base},
            "label_cells": label_cells,
            "sample_sections": list(sample_sections),
            "placed": placed,
            "ready_count": len(ready),
            "isolated": rejected,
            "excluded_not_ready": True,
        }


    def ingest(
        self,
        charts: Sequence[Sequence[FiberSeries]],
        object_key: str,
    ) -> dict:
        """
        函数名: GeodesicEngine.ingest
        作用: 稀疏纤维先成各自源图，再构建 U_in，不先 glue
        输入:
            charts (Sequence[Sequence[FiberSeries]])
            object_key (str)
        输出:
            dict
        """
        atlases: list[ChartAtlas] = []
        for fibers in charts:
            labels, records = records_from_fibers(fibers, object_key)
            name = fibers[0].source if fibers else ""
            atlases.append(
                ChartAtlas(name=name, labels=tuple(labels), records=tuple(records))
            )
        return self.input_groupoid(atlases)
