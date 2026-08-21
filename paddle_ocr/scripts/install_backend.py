"""启动时硬件探测 + GPU paddle 安装引导（不能在已 import paddle 的进程内热替换）。

用法:
    python paddle_ocr/scripts/install_backend.py            自动探测硬件
    python paddle_ocr/scripts/install_backend.py gpu        强制 GPU 路径
    python paddle_ocr/scripts/install_backend.py cpu        强制 CPU-only（prune VL 残留）

GPU 路径：卸载 CPU 版 paddlepaddle → 装 paddlepaddle-gpu（CUDA 12.9）
→ 子进程预热 PP-OCRv6 + PP-StructureV3。
CPU 路径：prune 旧 PaddleOCR-VL 模型。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


_PADDLE_GPU_INDEX = "https://www.paddlepaddle.org.cn/packages/stable/cu129/"
_PADDLE_VERSION = "3.3.1"



def _pip(args: list[str]) -> int:
    """
    函数名: _pip
    作用: 优先 uv pip（绑定当前解释器），否则 python -m pip；返回退出码
    输入:
        args (list[str]): pip 子命令参数（如 install / uninstall …）
    输出:
        int: 进程退出码
    """
    uv = shutil.which("uv")
    if uv and args and args[0] in ("install", "uninstall"):
        cmd = [uv, "pip", args[0], "--python", sys.executable] + args[1:]
    elif uv:
        cmd = [uv, "pip"] + args
    else:
        cmd = [sys.executable, "-m", "pip"] + args
    print(f">>> {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd)



def _paddle_gpu_installed() -> bool:
    """
    函数名: _paddle_gpu_installed
    作用: 判断 paddlepaddle-gpu 是否已安装（metadata，不 import paddle）
    输入: 无
    输出:
        bool: 已安装则为 True
    """
    try:
        import importlib.metadata as md
        md.version("paddlepaddle-gpu")
        return True
    except Exception:
        return False



def _paddle_cpu_installed() -> bool:
    """
    函数名: _paddle_cpu_installed
    作用: 判断 CPU 版 paddlepaddle 是否已安装
    输入: 无
    输出:
        bool: 已安装则为 True
    """
    try:
        import importlib.metadata as md
        md.version("paddlepaddle")
        return True
    except Exception:
        return False



def install_gpu_backend() -> int:
    """
    函数名: install_gpu_backend
    作用: 卸载 CPU paddlepaddle → 装 paddlepaddle-gpu → 子进程预热 OCR/Structure
    输入: 无
    输出:
        int: 退出码
    """
    if _paddle_gpu_installed():
        print("paddlepaddle-gpu 已安装，跳过库安装。", flush=True)
    else:
        if _paddle_cpu_installed():
            print("卸载 CPU 版 paddlepaddle ...", flush=True)
            _pip(["uninstall", "-y", "paddlepaddle"])
        print(f"安装 paddlepaddle-gpu=={_PADDLE_VERSION} (CUDA 12.9) ...", flush=True)
        install_args = [
            "install", f"paddlepaddle-gpu=={_PADDLE_VERSION}",
            "-i", _PADDLE_GPU_INDEX,
        ]
        if not shutil.which("uv"):
            install_args.append("--default-timeout=200")
        rc = _pip(install_args)
        if rc != 0:
            print("paddlepaddle-gpu 安装失败；请检查网络/CUDA 兼容性。", flush=True)
            return rc
    print("预热 PP-OCRv6 / PP-StructureV3 并下载模型 ...", flush=True)
    warm_rc = subprocess.call([sys.executable, str(Path(__file__).parent / "_warm_structure.py")])
    if warm_rc != 0:
        print("OCR/Structure 预热未完成；可稍后重跑本脚本。", flush=True)
        return warm_rc
    print("GPU OCR 后端就绪。请重启 OCR 进程以加载 paddlepaddle-gpu。", flush=True)
    return 0



def install_cpu_backend() -> int:
    """
    函数名: install_cpu_backend
    作用: CPU-only：prune 旧 VL 模型
    输入: 无
    输出:
        int: 退出码
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from paddle_ocr.models_catalog import prune_vl_official_models
    removed = prune_vl_official_models()
    print(f"CPU-only 路径：已 prune VL 残留 {removed}。", flush=True)
    return 0



def main(argv: list[str] | None = None) -> int:
    """
    函数名: main
    作用: 按目标后端安装 GPU/CPU OCR 配套
    输入:
        argv (list[str] | None): 可选 gpu/cpu；缺省则自动探测
    输出:
        int: 退出码
    """
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
        print("NPU 后端暂未实现；本次跳过。", flush=True)
        return 0
    print(f"未知目标: {target}（可用: gpu / cpu / 自动探测）", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
