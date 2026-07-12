"""启动时硬件探测 + 对应 VL 库/模型安装引导（不能在已 import paddle 的进程内热替换）。

用法:
    python paddle_ocr/scripts/install_backend.py            自动探测硬件
    python paddle_ocr/scripts/install_backend.py gpu        强制 GPU 路径
    python paddle_ocr/scripts/install_backend.py cpu        强制 CPU-only（prune VL 模型）

GPU 路径：卸载 CPU 版 paddlepaddle → 装 paddlepaddle-gpu（CUDA 12.9，驱动向后兼容）
→ 启动全新子进程构造 PaddleOCRVL(device=gpu) 触发 PaddleX 下载 VL official_models。
CPU 路径：prune VL 模型释放磁盘；运行时走 Gemma4 直接纠错（无需 VL）。
NPU 路径：暂未实现（未来加 OpenVINO paddleocr_vl_openvino 后端）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# paddlepaddle-gpu 安装源（CUDA 12.9；NVIDIA 驱动向后兼容，13.x 驱动可跑 12.9 运行时）。
_PADDLE_GPU_INDEX = "https://www.paddlepaddle.org.cn/packages/stable/cu129/"
_PADDLE_VERSION = "3.3.1"



def _pip(args: list[str]) -> int:
    """调本环境 pip；返回退出码。"""
    cmd = [sys.executable, "-m", "pip"] + args
    print(f">>> {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd)



def _paddle_gpu_installed() -> bool:
    """paddlepaddle-gpu 是否已装（用 metadata，不 import paddle）。"""
    try:
        import importlib.metadata as md
        md.version("paddlepaddle-gpu")
        return True
    except Exception:
        return False



def _paddle_cpu_installed() -> bool:
    try:
        import importlib.metadata as md
        md.version("paddlepaddle")
        return True
    except Exception:
        return False



def install_gpu_backend() -> int:
    """卸载 CPU paddlepaddle → 装 paddlepaddle-gpu → 子进程预热 VL 下载模型。"""
    if _paddle_gpu_installed():
        print("paddlepaddle-gpu 已安装，跳过库安装。", flush=True)
    else:
        if _paddle_cpu_installed():
            print("卸载 CPU 版 paddlepaddle ...", flush=True)
            _pip(["uninstall", "-y", "paddlepaddle"])
        print(f"安装 paddlepaddle-gpu=={_PADDLE_VERSION} (CUDA 12.9) ...", flush=True)
        rc = _pip([
            "install", f"paddlepaddle-gpu=={_PADDLE_VERSION}",
            "-i", _PADDLE_GPU_INDEX,
            "--default-timeout=200",
        ])
        if rc != 0:
            print("paddlepaddle-gpu 安装失败；请检查网络/CUDA 兼容性。", flush=True)
            return rc
    # 全新子进程构造 PaddleOCRVL(device=gpu) 触发 PaddleX 下载 VL official_models。
    print("预热 PaddleOCRVL(GPU) 并下载 VL 模型 ...", flush=True)
    warm_rc = subprocess.call([sys.executable, str(Path(__file__).parent / "_warm_vl_gpu.py")])
    if warm_rc != 0:
        print("VL 预热/模型下载未完成；可稍后重跑本脚本。", flush=True)
        return warm_rc
    print("GPU VL 后端就绪。请重启 OCR 进程以加载 paddlepaddle-gpu。", flush=True)
    return 0



def install_cpu_backend() -> int:
    """CPU-only：prune VL 模型释放磁盘；运行时走 Gemma4 直接纠错。"""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from paddle_ocr.models_catalog import prune_extra_official_models
    removed = prune_extra_official_models(keep_vl=False)
    print(f"CPU-only 路径：已 prune VL 模型 {removed}；运行时走 Gemma4 直接纠错。", flush=True)
    return 0



def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from paddle_ocr.gate.hardware_probe import detect_accelerator
    target = argv[0].lower() if argv else detect_accelerator()
    print(f"硬件探测/目标后端: {target}", flush=True)
    if target == "gpu":
        return install_gpu_backend()
    if target == "cpu":
        return install_cpu_backend()
    if target == "npu":
        print("NPU 后端暂未实现（需 OpenVINO + paddleocr_vl_openvino）；本次跳过。", flush=True)
        return 0
    print(f"未知目标: {target}（可用: gpu / cpu / 自动探测）", flush=True)
    return 1



if __name__ == "__main__":
    raise SystemExit(main())
