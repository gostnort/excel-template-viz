"""文本通道：列名句子进 BERT，高斯平滑、谱截断、球面朗之万与切空间残差。"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from geodesic_align.digit_processor import cell_to_z
from geodesic_align.digit_router import route_columns


OVERLAP_TAU = 0.85
GAUSS_SIGMA = 1.0
SPECTRUM_OMEGA = 0.05
Z_DAY_UNIT = 365.0
SDE_DT = 0.05
SDE_STEPS = 40
SDE_LAMBDA = 1.0
SDE_SIGMA_SHORT = 0.08
SDE_SIGMA_LONG = 0.20
NAME_SDE_PARTICLES = 8
T_FLOOR = 1e-6
ANTIPODE_EPS = 1e-9
SDE_SEED = 42



@dataclass
class TextCloud:
    """一列文本的列名粒子云。"""

    key: str
    sheet: str
    label: str
    kind: str
    mu: np.ndarray | None
    particles: np.ndarray | None
    day_mean: float | None = None




@dataclass
class TextArrow:
    """同类文本列之间的一条态射。"""

    src_key: str
    dst_key: str
    L_sphere: float
    assign_cost: float




@dataclass
class GeodesicEnd:
    """文本列测地线尽头。"""

    input_label: str
    klass: str
    field: str
    source_sheet: str
    E_in: float
    E_out: float
    rho: float
    n_close: int
    rule: str



def text_headers(headers: list[str], rows: list[dict[str, str]]) -> list[str]:
    """
    函数名: text_headers
    作用: 只留下文本通道列名
    输入:
        headers (list[str]): 表头
        rows (list[dict[str, str]]): 数据行
    输出:
        list[str]
    """
    routes = {item.label: item for item in route_columns(headers, rows)}
    return [name for name in headers if routes[name].channel == "text"]



def named_row_sentence(headers: list[str], row: dict[str, str]) -> str:
    """
    函数名: named_row_sentence
    作用: 只拼接文本列的「列名：值」
    输入:
        headers (list[str]): 已过滤的文本表头
        row (dict[str, str]): 一行
    输出:
        str
    """
    pieces: list[str] = []
    for name in headers:
        raw = str(row.get(name) or "").strip()
        if not raw or raw.lower() in {"null", "none", "n/a"}:
            continue
        pieces.append(f"{name}：{raw}")
    return "，".join(pieces)



def _unit(vector: np.ndarray) -> np.ndarray:
    """
    函数名: _unit
    作用: 单位化；零向量原样返回
    输入:
        vector (np.ndarray): 向量
    输出:
        np.ndarray
    """
    vec = np.asarray(vector, dtype=np.float64).reshape(-1)
    nrm = float(np.linalg.norm(vec))
    if nrm < 1e-12:
        return vec
    return vec / nrm



def _tangent_project(base: np.ndarray, vector: np.ndarray) -> np.ndarray:
    """
    函数名: _tangent_project
    作用: 把向量投到单位向量的切空间
    输入:
        base (np.ndarray): 球面上的点
        vector (np.ndarray): 待投影向量
    输出:
        np.ndarray
    """
    point = _unit(base)
    vec = np.asarray(vector, dtype=np.float64).reshape(-1)
    return vec - float(np.dot(vec, point)) * point



def _cosine(left: np.ndarray, right: np.ndarray) -> float:
    """
    函数名: _cosine
    作用: 两向量余弦
    输入:
        left (np.ndarray): 向量
        right (np.ndarray): 向量
    输出:
        float
    """
    a = _unit(left)
    b = _unit(right)
    if float(np.linalg.norm(a)) < 1e-12 or float(np.linalg.norm(b)) < 1e-12:
        return 0.0
    return float(np.clip(np.dot(a, b), -1.0, 1.0))



def spherical_length(left: np.ndarray, right: np.ndarray) -> float:
    """
    函数名: spherical_length
    作用: 单位向量之间的大圆长度
    输入:
        left (np.ndarray): 云均值
        right (np.ndarray): 云均值
    输出:
        float
    """
    return float(np.arccos(_cosine(left, right)))



def riemannian_log_map(mu: np.ndarray, point: np.ndarray) -> np.ndarray:
    """
    函数名: riemannian_log_map
    作用: 球面精确对数映射，切向量模长等于测地距离 θ
    输入:
        mu (np.ndarray): 切点
        point (np.ndarray): 球面上的另一点
    输出:
        np.ndarray: log_μ(point)，‖v‖ = arccos(μ·point)
    """
    base = _unit(mu)
    other = _unit(point)
    cosine = float(np.clip(np.dot(base, other), -1.0, 1.0))
    theta = float(np.arccos(cosine))
    # 极近时用泰勒展开，避免除以 sin(0)
    sin_theta = float(np.sin(theta))
    if sin_theta < 1e-7:
        scale = 1.0 + (theta ** 2) / 6.0
    else:
        scale = theta / sin_theta
    return scale * (other - cosine * base)



def tangent_subspace_sde(
    x0: np.ndarray,
    basis_vectors: np.ndarray | None,
    *,
    lam: float,
    sigma: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """
    函数名: tangent_subspace_sde
    作用: 只在该列主切向子空间里做 Euler–Maruyama，正交方向只留 1/√D 的背景噪声
    输入:
        x0 (np.ndarray): 观测点
        basis_vectors (np.ndarray | None): (k, D) 主切向基；没有样本基时为 None
        lam (float): 拉回观测点的阻尼
        sigma (float): 扩散强度
        rng (np.random.Generator): 随机源
    输出:
        np.ndarray: 球面上的终点
    """
    point = _unit(x0)
    origin = point.copy()
    dim = int(point.size)
    sqrt_dt = float(np.sqrt(SDE_DT))
    use_subspace = basis_vectors is not None and int(basis_vectors.shape[0]) > 0
    rank = int(basis_vectors.shape[0]) if use_subspace else dim
    for _step in range(SDE_STEPS):
        # 漂移把点拉回这条观测
        drift = _tangent_project(point, -float(lam) * (point - origin)) * float(SDE_DT)
        if use_subspace:
            # 主方差留在 k 维语义切空间，其余方向只做维数归一化的微量摄动
            sub_noise = rng.normal(0.0, 1.0, size=rank)
            flow_tangent = sub_noise @ basis_vectors
            ambient = rng.normal(0.0, 1.0 / np.sqrt(dim), size=dim)
            noise_dir = flow_tangent + 0.1 * ambient
        else:
            noise_dir = rng.normal(0.0, 1.0 / np.sqrt(dim), size=dim)
        diffusion = float(sigma) * sqrt_dt * _tangent_project(point, noise_dir)
        point = _unit(point + drift + diffusion)
    return point



def euler_maruyama_sphere(
    x0: np.ndarray,
    *,
    lam: float,
    sigma: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """
    函数名: euler_maruyama_sphere
    作用: 没有主切向基时的球面扩散，噪声方差按 1/√D 归一化
    输入:
        x0 (np.ndarray): 初值
        lam (float): 阻尼
        sigma (float): 扩散
        rng (np.random.Generator): 随机源
    输出:
        np.ndarray
    """
    return tangent_subspace_sde(x0, None, lam=lam, sigma=sigma, rng=rng)



def cloud_logs(mu: np.ndarray, particles: np.ndarray) -> np.ndarray:
    """
    函数名: cloud_logs
    作用: 粒子在 μ 处的黎曼对数，模长是弧度而不是弦长
    输入:
        mu (np.ndarray): 云均值
        particles (np.ndarray): (P, d)
    输出:
        np.ndarray
    """
    mean = np.asarray(mu, dtype=np.float64).reshape(-1)
    mat = np.asarray(particles, dtype=np.float64)
    packed = np.zeros((int(mat.shape[0]), int(mean.shape[0])), dtype=np.float64)
    for idx in range(int(mat.shape[0])):
        packed[idx] = riemannian_log_map(mean, mat[idx])
    return packed



def cloud_radius(cloud: TextCloud) -> float:
    """
    函数名: cloud_radius
    作用: 对数映射长度的均方根
    输入:
        cloud (TextCloud): 列云
    输出:
        float
    """
    if cloud.mu is None or cloud.particles is None or cloud.particles.shape[0] == 0:
        return 0.0
    logs = cloud_logs(cloud.mu, cloud.particles)
    nrms = np.linalg.norm(logs, axis=1)
    return float(np.sqrt(np.mean(nrms ** 2)))



def sphere_parallel_transport(mu_s: np.ndarray, mu_d: np.ndarray, vec: np.ndarray) -> np.ndarray | None:
    """
    函数名: sphere_parallel_transport
    作用: 沿大圆把切向量从 μs 搬到 μd
    输入:
        mu_s (np.ndarray): 源点
        mu_d (np.ndarray): 目标点
        vec (np.ndarray): 切向量
    输出:
        np.ndarray | None
    """
    p = _unit(mu_s)
    q = _unit(mu_d)
    moved_in = np.asarray(vec, dtype=np.float64).reshape(-1)
    cosine = float(np.dot(p, q))
    if cosine <= -1.0 + ANTIPODE_EPS:
        return None
    moved = moved_in - (float(np.dot(moved_in, q)) / (1.0 + cosine)) * (p + q)
    return _tangent_project(q, moved)



def list_arrows(src: list[TextCloud], dst: list[TextCloud]) -> list[TextArrow]:
    """
    函数名: list_arrows
    作用: 只连接 kind 相同且都有云均值的文本列
    输入:
        src (list[TextCloud]): 源云
        dst (list[TextCloud]): 模板云
    输出:
        list[TextArrow]
    """
    packed: list[TextArrow] = []
    for left in src:
        for right in dst:
            if left.kind == "DATETIME" or right.kind == "DATETIME":
                continue
            if left.kind != right.kind or left.mu is None or right.mu is None:
                continue
            length = spherical_length(left.mu, right.mu)
            packed.append(TextArrow(left.key, right.key, length, length))
    return packed



def list_date_arrows(src: list[TextCloud], dst: list[TextCloud]) -> list[TextArrow]:
    """
    函数名: list_date_arrows
    作用: 日期列按 |z| / 365 排名；一年以内且球面相交才连虚拟箭头
    输入:
        src (list[TextCloud]): 源云，日期列带 day_mean
        dst (list[TextCloud]): 模板云
    输出:
        list[TextArrow]
    """
    packed: list[TextArrow] = []
    for left in src:
        for right in dst:
            if left.kind != "DATETIME" or right.kind != "DATETIME":
                continue
            if left.day_mean is None or right.day_mean is None:
                continue
            # 用日差除以一年，当作日期自己的距离单位
            year = abs(float(left.day_mean) - float(right.day_mean)) / Z_DAY_UNIT
            # 得到相差多少年
            if year > 1.0:
                continue
            length = 0.0
            if left.mu is not None and right.mu is not None:
                length = spherical_length(left.mu, right.mu)
                # 得到两侧列名云的大圆长度
            packed.append(TextArrow(left.key, right.key, length, year))
            # 得到一条年内的日期箭头，代价是年差
    return packed



def _vin(src: list[TextCloud], dest: TextCloud) -> np.ndarray:
    """
    函数名: _vin
    作用: 源云对数搬到目标切空间后做 SVD
    输入:
        src (list[TextCloud]): 源云
        dest (TextCloud): 目标云
    输出:
        np.ndarray
    """
    if dest.mu is None:
        return np.zeros((0, 0), dtype=np.float64)
    mu_d = np.asarray(dest.mu, dtype=np.float64).reshape(-1)
    dim = int(mu_d.shape[0])
    rows: list[np.ndarray] = []
    for item in src:
        if item.mu is None or item.particles is None:
            continue
        for vec in cloud_logs(item.mu, item.particles):
            moved = sphere_parallel_transport(item.mu, mu_d, vec)
            if moved is not None:
                rows.append(moved)
    if not rows:
        return np.zeros((0, dim), dtype=np.float64)
    stacked = np.stack(rows, axis=0)
    rms = float(np.sqrt(np.mean(np.sum(stacked ** 2, axis=1))))
    sigma = SDE_SIGMA_SHORT if dest.kind == "SHORT_STRING" else SDE_SIGMA_LONG
    floor = max(T_FLOOR, rms * sigma)
    _u, spec, vt = np.linalg.svd(stacked, full_matrices=False)
    # 相对最大奇异值做 ω 截断，小于谱峰比例的方向丢掉
    peak = float(spec[0]) if len(spec) else 0.0
    kept = [
        vt[idx] for idx, val in enumerate(spec)
        if float(val) > floor and (peak <= 0.0 or float(val) / peak >= SPECTRUM_OMEGA)
    ]
    if not kept:
        return np.zeros((0, dim), dtype=np.float64)
    return np.stack(kept, axis=0)



def _energies(dest: TextCloud, basis: np.ndarray) -> tuple[float, float, float]:
    """
    函数名: _energies
    作用: 目标云在 V_in 内外的能量
    输入:
        dest (TextCloud): 目标云
        basis (np.ndarray): 切空间基
    输出:
        tuple[float, float, float]
    """
    if dest.mu is None or dest.particles is None:
        return 0.0, 0.0, 0.0
    logs = cloud_logs(dest.mu, dest.particles)
    e_in = 0.0
    e_out = 0.0
    if basis.ndim != 2 or basis.shape[0] == 0:
        for vec in logs:
            e_out += float(np.dot(vec, vec))
    else:
        proj = basis.T @ basis
        for vec in logs:
            inside = proj @ vec
            perp = vec - inside
            e_in += float(np.dot(inside, inside))
            e_out += float(np.dot(perp, perp))
    total = e_in + e_out
    rho = 0.0 if total <= 0.0 else e_out / total
    return float(e_in), float(e_out), float(rho)



def classify_text_ends(
    src: list[TextCloud],
    dst: list[TextCloud],
    arrows: list[TextArrow],
) -> list[GeodesicEnd]:
    """
    函数名: classify_text_ends
    作用: 文本列按切空间残差与近箭头数分类；n_close>=2 才是 derived
    输入:
        src (list[TextCloud]): 源云
        dst (list[TextCloud]): 模板云
        arrows (list[TextArrow]): 态射
    输出:
        list[GeodesicEnd]
    """
    by_key = {item.key: item for item in src}
    incoming: dict[str, list[TextArrow]] = {item.key: [] for item in dst}
    for arrow in arrows:
        incoming.setdefault(arrow.dst_key, []).append(arrow)
    packed: list[GeodesicEnd] = []
    for dest in dst:
        basis = _vin(src, dest)
        e_in, e_out, rho = _energies(dest, basis)
        close: list[TextArrow] = []
        for arrow in incoming.get(dest.key, []):
            left = by_key.get(arrow.src_key)
            if left is None:
                continue
            span = cloud_radius(left) + cloud_radius(dest)
            # 日期虚拟箭头还要落在一年以内；普通箭头只看两朵云是否相交
            if left.kind == "DATETIME" and dest.kind == "DATETIME" and arrow.assign_cost > 1.0:
                continue
            if arrow.L_sphere <= span:
                close.append(arrow)
        outspan = e_out > e_in or (e_out == e_in and e_out > 0.0)
        field_name = ""
        sheet = ""
        if outspan:
            klass = "outspan"
            rule = "E_out_gt_E_in"
        elif len(close) >= 2:
            klass = "derived"
            rule = "multi_close"
        elif len(close) == 1:
            klass = "carry"
            rule = "one_close"
        else:
            klass = "inspan_miss"
            rule = "no_close"
        if not outspan and close:
            ranked = sorted(close, key=lambda item: (item.assign_cost, item.src_key))
            names: list[str] = []
            sheets: list[str] = []
            for item in ranked:
                bit = item.src_key.split(".", 1)[-1]
                if bit not in names:
                    names.append(bit)
                sheet_name = item.src_key.split(".", 1)[0]
                if sheet_name not in sheets:
                    sheets.append(sheet_name)
            field_name = "|".join(names)
            sheet = "|".join(sheets)
        packed.append(
            GeodesicEnd(
                dest.label,
                klass,
                field_name,
                sheet,
                e_in,
                e_out,
                rho,
                len(close),
                rule,
            )
        )
    return packed



def run_text_align(
    sources: list[tuple[str, list[str], list[dict[str, str]]]],
    dest_sheet: str,
    dest_headers: list[str],
    dest_rows: list[dict[str, str]],
) -> list[GeodesicEnd]:
    """
    函数名: run_text_align
    作用: 文本列建云并分类；没有权重时仍用日期的日差做虚拟箭头
    输入:
        sources (list): (sheet, headers, rows)
        dest_sheet (str): 模板表名
        dest_headers (list[str]): 模板表头
        dest_rows (list[dict[str, str]]): 模板行
    输出:
        list[GeodesicEnd]
    """
    engine = None
    try:
        from geodesic_align.mlm_tokens import load_masked_bert, pick_model_id, weights_ready
    except Exception:
        weights_ready = None
    if weights_ready is not None:
        blobs = [" ".join(dest_headers)]
        for _sheet, headers, rows in sources:
            blobs.append(" ".join(headers))
            for row in rows[:3]:
                blobs.append(" ".join(str(v) for v in row.values()))
        model_id = pick_model_id(*blobs)
        if weights_ready(model_id):
            engine = load_masked_bert(model_id)
    # 得到可用的掩码模型；没有权重时只保留日期列
    src_clouds: list[TextCloud] = []
    for sheet, headers, rows in sources:
        if engine is not None:
            src_clouds.extend(_clouds_for_sheet(engine, sheet, text_headers(headers, rows), rows))
        src_clouds.extend(_date_clouds(engine, sheet, headers, rows))
    dst_clouds = _date_clouds(engine, dest_sheet, dest_headers, dest_rows)
    if engine is not None:
        dst_clouds = _clouds_for_sheet(engine, dest_sheet, text_headers(dest_headers, dest_rows), dest_rows) + dst_clouds
    arrows = list_arrows(src_clouds, dst_clouds) + list_date_arrows(src_clouds, dst_clouds)
    # 得到普通箭头和一年以内的日期箭头
    if not src_clouds and not dst_clouds:
        return []
    return classify_text_ends(src_clouds, dst_clouds, arrows)



def _day_mean(rows: list[dict[str, str]], label: str) -> float | None:
    """
    函数名: _day_mean
    作用: 一列干净日期 z 的实部平均，作为虚拟箭头的日位
    输入:
        rows (list[dict[str, str]]): 数据行
        label (str): 列名
    输出:
        float | None
    """
    vals: list[float] = []
    for row in rows:
        value = cell_to_z(str(row.get(label) or ""), kind="DATETIME")
        if value.imag < 0.0:
            continue
        vals.append(float(value.real))
    if not vals:
        return None
    return sum(vals) / len(vals)



def _date_clouds(
    engine: object | None,
    sheet: str,
    headers: list[str],
    rows: list[dict[str, str]],
) -> list[TextCloud]:
    """
    函数名: _date_clouds
    作用: 日期列带上日位；有模型时列名粒子仍来自名称空间
    输入:
        engine (object | None): MaskedBert，没有权重则为 None
        sheet (str): 表名
        headers (list[str]): 表头
        rows (list[dict[str, str]]): 数据行
    输出:
        list[TextCloud]
    """
    routes = {item.label: item for item in route_columns(headers, rows)}
    names = [name for name in headers if routes[name].kind == "DATETIME"]
    named: dict[str, TextCloud] = {}
    if engine is not None and names:
        for cloud in _clouds_for_sheet(engine, sheet, names, rows):
            named[cloud.label] = cloud
    packed: list[TextCloud] = []
    for name in names:
        day = _day_mean(rows, name)
        # 得到该列的平均日位
        base = named.get(name)
        if base is None or base.mu is None:
            packed.append(TextCloud(f"{sheet}.{name}", sheet, name, "DATETIME", None, None, day))
            # 得到只有日位、没有列名粒子的日期云
            continue
        packed.append(TextCloud(base.key, sheet, name, "DATETIME", base.mu, base.particles, day))
        # 得到带列名粒子和日位的日期云
    return packed



def _principal_tangent_basis(vecs: list[np.ndarray]) -> np.ndarray | None:
    """
    函数名: _principal_tangent_basis
    作用: 取该列观测在均值切空间里的主成分，作为扩散子空间
    输入:
        vecs (list[np.ndarray]): 单位观测
    输出:
        np.ndarray | None: (k, D)，样本少于 2 或没有有效方向时为 None
    """
    if len(vecs) < 2:
        return None
    center = _unit(np.mean(np.stack(vecs, axis=0), axis=0))
    logs = np.stack([riemannian_log_map(center, item) for item in vecs], axis=0)
    _left, spec, vt = np.linalg.svd(logs, full_matrices=False)
    if len(spec) == 0:
        return None
    peak = float(spec[0])
    if peak <= 1e-12:
        return None
    kept = [vt[idx] for idx, val in enumerate(spec) if float(val) / peak >= SPECTRUM_OMEGA and float(val) > 1e-8]
    if not kept:
        return None
    return np.stack(kept, axis=0)



def _clouds_for_sheet(engine: object, sheet: str, headers: list[str], rows: list[dict[str, str]]) -> list[TextCloud]:
    """
    函数名: _clouds_for_sheet
    作用: 文本列名 token 做高斯平滑与球面扩散，得到列云
    输入:
        engine (object): MaskedBert
        sheet (str): 表名
        headers (list[str]): 文本列
        rows (list[dict[str, str]]): 数据行
    输出:
        list[TextCloud]
    """
    # 没有文本列时不建云
    if not headers:
        return []
    # 得到空云列表
    # 按列收集每一行里该列名对应的单位向量
    collected: dict[str, list[np.ndarray]] = {name: [] for name in headers}
    for row in rows:
        # 只把文本列拼成「列名：值」，空值和哨兵不进句子
        sentence = named_row_sentence(headers, row)
        # 得到这一行的命名句
        if not sentence:
            continue
        # 整句做一次掩码模型前向，后面按字符位置切列
        bundle = engine.encode(sentence)
        # 得到每个 token 的隐状态
        for name in headers:
            # 用「列名：」在句子里的字符区间对齐内容 token
            token = f"{name}："
            start = sentence.find(token)
            # 得到列名在句中的起点，找不到则为 -1
            if start < 0:
                continue
            stop = start + len(token)
            # 得到列名区间的终点
            offsets = engine.content_offsets(sentence)
            # 得到内容 token 的下标和字符起止
            # 重叠比例达到 τ 的 token 按距列名中心的高斯权重平均
            center = (float(start) + float(stop)) / 2.0
            label_span = max(float(stop - start), 1.0)
            acc: np.ndarray | None = None
            weight_sum = 0.0
            for tok_idx, a, b in offsets:
                overlap = float(min(stop, b) - max(start, a))
                if overlap <= 0.0:
                    continue
                token_span = max(float(b - a), 1.0)
                if overlap / token_span < OVERLAP_TAU and overlap / label_span < OVERLAP_TAU:
                    continue
                mid = (float(a) + float(b)) / 2.0
                weight = math.exp(-0.5 * ((mid - center) / GAUSS_SIGMA) ** 2)
                # 得到该 token 的高斯权重
                vec = np.asarray(bundle.hidden[tok_idx], dtype=np.float64) * weight
                acc = vec if acc is None else acc + vec
                weight_sum += weight
            if acc is not None and weight_sum > 0.0:
                collected[name].append(_unit(acc / weight_sum))
                # 得到高斯平滑后的单位向量
    # 固定随机源，把每列的单位向量扩散成球面粒子云
    clouds: list[TextCloud] = []
    rng = np.random.default_rng(SDE_SEED)
    for name in headers:
        vecs = collected[name]
        # 得到该列收集到的单位向量
        # 一行都没对上列名时，留下空云，避免后面当近邻
        if not vecs:
            clouds.append(TextCloud(f"{sheet}.{name}", sheet, name, "SHORT_STRING", None, None))
            # 得到没有均值、没有粒子的空云
            continue
        # 按单元格长短决定扩散强度
        kind = "LONG_STRING" if any(len(str(row.get(name) or "")) >= 16 for row in rows) else "SHORT_STRING"
        # 得到短文本或长文本
        sigma = SDE_SIGMA_LONG if kind == "LONG_STRING" else SDE_SIGMA_SHORT
        # 得到该列的球面扩散系数
        # 用本列观测的主切向做扩散，不在全部隐空间里各向同性撒噪声
        basis = _principal_tangent_basis(vecs)
        particles: list[np.ndarray] = []
        for vec in vecs:
            for _idx in range(NAME_SDE_PARTICLES):
                particles.append(tangent_subspace_sde(vec, basis, lam=SDE_LAMBDA, sigma=sigma, rng=rng))
        # 得到该列全部粒子
        mat = np.stack(particles, axis=0)
        # 得到粒子矩阵，行是粒子
        clouds.append(TextCloud(f"{sheet}.{name}", sheet, name, kind, _unit(np.mean(mat, axis=0)), mat))
        # 得到以粒子均值方向为中心的列云
    return clouds
    # 得到本表每一文本列的云
