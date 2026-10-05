"""一行事件句：LLM 串句与 MLM 打分同对象保存，供日后对比。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np

from fisher_groupoid.manifold import FisherManifold, UsageGroupoid
from fisher_groupoid.mlm_invert import invert_labels_mlm
from fisher_groupoid.mlm_tokens import (
    encode_text,
    load_masked_bert,
    mask_logprob,
    pick_model_id,
    pooled_vector,
    uses_cjk,
)
from llm_lmstudio.chat import chat_text
from llm_lmstudio.client import LmStudioError
from llm_lmstudio.models import list_models


PERSON_PROBE = "有年龄和收入的自然人"
PLACE_PROBE = "城市地名"
WEATHER_DISTRACTOR = "今晚天气预报"
DEFAULT_LM_MODEL = "gemma-4-e4b-it"
VERBALIZE_SYSTEM = (
    "把一行表格写成一句通顺中文陈述句。"
    "用数据本身的含义说话，不要解释列名，不要列清单。"
    "只输出那一句话。"
)
_probe_cache: dict[tuple[str, str], np.ndarray] = {}



def _floats(vector: np.ndarray) -> list[float]:
    """
    函数名: _floats
    作用: 把向量写成 JSON 可用的浮点列表
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



def short_pair_sentence(label: str, value: str) -> str:
    """
    函数名: short_pair_sentence
    作用: 单列表头加字面，短到欠定，如 姓名张三
    输入:
        label (str): 表头
        value (str): 单元格
    输出:
        str
    """
    name = str(label).strip()
    text = str(value).strip()
    if uses_cjk(name) or uses_cjk(text):
        return f"{name}{text}"
    return f"{name} {text}"



def glue_event_sentence(values: dict[str, str]) -> str:
    """
    函数名: glue_event_sentence
    作用: 把一行所有列用顿号拼成一句，不含 LLM 释义
    输入:
        values (dict[str, str]): 表头 -> 字面
    输出:
        str
    """
    parts: list[str] = []
    for label, value in values.items():
        if not str(label).strip() or not str(value).strip():
            continue
        parts.append(short_pair_sentence(label, value))
    return "，".join(parts)



def values_only_text(values: dict[str, str]) -> str:
    """
    函数名: values_only_text
    作用: 只保留单元格字面，供 log p(表头|值) 使用
    输入:
        values (dict[str, str])
    输出:
        str
    """
    parts: list[str] = []
    for value in values.values():
        text = str(value).strip()
        if text:
            parts.append(text)
    return "，".join(parts)



def lm_studio_reachable() -> bool:
    """
    函数名: lm_studio_reachable
    作用: LM Studio 能否列出模型
    输入: 无
    输出:
        bool
    """
    try:
        list_models(refresh=True)
    except LmStudioError:
        return False
    return True



def verbalize_row_llm(
    values: dict[str, str],
    *,
    model: str | None = None,
) -> "LlmReturn":
    """
    函数名: verbalize_row_llm
    作用: 让 LM Studio 把一行串成一句陈述句
    输入:
        values (dict[str, str]): 表头 -> 字面
        model (str | None): 空则 gemma-4-e4b-it
    输出:
        LlmReturn
    """
    key = str(model or DEFAULT_LM_MODEL).strip()
    cells = "；".join(f"{label}={value}" for label, value in values.items())
    prompt = f"表格一行：{cells}"
    try:
        packed = chat_text(
            prompt,
            model=key,
            system_prompt=VERBALIZE_SYSTEM,
            temperature=0.0,
            max_output_tokens=120,
            thinking=False,
            store=False,
        )
    except LmStudioError as exc:
        return LlmReturn(model=key, prompt=prompt, text="", error=str(exc))
    text = str(packed.get("text") or "").strip()
    thought = packed.get("thought")
    response_id = packed.get("response_id")
    return LlmReturn(
        model=key,
        prompt=prompt,
        text=text,
        thought=str(thought) if thought else "",
        response_id=str(response_id) if response_id else "",
        error="",
    )



def _probe_vector(text: str, model_id: str) -> np.ndarray:
    """
    函数名: _probe_vector
    作用: 缓存类型探针的句向量
    输入:
        text (str)
        model_id (str)
    输出:
        np.ndarray
    """
    key = (str(model_id), str(text))
    found = _probe_cache.get(key)
    if found is None:
        found = pooled_vector(text, model_id=model_id)
        _probe_cache[key] = found
    return found



