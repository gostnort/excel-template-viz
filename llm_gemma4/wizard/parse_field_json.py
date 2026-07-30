"""从模型 answer 文本抽取单个 JSON 对象。"""

from __future__ import annotations

from dataclasses import dataclass

from llm_gemma4.runtime.json_extract import extract_json_object



@dataclass(frozen=True)
class ParseFieldError:
    """JSON 解析失败时的错误载体。"""
    message: str
    raw_text: str



def parse_field_json(text: str) -> dict | ParseFieldError:
    """
    函数名: parse_field_json
    作用: 从模型回答中抽取一个 JSON 对象（容忍 markdown 围栏与前后废话）
    输入:
        text (str): 模型 answer 原文
    输出:
        dict | ParseFieldError: 成功返回 dict，失败返回 ParseFieldError
    """
    payload, err = extract_json_object(text)
    if err is not None:
        return ParseFieldError(message=err, raw_text=text)
    return payload
