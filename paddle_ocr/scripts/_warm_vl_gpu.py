"""install_backend.py 在全新子进程里调本脚本：构造 PaddleOCRVL(GPU) 触发 VL 模型下载。

本脚本在 install_backend 装好 paddlepaddle-gpu 之后由独立子进程运行，因此 import
到的就是新装的 CUDA 版 paddle。仅构造引擎 + 跑一次预测，让 PaddleX 把 VL
official_models 拉到 paddle_ocr/models/official_models/。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from paddle_ocr import config
from paddle_ocr.models_catalog import vl_models_present
from paddle_ocr.runtime.image_decode import load_for_ocr



def main() -> int:
    config.ensure_pdx_cache_env()
    try:
        from paddleocr import PaddleOCRVL
        from paddlex.utils import logging as pdx_logging
        pdx_logging._logger.disabled = True
    except Exception as exc:
        print(f"import PaddleOCRVL 失败: {exc!r}", flush=True)
        return 1
    try:
        engine = PaddleOCRVL(
            pipeline_version=config.DEFAULT_VL_PIPELINE_VERSION,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_seal_recognition=False,
            use_chart_recognition=False,
            enable_mkldnn=False,
            device="gpu",
        )
    except Exception as exc:
        print(f"PaddleOCRVL(GPU) 构造失败: {exc!r}", flush=True)
        return 1
    sample = config.SAMPLE_IMAGE
    try:
        if sample.is_file():
            img = load_for_ocr(sample, None)
            engine.predict(img)
        else:
            import numpy as np
            engine.predict(np.zeros((960, 640, 3), dtype=np.uint8))
    except Exception as exc:
        print(f"VL 预热 predict 失败（模型可能仍在下载）: {exc!r}", flush=True)
    ok = vl_models_present()
    print(f"VL 模型就绪: {ok}", flush=True)
    return 0 if ok else 1



if __name__ == "__main__":
    raise SystemExit(main())