def _mean_hidden_for_word(text: str, word: str, *, model_id: str) -> np.ndarray | None:
    """
    函数名: _mean_hidden_for_word
    作用: 句子里对应表层词的 token 隐状态均值；找不到则 None
    输入:
        text (str): 整句
        word (str): 表头或字面
        model_id (str)
    输出:
        np.ndarray | None
    """
    token = str(word).strip()
    if not token:
        return None
    engine = load_masked_bert(model_id, text, token)
    piece_ids = [int(x) for x in engine.tokenizer(token, add_special_tokens=False)["input_ids"]]
    if not piece_ids:
        return None
    bundle = encode_text(text, model_id=model_id)
    ids = list(bundle.input_ids)
    width = len(piece_ids)
    start = None
    for idx in range(0, len(ids) - width + 1):
        if ids[idx : idx + width] == piece_ids:
            start = idx
            break
    if start is None:
        return None
    rows = bundle.hidden[start : start + width]
    return np.mean(rows, axis=0)



def _leave_one_out_deltas(text: str, values: dict[str, str], *, model_id: str) -> dict[str, float]:
    """
    函数名: _leave_one_out_deltas
    作用: 从句中拿掉某一列的字面后，句向量位移
    输入:
        text (str)
        values (dict[str, str])
        model_id (str)
    输出:
        dict[str, float]
    """
    full = pooled_vector(text, model_id=model_id)
    out: dict[str, float] = {}
    for label, value in values.items():
        stripped = str(text)
        literal = str(value).strip()
        name = str(label).strip()
        if literal and literal in stripped:
            stripped = stripped.replace(literal, "", 1)
        elif name and name in stripped:
            stripped = stripped.replace(name, "", 1)
        if stripped.strip() == str(text).strip():
            out[name] = 0.0
            continue
        other = pooled_vector(stripped, model_id=model_id)
        out[name] = float(np.linalg.norm(full - other))
    return out



def score_sentence_mlm(
    text: str,
    values: dict[str, str],
    *,
    model_id: str | None = None,
    value_context: str = "",
) -> "MlmReturn":
    """
    函数名: score_sentence_mlm
    作用: 对一句事件句做 MLM 句向量、表头上下文、类型余弦与条件对数概率
    输入:
        text (str): 待打分句子
        values (dict[str, str]): 该行表头与字面
        model_id (str | None)
        value_context (str): 不含表头的值侧上下文；空则用 values_only_text
    输出:
        MlmReturn
    """
    sentence = str(text or "").strip()
    headers = [str(name).strip() for name in values.keys() if str(name).strip()]
    name = model_id or pick_model_id(sentence, *headers, *values.values())
    if not sentence:
        dim = int(load_masked_bert(name).hidden_dim)
        return MlmReturn(model=name, dim=dim)
    sent_vec = pooled_vector(sentence, model_id=name)
    person_vec = _probe_vector(PERSON_PROBE, name)
    place_vec = _probe_vector(PLACE_PROBE, name)
    ctx = str(value_context).strip() or values_only_text(values)
    lexical: dict[str, list[float]] = {}
    contextual: dict[str, list[float]] = {}
    logprobs: dict[str, float] = {}
    for header in headers:
        lex = pooled_vector(header, model_id=name)
        lexical[header] = _floats(lex)
        hidden = _mean_hidden_for_word(sentence, header, model_id=name)
        if hidden is not None:
            contextual[header] = _floats(hidden)
        logprobs[header] = float(mask_logprob(ctx, header, model_id=name))
    return MlmReturn(
        model=name,
        dim=int(sent_vec.size),
        sentence_vector=_floats(sent_vec),
        lexical=lexical,
        contextual=contextual,
        person_cosine=_cosine(sent_vec, person_vec),
        place_cosine=_cosine(sent_vec, place_vec),
        header_logprob=logprobs,
        leave_one_out=_leave_one_out_deltas(sentence, values, model_id=name),
    )



def _manifold_payload(item: FisherManifold) -> dict:
    """
    函数名: _manifold_payload
    作用: 把一个用法流形收成可对比的字典
    输入:
        item (FisherManifold)
    输出:
        dict
    """
    return {
        "word": item.word,
        "posterior": [float(x) for x in item.posterior()],
        "log_like": [float(x) for x in item.log_like],
        "entropy": item.fisher_entropy(),
        "n_eff": item.n_eff(),
        "check": item.manifold_check(),
    }



