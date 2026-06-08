from pathlib import Path
from unittest.mock import patch

from app.services.phi35_vision_model import (
    PHI35_VISION_MODEL_ID,
    download_vision_model,
    get_vision_model_dir,
    get_vision_model_status,
)


def test_get_vision_model_dir_under_app_vllm() -> None:
    model_dir = get_vision_model_dir()
    assert model_dir.parts[-2:] == ("vllm", "phi-3.5-vision-instruct-int4-ov")


def test_get_vision_model_status_incomplete(tmp_path: Path) -> None:
    with patch("app.services.phi35_vision_model.get_vision_model_dir", return_value=tmp_path):
        with patch("app.services.phi35_vision_model._missing_model_files", return_value=["config.json"]):
            status = get_vision_model_status()
    assert status.complete is False
    assert status.model_dir == tmp_path
    assert status.missing_files == ("config.json",)


def test_get_vision_model_status_complete(tmp_path: Path) -> None:
    with patch("app.services.phi35_vision_model.get_vision_model_dir", return_value=tmp_path):
        with patch("app.services.phi35_vision_model._missing_model_files", return_value=[]):
            with patch("app.services.phi35_vision_model._directory_size", return_value=2048):
                status = get_vision_model_status()
    assert status.complete is True
    assert status.size_bytes == 2048


def test_download_vision_model_uses_project_local_dir(tmp_path: Path) -> None:
    with patch("app.services.phi35_vision_model.get_vision_model_dir", return_value=tmp_path):
        with patch("huggingface_hub.snapshot_download") as mocked:
            with patch("app.services.phi35_vision_model._missing_model_files", return_value=[]):
                path = download_vision_model(model_id=PHI35_VISION_MODEL_ID)
    assert path == tmp_path
    mocked.assert_called_once()
    kwargs = mocked.call_args.kwargs
    assert kwargs["local_dir"] == str(tmp_path)
