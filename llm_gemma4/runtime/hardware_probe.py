"""Hardware detection and available inference profile selection."""

from __future__ import annotations

import json
import platform
import subprocess
from dataclasses import asdict, dataclass, field
from typing import Any

from llm_gemma4.backends.llamacpp import cpu_features
from llm_gemma4.backends.llamacpp.cuda_probe import probe_cuda
from llm_gemma4.backends.openvino.ov_probe import probe_openvino


@dataclass
class HardwareReport:
    cpu_vendor: str
    cpu_model: str
    ram_gb: float | None
    avx: bool
    avx2: bool
    avx512f: bool
    simd_source: str
    llama_cpp_cpu_wheel: str
    cpu_llama_eligible: bool
    cpu_llama_note: str | None
    has_nvidia_cuda: bool
    nvidia_gpu_name: str | None
    nvidia_driver: str | None
    llama_cpp_cuda_import_ok: bool
    cuda_note: str | None
    openvino_installed: bool
    openvino_version: str | None
    openvino_devices: list[str]
    has_intel_gpu: bool
    has_npu: bool
    openvino_note: str | None
    openvino_eligible: bool
    openvino_eligible_note: str | None
    available_profiles: list[str] = field(default_factory=list)


def detect_cpu_vendor() -> str:
    """Return intel, amd, or other from platform / WMI hints."""
    processor = (platform.processor() or "").lower()
    uname = " ".join(platform.uname()).lower()
    blob = f"{processor} {uname}"
    if "intel" in blob or "genuineintel" in blob:
        return "intel"
    if "amd" in blob or "authenticamd" in blob:
        return "amd"
    if platform.system() == "Windows":
        wmi_vendor = _wmi_cpu_vendor()
        if wmi_vendor:
            return wmi_vendor
    return "other"


def _wmi_cpu_vendor() -> str | None:
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-CimInstance Win32_Processor | Select-Object -First 1).Manufacturer",
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if completed.returncode != 0:
            return None
        text = completed.stdout.strip().lower()
        if "intel" in text:
            return "intel"
        if "amd" in text:
            return "amd"
    except (OSError, subprocess.TimeoutExpired):
        return None
    return None


def detect_cpu_model() -> str:
    """Best-effort CPU marketing name."""
    if platform.system() == "Windows":
        try:
            completed = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "(Get-CimInstance Win32_Processor | Select-Object -First 1).Name",
                ],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            if completed.returncode == 0 and completed.stdout.strip():
                return completed.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    return platform.processor() or "unknown"


def detect_ram_gb() -> float | None:
    try:
        import psutil
        return round(psutil.virtual_memory().total / (1024 ** 3), 1)
    except ImportError:
        return None


def _cpu_llama_eligibility(simd: dict[str, Any]) -> tuple[bool, str | None]:
    """llama.cpp CPU: AVX2 minimum; wheel 0.3.29 needs AVX-512F (see cpu_features)."""
    if simd.get("source") == "non_x86":
        return True, None
    if simd.get("avx512f") or simd.get("avx512"):
        return True, None
    if simd.get("avx2"):
        return True, "AVX2 only (no AVX-512F): use llama-cpp-python 0.3.28 CPU wheel"
    if simd.get("avx"):
        return True, "AVX only: CPU wheel may be unsupported or very slow"
    return False, "No AVX: llama.cpp CPU wheel likely unsupported on this CPU"


def _openvino_eligibility(
    cpu_vendor: str,
    simd: dict[str, Any],
    ov_installed: bool,
) -> tuple[bool, str | None]:
    """OpenVINO INT4: Intel + AVX-512F (recent Core); package must be installed."""
    if cpu_vendor != "intel":
        return False, f"OpenVINO profile skipped: CPU vendor is {cpu_vendor} (Intel only in this project)"
    if not simd.get("avx512f") and not simd.get("avx512"):
        return False, "OpenVINO skipped: CPU lacks AVX-512F (need recent Intel Core)"
    if not ov_installed:
        return False, "OpenVINO skipped: package not installed"
    return True, None


def resolve_available_profiles(report: HardwareReport) -> list[str]:
    """Build ordered profile menu: cuda / openvino / cpu per hardware."""
    profiles: list[str] = []
    if report.has_nvidia_cuda:
        profiles.append("cuda")
    if report.openvino_eligible:
        profiles.append("openvino")
    if report.cpu_llama_eligible or "cpu" not in profiles:
        profiles.append("cpu")
    # dedupe while preserving order
    seen: set[str] = set()
    ordered: list[str] = []
    for name in profiles:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    if "cpu" not in ordered:
        ordered.append("cpu")
    return ordered


