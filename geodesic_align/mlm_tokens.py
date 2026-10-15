"""本地 BERT 掩码模型：CPU 前向，供文本列名编码。"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    offsets: list[tuple[int, int, int]] = field(default_factory=list)




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
        作用: 单句 CPU 前向，走 encode_batch
        输入:
            text (str): 句子
        输出:
            TokenBundle
        """
        return self.encode_batch([str(text)])[0]


    def encode_batch(self, texts: list[str]) -> list[TokenBundle]:
        """
        函数名: MaskedBert.encode_batch
        作用: 多句一次 CPU 前向；padding 用 attention mask 隔开，隐状态与单句前向对应
        输入:
            texts (list[str]): 句子列表
        输出:
            list[TokenBundle]: 与 texts 等长，offsets 是内容 token 的字符区间
        """
        packed = [str(text) for text in texts]
        if not packed:
            return []
        encoded = self.tokenizer(
            packed,
            return_tensors="pt",
            truncation=True,
            padding=True,
            max_length=MAX_LENGTH,
            add_special_tokens=True,
            return_offsets_mapping=True,
        )
        # offset_mapping 不是 BERT 的输入，先拿出来
        offset_mapping = encoded.pop("offset_mapping")
        batch = {key: value.to(DEVICE) for key, value in encoded.items()}
        with torch.inference_mode():
            outputs = self.model(**batch, output_hidden_states=True)
        hidden = outputs.hidden_states[-1].detach().cpu().numpy()
        special = set(self.tokenizer.all_special_tokens)
        bundles: list[TokenBundle] = []
        for idx in range(len(packed)):
            # 真实 token 长度，不含 padding
            length = int(batch["attention_mask"][idx].sum().item())
            row = np.asarray(hidden[idx, :length], dtype=np.float64)
            ids = [int(token_id) for token_id in batch["input_ids"][idx, :length].tolist()]
            tokens = self.tokenizer.convert_ids_to_tokens(ids)
            keep = [tok_i for tok_i, name in enumerate(tokens) if name not in special]
            pooled = row[keep].mean(axis=0) if keep else row[0].copy()
            raw_offsets = offset_mapping[idx]
            if hasattr(raw_offsets, "detach"):
                pairs = raw_offsets[:length].detach().cpu().tolist()
            else:
                pairs = list(raw_offsets)[:length]
            hits: list[tuple[int, int, int]] = []
            for tok_i, name in enumerate(tokens):
                if name in special:
                    continue
                start, stop = int(pairs[tok_i][0]), int(pairs[tok_i][1])
                if stop > start:
                    hits.append((tok_i, start, stop))
            bundles.append(TokenBundle(hidden=row, pooled=np.asarray(pooled, dtype=np.float64), offsets=hits))
        return bundles



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
