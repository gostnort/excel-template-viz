"""
Phi-4 Field Matcher (Transformers + GGUF)

Uses Phi-4-mini-instruct via Transformers with GGUF support (pure Python, no compilation).
Automatically selects quantization based on available memory.
"""
import importlib.metadata
import json
import logging
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str, dict[str, str]], None]

# Last load failure message for UI feedback (set by create_field_matcher).
_last_load_error: str | None = None

# Model configuration
MODEL_REPO = "bartowski/microsoft_Phi-4-mini-instruct-GGUF"
MODEL_DIR = Path("models/phi4")

# Quantization versions (in preference order)
QUANT_VERSIONS = ["Q8_0", "Q6_K", "Q5_K_M", "Q4_K_M", "Q3_K_M", "Q2_K"]

# (name, memory_gb, description)
QUANT_SPECS: list[tuple[str, float, str]] = [
    ("Q8_0", 6.5, "Best quality, highest memory"),
    ("Q6_K", 5.0, "Very good quality"),
    ("Q5_K_M", 4.0, "Good quality, balanced"),
    ("Q4_K_M", 3.5, "Balanced (recommended)"),
    ("Q3_K_M", 3.0, "Lower quality, smaller"),
    ("Q2_K", 2.5, "Minimal quality, smallest"),
]


class ModelDownloadError(Exception):
    """Model download failed; message is user-facing and actionable."""


class ModelLoadError(Exception):
    """Phi-4 GGUF model could not be loaded; message is user-facing and actionable."""


def get_last_load_error() -> str | None:
    """Return the most recent model load failure message, if any."""
    return _last_load_error


def _ensure_gguf_version() -> None:
    """
    Work around gguf package missing __version__ (breaks transformers>=5 is_gguf_available).
    Must run before any transformers GGUF code path.
    """
    import gguf

    if getattr(gguf, "__version__", None):
        return
    try:
        gguf.__version__ = importlib.metadata.version("gguf")
    except importlib.metadata.PackageNotFoundError:
        gguf.__version__ = "0.10.0"


def _ensure_gguf_hub_accessible(hub_filename: str) -> None:
    """
    Ensure GGUF can be loaded via MODEL_REPO + gguf_file (HF hub cache).

    Transformers resolves GGUF by repo id + filename, not by passing a local path
    as pretrained_model_name_or_path. local_dir must not be passed to model loading.
    """
    from huggingface_hub import hf_hub_download

    try:
        hf_hub_download(
            repo_id=MODEL_REPO,
            filename=hub_filename,
            local_files_only=True,
        )
        return
    except Exception:
        pass

    local_path = MODEL_DIR / hub_filename
    if local_path.is_file():
        hf_hub_download(repo_id=MODEL_REPO, filename=hub_filename)
        return

    raise FileNotFoundError(
        f"GGUF file not found: {local_path}. "
        f"Run install.bat or: python scripts/download_phi4_model.py"
    )


def _resolve_gguf_source(
    model_path: str | Path | None,
) -> tuple[str, Path]:
    """
    Resolve (hub_filename, local_path) for the GGUF weights.

    Returns:
        hub_filename: filename on the Hugging Face repo (not a directory path)
        local_path: resolved local file path under MODEL_DIR
    """
    if model_path is not None:
        local_path = Path(model_path).resolve()
        if not local_path.is_file():
            raise FileNotFoundError(f"Model file not found: {local_path}")
        return local_path.name, local_path

    found = find_model_file()
    if found:
        hub_filename, local_path = found
        return hub_filename, local_path.resolve()

    raise FileNotFoundError(
        f"No Phi-4 GGUF model in {MODEL_DIR.resolve()}. "
        f"Download with: python scripts/download_phi4_model.py"
    )


def _check_download_dependencies() -> None:
    """Verify packages required for Hugging Face model download."""
    missing: list[str] = []
    try:
        import huggingface_hub  # noqa: F401
    except ImportError:
        missing.append("huggingface-hub")
    try:
        import psutil  # noqa: F401
    except ImportError:
        missing.append("psutil")
    if missing:
        packages = " ".join(missing)
        raise ModelDownloadError(
            f"缺少依赖包: {', '.join(missing)}。"
            f"请运行 install.bat 重新安装，或手动执行: pip install {packages}"
        )


def get_available_memory_gb() -> tuple[float, float]:
    """Return (available_gb, total_gb) of system memory."""
    import psutil

    mem = psutil.virtual_memory()
    return mem.available / (1024 ** 3), mem.total / (1024 ** 3)


