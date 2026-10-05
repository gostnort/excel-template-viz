"""用 BERT MLM 的 log p(w|c) 做用法反演；不走聊天续写也不走嵌入余弦。"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path

from fisher_groupoid.manifold import FisherManifold, UsageGroupoid
from fisher_groupoid.mlm_tokens import (
    EN_MODEL_ID,
    label_token_matrix,
    load_masked_bert,
    mask_logprob,
    pick_model_id,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = PROJECT_ROOT / "plans" / "usage_mlm_inversion_out.json"
DEFAULT_LABELS = ("ID", "name", "gender", "dob")
DEFAULT_SCENARIOS = (
    "personnel roster of people",
    "calendar birth record",
    "weather forecast tonight",
    "python def power",
)


def invert_word_mlm(
    word: str,
    scenarios: Sequence[str],
    *,
    model_id: str | None = None,
    log: Callable[[str], None] | None = None,
) -> FisherManifold:
    """
    函数名: invert_word_mlm
    作用: 在共享场景池上用 MLM 的 log p(w|c) 收成 Fisher 流形
    输入:
        word (str)
        scenarios (Sequence[str])
        model_id (str | None)
        log (Callable | None)
    输出:
        FisherManifold
    """
    talk = log or (lambda _msg: None)
    texts = tuple(str(item) for item in scenarios)
    token = str(word).strip()
    if not token:
        raise ValueError("词不能为空")
    if not texts:
        raise ValueError("场景池不能为空")
    name = model_id or pick_model_id(token, *texts)
    load_masked_bert(name)
    scores: list[float] = []
    for context in texts:
        score = mask_logprob(context, token, model_id=name)
        scores.append(score)
        talk(f"mlm logp({token!r}|c)={score:.3f} c={context[:60]!r}")
    return FisherManifold(word=token, scenarios=texts, log_like=tuple(scores))


def invert_labels_mlm(
    labels: Sequence[str],
    scenarios: Sequence[str],
    *,
    model_id: str | None = None,
    log: Callable[[str], None] | None = None,
) -> UsageGroupoid:
    """
    函数名: invert_labels_mlm
    作用: 共享场景池上对每个 label 做 MLM 反演，再组成用法群胚
    输入:
        labels (Sequence[str])
        scenarios (Sequence[str])
        model_id (str | None)
        log (Callable | None)
    输出:
        UsageGroupoid
    """
    talk = log or (lambda _msg: None)
    names = [str(item).strip() for item in labels if str(item).strip()]
    texts = [str(item) for item in scenarios if str(item).strip()]
    if not names:
        raise ValueError("没有 Label")
    if not texts:
        raise ValueError("场景池不能为空")
    name = model_id or pick_model_id(*names, *texts)
    talk(f"mlm_model={name} device=cpu n_labels={len(names)} n_scenarios={len(texts)}")
    load_masked_bert(name)
    manifolds = [invert_word_mlm(word, texts, model_id=name, log=talk) for word in names]
    return UsageGroupoid(objects=tuple(manifolds))


def run_mlm_probe(
    *,
    labels: Sequence[str] = DEFAULT_LABELS,
    scenarios: Sequence[str] = DEFAULT_SCENARIOS,
    model_id: str | None = EN_MODEL_ID,
    out_path: Path | None = None,
) -> Path:
    """
    函数名: run_mlm_probe
    作用: CPU 上跑 MLM 反演，并写出 token 张量与群胚 JSON
    输入:
        labels (Sequence[str])
        scenarios (Sequence[str])
        model_id (str | None)
        out_path (Path | None)
    输出:
        Path
    """
    path = out_path or DEFAULT_OUT
    packed = label_token_matrix(tuple(labels), model_id=model_id)
    groupoid = invert_labels_mlm(labels, scenarios, model_id=packed["model"], log=print)
    payload = {
        "model": packed["model"],
        "device": "cpu",
        "scoring": "bert_mlm_pseudo_loglikelihood",
        "dim": packed["dim"],
        "tokens": packed["tokens"],
        "label_vectors": {
            name: [float(x) for x in packed["matrix"][idx]]
            for idx, name in enumerate(packed["labels"])
        },
        "groupoid": groupoid.report(),
        "scenarios": list(groupoid.objects[0].scenarios) if groupoid.objects else [],
        "posteriors": {
            item.word: [float(x) for x in item.posterior()]
            for item in groupoid.objects
        },
        "log_likes": {
            item.word: [float(x) for x in item.log_like]
            for item in groupoid.objects
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(path))
    return path
