"""Fisher 流形：一个词的用法测度。GOP 的对象是这类流形，不是箱子。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def _word_pieces(text: str) -> list[str]:
    """
    函数名: _word_pieces
    作用: 把字符串切成小写字母数字块，供场景重叠与续写对齐
    输入:
        text (str)
    输出:
        list[str]
    """
    buf: list[str] = []
    piece: list[str] = []
    for ch in str(text):
        if ch.isalnum():
            piece.append(ch.lower())
            continue
        if piece:
            buf.append("".join(piece))
            piece = []
    if piece:
        buf.append("".join(piece))
    return buf


def generated_hits_word(text: str, word: str) -> bool:
    """
    函数名: generated_hits_word
    作用: 续写是否以该词的 token 块开头（估计 p(w|c) 的命中）
    输入:
        text (str): 模型续写
        word (str): 被反演的词
    输出:
        bool
    """
    got = _word_pieces(text)
    want = _word_pieces(word)
    if not want:
        return False
    return got[: len(want)] == want


def jaccard(left: str, right: str) -> float:
    """
    函数名: jaccard
    作用: 两段场景文本的 token Jaccard
    输入:
        left (str)
        right (str)
    输出:
        float
    """
    a = set(_word_pieces(left))
    b = set(_word_pieces(right))
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return float(len(a & b) / len(a | b))



@dataclass(frozen=True)
class FisherManifold:
    """一个词 = 其用法场景上的概率测度（有限单纯形上的 Fisher 流形）。"""

    word: str
    scenarios: tuple[str, ...]
    log_like: tuple[float, ...]


    def posterior(self) -> np.ndarray:
        """
        函数名: FisherManifold.posterior
        作用: 在共享场景池上做 p(c|w)∝p(w|c)p(c)；p(c) 已由采样给出故只对似然归一
        输入: 无
        输出:
            np.ndarray: 单纯形上的后验
        """
        logp = np.asarray(self.log_like, dtype=np.float64).reshape(-1)
        if logp.size == 0:
            return np.zeros(0, dtype=np.float64)
        shifted = logp - float(np.max(logp))
        mass = np.exp(shifted)
        total = float(np.sum(mass))
        if total <= 0.0:
            return np.ones(logp.size, dtype=np.float64) / float(logp.size)
        return mass / total


    def sqrt_map(self) -> np.ndarray:
        """
        函数名: FisherManifold.sqrt_map
        作用: 单纯形到球面的平方根映射 √p，Fisher–Rao 与球面度量对应
        输入: 无
        输出:
            np.ndarray
        """
        return np.sqrt(np.clip(self.posterior(), 0.0, 1.0))


    def fisher_entropy(self) -> float:
        """
        函数名: FisherManifold.fisher_entropy
        作用: 后验的香农熵；峰越尖测度越稳
        输入: 无
        输出:
            float
        """
        probs = np.clip(self.posterior(), 1e-12, 1.0)
        return float(-np.sum(probs * np.log(probs)))


    def n_eff(self) -> float:
        """
        函数名: FisherManifold.n_eff
        作用: 有效场景数 1/Σp²
        输入: 无
        输出:
            float
        """
        probs = self.posterior()
        denom = float(np.sum(probs * probs))
        if denom <= 0.0:
            return 0.0
        return 1.0 / denom


    def hellinger(self, other: "FisherManifold") -> float:
        """
        函数名: FisherManifold.hellinger
        作用: 两词用法后验的 Hellinger 距离（与 Fisher–Rao 同型）
        输入:
            other (FisherManifold): 同一场景池上的另一词
        输出:
            float
        """
        if self.scenarios != other.scenarios:
            raise ValueError("Hellinger 只在同一场景池上有定义")
        gap = self.sqrt_map() - other.sqrt_map()
        return float(np.linalg.norm(gap) / np.sqrt(2.0))


    def overlap(self, other: "FisherManifold") -> float:
        """
        函数名: FisherManifold.overlap
        作用: 两后验的逐点 min 之和，群胚箭头的质量
        输入:
            other (FisherManifold)
        输出:
            float
        """
        if self.scenarios != other.scenarios:
            raise ValueError("重叠只在同一场景池上有定义")
        return float(np.sum(np.minimum(self.posterior(), other.posterior())))


    def modes(self, *, jaccard_min: float = 0.25, mass_floor: float = 0.05) -> list[dict]:
        """
        函数名: FisherManifold.modes
        作用: 不预设类数；按后验质量贪心，Jaccard 不够近则新开一块用法
        输入:
            jaccard_min (float): 并入已有峰的下限
            mass_floor (float): 忽略更小的质量
        输出:
            list[dict]: 峰的中心场景与质量
        """
        probs = self.posterior()
        order = np.argsort(-probs)
        peaks: list[dict] = []
        for idx in order:
            mass = float(probs[int(idx)])
            if mass < mass_floor:
                continue
            text = self.scenarios[int(idx)]
            placed = False
            for peak in peaks:
                if jaccard(text, str(peak["center"])) >= jaccard_min:
                    peak["mass"] = float(peak["mass"]) + mass
                    peak["members"] = int(peak["members"]) + 1
                    placed = True
                    break
            if placed:
                continue
            peaks.append({"center": text, "mass": mass, "members": 1})
        peaks.sort(key=lambda item: float(item["mass"]), reverse=True)
        return peaks


    def manifold_check(self) -> dict:
        """
        函数名: FisherManifold.manifold_check
        作用: 检验后验是否能当 Fisher 流形上的点（概率、球面、峰是否稳）
        输入: 无
        输出:
            dict
        """
        probs = self.posterior()
        sphere = self.sqrt_map()
        n = int(probs.size)
        entropy = self.fisher_entropy()
        n_eff = self.n_eff()
        peaks = self.modes()
        max_p = float(np.max(probs)) if n else 0.0
        on_simplex = n > 0 and abs(float(np.sum(probs)) - 1.0) < 1e-8 and bool(np.all(probs >= -1e-12))
        on_sphere = n > 0 and abs(float(np.linalg.norm(sphere)) - 1.0) < 1e-8
        stable = n > 0 and (n_eff <= max(2.0, 0.45 * n) or max_p >= 0.35)
        opened = len(peaks) >= 2 and float(peaks[0]["mass"]) < 0.8
        return {
            "word": self.word,
            "n_scenarios": n,
            "on_simplex": on_simplex,
            "sqrt_on_sphere": on_sphere,
            "entropy": entropy,
            "n_eff": n_eff,
            "n_modes": len(peaks),
            "modes": peaks[:8],
            "stable_measure": stable,
            "usage_open": opened,
            "max_posterior": max_p,
            "meets_fisher_object": on_simplex and on_sphere,
        }



@dataclass(frozen=True)
class UsageGroupoid:
    """GOP：对象是 Fisher 流形，箭头是用法重叠上的可逆转移。"""

    objects: tuple[FisherManifold, ...]
    overlap_floor: float = 0.08


    def arrows(self) -> list[dict]:
        """
        函数名: UsageGroupoid.arrows
        作用: 重叠超过门限则记一条可逆箭头；Hom 空即群破缺候选
        输入: 无
        输出:
            list[dict]
        """
        items: list[dict] = []
        for i, left in enumerate(self.objects):
            for j, right in enumerate(self.objects):
                if j <= i:
                    continue
                mass = left.overlap(right)
                dist = left.hellinger(right)
                items.append(
                    {
                        "src": left.word,
                        "dst": right.word,
                        "overlap": mass,
                        "hellinger": dist,
                        "arrow": mass >= self.overlap_floor,
                    }
                )
        return items


    def report(self) -> dict:
        """
        函数名: UsageGroupoid.report
        作用: 各词流形检验与群胚箭头
        输入: 无
        输出:
            dict
        """
        return {
            "kind": "groupoid_of_fisher_manifolds",
            "objects": [item.manifold_check() for item in self.objects],
            "arrows": self.arrows(),
        }