def select_quantization(auto_mode: bool = True) -> tuple[str, float]:
    """
    Pick a GGUF quantization that fits available memory.

    Returns:
        (quant_name, memory_required_gb)
    """
    _check_download_dependencies()
    available_gb, total_gb = get_available_memory_gb()
    logger.debug(
        "System memory: %.1f GB total, %.1f GB available",
        total_gb,
        available_gb,
    )

    usable_gb = available_gb - 2.0
    selected: tuple[str, float, str] | None = None
    for spec in QUANT_SPECS:
        if spec[1] <= usable_gb:
            selected = spec
            break
    if selected is None:
        selected = QUANT_SPECS[-1]
        logger.debug(
            "Limited memory (%.1f GB usable); using smallest quantization %s",
            usable_gb,
            selected[0],
        )

    quant_name, mem_req, desc = selected
    logger.debug(
        "Selected quantization %s (~%.1f GB, %s)%s",
        quant_name,
        mem_req,
        desc,
        " [auto]" if auto_mode else "",
    )
    return quant_name, mem_req


def ensure_model_downloaded(
    *,
    auto_mode: bool = True,
    force_redownload: bool = False,
    quant_name: str | None = None,
) -> Path:
    """
    Ensure a local Phi-4 GGUF model exists, downloading from Hugging Face if needed.

    Returns:
        Path to the GGUF file on disk.

    Raises:
        ModelDownloadError: Missing dependencies or download failure.
    """
    existing = find_model_file()
    if existing and not force_redownload:
        logger.debug("Model already present: %s", existing[1])
        return existing[1]

    _check_download_dependencies()
    from huggingface_hub import hf_hub_download

    if quant_name is None:
        quant_name, mem_req = select_quantization(auto_mode=auto_mode)
    else:
        mem_req = next((m for q, m, _ in QUANT_SPECS if q == quant_name), 3.5)

    model_filename = f"microsoft_Phi-4-mini-instruct-{quant_name}.gguf"
    model_path = MODEL_DIR / model_filename
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    if model_path.exists() and not force_redownload:
        logger.debug("Model already present: %s", model_path)
        return model_path

    logger.info(
        "Downloading %s from %s (~%.1f GB)...",
        model_filename,
        MODEL_REPO,
        mem_req,
    )

    try:
        downloaded_path = hf_hub_download(
            repo_id=MODEL_REPO,
            filename=model_filename,
            local_dir=MODEL_DIR,
            local_dir_use_symlinks=False,
            resume_download=True,
        )
    except Exception as exc:
        raise ModelDownloadError(
            f"模型下载失败: {exc}。"
            f"请检查网络连接，或访问 https://huggingface.co/{MODEL_REPO} 手动下载到 {MODEL_DIR}"
        ) from exc

    path = Path(downloaded_path)
    logger.info("Download complete: %s", path)
    return path


def find_model_file() -> tuple[str, Path] | None:
    """
    Find the downloaded GGUF model file

    Returns:
        (filename_on_hub, local_path) tuple, or None if not found
    """
    if not MODEL_DIR.exists():
        return None

    for quant in QUANT_VERSIONS:
        model_filename = f"microsoft_Phi-4-mini-instruct-{quant}.gguf"
        model_path = MODEL_DIR / model_filename
        if model_path.exists():
            logger.debug("Found model: %s", model_filename)
            return (model_filename, model_path)

    return None


def _collect_yaml_fields(
    yaml_config: dict[str, Any],
) -> list[tuple[str, str, str | None]]:
    """Return (template_field, column_hint, regex) for each mappable field."""
    fields: list[tuple[str, str, str | None]] = []
    for template_field, rules in yaml_config.items():
        if isinstance(template_field, str) and template_field.startswith("_"):
            continue
        if not isinstance(rules, list) or not rules:
            continue
        rule = rules[0]
        if not isinstance(rule, dict):
            continue
        hint = str(rule.get("filed") or template_field)
        regex = rule.get("regex")
        if regex in (None, "None", ""):
            regex = None
        else:
            regex = str(regex)
        fields.append((template_field, hint, regex))
    return fields