def score_header_usage(
    labels: tuple[str, ...],
    scenarios: tuple[str, ...],
    *,
    model_id: str | None = None,
) -> dict:
    """
    函数名: score_header_usage
    作用: 共享场景池上对表头与对照词做 MLM 用法反演
    输入:
        labels (tuple[str, ...]): 含表头与对照词
        scenarios (tuple[str, ...]): 短值、完整事件、干扰场景
        model_id (str | None)
    输出:
        dict
    """
    groupoid: UsageGroupoid = invert_labels_mlm(labels, scenarios, model_id=model_id)
    return {
        "model": model_id or pick_model_id(*labels, *scenarios),
        "scenarios": list(scenarios),
        "labels": list(labels),
        "objects": [_manifold_payload(item) for item in groupoid.objects],
        "arrows": groupoid.arrows(),
    }



@dataclass(frozen=True)
class LlmReturn:
    """一次 LM Studio 串句的返回。"""

    model: str
    prompt: str
    text: str
    thought: str = ""
    response_id: str = ""
    error: str = ""


    def as_dict(self) -> dict:
        """
        函数名: LlmReturn.as_dict
        作用: 序列化 LLM 返回，不含原始 HTTP 体
        输入: 无
        输出:
            dict
        """
        return {
            "model": self.model,
            "prompt": self.prompt,
            "text": self.text,
            "thought": self.thought,
            "response_id": self.response_id,
            "error": self.error,
            "ok": bool(self.text) and not self.error,
        }



@dataclass(frozen=True)
class MlmReturn:
    """一次本地 BERT 打分的返回。"""

    model: str
    dim: int
    sentence_vector: list[float] = field(default_factory=list)
    lexical: dict[str, list[float]] = field(default_factory=dict)
    contextual: dict[str, list[float]] = field(default_factory=dict)
    person_cosine: float = 0.0
    place_cosine: float = 0.0
    header_logprob: dict[str, float] = field(default_factory=dict)
    leave_one_out: dict[str, float] = field(default_factory=dict)


    def person_place_margin(self) -> float:
        """
        函数名: MlmReturn.person_place_margin
        作用: 整句更靠近自然人探针还是地名探针
        输入: 无
        输出:
            float: person_cosine - place_cosine
        """
        return float(self.person_cosine) - float(self.place_cosine)


    def lexical_full_cosine(self, header: str) -> float:
        """
        函数名: MlmReturn.lexical_full_cosine
        作用: 表头词典向量与整句向量的余弦；用来对照「直译列名」
        输入:
            header (str)
        输出:
            float
        """
        lex = self.lexical.get(str(header))
        if not lex or not self.sentence_vector:
            return 0.0
        return _cosine(np.array(lex, dtype=np.float64), np.array(self.sentence_vector, dtype=np.float64))


    def as_dict(self) -> dict:
        """
        函数名: MlmReturn.as_dict
        作用: 序列化 MLM 返回
        输入: 无
        输出:
            dict
        """
        return {
            "model": self.model,
            "dim": self.dim,
            "sentence_vector": list(self.sentence_vector),
            "lexical": {key: list(val) for key, val in self.lexical.items()},
            "contextual": {key: list(val) for key, val in self.contextual.items()},
            "person_cosine": float(self.person_cosine),
            "place_cosine": float(self.place_cosine),
            "person_place_margin": self.person_place_margin(),
            "header_logprob": {key: float(val) for key, val in self.header_logprob.items()},
            "leave_one_out": {key: float(val) for key, val in self.leave_one_out.items()},
        }



@dataclass(frozen=True)
class ScoredSentence:
    """一句事件话：来源、LLM 迹、MLM 迹。"""

    text: str
    source: str
    llm: LlmReturn | None = None
    mlm: MlmReturn | None = None


    def as_dict(self) -> dict:
        """
        函数名: ScoredSentence.as_dict
        作用: 一句上同时带 LLM 与 MLM 字段，缺的为 null
        输入: 无
        输出:
            dict
        """
        return {
            "text": self.text,
            "source": self.source,
            "llm": None if self.llm is None else self.llm.as_dict(),
            "mlm": None if self.mlm is None else self.mlm.as_dict(),
        }



