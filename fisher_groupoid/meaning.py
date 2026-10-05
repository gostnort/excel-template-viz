"""Label 算子：调用层注入模型原生向量，再构造 L。"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


CACHE_PATH = Path(__file__).resolve().parent / "meaning_cache.json"
ALIAS_PATH = Path(__file__).resolve().parent / "label_alias_cache.json"
AMBIGUITY_SECOND_PEAK = 0.28
Clarifier = Callable[[str, list[str]], str]
ProbeScorer = Callable[[str], np.ndarray]
MeaningOpenFn = Callable[[str, np.ndarray], bool]
_memory: dict[str, list[float]] | None = None
_alias_memory: dict[str, dict] | None = None
_probe_scorer: ProbeScorer | None = None
_cache_key: str = ""
_persist_scores: bool = True
_clarifier: Clarifier | None = None
_meaning_open_fn: MeaningOpenFn | None = None
_space_dim: int = 0


def space_dim() -> int:
    """
    函数名: space_dim
    作用: 返回已锁定的模型向量维数；未采样前为 0
    输入: 无
    输出:
        int
    """
    return int(_space_dim)


def coordinate_keys() -> list[str]:
    """
    函数名: coordinate_keys
    作用: 与维数等长的 JSON 键名 0..n-1
    输入: 无
    输出:
        list[str]
    """
    return [str(idx) for idx in range(space_dim())]


def _lock_dim(n: int) -> None:
    """
    函数名: _lock_dim
    作用: 用模型给出的长度锁定维数；长度不一致则拒绝，不裁切
    输入:
        n (int): 向量长度
    输出: 无
    """
    global _space_dim
    size = int(n)
    if size < 1:
        raise ValueError("模型向量维数必须为正")
    if _space_dim == 0:
        _space_dim = size
        return
    if size != _space_dim:
        raise ValueError(f"向量长度 {size} 与模型维数 {_space_dim} 不符，拒绝裁切")


def vector_to_key_map(vector: np.ndarray) -> dict[str, float]:
    """
    函数名: vector_to_key_map
    作用: 把向量写成键数等于维数的 JSON 对象，键为 0..n-1
    输入:
        vector (np.ndarray)
    输出:
        dict[str, float]
    """
    arr = np.asarray(vector, dtype=np.float64).reshape(-1)
    _lock_dim(arr.size)
    return {str(idx): float(arr[idx]) for idx in range(arr.size)}


def key_map_to_vector(payload: dict) -> np.ndarray:
    """
    函数名: key_map_to_vector
    作用: 从键 0..n-1 的对象还原向量；缺键或跳号视为裁切，拒绝
    输入:
        payload (dict)
    输出:
        np.ndarray
    """
    if not payload:
        raise ValueError("空向量对象")
    keys = []
    for key in payload:
        try:
            keys.append(int(key))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"非法坐标键 {key!r}") from exc
    n = len(keys)
    if sorted(keys) != list(range(n)):
        raise ValueError("坐标键必须恰好是 0..n-1，不得缺键或裁切")
    out = np.empty(n, dtype=np.float64)
    for idx in range(n):
        out[idx] = float(payload[str(idx)])
    _lock_dim(n)
    return out


def _as_full_vector(value: object, *, lock: bool = True) -> np.ndarray | None:
    """
    函数名: _as_full_vector
    作用: 接受键对象或等长列表；lock=False 时不锁定维数（别名表）
    输入:
        value (object)
        lock (bool): 是否用该向量锁定维数
    输出:
        np.ndarray | None
    """
    arr: np.ndarray | None = None
    if isinstance(value, dict):
        try:
            if not value:
                return None
            keys = []
            for key in value:
                keys.append(int(key))
            n = len(keys)
            if sorted(keys) != list(range(n)):
                return None
            arr = np.empty(n, dtype=np.float64)
            for idx in range(n):
                arr[idx] = float(value[str(idx)])
        except (TypeError, ValueError):
            return None
    elif isinstance(value, list):
        if not value:
            return None
        arr = np.array([float(x) for x in value], dtype=np.float64)
    if arr is None:
        return None
    if _space_dim and arr.size != _space_dim:
        return None
    if lock:
        _lock_dim(arr.size)
    return arr


def ground_vector() -> np.ndarray:
    """
    函数名: ground_vector
    作用: 纤维原点，长度等于已锁定维数
    输入: 无
    输出:
        np.ndarray
    """
    if _space_dim < 1:
        raise RuntimeError("尚未从模型锁定向量维数")
    return np.zeros(_space_dim, dtype=np.float64)


def ambiguity_entropy_gate(n: int) -> float:
    """
    函数名: ambiguity_entropy_gate
    作用: 按当前维数计算歧义熵阈值
    输入:
        n (int): 维数
    输出:
        float
    """
    size = int(n) if int(n) > 1 else 2
    return math.log(size) * 0.85


def set_probe_scorer(
    fn: ProbeScorer | None,
    *,
    cache_key: str | None = None,
    persist: bool = True,
) -> None:
    """
    函数名: set_probe_scorer
    作用: 由调用层注入「文本 -> 模型原生向量」；意义层不发起网络调用
    输入:
        fn (ProbeScorer | None): 打分函数；None 表示尚未绑定
        cache_key (str | None): 向量缓存分区键；None 表示不改
        persist (bool): 是否写入 meaning_cache.json
    输出: 无
    """
    global _probe_scorer, _cache_key, _persist_scores, _memory, _space_dim
    if cache_key is not None:
        key = str(cache_key)
        if key != _cache_key:
            _memory = None
            _space_dim = 0
        _cache_key = key
    if fn is None:
        _space_dim = 0
    _probe_scorer = fn
    _persist_scores = bool(persist) if fn is not None else True


def set_embedder_override(fn: Callable[[str], np.ndarray] | None) -> None:
    """
    函数名: set_embedder_override
    作用: 测试注入模型向量且不落向量缓存；None 则清空打分函数
    输入:
        fn (Callable[[str], np.ndarray] | None)
    输出: 无
    """
    if fn is None:
        set_probe_scorer(None)
        return
    set_probe_scorer(fn, persist=False)


def set_clarifier(fn: Clarifier | None) -> None:
    """
    函数名: set_clarifier
    作用: 注册高歧义 Label 的人类澄清回调；None 则遇歧义抛错
    输入:
        fn (Clarifier | None): (label_raw, candidates) -> 用户释义
    输出: 无
    """
    global _clarifier
    _clarifier = fn


def set_meaning_open_fn(fn: MeaningOpenFn | None) -> None:
    """
    函数名: set_meaning_open_fn
    作用: 注入「该 Label 含义是否未定、必须问人」；None 则只用向量几何
    输入:
        fn (MeaningOpenFn | None): (label, vector) -> True 表示必须问人
    输出: 无
    """
    global _meaning_open_fn
    _meaning_open_fn = fn


def set_alias_cache_path(path: Path | None) -> None:
    """
    函数名: set_alias_cache_path
    作用: 测试或自定义别名缓存路径；None 则回到默认文件
    输入:
        path (Path | None)
    输出: 无
    """
    global ALIAS_PATH, _alias_memory
    _alias_memory = None
    if path is None:
        ALIAS_PATH = Path(__file__).resolve().parent / "label_alias_cache.json"
        return
    ALIAS_PATH = Path(path)



class AmbiguousLabelError(RuntimeError):
    """高歧义 Label 且尚未注册澄清回调。"""

    def __init__(self, label: str, vector: np.ndarray, entropy: float, candidates: list[str]) -> None:
        """
        函数名: AmbiguousLabelError.__init__
        作用: 记录歧义 Label 与探针候选
        输入:
            label (str)
            vector (np.ndarray)
            entropy (float)
            candidates (list[str])
        输出: 无
        """
        self.label = str(label)
        self.vector = np.asarray(vector, dtype=np.float64)
        self.entropy = float(entropy)
        self.candidates = list(candidates)
        super().__init__(f"Label {self.label!r} 语义歧义 H={self.entropy:.3f} candidates={self.candidates}")


def _load_cache() -> dict[str, list[float]]:
    """
    函数名: _load_cache
    作用: 读已钉死的意义向量；分区键不一致则丢弃
    输入: 无
    输出:
        dict[str, list[float]]
    """
    global _memory
    if _memory is not None:
        return _memory
    _memory = {}
    if not CACHE_PATH.is_file():
        return _memory
    raw = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return _memory
    if str(raw.get("model") or "") != _cache_key:
        return _memory
    # 中文注释: 旧 5 键探针缓存没有 dim，整份丢弃
    file_dim = raw.get("dim")
    if not isinstance(file_dim, int) or file_dim < 1:
        return _memory
    _lock_dim(file_dim)
    items = raw.get("items") or {}
    if isinstance(items, dict):
        for key, value in items.items():
            vector = _as_full_vector(value)
            if vector is None or int(vector.size) != file_dim:
                continue
            _memory[str(key)] = [float(x) for x in vector]
    return _memory


def _save_cache() -> None:
    """
    函数名: _save_cache
    作用: 把意义向量钉到 meaning_cache.json
    输入: 无
    输出: 无
    """
    stored = _load_cache()
    items = {key: vector_to_key_map(np.array(value, dtype=np.float64)) for key, value in stored.items()}
    payload = {"model": _cache_key, "dim": space_dim(), "items": items}
    _atomic_write_json(CACHE_PATH, payload)


def _atomic_write_json(path: Path, payload: dict) -> None:
    """
    函数名: _atomic_write_json
    作用: 先写同目录临时文件再替换，避免半截 JSON
    输入:
        path (Path)
        payload (dict)
    输出: 无
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    except Exception:
        if tmp.is_file():
            tmp.unlink()
        raise


