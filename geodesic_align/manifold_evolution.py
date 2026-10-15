"""流形历史沉淀：吸收 outspan 列的外在曲率，让格拉斯曼子空间长出新维。

生产路径不导入本模块。example_workflow 里只有注释掉的调用。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from geodesic_align.text_processor import (
    build_text_clouds,
    cached_text_align,
    classify_text_ends,
    cloud_logs,
    list_arrows,
    list_date_arrows,
    _vin,
)


SINGULAR_KEEP = 0.15



def _orthogonalize_rows(current: np.ndarray | None, extra: np.ndarray | None) -> np.ndarray:
    """
    函数名: _orthogonalize_rows
    作用: 把已有切基和新方向按行做 Gram-Schmidt，丢掉范数过小的向量
    输入:
        current (np.ndarray | None): (k, D) 已有基底，可以是 None
        extra (np.ndarray | None): (m, D) 待并入的方向
    输出:
        np.ndarray: (k_new, D) 行正交归一基
    """
    blocks: list[np.ndarray] = []
    dim = 0
    if current is not None and int(np.size(current)) > 0:
        current_mat = np.atleast_2d(np.asarray(current, dtype=np.float64))
        blocks.append(current_mat)
        dim = int(current_mat.shape[1])
    if extra is not None and int(np.size(extra)) > 0:
        extra_mat = np.atleast_2d(np.asarray(extra, dtype=np.float64))
        blocks.append(extra_mat)
        dim = int(extra_mat.shape[1])
    if dim == 0 or not blocks:
        return np.zeros((0, dim), dtype=np.float64)
    # QR：列是待正交方向。R 对角过小的列是数值零空间，丢掉，避免补出无关方向
    stacked = np.vstack(blocks)
    q_factor, r_factor = np.linalg.qr(stacked.T, mode="reduced")
    rank = min(int(q_factor.shape[1]), int(r_factor.shape[0]), int(r_factor.shape[1]))
    diag = np.abs(np.diag(r_factor[:rank, :rank]))
    keep = diag >= 1e-8
    if not np.any(keep):
        return np.zeros((0, dim), dtype=np.float64)
    return np.asarray(q_factor[:, :rank][:, keep].T, dtype=np.float64)



@dataclass
class ManifoldSedimentMemory:
    """流形历史沉淀与外在曲率吸收内存对象。"""

    epoch: int = 0
    V_in: np.ndarray | None = None
    records: list[dict[str, object]] = field(default_factory=list)


    def absorb(self, col_name: str, logs: np.ndarray, rho: float) -> np.ndarray:
        """
        函数名: ManifoldSedimentMemory.absorb
        作用: 提取法向残差的主序参量，正交并入 V_in，完成一次格拉斯曼维数跃迁
        输入:
            col_name (str): 列名
            logs (np.ndarray): (P, D) 该列在目标切点的黎曼对数
            rho (float): 跃迁前的域外能量比
        输出:
            np.ndarray: (k_new, D) 跃迁后的切基
        """
        mat = np.asarray(logs, dtype=np.float64)
        if mat.ndim == 1:
            mat = mat.reshape(1, -1)
        # 法向残差 v_out = (I - P_in) logs；还没有内蕴基时整团对数都在外面
        if self.V_in is not None and int(self.V_in.shape[0]) > 0:
            inside = (mat @ self.V_in.T) @ self.V_in
        else:
            inside = 0.0
        v_out = mat - inside
        _left, spec, vt = np.linalg.svd(v_out, full_matrices=False)
        peak = float(spec[0]) if len(spec) else 0.0
        if peak <= 1e-15:
            u_ext = np.zeros((0, int(mat.shape[1])), dtype=np.float64)
        else:
            # 只留下相对最大奇异值不低于 15% 的外部方向
            u_ext = vt[spec / peak >= SINGULAR_KEEP]
        grown = _orthogonalize_rows(self.V_in, u_ext)
        self.V_in = grown
        self.epoch += 1
        self.records.append({
            "epoch": self.epoch,
            "col": str(col_name),
            "rho_before": float(rho),
            "k_dim": int(grown.shape[0]),
        })
        return grown


    def evaluate_closure(self, logs: np.ndarray) -> float:
        """
        函数名: ManifoldSedimentMemory.evaluate_closure
        作用: 用当前 V_in 计算域外能量比，观察吸收后是否闭合
        输入:
            logs (np.ndarray): (P, D) 黎曼对数
        输出:
            float: rho，1 表示能量全在子空间外
        """
        mat = np.asarray(logs, dtype=np.float64)
        if mat.ndim == 1:
            mat = mat.reshape(1, -1)
        total = float(np.sum(mat * mat))
        if total <= 0.0 or self.V_in is None or int(self.V_in.shape[0]) == 0:
            return 1.0 if total > 0.0 else 0.0
        coords = mat @ self.V_in.T
        inside = float(np.sum(coords ** 2))
        leftover = max(0.0, total - inside)
        return leftover / total



def _sheet_tuples(table: object) -> tuple[str, list[str], list[dict[str, str]]]:
    """
    函数名: _sheet_tuples
    作用: 把 TableView 或已经拆开的三元组收成 (sheet, headers, rows)
    输入:
        table (object): TableView，或 (sheet, headers, rows)
    输出:
        tuple[str, list[str], list[dict[str, str]]]
    """
    if isinstance(table, tuple):
        sheet, headers, rows = table
        return str(sheet), list(headers), list(rows)
    return str(getattr(table, "sheet")), list(getattr(table, "headers")), list(getattr(table, "rows"))



def record_manifold_sediment(sources: list[object], dest: object, decisions: list[object]) -> ManifoldSedimentMemory:
    """
    函数名: record_manifold_sediment
    作用: 对仍是手工输入的 outspan 列，把正交残差吸进流形沉淀内存；优先复用 run_text_align 刚留下的列云
    输入:
        sources (list[object]): 源表，TableView 或 (sheet, headers, rows)
        dest (object): 模板表，TableView 或 (sheet, headers, rows)
        decisions (list[object]): 映射决策；只处理 cell_role 仍为 input 的列
    输出:
        ManifoldSedimentMemory: 跃迁后的内存，records 里有每列跃迁前的 rho
    """
    sheets = [_sheet_tuples(item) for item in sources]
    dest_sheet, dest_headers, dest_rows = _sheet_tuples(dest)
    source_sheets = tuple(item[0] for item in sheets)
    cached = cached_text_align(source_sheets, dest_sheet)
    if cached is None:
        src_clouds, dst_clouds = build_text_clouds(sheets, dest_sheet, dest_headers, dest_rows)
        arrows = list_arrows(src_clouds, dst_clouds) + list_date_arrows(src_clouds, dst_clouds)
        ends = classify_text_ends(src_clouds, dst_clouds, arrows) if src_clouds or dst_clouds else []
    else:
        src_clouds, dst_clouds, ends = cached
    # 只跟踪分类之后仍然留给手工输入的列
    still_input = {
        str(getattr(item, "input_label", ""))
        for item in decisions
        if str(getattr(item, "cell_role", "")) == "input"
    }
    by_label = {cloud.label: cloud for cloud in dst_clouds}
    memory = ManifoldSedimentMemory()
    for end in ends:
        if str(end.klass) != "outspan" or end.input_label not in still_input:
            continue
        cloud = by_label.get(end.input_label)
        if cloud is None or cloud.mu is None or cloud.particles is None:
            continue
        logs = cloud_logs(cloud.mu, cloud.particles)
        basis = _vin(src_clouds, cloud)
        # 第一列用它自己的源切基当内蕴子空间，后面的列沿用已经长出来的基
        if memory.V_in is None and basis.ndim == 2 and int(basis.shape[0]) > 0:
            memory.V_in = np.array(basis, dtype=np.float64, copy=True)
        memory.absorb(end.input_label, logs, float(end.rho))
    return memory