class Phi4FieldMatcher:
    """
    Match Google Sheet fields to YAML template fields using Phi-4 via Transformers

    Uses pure Python Transformers library with GGUF support - no compilation required.
    """

    def __init__(self, model_path: str | Path | None = None):
        """
        Initialize Phi-4 field matcher

        Args:
            model_path: Path to local GGUF file. If None, auto-detects under MODEL_DIR.

        Raises:
            FileNotFoundError: If model file doesn't exist
            ImportError: If transformers/gguf/torch are not installed
            ModelLoadError: If GGUF loading fails
        """
        _ensure_gguf_version()

        try:
            import torch  # noqa: F401
            import gguf  # noqa: F401
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise ImportError(
                "缺少 LLM 依赖。请运行 install.bat 重新安装，或手动执行: "
                "pip install torch transformers>=5.0 gguf>=0.10.0 accelerate"
            ) from exc

        hub_filename, local_path = _resolve_gguf_source(model_path)
        logger.debug("Using local GGUF: %s (hub file: %s)", local_path, hub_filename)

        _ensure_gguf_hub_accessible(hub_filename)

        logger.info("Loading Phi-4 model...")

        load_kwargs = {
            "gguf_file": hub_filename,
            "device_map": "cpu",
            "trust_remote_code": True,
            "low_cpu_mem_usage": True,
        }

        try:
            self.tokenizer = AutoTokenizer.from_pretrained(MODEL_REPO, **load_kwargs)
            self.model = AutoModelForCausalLM.from_pretrained(MODEL_REPO, **load_kwargs)
        except Exception as exc:
            raise ModelLoadError(
                f"GGUF 加载失败 ({hub_filename}): {exc}. "
                "请确认已安装 torch、transformers>=5.0、gguf>=0.10.0，"
                "并重新运行 install.bat。"
            ) from exc

        self.model.eval()
        logger.info("Phi-4 model ready")

    def match_sheet_fields_to_yaml(
        self,
        sheet_row: dict[str, str],
        yaml_config: dict[str, Any],
        on_progress: ProgressCallback | None = None,
    ) -> dict[str, str]:
        """Match Sheet field values to YAML template fields, one field at a time."""
        result: dict[str, str] = {}
        for stage, partial in self.iter_match_sheet_fields_to_yaml(
            sheet_row, yaml_config
        ):
            if on_progress:
                on_progress(stage, partial)
            result = partial
        return result

    def iter_match_sheet_fields_to_yaml(
        self,
        sheet_row: dict[str, str],
        yaml_config: dict[str, Any],
    ) -> Iterator[tuple[str, dict[str, str]]]:
        """
        Yield (stage_message, cumulative_matches) after each template field.

        Stages are human-readable status strings suitable for UI display.
        """
        if not sheet_row or not yaml_config:
            yield ("无可用数据", {})
            return

        sheet_columns = list(sheet_row.keys())
        fields = _collect_yaml_fields(yaml_config)
        if not fields:
            yield ("模板无字段", {})
            return

        total = len(fields)
        result: dict[str, str] = {}
        used_columns: set[str] = set()

        yield (f"准备匹配 {total} 个字段（Sheet 共 {len(sheet_columns)} 列）", dict(result))

        for index, (template_field, hint, regex) in enumerate(fields, start=1):
            stage = f"正在匹配 {template_field} ({index}/{total})…"
            yield (stage, dict(result))

            available = [c for c in sheet_columns if c not in used_columns]
            column = self._try_exact_column_match(
                template_field, hint, available
            )

            if column is None:
                column = self._llm_match_column(
                    template_field, hint, sheet_row, available
                )

            if column:
                used_columns.add(column)
                value = str(sheet_row.get(column, "") or "")
                value = self._apply_regex(value, regex)
                result[template_field] = value

            yield (stage, dict(result))

        yield (f"匹配完成：{len(result)}/{total} 个字段", dict(result))

    def match_fields_to_columns(
        self,
        sheet_columns: list[str],
        yaml_fields: list[tuple[str, str]],
        on_progress: ProgressCallback | None = None,
    ) -> dict[str, str | None]:
        """
        Map template fields to sheet column names (no sample values required).

        yaml_fields: list of (template_field, column_hint)
        """
        result: dict[str, str | None] = {}
        total = len(yaml_fields)
        used_columns: set[str] = set()

        if on_progress:
            on_progress(f"准备匹配 {total} 个字段", {})

        for index, (template_field, hint) in enumerate(yaml_fields, start=1):
            stage = f"正在匹配 {template_field} ({index}/{total})…"
            if on_progress:
                on_progress(stage, {k: v or "" for k, v in result.items()})

            available = [c for c in sheet_columns if c not in used_columns]
            column = self._try_exact_column_match(
                template_field, hint, available
            )
            if column is None:
                empty_row = {col: "" for col in available}
                column = self._llm_match_column(
                    template_field, hint, empty_row, available
                )

            result[template_field] = column
            if column:
                used_columns.add(column)

            if on_progress:
                on_progress(stage, {k: v or "" for k, v in result.items()})

        return result

    def _try_exact_column_match(
        self,
        template_field: str,
        hint: str,
        available_columns: list[str],
    ) -> str | None:
        """Case-insensitive column name match using hint then template field name."""
        names = []
        if hint and hint != "?":
            names.append(hint.strip())
        names.append(template_field.strip())

        for name in names:
            name_lower = name.lower()
            for col in available_columns:
                if col.strip().lower() == name_lower:
                    return col
        return None

    def _llm_match_column(
        self,
        template_field: str,
        hint: str,
        sheet_row: dict[str, str],
        available_columns: list[str],
    ) -> str | None:
        """Ask Phi-4 which sheet column best matches a single template field."""
        if not available_columns:
            return None

        try:
            prompt = self._build_single_field_prompt(
                template_field, hint, sheet_row, available_columns
            )
            inputs = self.tokenizer(prompt, return_tensors="pt")
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=64,
                temperature=0.0,
                do_sample=False,
                pad_token_id=self.tokenizer.eos_token_id,
            )
            response_text = self.tokenizer.decode(
                outputs[0], skip_special_tokens=True
            )
            response_text = response_text[len(prompt):].strip()
            logger.debug("Phi-4 field %s response: %s", template_field, response_text)
            return self._parse_column_result(response_text, available_columns)
        except Exception as exc:
            logger.warning(
                "Phi-4 match failed for %s: %s", template_field, exc
            )
            return None

    def _build_single_field_prompt(
        self,
        template_field: str,
        hint: str,
        sheet_row: dict[str, str],
        available_columns: list[str],
    ) -> str:
        """Build a focused prompt for matching one template field to one column."""
        col_lines = []
        for col in available_columns:
            sample = str(sheet_row.get(col, "") or "")
            if len(sample) > 40:
                sample = sample[:37] + "..."
            col_lines.append(f'  - "{col}": "{sample}"')
        cols_str = "\n".join(col_lines)

        hint_line = ""
        if hint and hint != "?":
            hint_line = f'\nExpected column hint: "{hint}"'

        return f"""Match one template field to a Google Sheet column.

Sheet columns (with sample values):
{cols_str}

Template field to match: "{template_field}"{hint_line}

Reply with JSON only: {{"column": "<exact column name>"}} or {{"column": null}} if no match.
JSON:"""

    def _parse_column_result(
        self,
        response_text: str,
        available_columns: list[str],
    ) -> str | None:
        """Parse LLM response into a validated sheet column name."""
        text = response_text.strip()

        json_match = re.search(
            r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL
        )
        if json_match:
            text = json_match.group(1)

        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group(0))
                if isinstance(parsed, dict):
                    col = parsed.get("column")
                    if col is None or str(col).upper() == "NONE":
                        return None
                    col_str = str(col).strip().strip('"')
                    for available in available_columns:
                        if available.strip().lower() == col_str.lower():
                            return available
            except json.JSONDecodeError:
                pass

        if text.upper() in ("NONE", "NULL", "无", "无匹配"):
            return None

        col_str = text.strip().strip('"').strip("'")
        for available in available_columns:
            if available.strip().lower() == col_str.lower():
                return available
        return None

    def _apply_regex(self, value: str, regex_pattern: str | None) -> str:
        """Apply a regex extraction pattern to a matched value."""
        if not regex_pattern or not value:
            return value
        try:
            match = re.search(regex_pattern, value)
            if match:
                return match.group(1) if match.groups() else match.group(0)
        except re.error as exc:
            logger.warning("Invalid regex %s: %s", regex_pattern, exc)
        return value


def create_field_matcher(model_path: str | Path | None = None) -> Phi4FieldMatcher | None:
    """Create field matcher instance, returning None if model is not available."""
    global _last_load_error
    _last_load_error = None
    try:
        return Phi4FieldMatcher(model_path)
    except (FileNotFoundError, ImportError, ModelLoadError) as exc:
        _last_load_error = str(exc)
        logger.warning("Phi-4 model not available: %s", exc)
        return None
