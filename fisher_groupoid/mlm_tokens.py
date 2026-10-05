"""本地 BERT 掩码模型：仅 CPU 前向，取出 token 张量与 log p(w|c)。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from huggingface_hub import snapshot_download
from transformers import AutoModelForMaskedLM, AutoTokenizer


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = PROJECT_ROOT / "MLM_models"
EN_MODEL_ID = "bert-large-cased"
UN_MODEL_ID = "bert-large-uncased"
ZH_MODEL_ID = "bert-base-chinese"
HUB_REPOS = {
    EN_MODEL_ID: "google-bert/bert-large-cased",
    UN_MODEL_ID: "google-bert/bert-large-uncased",
    ZH_MODEL_ID: "google-bert/bert-base-chinese",
}
WEIGHT_NAME = "model.safetensors"
IGNORE_WEIGHT_GLOBS = ("*.h5", "*.msgpack", "*.bin", "*.tar.gz")
DEVICE = torch.device("cpu")
MAX_LENGTH = 512
_CJK_LO = 0x4E00
_CJK_HI = 0x9FFF
_loaded: dict[str, "MaskedBert"] = {}


def uses_cjk(text: str) -> bool:
    """
    函数名: uses_cjk
    作用: 文本是否含汉字，用来选中文 BERT
    输入:
        text (str)
    输出:
        bool
    """
    for ch in str(text):
        if _CJK_LO <= ord(ch) <= _CJK_HI:
            return True
    return False


def pick_model_id(*texts: str) -> str:
    """
    函数名: pick_model_id
    作用: 任一段含汉字则用 bert-base-chinese，否则 bert-large-cased
    输入:
        texts (str): 待判语言的字符串
    输出:
        str: 本地目录名
    """
    for item in texts:
        if uses_cjk(item):
            return ZH_MODEL_ID
    return EN_MODEL_ID


def model_dir(model_id: str) -> Path:
    """
    函数名: model_dir
    作用: 本地权重目录
    输入:
        model_id (str): bert-large-cased、bert-large-uncased 或 bert-base-chinese
    输出:
        Path
    """
    name = str(model_id).strip()
    if name not in HUB_REPOS:
        raise ValueError(f"未知 MLM 模型 {name!r}，可选 {sorted(HUB_REPOS)}")
    return MODEL_ROOT / name


def weights_ready(model_id: str) -> bool:
    """
    函数名: weights_ready
    作用: 本地是否已有 safetensors 权重
    输入:
        model_id (str)
    输出:
        bool
    """
    path = model_dir(model_id) / WEIGHT_NAME
    return path.is_file()


def download_models(model_ids: tuple[str, ...] | None = None) -> dict[str, Path]:
    """
    函数名: download_models
    作用: 从 Hugging Face 拉 BERT 权重到 MLM_models，跳过 TF/Flax 副本
    输入:
        model_ids (tuple[str, ...] | None): 空则两个都下
    输出:
        dict[str, Path]: 模型名 -> 本地目录
    """
    wanted = tuple(model_ids) if model_ids else (EN_MODEL_ID, ZH_MODEL_ID)
    found: dict[str, Path] = {}
    for name in wanted:
        dest = model_dir(name)
        dest.mkdir(parents=True, exist_ok=True)
        snapshot_download(
            repo_id=HUB_REPOS[name],
            local_dir=str(dest),
            ignore_patterns=list(IGNORE_WEIGHT_GLOBS),
        )
        if not (dest / WEIGHT_NAME).is_file():
            raise FileNotFoundError(f"{dest} 缺少 {WEIGHT_NAME}")
        found[name] = dest
    return found


def _join_context_word(context: str, word: str, *, chinese: bool) -> str:
    """
    函数名: _join_context_word
    作用: 场景后接目标词；中文不加空格
    输入:
        context (str)
        word (str)
        chinese (bool)
    输出:
        str
    """
    ctx = str(context).rstrip()
    token = str(word).strip()
    if not token:
        raise ValueError("词不能为空")
    if not ctx:
        return token
    if chinese:
        return ctx + token
    return ctx + " " + token



@dataclass(frozen=True)
class TokenBundle:
    """一次前向得到的 token 序列及其隐状态。"""

    text: str
    model_id: str
    hidden_dim: int
    tokens: tuple[str, ...]
    input_ids: tuple[int, ...]
    hidden: np.ndarray
    pooled: np.ndarray
    cls: np.ndarray
    mask_index: int | None


    def token_rows(self) -> list[dict]:
        """
        函数名: TokenBundle.token_rows
        作用: 每个 token 一行，便于后续按位运算
        输入: 无
        输出:
            list[dict]
        """
        rows: list[dict] = []
        for idx, name in enumerate(self.tokens):
            rows.append(
                {
                    "index": idx,
                    "token": name,
                    "id": int(self.input_ids[idx]),
                    "vector": [float(x) for x in self.hidden[idx]],
                }
            )
        return rows



class MaskedBert:
    """一块本地 BERT MLM：始终在 CPU，不走 CUDA。"""

    def __init__(self, model_id: str) -> None:
        """
        函数名: MaskedBert.__init__
        作用: 从 MLM_models 载入分词器与掩码模型到 CPU
        输入:
            model_id (str)
        输出: 无
        """
        path = model_dir(model_id)
        weight = path / WEIGHT_NAME
        if not weight.is_file():
            raise FileNotFoundError(f"缺少本地权重 {weight}，先 download_models()")
        # 中文注释: 禁止 device_map，避免被调度到 GPU
        tokenizer = AutoTokenizer.from_pretrained(str(path), local_files_only=True)
        model = AutoModelForMaskedLM.from_pretrained(str(path), local_files_only=True)
        model.to(DEVICE)
        model.eval()
        model.config.output_hidden_states = True
        for param in model.parameters():
            param.requires_grad_(False)
        if next(model.parameters()).device.type != "cpu":
            raise RuntimeError("MLM 必须在 CPU 上加载")
        self.model_id = str(model_id)
        self.path = path
        self.tokenizer = tokenizer
        self.model = model
        self.hidden_dim = int(getattr(model.config, "hidden_size", 0))
        if self.hidden_dim < 1:
            raise RuntimeError(f"{self.model_id} 未给出 hidden_size")


    def encode(self, text: str) -> TokenBundle:
        """
        函数名: MaskedBert.encode
        作用: 整句分词后做 CPU 前向，返回各 token 隐向量
        输入:
            text (str)
        输出:
            TokenBundle
        """
        raw = str(text)
        encoded = self.tokenizer(
            raw,
            return_tensors="pt",
            truncation=True,
            max_length=MAX_LENGTH,
            add_special_tokens=True,
        )
        batch = {key: value.to(DEVICE) for key, value in encoded.items()}
        # 中文注释: 无梯度 CPU 前向，同时要 MLM logits 与最后一层隐状态
        with torch.inference_mode():
            outputs = self.model(**batch, output_hidden_states=True)
        states = outputs.hidden_states
        if not states:
            raise RuntimeError(f"{self.model_id} 未返回 hidden_states")
        hidden = states[-1].squeeze(0).detach().cpu().numpy().astype(np.float64, copy=True)
        ids = [int(x) for x in batch["input_ids"].squeeze(0).tolist()]
        tokens = tuple(self.tokenizer.convert_ids_to_tokens(ids))
        special = set(self.tokenizer.all_special_tokens)
        keep = [idx for idx, name in enumerate(tokens) if name not in special]
        if keep:
            pooled = hidden[keep].mean(axis=0)
        else:
            pooled = hidden[0].copy()
        mask_id = self.tokenizer.mask_token_id
        mask_index = None
        if mask_id is not None:
            for idx, tok_id in enumerate(ids):
                if tok_id == int(mask_id):
                    mask_index = idx
                    break
        return TokenBundle(
            text=raw,
            model_id=self.model_id,
            hidden_dim=int(hidden.shape[-1]),
            tokens=tokens,
            input_ids=tuple(ids),
            hidden=hidden,
            pooled=np.asarray(pooled, dtype=np.float64),
            cls=hidden[0].copy(),
            mask_index=mask_index,
        )


    def mask_hidden(self, template: str) -> np.ndarray:
        """
        函数名: MaskedBert.mask_hidden
        作用: 取 [MASK] 位置的上下文张量；模板必须含掩码
        输入:
            template (str): 含 tokenizer.mask_token 的句子
        输出:
            np.ndarray
        """
        bundle = self.encode(template)
        if bundle.mask_index is None:
            raise ValueError("模板里没有 [MASK]")
        return bundle.hidden[int(bundle.mask_index)].copy()


    def word_logprob(self, context: str, word: str) -> float:
        """
        函数名: MaskedBert.word_logprob
        作用: 伪对数似然：把词接在场景后，逐片掩码求 log p
        输入:
            context (str): 场景
            word (str): 目标词
        输出:
            float: 各 wordpiece log 概率之和
        """
        chinese = self.model_id == ZH_MODEL_ID
        _ = _join_context_word(context, word, chinese=chinese)
        word_ids = self.tokenizer(
            str(word).strip(),
            add_special_tokens=False,
            truncation=True,
            max_length=MAX_LENGTH - 2,
        )["input_ids"]
        ctx_ids = self.tokenizer(
            str(context).rstrip(),
            add_special_tokens=False,
            truncation=True,
            max_length=MAX_LENGTH - 2,
        )["input_ids"]
        word_ids = [int(x) for x in word_ids]
        ctx_ids = [int(x) for x in ctx_ids]
        if not word_ids:
            raise ValueError(f"词无法切成 token: {word!r}")
        budget = MAX_LENGTH - 2 - len(word_ids)
        if budget < 0:
            raise ValueError("词本身超过 BERT 窗口")
        if len(ctx_ids) > budget:
            ctx_ids = ctx_ids[-budget:]
        cls_id = int(self.tokenizer.cls_token_id)
        sep_id = int(self.tokenizer.sep_token_id)
        mask_id = int(self.tokenizer.mask_token_id)
        full = [cls_id] + ctx_ids + word_ids + [sep_id]
        start = 1 + len(ctx_ids)
        total = 0.0
        # 中文注释: 只掩码目标词的每一片，其余位置保持原 token
        for offset, tok_id in enumerate(word_ids):
            masked = list(full)
            pos = start + offset
            masked[pos] = mask_id
            batch = {
                "input_ids": torch.tensor([masked], dtype=torch.long, device=DEVICE),
                "attention_mask": torch.ones((1, len(masked)), dtype=torch.long, device=DEVICE),
            }
            with torch.inference_mode():
                logits = self.model(**batch).logits
            logp = torch.log_softmax(logits[0, pos], dim=-1)
            total += float(logp[int(tok_id)].item())
        return total


def load_masked_bert(model_id: str | None = None, *texts: str) -> MaskedBert:
    """
    函数名: load_masked_bert
    作用: 按语言取出已缓存的 CPU 模型；首次从磁盘加载
    输入:
        model_id (str | None): 指定模型；空则按 texts 判断
        texts (str): 用来选中英文的样例
    输出:
        MaskedBert
    """
    name = str(model_id) if model_id else pick_model_id(*texts)
    found = _loaded.get(name)
    if found is None:
        found = MaskedBert(name)
        _loaded[name] = found
    return found


def encode_text(text: str, *, model_id: str | None = None) -> TokenBundle:
    """
    函数名: encode_text
    作用: 对一段文本做掩码模型前向，得到 token 张量
    输入:
        text (str)
        model_id (str | None)
    输出:
        TokenBundle
    """
    engine = load_masked_bert(model_id, text)
    return engine.encode(text)


def pooled_vector(text: str, *, model_id: str | None = None) -> np.ndarray:
    """
    函数名: pooled_vector
    作用: 内容 token 隐状态均值，作为该字符串的一条张量
    输入:
        text (str)
        model_id (str | None)
    输出:
        np.ndarray
    """
    return encode_text(text, model_id=model_id).pooled


def mask_logprob(context: str, word: str, *, model_id: str | None = None) -> float:
    """
    函数名: mask_logprob
    作用: MLM 估计 log p(w|c)，供后续 Fisher 反演
    输入:
        context (str)
        word (str)
        model_id (str | None)
    输出:
        float
    """
    engine = load_masked_bert(model_id, context, word)
    return engine.word_logprob(context, word)


def label_token_matrix(
    labels: list[str] | tuple[str, ...],
    *,
    model_id: str | None = None,
) -> dict:
    """
    函数名: label_token_matrix
    作用: 把一组 Label 编成同空间张量矩阵，供后续线性运算
    输入:
        labels (list[str] | tuple[str, ...])
        model_id (str | None): 空则按全部 Label 的语言选择
    输出:
        dict: model / dim / labels / tokens / matrix
    """
    names = [str(item).strip() for item in labels if str(item).strip()]
    if not names:
        raise ValueError("没有 Label")
    engine = load_masked_bert(model_id, *names)
    rows: list[np.ndarray] = []
    tokens: dict[str, list[str]] = {}
    for name in names:
        bundle = engine.encode(name)
        rows.append(bundle.pooled)
        tokens[name] = [tok for tok in bundle.tokens if tok not in set(engine.tokenizer.all_special_tokens)]
    stacked = np.stack(rows, axis=0)
    return {
        "model": engine.model_id,
        "device": "cpu",
        "dim": int(stacked.shape[1]),
        "labels": names,
        "tokens": tokens,
        "matrix": stacked,
    }
