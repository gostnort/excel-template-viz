# LM Studio 推理底座

> 状态：feature-llm-toml-4  
> 包：[`llm_lmstudio/`](../llm_lmstudio/)  
> 向导编排：[`toml_wizard.md`](toml_wizard.md)

本仓库不再内嵌 LiteRT / HuggingFace 权重。所有 LLM 查询（TOML 向导、CLI、OCR 语义门禁与读图）走本机 [LM Studio](https://lmstudio.ai/docs/developer/rest) 原生 REST `/api/v1`。

## 配置

复制 [`llm_lmstudio/user.toml.example`](../llm_lmstudio/user.toml.example) 为 `llm_lmstudio/user.toml`（gitignore，勿提交）：

```toml
api_url = "http://localhost:9999"
api_token = ""
model = ""
model_history = []
```

- `api_url`：LM Studio Developer 服务地址（本机默认 `http://localhost:9999`）
- `api_token`：若未开鉴权则留空
- `model`：模型 `key`（如 `google/gemma-4-26b-a4b`），与顶栏可编辑名称相同
- `model_history`：曾输入过的名称

## REST

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/v1/models` | 已下载/已加载列表；`capabilities.vision` |
| GET | `/api/v1/models/{key}` | 单模型详情（`key` 含 `/` 时须 URL 编码） |
| POST | `/api/v1/models/load` | `{"model": "<key>"}` |
| POST | `/api/v1/models/unload` | `{"instance_id": "..."}`，id 来自 `loaded_instances` |
| POST | `/api/v1/chat` | 文本或 `{type:image, data_url}` 读图 |

NiceGUI 顶栏：可编辑模型名 + 开关遥控 load/unload。开关状态看 `loaded_instances` 是否非空。停止向导**不**自动 unload。

多模态：读图前查 `capabilities.vision`；为 false 则 OCR 视觉纠错跳过，保留 fast。

## CLI

```bat
.\uv_run.ps1 python -m llm_lmstudio models
.\uv_run.ps1 python -m llm_lmstudio health
.\uv_run.ps1 python -m llm_lmstudio load
.\uv_run.ps1 python -m llm_lmstudio ask "用一句话介绍你自己"
.\uv_run.ps1 python -m llm_lmstudio unload
```