def detect() -> HardwareReport:
    """Run full hardware probe and return HardwareReport."""
    cpu_vendor = detect_cpu_vendor()
    cpu_model = detect_cpu_model()
    ram_gb = detect_ram_gb()
    simd = cpu_features.detect_simd_features()
    cpu_ok, cpu_note = _cpu_llama_eligibility(simd)
    cuda = probe_cuda()
    ov = probe_openvino()
    ov_ok, ov_note = _openvino_eligibility(cpu_vendor, simd, ov.installed)
    report = HardwareReport(
        cpu_vendor=cpu_vendor,
        cpu_model=cpu_model,
        ram_gb=ram_gb,
        avx=bool(simd.get("avx")),
        avx2=bool(simd.get("avx2")),
        avx512f=bool(simd.get("avx512f")),
        simd_source=str(simd.get("source", "")),
        llama_cpp_cpu_wheel=cpu_features.recommended_llama_cpp_version(),
        cpu_llama_eligible=cpu_ok,
        cpu_llama_note=cpu_note,
        has_nvidia_cuda=cuda.has_nvidia_cuda,
        nvidia_gpu_name=cuda.gpu_name,
        nvidia_driver=cuda.driver_version,
        llama_cpp_cuda_import_ok=cuda.llama_cpp_cuda_import_ok,
        cuda_note=cuda.note,
        openvino_installed=ov.installed,
        openvino_version=ov.version,
        openvino_devices=list(ov.devices),
        has_intel_gpu=ov.has_intel_gpu,
        has_npu=ov.has_npu,
        openvino_note=ov.note,
        openvino_eligible=ov_ok,
        openvino_eligible_note=ov_note,
        available_profiles=[],
    )
    report.available_profiles = resolve_available_profiles(report)
    return report


def format_report(report: HardwareReport) -> str:
    """Human-readable probe summary for CLI."""
    lines = [
        "[Gemma4] hardware probe",
        f"  CPU: {report.cpu_model} ({report.cpu_vendor})",
    ]
    if report.ram_gb is not None:
        lines.append(f"  RAM: {report.ram_gb} GB")
    simd_bits = []
    if report.avx:
        simd_bits.append("AVX")
    if report.avx2:
        simd_bits.append("AVX2")
    if report.avx512f:
        simd_bits.append("AVX-512F")
    simd_text = ", ".join(simd_bits) if simd_bits else "none detected"
    lines.append(f"  SIMD: {simd_text} (source={report.simd_source})")
    lines.append(f"  llama.cpp CPU wheel hint: {report.llama_cpp_cpu_wheel} (AVX-512F -> 0.3.29, else 0.3.28)")
    if report.cpu_llama_note:
        lines.append(f"  CPU profile: {report.cpu_llama_note}")
    cuda_line = "yes" if report.has_nvidia_cuda else "no"
    if report.nvidia_gpu_name:
        cuda_line += f" ({report.nvidia_gpu_name})"
    lines.append(f"  NVIDIA CUDA: {cuda_line}")
    if report.cuda_note:
        lines.append(f"    {report.cuda_note}")
    igpu = "yes" if report.has_intel_gpu else "no"
    lines.append(f"  Intel GPU (OpenVINO): {igpu} | NPU: {'yes' if report.has_npu else 'no'}")
    if report.openvino_installed:
        devs = ", ".join(report.openvino_devices) or "(none)"
        ver = report.openvino_version or "?"
        lines.append(f"  OpenVINO {ver} devices: {devs}")
    if report.openvino_eligible_note:
        lines.append(f"  OpenVINO profile: {report.openvino_eligible_note}")
    lines.append("")
    lines.append("Available profiles:")
    for index, name in enumerate(report.available_profiles, start=1):
        desc = _profile_blurb(name, report)
        lines.append(f"  [{index}] {name} - {desc}")
    lines.append("")
    lines.append("Standalone test: python -m llm_gemma4 probe")
    lines.append("JSON:          python -m llm_gemma4 probe --json")
    return "\n".join(lines)


def _profile_blurb(name: str, report: HardwareReport) -> str:
    if name == "cuda":
        return "llama.cpp · CUDA GGUF (NVIDIA)"
    if name == "openvino":
        return "OpenVINO · Intel GPU INT4"
    return "llama.cpp · CPU GGUF (fallback)"


def report_to_json(report: HardwareReport) -> str:
    """Serialize report for scripting."""
    payload = asdict(report)
    return json.dumps(payload, indent=2, ensure_ascii=False)


def choose_profile(
    report: HardwareReport,
    profile: str | None,
    *,
    interactive: bool = True,
) -> str:
    """Resolve profile from arg, env, auto-pick, or TTY menu."""
    profiles = list(report.available_profiles)
    if not profiles:
        raise SystemExit("No inference profiles available; run: python -m llm_gemma4 probe")
    if profile:
        name = profile.strip().lower()
        if name not in profiles:
            raise SystemExit(
                f"Profile {name!r} not available. Choices: {', '.join(profiles)}"
            )
        return name
    if len(profiles) == 1:
        return profiles[0]
    if not interactive:
        raise SystemExit(
            f"Multiple profiles available ({', '.join(profiles)}); pass --profile"
        )
    print(format_report(report))
    while True:
        raw = input(f"Enter profile number [1-{len(profiles)}]: ").strip()
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(profiles):
                return profiles[index - 1]
        print("Invalid choice; try again.")
