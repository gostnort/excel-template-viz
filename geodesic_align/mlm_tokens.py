"""本地 BERT 掩码模型：CPU 前向，供文本列名编码。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModelForMaskedLM, AutoTokenizer


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = PROJECT_ROOT / "MLM_models"
ZH_MODEL_ID = "bert-base-chinese"
EN_MODEL_ID = "bert-large-cased"
UN_MODEL_ID = "bert-large-uncased"
WEIGHT_NAME = "model.safetensors"
DEVICE = torch.device("cpu")
MAX_LENGTH = 512
_CJK_LO = 0x4E00
_CJK_HI = 0x9FFF
_loaded: dict[str, "MaskedBert"] = {}



@dataclass
class TokenBundle:
    """一次前向的 token 隐状态。"""

    hidden: np.ndarray
    pooled: np.ndarray




def uses_cjk(text: str) -> bool:
    """
    函数名: uses_cjk
    作用: 文本是否含汉字
    输入:
        text (str): 待测字符串
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
    作用: 全表没有汉字时用英文 uncased BERT，否则用中文 BERT
    输入:
        texts (str): 表内文本
    输出:
        str
    """
    # 统计全部文本里的汉字个数
    cjk_count = 0
    for block in texts:
        for ch in str(block):
            code = ord(ch)
            if _CJK_LO <= code <= _CJK_HI:
                cjk_count += 1
    # 得到汉字计数
    # 一个汉字都没有时走英文 uncased，否则走中文
    if cjk_count == 0:
        return UN_MODEL_ID
    # 得到 bert-large-uncased
    return ZH_MODEL_ID
    # 得到 bert-base-chinese



def weights_ready(model_id: str) -> bool:
    """
    函数名: weights_ready
    作用: 本地 safetensors 是否存在
    输入:
        model_id (str): 模型目录名
    输出:
        bool
    """
    return (MODEL_ROOT / str(model_id) / WEIGHT_NAME).is_file()



class MaskedBert:
    """CPU 上的掩码语言模型。"""

    def __init__(self, model_id: str) -> None:
        """
        函数名: MaskedBert.__init__
        作用: 从 MLM_models 载入分词器与模型到 CPU
        输入:
            model_id (str): 模型目录名
        输出: 无
        """
        path = MODEL_ROOT / str(model_id)
        tokenizer = AutoTokenizer.from_pretrained(str(path), local_files_only=True)
        model = AutoModelForMaskedLM.from_pretrained(str(path), local_files_only=True)
        model.to(DEVICE)
        model.eval()
        for param in model.parameters():
            param.requires_grad_(False)
        self.model_id = str(model_id)
        self.tokenizer = tokenizer
        self.model = model



    def encode(self, text: str) -> TokenBundle:
        """
        函数名: MaskedBert.encode
        作用: 整句 CPU 前向，返回隐状态与内容 token 均值
        输入:
            text (str): 句子
        输出:
            TokenBundle
        """
        encoded = self.tokenizer(
            str(text),
            return_tensors="pt",
            truncation=True,
            max_length=MAX_LENGTH,
            add_special_tokens=True,
        )
        batch = {key: value.to(DEVICE) for key, value in encoded.items()}
        with torch.inference_mode():
            outputs = self.model(**batch, output_hidden_states=True)
        hidden = outputs.hidden_states[-1].squeeze(0).detach().cpu().numpy().astype(np.float64, copy=True)
        ids = [int(x) for x in batch["input_ids"].squeeze(0).tolist()]
        tokens = self.tokenizer.convert_ids_to_tokens(ids)
        special = set(self.tokenizer.all_special_tokens)
        keep = [idx for idx, name in enumerate(tokens) if name not in special]
        pooled = hidden[keep].mean(axis=0) if keep else hidden[0].copy()
        return TokenBundle(hidden=hidden, pooled=np.asarray(pooled, dtype=np.float64))



    def content_offsets(self, sentence: str) -> list[tuple[int, int, int]]:
        """
        函数名: MaskedBert.content_offsets
        作用: 内容 token 的下标与字符起止
        输入:
            sentence (str): 与 encode 相同的句子
        输出:
            list[tuple[int, int, int]]
        """
        encoded = self.tokenizer(
            sentence,
            return_offsets_mapping=True,
            truncation=True,
            max_length=MAX_LENGTH,
            add_special_tokens=True,
        )
        offsets = list(encoded["offset_mapping"])
        ids = [int(x) for x in encoded["input_ids"]]
        tokens = self.tokenizer.convert_ids_to_tokens(ids)
        special = set(self.tokenizer.all_special_tokens)
        hits: list[tuple[int, int, int]] = []
        for idx, name in enumerate(tokens):
            if name in special:
                continue
            start, stop = int(offsets[idx][0]), int(offsets[idx][1])
            if stop > start:
                hits.append((idx, start, stop))
        return hits



def load_masked_bert(model_id: str) -> MaskedBert:
    """
    函数名: load_masked_bert
    作用: 取出已缓存的 CPU 模型
    输入:
        model_id (str): 模型目录名
    输出:
        MaskedBert
    """
    found = _loaded.get(model_id)
    if found is None:
        found = MaskedBert(model_id)
        _loaded[model_id] = found
    return found