def _alias_key(text: str) -> str:
    """
    函数名: _alias_key
    作用: 别名查找键，大小写不敏感
    输入:
        text (str)
    输出:
        str
    """
    return str(text or "").strip().casefold()


def _load_aliases() -> dict[str, dict]:
    """
    函数名: _load_aliases
    作用: 读 label_alias_cache.json；不按向量缓存分区键隔离
    输入: 无
    输出:
        dict[str, dict]
    """
    global _alias_memory
    if _alias_memory is not None:
        return _alias_memory
    _alias_memory = {}
    if not ALIAS_PATH.is_file():
        return _alias_memory
    raw = json.loads(ALIAS_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return _alias_memory
    aliases = raw.get("aliases") or {}
    if not isinstance(aliases, dict):
        return _alias_memory
    for key, item in aliases.items():
        if not isinstance(item, dict):
            continue
        vector = item.get("vector")
        definition = str(item.get("user_definition") or "").strip()
        parsed = _as_full_vector(vector, lock=False)
        if parsed is None or not definition:
            continue
        _alias_memory[_alias_key(str(key))] = {
            "raw": str(key),
            "user_definition": definition,
            "vector": [float(x) for x in parsed],
            "timestamp": str(item.get("timestamp") or ""),
        }
    return _alias_memory


def _save_aliases() -> None:
    """
    函数名: _save_aliases
    作用: 原子写盘人类澄清别名
    输入: 无
    输出: 无
    """
    stored = _load_aliases()
    aliases: dict[str, dict] = {}
    # 中文注释: 磁盘上维数不符的旧别名原样保留，不经当前模型维数重写
    if ALIAS_PATH.is_file():
        raw = json.loads(ALIAS_PATH.read_text(encoding="utf-8"))
        old = (raw.get("aliases") or {}) if isinstance(raw, dict) else {}
        if isinstance(old, dict):
            aliases.update(old)
    for _key, item in stored.items():
        vec = np.asarray(item["vector"], dtype=np.float64).reshape(-1)
        if _space_dim and int(vec.size) != int(_space_dim):
            continue
        aliases[str(item.get("raw") or _key)] = {
            "user_definition": item["user_definition"],
            "vector": vector_to_key_map(vec),
            "timestamp": item.get("timestamp") or "",
        }
    _atomic_write_json(ALIAS_PATH, {"aliases": aliases})


def reload_aliases() -> None:
    """
    函数名: reload_aliases
    作用: 丢弃内存中的别名表，下次从磁盘重读（模拟重启或重置配置）
    输入: 无
    输出: 无
    """
    global _alias_memory
    _alias_memory = None


def lookup_alias(text: str) -> dict | None:
    """
    函数名: lookup_alias
    作用: 按原文查找已澄清的别名记录
    输入:
        text (str)
    输出:
        dict | None
    """
    key = _alias_key(text)
    if not key:
        return None
    found = _load_aliases().get(key)
    if found is None:
        return None
    vec = found.get("vector") or []
    if _space_dim and len(vec) != _space_dim:
        return None
    return found


def remember_alias(label_raw: str, user_definition: str, vector: np.ndarray) -> None:
    """
    函数名: remember_alias
    作用: 写入别名缓存并立即落盘
    输入:
        label_raw (str)
        user_definition (str)
        vector (np.ndarray)
    输出: 无
    """
    stored = _load_aliases()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    stored[_alias_key(label_raw)] = {
        "raw": str(label_raw).strip(),
        "user_definition": str(user_definition).strip(),
        "vector": [float(x) for x in np.asarray(vector, dtype=np.float64).reshape(-1)],
        "timestamp": stamp,
    }
    _lock_dim(len(stored[_alias_key(label_raw)]["vector"]))
    _save_aliases()


def probe_entropy(vector: np.ndarray) -> float:
    """
    函数名: probe_entropy
    作用: 探针分布的香农熵 H(v)=-Σ p_i log p_i
    输入:
        vector (np.ndarray)
    输出:
        float
    """
    probs = np.asarray(vector, dtype=np.float64).reshape(-1)
    total = float(np.sum(probs))
    if total <= 1e-12:
        return 0.0
    probs = np.clip(probs / total, 1e-12, 1.0)
    return float(-np.sum(probs * np.log(probs)))


def is_multimodal(vector: np.ndarray) -> bool:
    """
    函数名: is_multimodal
    作用: 两个探针峰都高且接近时视为双峰/多峰
    输入:
        vector (np.ndarray)
    输出:
        bool
    """
    probs = np.asarray(vector, dtype=np.float64).reshape(-1)
    if probs.size < 2:
        return False
    ordered = np.sort(probs)[::-1]
    first = float(ordered[0])
    second = float(ordered[1])
    if second < AMBIGUITY_SECOND_PEAK:
        return False
    return (first - second) < 0.15


def ambiguity_candidates(vector: np.ndarray) -> list[str]:
    """
    函数名: ambiguity_candidates
    作用: 按坐标分量给出澄清候选键名
    输入:
        vector (np.ndarray)
    输出:
        list[str]
    """
    probs = np.asarray(vector, dtype=np.float64).reshape(-1)
    order = np.argsort(-probs)
    names: list[str] = []
    for idx in order:
        if len(names) >= 3:
            break
        names.append(str(int(idx)))
    return names


def is_ambiguous_vector(vector: np.ndarray) -> bool:
    """
    函数名: is_ambiguous_vector
    作用: 熵过高或双峰则标为歧义
    输入:
        vector (np.ndarray)
    输出:
        bool
    """
    arr = np.asarray(vector, dtype=np.float64).reshape(-1)
    if float(np.linalg.norm(arr)) < 1e-12:
        return False
    if np.any(arr < -1e-12):
        return False
    if probe_entropy(arr) > ambiguity_entropy_gate(arr.size):
        return True
    return is_multimodal(arr)


def _ask_probes(text: str) -> np.ndarray:
    """
    函数名: _ask_probes
    作用: 调用层注入的打分函数；此处不访问网络
    输入:
        text (str)
    输出:
        np.ndarray
    """
    if _probe_scorer is None:
        raise RuntimeError("调用层须先 set_probe_scorer")
    vector = np.asarray(_probe_scorer(text), dtype=np.float64).reshape(-1)
    _lock_dim(vector.size)
    return vector


def _cached_or_scored(text: str) -> np.ndarray:
    """
    函数名: _cached_or_scored
    作用: 可选读向量缓存，否则问注入的打分函数
    输入:
        text (str)
    输出:
        np.ndarray
    """
    if _persist_scores:
        cache = _load_cache()
        if text in cache:
            cached = np.array(cache[text], dtype=np.float64)
            _lock_dim(cached.size)
            return cached
    vector = _ask_probes(text)
    if _persist_scores:
        cache = _load_cache()
        cache[text] = [float(x) for x in vector]
        _save_cache()
    return vector


def _score_plain(text: str) -> np.ndarray:
    """
    函数名: _score_plain
    作用: 按释义打分，不走别名、不跑歧义门禁
    输入:
        text (str)
    输出:
        np.ndarray
    """
    return _ask_probes(text)


def meaning_needs_user(label: str, vector: np.ndarray) -> bool:
    """
    函数名: meaning_needs_user
    作用: 含义未定时必须问人；有注入函数用注入的，否则用向量几何
    输入:
        label (str)
        vector (np.ndarray)
    输出:
        bool
    """
    if _meaning_open_fn is not None:
        return bool(_meaning_open_fn(str(label), np.asarray(vector, dtype=np.float64)))
    return is_ambiguous_vector(vector)


def _clarify_label(label: str, vector: np.ndarray) -> np.ndarray:
    """
    函数名: _clarify_label
    作用: 挂起自动推导，用人类释义重建向量并写入别名缓存
    输入:
        label (str)
        vector (np.ndarray): 触发歧义的原始分布
    输出:
        np.ndarray
    """
    candidates = ambiguity_candidates(vector)
    if _clarifier is None:
        raise AmbiguousLabelError(label, vector, probe_entropy(vector), candidates)
    definition = str(_clarifier(label, candidates) or "").strip()
    if not definition:
        raise ValueError("澄清释义不能为空")
    resolved = _score_plain(definition)
    remember_alias(label, definition, resolved)
    if _persist_scores:
        cache = _load_cache()
        if label in cache:
            del cache[label]
            _save_cache()
    return resolved


def semantic_embedder(raw_text: str | None) -> np.ndarray:
    """
    函数名: semantic_embedder
    作用: 先查人类别名，再读向量缓存或问调用层打分；数据格不触发澄清
    输入:
        raw_text (str | None)
    输出:
        np.ndarray
    """
    text = "" if raw_text is None else str(raw_text).strip()
    if text == "" or text.lower() == "null":
        return ground_vector()
    alias = lookup_alias(text)
    if alias is not None:
        return np.array(alias["vector"], dtype=np.float64)
    return _cached_or_scored(text)


def embed_label(label: str) -> np.ndarray:
    """
    函数名: embed_label
    作用: Label 向量；含义未定则必须问人，不得自行猜
    输入:
        label (str)
    输出:
        np.ndarray
    """
    text = str(label or "").strip()
    if text == "" or text.lower() == "null":
        return ground_vector()
    alias = lookup_alias(text)
    if alias is not None:
        return np.array(alias["vector"], dtype=np.float64)
    vector = _cached_or_scored(text)
    if meaning_needs_user(text, vector):
        return _clarify_label(text, vector)
    return vector


def ensure_labels_resolved(labels: Sequence[str]) -> None:
    """
    函数名: ensure_labels_resolved
    作用: 每个 Label 先嵌入；含义未定则在此询问，不能带着歧义往下算
    输入:
        labels (Sequence[str])
    输出: 无
    """
    seen: set[str] = set()
    for name in labels:
        text = str(name or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        embed_label(text)


def operator_matrix(label: str) -> np.ndarray:
    """
    函数名: operator_matrix
    作用: 由 Label 意义向量构造 L
    输入:
        label (str)
    输出:
        np.ndarray
    """
    meaning = embed_label(label)
    n = int(meaning.size)
    _lock_dim(n)
    return np.diag(meaning) + 0.25 * np.eye(n)


def cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    """
    函数名: cosine_similarity
    作用: 探针空间余弦相似度；零向量为 0
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


def geometric_variance(vectors: Sequence[np.ndarray]) -> float:
    """
    函数名: geometric_variance
    作用: 探针空间几何方差 (1/N) Σ ||v_i - v̄||²
    输入:
        vectors (Sequence[np.ndarray])
    输出:
        float
    """
    items = [np.asarray(item, dtype=np.float64).reshape(-1) for item in vectors]
    if not items:
        return 0.0
    stacked = np.stack(items, axis=0)
    mean = stacked.mean(axis=0)
    return float(np.mean(np.sum((stacked - mean) ** 2, axis=1)))


def homomorphism_distance(L_src: np.ndarray, L_dst: np.ndarray) -> float:
    """
    函数名: homomorphism_distance
    作用: ||L_dst L_src^{-1} - I||_F，同态偏离
    输入:
        L_src (np.ndarray)
        L_dst (np.ndarray)
    输出:
        float
    """
    src = np.asarray(L_src, dtype=np.float64)
    dst = np.asarray(L_dst, dtype=np.float64)
    transported = dst @ np.linalg.inv(src)
    ident = np.eye(src.shape[0], dtype=np.float64)
    return float(np.linalg.norm(transported - ident, ord="fro"))


def gauge_transport_matrix(L_src: np.ndarray, L_dst: np.ndarray) -> np.ndarray:
    """
    函数名: gauge_transport_matrix
    作用: 规范平移 T = L_dst L_src^{-1}
    输入:
        L_src (np.ndarray)
        L_dst (np.ndarray)
    输出:
        np.ndarray
    """
    src = np.asarray(L_src, dtype=np.float64)
    dst = np.asarray(L_dst, dtype=np.float64)
    return dst @ np.linalg.inv(src)


@dataclass(frozen=True)
class MeaningPoint:
    """流形上的一点。"""

    raw: str
    vector: np.ndarray


    def as_dict(self) -> dict:
        """
        函数名: MeaningPoint.as_dict
        作用: 序列化
        输入: 无
        输出:
            dict
        """
        keyed = vector_to_key_map(self.vector)
        norm = float(np.linalg.norm(self.vector))
        peak = str(int(np.argmax(self.vector))) if norm > 1e-12 else ""
        return {
            "raw": self.raw,
            "vector": keyed,
            "weights": keyed,
            "peak": peak,
            "peak_score": float(np.max(self.vector)) if norm > 1e-12 else 0.0,
            "entropy": probe_entropy(self.vector),
            "is_ground": norm == 0.0,
            "is_ambiguous": is_ambiguous_vector(self.vector),
            "from_alias": lookup_alias(self.raw) is not None,
            "dim": space_dim(),
        }



def orbit_phrase(label: str, literal: str | None) -> str:
    """
    函数名: orbit_phrase
    作用: 纤维上的观测句；空值为 NULL of Label
    输入:
        label (str)
        literal (str | None)
    输出:
        str
    """
    text = "" if literal is None else str(literal).strip()
    if text == "" or text.lower() == "null":
        return f"NULL of {label}"
    return f"{text} of {label}"



class VectorLabelOperator:
    """列名算子：Label 定 L；纤维点是轨道句的模型向量。"""

    def __init__(self, label_name: str) -> None:
        """
        函数名: VectorLabelOperator.__init__
        作用: 按列名固定 L（列名只打分一次）
        输入:
            label_name (str)
        输出: 无
        """
        self.label_name = label_name
        self.L_matrix = operator_matrix(label_name)


    def __call__(self, raw_input_text: str | None) -> np.ndarray:
        """
        函数名: VectorLabelOperator.__call__
        作用: 轨道句的模型向量；空值为原点
        输入:
            raw_input_text (str | None)
        输出:
            np.ndarray
        """
        packed = self.instantiate(raw_input_text)
        return np.array(packed["state"], dtype=np.float64)


    def instantiate(self, raw_input_text: str | None) -> dict:
        """
        函数名: VectorLabelOperator.instantiate
        作用: 把字面编成「literal of Label」整句，用模型维数向量落在纤维上
        输入:
            raw_input_text (str | None): 单元格字面；空 / NULL 为纤维原点
        输出:
            dict: fiber / orbit / v_literal / state
        """
        raw = "" if raw_input_text is None else str(raw_input_text)
        stripped = raw.strip()
        empty = stripped == "" or stripped.lower() == "null"
        orbit = orbit_phrase(self.label_name, None if empty else stripped)
        if empty:
            state = ground_vector()
        else:
            state = semantic_embedder(orbit)
        return {
            "fiber": f"F_{self.label_name}",
            "base": self.label_name,
            "orbit": orbit,
            "literal": "" if empty else stripped,
            "v_literal": [float(x) for x in state],
            "state": [float(x) for x in state],
            "formula": "embed(orbit)",
            "projection": self.label_name,
            "ground": empty,
            "dim": space_dim(),
        }


def manifold_inner(left: np.ndarray, right: np.ndarray) -> dict:
    """
    函数名: manifold_inner
    作用: 两点内积；原点不是失败
    输入:
        left (np.ndarray)
        right (np.ndarray)
    输出:
        dict
    """
    n1 = float(np.linalg.norm(left))
    n2 = float(np.linalg.norm(right))
    if n1 == 0.0 or n2 == 0.0:
        return {"similarity": None, "either_ground": True, "inner": 0.0}
    inner = float(np.dot(left, right))
    return {"similarity": inner / (n1 * n2), "either_ground": False, "inner": inner}


def meaning_of_label(label: str) -> MeaningPoint:
    """
    函数名: meaning_of_label
    作用: 列名在意义空间中的点
    输入:
        label (str)
    输出:
        MeaningPoint
    """
    return MeaningPoint(raw=label, vector=embed_label(label))


def apply_label_operator(label: str, value: str) -> dict:
    """
    函数名: apply_label_operator
    作用: 任意列名纤维上的实例化环
    输入:
        label (str)
        value (str)
    输出:
        dict
    """
    return VectorLabelOperator(label).instantiate(value)
