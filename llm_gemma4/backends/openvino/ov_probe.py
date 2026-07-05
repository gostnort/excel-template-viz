"""OpenVINO runtime device probe (Intel GPU / CPU / NPU)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OpenVinoProbeResult:
    installed: bool
    devices: tuple[str, ...]
    has_intel_gpu: bool
    has_npu: bool
    version: str | None
    note: str | None


def probe_openvino() -> OpenVinoProbeResult:
    """Return OpenVINO Core devices when the package is importable."""
    try:
        from openvino.runtime import Core
    except ImportError:
        return OpenVinoProbeResult(
            installed=False,
            devices=(),
            has_intel_gpu=False,
            has_npu=False,
            version=None,
            note="openvino not installed",
        )
    try:
        core = Core()
        devices = tuple(core.available_devices)
    except Exception as exc:
        return OpenVinoProbeResult(
            installed=True,
            devices=(),
            has_intel_gpu=False,
            has_npu=False,
            version=_openvino_version(),
            note=f"OpenVINO Core failed: {exc}",
        )
    has_gpu = "GPU" in devices
    has_npu = "NPU" in devices
    note = None
    if not has_gpu and "CPU" in devices:
        note = "OpenVINO CPU only (no GPU device)"
    return OpenVinoProbeResult(
        installed=True,
        devices=devices,
        has_intel_gpu=has_gpu,
        has_npu=has_npu,
        version=_openvino_version(),
        note=note,
    )


def _openvino_version() -> str | None:
    try:
        import openvino
        return getattr(openvino, "__version__", None)
    except ImportError:
        return None
