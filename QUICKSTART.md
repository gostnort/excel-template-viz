# 快速开始 / Quickstart

以下步骤适用于 Windows 与本地运行环境。  
The steps below apply to Windows and local development.

## 安装与运行 / Install & Run

```bash
cd excel-template-viz
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Windows 用户也可使用 `install.bat` 完成安装与模型下载。

启动应用（端口 **8501**）：

```batch
run.bat
```

或：

```bash
python gradio_app.py
```

将需要使用的 xlsx 文件复制到 `templates/` 目录，启动后会自动识别。  
Copy your xlsx files into `templates/`; the app will detect them on startup.

## LLM 依赖（Gemma 4）/ LLM Dependencies (Gemma 4)

Gemma 4 字段匹配使用 `llama-cpp-python` CPU 预编译 wheel。Windows 上 **0.3.29 及更高版本的 CPU wheel 可能启用 AVX512**；在无 AVX512 的 CPU 上会触发非法指令错误 `WinError 0xc000001d`。  
Gemma 4 field matching uses the `llama-cpp-python` CPU wheel. On Windows, **0.3.29+ CPU wheels may require AVX512**; on CPUs without AVX512 you may see illegal-instruction `WinError 0xc000001d`.

**`install.bat` 会自动检测 CPU（CPUID：AVX / AVX2 / AVX512F）并安装匹配的 wheel：**  
**`install.bat` auto-detects CPU features (CPUID: AVX / AVX2 / AVX512F) and installs the matching wheel:**

| 检测结果 / Detection | 安装版本 / Installed version |
|---|---|
| 有 AVX512F / AVX512 present | `0.3.29` |
| 无 AVX512（大多数笔记本与桌面）/ no AVX512 | `0.3.28` |

手动安装（同样按 CPU 选择版本）/ Manual install (same CPU-based selection):

```batch
python -c "from app.services.cpu_features import llama_cpp_install_command; print(llama_cpp_install_command())"
```

复制输出的 `pip install …` 命令并执行。  
Copy the printed `pip install …` command and run it.

`install.bat` 会在 `pip install -r requirements.txt` 之前先安装检测到的版本。  
`install.bat` installs the detected version before `pip install -r requirements.txt`.

下载模型 / Download model：

```batch
python app/download_gemma4_model.py --auto
```

### CPU 与 wheel 版本对照 / CPU ↔ wheel compatibility

| CPU 系列 / CPU family | AVX512 | 推荐 llama-cpp-python / Recommended |
|---|---|---|
| Intel Core Ultra Series 1（Meteor Lake U/H，如 125U、155U） | 否 No（AVX2 + AVX-VNNI） | **0.3.28** |
| Intel Core 7/5/3 Series 1 非 Ultra（Raptor Lake 刷新，如 **Core 7 150U**） | 否 No（AVX2） | **0.3.28** |
| Intel 第 12–14 代客户端（Alder / Raptor / Meteor Lake） | 否 No | **0.3.28** |
| AMD Ryzen Zen 1–3 桌面与移动（如 5600X、5800U） | 否 No | **0.3.28** |
| 多数 Windows 笔记本 / Most Windows laptops | 通常否 Usually no | **0.3.28** |
| AMD Ryzen Zen 4+（7000 系列及更新） | 是 Yes | 0.3.29+ 可选 / optional |
| Intel Xeon / 多数工作站 CPU | 通常有 Often yes | 0.3.29+ 可选 / optional |

> **说明 / Note：** 市场上常见 **Intel Core 7 150U**（非 “Core Ultra 150U”）为 Raptor Lake-U 刷新，仅 AVX2，应使用 **0.3.28**。  
> The common **Intel Core 7 150U** (not “Core Ultra 150U”) is a Raptor Lake-U refresh with AVX2 only — use **0.3.28**.

若已安装 0.3.29+ 并出现 `0xc000001d`，请降级：  
If you installed 0.3.29+ and see `0xc000001d`, downgrade:

```batch
pip install llama-cpp-python==0.3.28 --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
```

## 数据源配置（简要）/ Data Source Setup (Brief)

1. 侧边栏点击 **添加数据源**。  
   Click **Add data source** in the sidebar.
2. 点击 **连接 Google 账号**，在浏览器中完成授权。  
   Click **Connect Google account** and complete authorization in the browser.
3. 填写 Sheet URL，**连接 Sheet** 成功后 **保存为默认数据源**。  
   Enter the Sheet URL, **Connect Sheet**, then **Save as default**.
4. 在模板页输入 PO（如 `10073`）→ **查询并填入**。  
   Enter a PO number (e.g. `10073`) → **Query & fill**.