@dataclass(frozen=True)
class EventUtterance:
    """一行 = 一件事；短句、胶合句、见证句、LLM 句都挂在同一对象上。"""

    object_id: str
    values: dict[str, str]
    short_pairs: dict[str, ScoredSentence]
    glue: ScoredSentence
    witness: ScoredSentence | None = None
    llm_sentence: ScoredSentence | None = None
    usage: dict | None = None


    def as_dict(self) -> dict:
        """
        函数名: EventUtterance.as_dict
        作用: 整行事件句档案，便于 LLM/MLM 日后对比
        输入: 无
        输出:
            dict
        """
        return {
            "object_id": self.object_id,
            "values": dict(self.values),
            "short_pairs": {key: item.as_dict() for key, item in self.short_pairs.items()},
            "glue": self.glue.as_dict(),
            "witness": None if self.witness is None else self.witness.as_dict(),
            "llm": None if self.llm_sentence is None else self.llm_sentence.as_dict(),
            "usage": self.usage,
        }



def build_event_utterance(
    object_id: str,
    values: dict[str, str],
    *,
    witness: str = "",
    ask_llm: bool = False,
    score_mlm: bool = True,
    lm_model: str | None = None,
    contrast_label: str = "地名",
) -> EventUtterance:
    """
    函数名: build_event_utterance
    作用: 构造一行事件句对象；可选问 LLM，可选用本地 MLM 打分
    输入:
        object_id (str): 行对象名
        values (dict[str, str]): 表头 -> 字面
        witness (str): 人工见证的完整事件句，可空
        ask_llm (bool): 是否调用 LM Studio 串句
        score_mlm (bool): 是否用 MLM_models 打分
        lm_model (str | None)
        contrast_label (str): 用法反演的对照词
    输出:
        EventUtterance
    """
    cells = {str(key).strip(): str(val).strip() for key, val in values.items() if str(key).strip()}
    shorts = {
        label: ScoredSentence(text=short_pair_sentence(label, literal), source="short")
        for label, literal in cells.items()
    }
    glue = ScoredSentence(text=glue_event_sentence(cells), source="glue")
    witness_s = None
    if str(witness).strip():
        witness_s = ScoredSentence(text=str(witness).strip(), source="witness")
    llm_s = None
    if ask_llm:
        trace = verbalize_row_llm(cells, model=lm_model)
        llm_s = ScoredSentence(text=trace.text, source="llm", llm=trace)
    model_id = None
    if score_mlm:
        blobs = [glue.text, *cells.keys(), *cells.values()]
        if witness_s is not None:
            blobs.append(witness_s.text)
        if llm_s is not None and llm_s.text:
            blobs.append(llm_s.text)
        model_id = pick_model_id(*blobs)
        name_value = cells.get("姓名", next(iter(cells.values())))
        short_ctx = str(name_value)
        full_ctx = witness_s.text if witness_s is not None else values_only_text(cells)
        scored_shorts: dict[str, ScoredSentence] = {}
        for label, sent in shorts.items():
            one_ctx = cells.get(label, short_ctx)
            scored_shorts[label] = replace(
                sent,
                mlm=score_sentence_mlm(sent.text, cells, model_id=model_id, value_context=one_ctx),
            )
        shorts = scored_shorts
        glue = replace(
            glue,
            mlm=score_sentence_mlm(glue.text, cells, model_id=model_id, value_context=values_only_text(cells)),
        )
        if witness_s is not None:
            witness_s = replace(
                witness_s,
                mlm=score_sentence_mlm(witness_s.text, cells, model_id=model_id, value_context=full_ctx),
            )
        if llm_s is not None and llm_s.text:
            llm_s = replace(
                llm_s,
                mlm=score_sentence_mlm(llm_s.text, cells, model_id=model_id, value_context=llm_s.text),
            )
        first_header = next(iter(cells.keys()))
        usage = score_header_usage(
            (first_header, str(contrast_label)),
            (short_ctx, full_ctx, WEATHER_DISTRACTOR),
            model_id=model_id,
        )
        return EventUtterance(
            object_id=str(object_id),
            values=cells,
            short_pairs=shorts,
            glue=glue,
            witness=witness_s,
            llm_sentence=llm_s,
            usage=usage,
        )
    return EventUtterance(
        object_id=str(object_id),
        values=cells,
        short_pairs=shorts,
        glue=glue,
        witness=witness_s,
        llm_sentence=llm_s,
        usage=None,
    )
