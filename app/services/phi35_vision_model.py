from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

PHI35_VISION_MODEL_ID = "OpenVINO/Phi-3.5-vision-instruct-int4-ov"
_REQUIRED_FILES = (
    "config.json",
    "openvino_language_model.xml",
    "openvino_language_model.bin",
    "openvino_tokenizer.xml",
    "tokenizer_config.json",
    "preprocessor_config.json",
    "openvino_vision_embeddings_model.xml",
)

_processor = None
_model = None

ProgressCallback = Callable[[float, str], None]


@dataclass(frozen=True)
class VisionModelStatus:
    complete: bool
    model_dir: Path
    size_bytes: int | None
    missing_files: tuple[str, ...]


def get_vision_model_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "vllm" / "phi-3.5-vision-instruct-int4-ov"


def _missing_model_files(model_dir: Path) -> list[str]:
    missing: list[str] = []
    for filename in _REQUIRED_FILES:
        if not (model_dir / filename).is_file():
            missing.append(filename)
    return missing


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def get_vision_model_status(model_id: str = PHI35_VISION_MODEL_ID) -> VisionModelStatus:
    del model_id
    model_dir = get_vision_model_dir()
    missing_files = tuple(_missing_model_files(model_dir))
    size_bytes = _directory_size(model_dir) if model_dir.exists() else None
    return VisionModelStatus(
        complete=not missing_files,
        model_dir=model_dir,
        size_bytes=size_bytes,
        missing_files=missing_files,
    )


def _build_tqdm_class(on_progress: ProgressCallback | None):
    from tqdm.auto import tqdm

    class _StreamlitTqdm(tqdm):
        def __init__(self, *args, **kwargs):
            kwargs["disable"] = True
            super().__init__(*args, **kwargs)
            self._on_progress = on_progress
            if on_progress is not None:
                on_progress(0.0, str(self.desc or "下载中"))

        def update(self, n: float = 1) -> bool | None:
            result = super().update(n)
            if self._on_progress is not None and self.total:
                self._on_progress(min(self.n / self.total, 1.0), str(self.desc or "下载中"))
            return result

        def set_description(self, desc: str | None = None, refresh: bool = True) -> None:
            super().set_description(desc, refresh=refresh)
            if self._on_progress is not None and desc:
                pct = min(self.n / self.total, 1.0) if self.total else 0.0
                self._on_progress(pct, str(desc))

        def close(self) -> None:
            if self._on_progress is not None:
                self._on_progress(1.0, "下载完成")
            super().close()

    return _StreamlitTqdm


def download_vision_model(
    *,
    on_progress: ProgressCallback | None = None,
    model_id: str = PHI35_VISION_MODEL_ID,
) -> Path:
    from huggingface_hub import snapshot_download

    model_dir = get_vision_model_dir()
    model_dir.mkdir(parents=True, exist_ok=True)
    download_kwargs: dict = {
        "repo_id": model_id,
        "local_dir": str(model_dir),
    }
    if on_progress is not None:
        download_kwargs["tqdm_class"] = _build_tqdm_class(on_progress)
    snapshot_download(**download_kwargs)
    missing = _missing_model_files(model_dir)
    if missing:
        raise RuntimeError(f"下载后仍缺少文件: {', '.join(missing)}")
    return model_dir


def get_phi35_vision_bundle():
    global _processor, _model
    if _model is not None and _processor is not None:
        return _processor, _model
    status = get_vision_model_status()
    if not status.complete:
        if status.missing_files:
            raise RuntimeError(
                f"视觉模型下载不完整（缺 {len(status.missing_files)} 个文件）。"
                f"请在「粘贴映射」Tab 重新点击「下载视觉模型」。目录：`{status.model_dir}`"
            )
        raise RuntimeError(
            f"视觉模型尚未下载。请先在「粘贴映射」Tab 点击「下载视觉模型」。"
            f"将保存到：`{status.model_dir}`"
        )
    try:
        from optimum.intel.openvino import OVModelForVisualCausalLM
        from transformers import AutoProcessor
    except ImportError as exc:
        raise RuntimeError(
            "未安装视觉模型依赖。请运行: pip install -r requirements.txt "
            "(需要 optimum-intel[openvino] 与 openvino>=2025.0.0)"
        ) from exc
    model_dir = str(status.model_dir)
    load_kwargs = {"trust_remote_code": True, "local_files_only": True}
    _processor = AutoProcessor.from_pretrained(model_dir, **load_kwargs)
    _model = OVModelForVisualCausalLM.from_pretrained(model_dir, **load_kwargs)
    return _processor, _model


def reset_phi35_vision_cache() -> None:
    global _processor, _model
    _processor = None
    _model = None
