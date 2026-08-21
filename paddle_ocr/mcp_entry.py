"""paddleocr-mcp 进程入口：CPU 关闭 oneDNN，避免 Paddle 3.3 PIR/MKLDNN 崩溃。"""

from __future__ import annotations

import os

from paddle_ocr import config


def _patch_disable_mkldnn() -> None:
    """
    函数名: _patch_disable_mkldnn
    作用: 给 PaddleOCR / PPStructureV3 默认 enable_mkldnn=False（paddleocr-mcp 本地构造不传该参数）。
    输入: 无。
    输出: 无。
    """
    import paddleocr
    ocr_cls = paddleocr.PaddleOCR
    st_cls = paddleocr.PPStructureV3
    class PaddleOCR(ocr_cls):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("enable_mkldnn", config.DEFAULT_ENABLE_MKLDNN)
            super().__init__(*args, **kwargs)
    class PPStructureV3(st_cls):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("enable_mkldnn", config.DEFAULT_ENABLE_MKLDNN)
            super().__init__(*args, **kwargs)
    paddleocr.PaddleOCR = PaddleOCR
    paddleocr.PPStructureV3 = PPStructureV3


def main() -> None:
    """
    函数名: main
    作用: 设置缓存环境、关掉 MKLDNN，再进入官方 paddleocr-mcp CLI。
    输入: 无。
    输出: 无。
    """
    config.ensure_pdx_cache_env()
    os.environ["FLAGS_use_mkldnn"] = "0"
    _patch_disable_mkldnn()
    from paddleocr_mcp.__main__ import main as mcp_main
    mcp_main()


if __name__ == "__main__":
    main()
