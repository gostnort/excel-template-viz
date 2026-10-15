# BERT 掩码模型下载位置

`MLM_models/` 里的权重不进 Git。`.gitignore` 只保留 `MLM_models/.gitkeep`。文本列编码从本地目录读取，`local_files_only=True`，运行时不会去网上拉模型。

检查点来自 Hugging Face 的 [google-bert](https://huggingface.co/google-bert)。下载后的目录名必须和 `geodesic_align/mlm_tokens.py` 里的模型 id 一致，并且目录中要有 `model.safetensors`。`weights_ready` 只认这一份文件。

| 本地目录 | 何时使用 | 页面 |
| --- | --- | --- |
| `MLM_models/bert-base-chinese` | 表内出现汉字 | [google-bert/bert-base-chinese](https://huggingface.co/google-bert/bert-base-chinese) |
| `MLM_models/bert-large-uncased` | 表内没有汉字 | [google-bert/bert-large-uncased](https://huggingface.co/google-bert/bert-large-uncased) |

`pick_model_id` 只在这两个之间选择。`EN_MODEL_ID`（`bert-large-cased`）仍写在同一文件里，当前分流不会加载它。需要时从 [google-bert/bert-large-cased](https://huggingface.co/google-bert/bert-large-cased) 放到 `MLM_models/bert-large-cased`。

在仓库根目录执行：

```
hf download google-bert/bert-base-chinese --local-dir MLM_models/bert-base-chinese
hf download google-bert/bert-large-uncased --local-dir MLM_models/bert-large-uncased
```

装好后每个目录里应能看到 `config.json`、`tokenizer.json`、`vocab.txt` 和 `model.safetensors`。缺 `model.safetensors` 时文本测地线对齐会跳过，不报下载错误。
