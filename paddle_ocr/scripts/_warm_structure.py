"""install_backend.py 在全新子进程里调本脚本：启动 paddleocr-mcp 触发模型下载。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from paddle_ocr import config
from paddle_ocr.mcp_runtime import call_ocr_mcp, call_structure_mcp, start_mcp, stop_mcp
from paddle_ocr.models_catalog import prune_vl_official_models, required_models_present
from paddle_ocr.runtime.image_decode import load_for_ocr



def main() -> int:
    """
    函数名: main
    作用: 启动 PP-OCRv6 + PP-StructureV3 MCP，对样图或空白图各跑一次以拉取权重。
    输入: 无。
    输出:
        int: 退出码。
    """
    config.ensure_pdx_cache_env()
    prune_vl_official_models()
    sample = config.SAMPLE_IMAGE
    try:
        if not start_mcp(include_structure=True):
            print("paddleocr-mcp 启动失败", flush=True)
            return 1
        if sample.is_file():
            img = load_for_ocr(sample, None)
        else:
            import numpy as np
            img = np.zeros((960, 640, 3), dtype=np.uint8)
        call_ocr_mcp(img)
        call_structure_mcp(img, mode="fast")
    except Exception as exc:
        print(f"预热 predict 失败（模型可能仍在下载）: {exc!r}", flush=True)
    finally:
        stop_mcp()
    ok = required_models_present()
    print(f"PP-OCRv6 模型就绪: {ok}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
