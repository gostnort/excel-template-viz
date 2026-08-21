# 交接 — feature-llm-toml-4（LM Studio + paddleocr-mcp）

> **给下一个对话直接复制本文 + 文末 Prompt。**  
> 日期：2026-08-21  
> 分支：`feature-llm-toml-4`  
> Git：**全部改动未 commit、未 push**（用户曾要求 commit，后中断；下一轮若仍要提交再做）  
> 测试：**已停止**（无 paddleocr-mcp 监听 18081/18082）

## 0. 先读这些

1. 本文件
2. `docs/llm_lmstudio.md`
3. `docs/toml_wizard.md`
4. `docs/embed_paddle_ocr.md`

已删除、不要恢复：`llm_gemma4/`、`engines/paddle_vl/`、PaddleOCR-VL、LiteRT。

## 1. 已完成

### uv / 虚拟环境

- 根因：`bootup/.install_profile` 曾是 `ocr=false`；裸 `uv run --project bootup` 会把 OCR extra **卸掉**。
- 现：`bootup/uv_profile.py` 读 profile；`run.ps1` / `run.sh` / **`uv_run.ps1`** 自动加 `--extra ocr` 或 `--extra ocr-gpu`。
- `install.bat` 默认装 OCR（只有 `--skip-ocr` 才跳过）。
- 本机已 `uv sync --project bootup --extra ocr-gpu`（RTX 4070）。profile：`accelerator=gpu ocr=true`（gitignore，不入库）。
- 启动请用 `.\run.ps1` 或 `.\uv_run.ps1 python ...`，不要裸 `uv run --project bootup`。

### OCR：paddleocr-mcp HTTP

- `mcp_runtime.py` 启停两个 HTTP MCP：工具 `ocr`（PP-OCRv6）、`pp_structurev3`（替代 VL）。
- 入口改为 `python -m paddle_ocr.mcp_entry`（给 PaddleOCR/PPStructureV3 默认 `enable_mkldnn=False`）。
- 无 `cudnn64_9.dll` 时 `resolve_device()` 回退 **cpu**（本机即如此）。
- JSON：`OcrMcpToStringJson` / `MarkdownToOcrJson`（后者会抽 `<table>` → `table*`）。对外仍是 `PaddleOcr(pic, rectangle)`。

### 样图测试（已停）

`test/ocr_sample.jpg` 经 **pp_structurev3**（CPU、关 MKLDNN）成功，exit 0。结果在 `temp/ocr_sample_result.json`。识别到标题「机上旅客遗失物品交接单」、表格字段（日期 7.5、航班 CA987、航段 PEK-LAX、姓名张清林等）和底部备注。第一次 GPU 失败（缺 cuDNN）；第二次 CPU+默认 MKLDNN 失败（Paddle 3.3 PIR）；第三次成功。

### 向导 CLI

`.\uv_run.ps1 python -m llm_toml_wizard.cli dialog demo --spec toml` → exit 0，`[event] finished`。

## 2. 不要做

- 恢复 LiteRT / PaddleOCR-VL / 并行 field match / 侧边栏聊天
- 裸 `uv run --project bootup`（会卸 OCR 包）
- 本机强制 `OCR_PROFILE=gpu`（没有 cudnn64_9.dll）

## 3. 下一轮

1. 若用户要求：**git commit**（仍未提交）。
2. 确认 `MarkdownToOcrJson` 的 HTML→`table*`（remap 被中断）。
3. 真实 LM Studio 顶栏 load/unload/ask。
4. 有 cuDNN 后再测 GPU。

## 4. 下一对话 Prompt

```
你在仓库 excel-template-viz 分支 feature-llm-toml-4 上工作。先读 plans/dynamic-wizard-runtime/HANDOFF.md。

状态：LM Studio + paddleocr-mcp HTTP 已实现，bootup 已 sync ocr-gpu，样图 OCR 已跑通。全部未 commit。测试已停。不要恢复 VL/LiteRT。启动用 .\uv_run.ps1，不要裸 uv run。

优先：用户若要求则 commit；不要再开长 OCR e2e，除非用户明确要求。
```
