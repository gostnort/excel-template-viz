"""
Gemma 4 Field Matcher (Transformers + GGUF)

Uses google/gemma-4-E4B-it-qat-q4_0-gguf for sheet-to-YAML field mapping.
Text-only inference via Transformers 5.x GGUF support (pure Python, no compilation).
"""
import importlib.metadata
import json
import logging
import re
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Literal, TypedDict

logger = logging.getLogger(__name__)

ProgressStage = Literal[
    "download",
    "load_tokenizer",
    "load_model",
    "warmup",
    "match",
]

ProgressCallback = Callable[[ProgressStage, int, int, str], None]


class SourceColumnData(TypedDict):
    """Source column info sent to batch LLM prompt."""

    index: int
    header: str
    data: list[str]



class FieldMappingResult(TypedDict):
    """Field mapping output from batch LLM parsing."""

    filed: str
    index: int
    confidence_reason: str



class TransformationRule(TypedDict):
    """Transformation rule inferred by LLM for format mismatches."""

    source_column: str
    target_field: str
    extraction_method: str
    pattern: str
    extract_group: int | None
    explanation: str


_last_load_error: str | None = None
_cached_matcher: "Gemma4FieldMatcher | None" = None
_cached_matcher_lock = None

MODEL_REPO = "google/gemma-4-E4B-it-qat-q4_0-gguf"
MODEL_DIR = Path("models/gemma4")
MODEL_WEIGHT_FILE = "gemma-4-E4B_q4_0-it.gguf"

MODEL_FILES = [
    MODEL_WEIGHT_FILE,
]

MIN_MEMORY_GB = 5.0

DEFAULT_GENERATE_MAX_TIME_S = 600
SLOW_GENERATE_WARN_S = 120



class ModelDownloadError(Exception):
    """Model download failed; message is user-facing and actionable."""



class ModelLoadError(Exception):
    """Gemma 4 model could not be loaded; message is user-facing and actionable."""



class InsufficientMemoryError(Exception):
    """Insufficient memory to load model; message is user-facing and actionable."""


def get_last_load_error() -> str | None:
    """Return the most recent model load failure message, if any."""
    return _last_load_error


def get_available_memory_gb() -> float:
    """Return available system memory in GB."""
    try:
        import psutil
        return psutil.virtual_memory().available / (1024**3)
    except ImportError:
        raise ImportError(
            f"缺少 psutil 依赖包。"
            f"当前 Python: {sys.executable}。"
            f"请执行: {_pip_install_hint('psutil>=5.9.0')}"
        )


def _pip_install_hint(*packages: str) -> str:
    """Return a pip command using the current interpreter."""
    quoted_exe = f'"{sys.executable}"'
    package_list = " ".join(packages)
    return f"{quoted_exe} -m pip install {package_list}"


def _check_llm_dependencies() -> None:
    """Verify packages required to load Gemma 4 via transformers."""
    exe = sys.executable
    missing: list[str] = []
    try:
        import transformers  # noqa: F401
    except ImportError:
        missing.append("transformers>=5.0")
    try:
        import torch  # noqa: F401
    except ImportError:
        missing.append("torch")
    try:
        import psutil  # noqa: F401
    except ImportError:
        missing.append("psutil")
    if missing:
        raise ImportError(
            f"缺少 LLM 依赖包: {', '.join(missing)}。"
            f"当前 Python: {exe}。"
            f"请执行: {_pip_install_hint(*missing)}"
        )


def _root_exception(exc: BaseException) -> BaseException:
    """Return the deepest exception cause."""
    current = exc
    while current.__cause__ is not None:
        current = current.__cause__
    return current


def _format_model_load_error(exc: Exception) -> str:
    """Build an actionable message from a model load failure."""
    root = _root_exception(exc)
    root_msg = str(root)
    exe = sys.executable
    if isinstance(root, ModuleNotFoundError) and root.name:
        return (
            f"Gemma 4 加载失败: 缺少模块 {root.name}。"
            f"当前 Python: {exe}。"
            f"请执行: {_pip_install_hint(root.name)}"
        )
    return (
        f"Gemma 4 加载失败: {exc}。"
        f"当前 Python: {exe}。"
        "请确认已下载模型 (python app/download_gemma4_model.py)，并执行: "
        f"{_pip_install_hint('transformers>=5.0', 'torch', 'psutil>=5.9.0')}"
    )


def _check_download_dependencies() -> None:
    """Verify packages required for Hugging Face model download."""
    missing: list[str] = []
    try:
        import huggingface_hub  # noqa: F401
    except ImportError:
        missing.append("huggingface-hub")
    if missing:
        packages = " ".join(missing)
        raise ModelDownloadError(
            f"缺少依赖包: {', '.join(missing)}。"
            f"请运行 install.bat 重新安装，或手动执行: pip install {packages}"
        )


def find_model_file() -> Path | None:
    """Return local model directory when GGUF file is present, else None."""
    weight_path = MODEL_DIR / MODEL_WEIGHT_FILE
    if weight_path.is_file():
        logger.debug("Found Gemma 4 GGUF model at %s", MODEL_DIR)
        return MODEL_DIR.resolve()
    return None


def _ensure_gguf_version() -> None:
    """Work around gguf package missing __version__ (breaks transformers GGUF check)."""
    import gguf
    if getattr(gguf, "__version__", None):
        return
    try:
        gguf.__version__ = importlib.metadata.version("gguf")
    except importlib.metadata.PackageNotFoundError:
        gguf.__version__ = "0.10.0"


def _ensure_gguf_hub_accessible(hub_filename: str, local_path: Path | None = None) -> None:
    """Ensure GGUF loads via MODEL_REPO + gguf_file (HF hub cache), not a raw file path."""
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
    resolved = local_path if local_path and local_path.is_file() else None
    canonical = MODEL_DIR / hub_filename
    if resolved is None and canonical.is_file():
        resolved = canonical
    if resolved is None or not resolved.is_file():
        raise FileNotFoundError(
            f"GGUF file not found: {canonical}. "
            f"Run: python app/download_gemma4_model.py"
        )
    hf_hub_download(
        repo_id=MODEL_REPO,
        filename=hub_filename,
        local_dir=MODEL_DIR,
        local_files_only=True,
    )


def _resolve_gguf_source(model_path: str | Path | None) -> tuple[str, Path]:
    """Resolve (hub_filename, local_path) for GGUF weights."""
    if model_path is not None:
        local_path = Path(model_path).resolve()
        if local_path.is_dir():
            local_path = local_path / MODEL_WEIGHT_FILE
        if not local_path.is_file():
            raise FileNotFoundError(
                f"Model file not found: {local_path}. "
                f"Run: python app/download_gemma4_model.py"
            )
        return local_path.name, local_path
    model_dir = _resolve_model_dir(None)
    local_path = model_dir / MODEL_WEIGHT_FILE
    return MODEL_WEIGHT_FILE, local_path


def _resolve_model_dir(model_path: str | Path | None) -> Path:
    """Resolve directory containing a complete local Gemma 4 checkpoint."""
    if model_path is not None:
        local_dir = Path(model_path).resolve()
        if local_dir.is_file():
            local_dir = local_dir.parent
        weight = local_dir / MODEL_WEIGHT_FILE
        if not weight.is_file():
            raise FileNotFoundError(
                f"Model weights not found: {weight}. "
                f"Run: python app/download_gemma4_model.py"
            )
        return local_dir
    found = find_model_file()
    if found:
        return found
    raise FileNotFoundError(
        f"No Gemma 4 model in {MODEL_DIR.resolve()}. "
        f"Download with: python app/download_gemma4_model.py"
    )


def ensure_model_downloaded(
    *,
    force_redownload: bool = False,
    on_progress: ProgressCallback | None = None,
) -> Path:
    """
    Ensure local Gemma 4 GGUF weights exist, downloading from Hugging Face if needed.

    Returns:
        Path to the local model directory.

    Raises:
        ModelDownloadError: Missing dependencies or download failure.
    """
    # Return early when local GGUF weights are already present
    existing = find_model_file()
    if existing and not force_redownload:
        logger.debug("Model already present: %s", existing)
        return existing
    _check_download_dependencies()
    from huggingface_hub import hf_hub_download
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    total_files = len(MODEL_FILES)
    logger.info("Downloading Gemma 4 GGUF model from %s...", MODEL_REPO)
    try:
        from tqdm.auto import tqdm
        class DownloadProgressTqdm(tqdm):
            """Forward hub download progress to callback."""
            def __init__(
                self,
                callback: ProgressCallback | None,
                file_index: int,
                file_total: int,
                filename: str,
                *args,
                **kwargs,
            ):
                super().__init__(*args, **kwargs)
                self.callback = callback
                self.file_index = file_index
                self.file_total = file_total
                self.filename = filename


            def update(self, n: int = 1):
                super().update(n)
                if not self.callback:
                    return
                current = self.n
                total = self.total or 1
                speed = self.format_dict.get("rate", 0) or 0
                msg = (
                    f"下载 {self.filename}… "
                    f"{current / 1024 / 1024:.1f}MB / {total / 1024 / 1024:.1f}MB "
                    f"({speed / 1024 / 1024:.1f}MB/s)"
                )
                overall = self.file_index * total + current
                overall_total = self.file_total * total
                self.callback("download", overall, overall_total, msg)
        # Download each listed weight file from Hugging Face
        for index, filename in enumerate(MODEL_FILES):
            dest = MODEL_DIR / filename
            if dest.exists() and not force_redownload:
                continue
            if on_progress:
                on_progress(
                    "download",
                    index,
                    total_files,
                    f"下载 {filename} ({index + 1}/{total_files})…",
                )
            tqdm_class = (
                lambda *args, fn=filename, idx=index, **kwargs: DownloadProgressTqdm(
                    on_progress, idx, total_files, fn, *args, **kwargs
                )
                if on_progress
                else tqdm
            )
            hf_hub_download(
                repo_id=MODEL_REPO,
                filename=filename,
                local_dir=MODEL_DIR,
                tqdm_class=tqdm_class,
            )
    except Exception as exc:
        raise ModelDownloadError(
            f"模型下载失败: {exc}。"
            f"请检查网络连接，或访问 https://huggingface.co/{MODEL_REPO} "
            f"手动下载到 {MODEL_DIR}"
        ) from exc
    model_dir = find_model_file()
    if model_dir is None:
        raise ModelDownloadError(f"下载完成但未找到 {MODEL_WEIGHT_FILE}")
    logger.info("Download complete: %s", model_dir)
    return model_dir


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


def build_batch_field_mapping_prompt(
    source_columns_data: list[SourceColumnData],
    yaml_field_names: list[str],
) -> str:
    """Build one-shot batch mapping prompt without loading the model."""
    source_json = json.dumps(source_columns_data, ensure_ascii=False, indent=2)
    fields_json = json.dumps(yaml_field_names, ensure_ascii=False, indent=2)
    return f"""You map Google Sheet source columns to template YAML fields for a paste/lookup config.
## Source columns (user-selected; header + sample rows)
Each column includes at least 5 sample values from the connected sheet.
{source_json}
## Template fields (YAML top-level keys)
{fields_json}
## Rules
1. For each template field, pick the best matching source "header" using BOTH header text and the "data" values.
2. "index" MUST be the source column's index from Source columns (0-based). Use -1 when filed is null.
3. One source column may map to multiple template fields only if they share the same cell (e.g. MM/DD/Receiving Date from one date column).
4. Do not invent column names. Do not map unrelated fields just to use every column.
5. For each mapping, provide "confidence_reason" explaining why this match was made.
Reply with JSON only (no markdown, no explanation):
{{
  "mappings": [
    {{
      "field": "P.O. No.",
      "filed": "PO",
      "index": 0,
      "confidence_reason": "Header 'PO' strongly matches field name, sample values are numeric IDs"
    }},
    {{
      "field": "Container No.",
      "filed": "Container#",
      "index": 1,
      "confidence_reason": "Header matches pattern, samples show container format (MSCU1234567)"
    }},
    {{
      "field": "Container Seal No.",
      "filed": null,
      "index": -1,
      "confidence_reason": "No source column contains seal number data"
    }}
  ]
}}"""


def prepare_batch_input(
    source_columns: list[str],
    sample_rows: list[dict[str, str]],
    min_rows: int = 5,
) -> list[SourceColumnData]:
    """Prepare batch input payload with at least min_rows sample values per column."""
    if len(sample_rows) < min_rows:
        raise ValueError(f"At least {min_rows} sample rows required, got {len(sample_rows)}")
    result: list[SourceColumnData] = []
    rows = sample_rows[:min_rows]
    for idx, header in enumerate(source_columns):
        data = [str(row.get(header, "") or "") for row in rows]
        result.append({"index": idx, "header": header, "data": data})
    return result


class Gemma4FieldMatcher:
    """Match Google Sheet fields to YAML template fields using Gemma 4 GGUF."""

    _SYSTEM_PROMPT = (
        "You are a precise data-mapping assistant for spreadsheet column matching. "
        "Follow instructions exactly. When asked for JSON, output valid JSON only "
        "with no markdown fences or extra commentary."
    )

    def __init__(
        self,
        model_path: str | Path | None = None,
        on_progress: ProgressCallback | None = None,
    ):
        # Load tokenizer and GGUF weights via hub filename
        if on_progress:
            on_progress("load_model", 1, 10, "检查依赖")
        _ensure_gguf_version()
        _check_llm_dependencies()
        from transformers import AutoModelForCausalLM, AutoTokenizer
        if on_progress:
            on_progress("load_model", 2, 10, "检查内存")
        available_memory = get_available_memory_gb()
        if available_memory < MIN_MEMORY_GB:
            raise InsufficientMemoryError(
                f"内存不足: 可用 {available_memory:.2f} GB，"
                f"需要至少 {MIN_MEMORY_GB:.1f} GB。"
                "请关闭其他应用程序后重试。"
            )
        if on_progress:
            on_progress("load_model", 3, 10, "加载 tokenizer")
        logger.debug("Loading tokenizer from google/gemma-4-E4B-it")
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(
                "google/gemma-4-E4B-it",
                trust_remote_code=True
            )
        except Exception:
            logger.warning("Failed to load tokenizer from base model, trying GGUF repo")
            self.tokenizer = AutoTokenizer.from_pretrained(
                MODEL_REPO,
                trust_remote_code=True
            )
        if on_progress:
            on_progress("load_model", 5, 10, "定位模型文件")
        hub_filename, local_path = _resolve_gguf_source(model_path)
        logger.debug("Using local GGUF: %s (hub file: %s)", local_path, hub_filename)
        if on_progress:
            on_progress("load_model", 6, 10, "确认 Hub 缓存")
        _ensure_gguf_hub_accessible(hub_filename, local_path)
        load_kwargs = {
            "gguf_file": hub_filename,
            "device_map": "cpu",
            "trust_remote_code": True,
            "low_cpu_mem_usage": True,
        }
        if on_progress:
            on_progress("load_model", 7, 10, "加载 GGUF 模型")
        try:
            self.model = AutoModelForCausalLM.from_pretrained(MODEL_REPO, **load_kwargs)
            self.model.eval()
        except Exception as exc:
            raise ModelLoadError(_format_model_load_error(exc)) from exc
        if on_progress:
            on_progress("load_model", 10, 10, "模型就绪")
        logger.info("Gemma 4 GGUF model ready (Transformers)")


    def _generate(
        self,
        user_prompt: str,
        max_new_tokens: int = 512,
        temperature: float = 0.0,
        max_time: float | None = DEFAULT_GENERATE_MAX_TIME_S,
    ) -> str:
        """Generate assistant text using the Gemma 4 chat template."""
        messages = [
            {"role": "system", "content": self._SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        prompt_text = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self.tokenizer(prompt_text, return_tensors="pt")
        prompt_tokens = inputs.input_ids.shape[1]
        logger.info(
            "Gemma4 generate start: prompt_tokens=%d max_new_tokens=%d",
            prompt_tokens,
            max_new_tokens,
        )
        started = time.monotonic()
        try:
            import torch
            generate_kwargs: dict[str, Any] = {
                **inputs,
                "max_new_tokens": max_new_tokens,
                "do_sample": temperature > 0,
                "pad_token_id": self.tokenizer.eos_token_id,
            }
            if temperature > 0:
                generate_kwargs["temperature"] = temperature
            if max_time is not None:
                generate_kwargs["max_time"] = max_time
            with torch.no_grad():
                outputs = self.model.generate(**generate_kwargs)
        except Exception as exc:
            logger.error("Gemma4 generation failed: %s", exc)
            raise
        elapsed = time.monotonic() - started
        response_text = self.tokenizer.decode(
            outputs[0][prompt_tokens:], skip_special_tokens=True
        ).strip()
        new_tokens = outputs.shape[1] - prompt_tokens
        logger.info(
            "Gemma4 generate done in %.1fs (new_tokens=%d, prompt_tokens=%d)",
            elapsed,
            new_tokens,
            prompt_tokens,
        )
        if elapsed >= SLOW_GENERATE_WARN_S:
            logger.warning(
                "Gemma4 generation took %.1fs on CPU; consider fewer columns/fields",
                elapsed,
            )
        return response_text


    def _parse_batch_mapping_result(
        self,
        response_text: str,
        source_columns: list[str],
        expected_fields: list[str],
    ) -> dict[str, FieldMappingResult]:
        """Parse batch JSON response into validated field mapping dictionary."""
        # Extract mappings JSON and validate each field entry
        json_match = re.search(r"\{[\s\S]*\"mappings\"[\s\S]*\}", response_text)
        if not json_match:
            logger.warning("No valid batch JSON found in LLM response")
            return {
                field: {
                    "filed": "?",
                    "index": -1,
                    "confidence_reason": "No valid JSON found in LLM response",
                }
                for field in expected_fields
            }
        try:
            parsed = json.loads(json_match.group(0))
        except json.JSONDecodeError as exc:
            logger.warning("Batch mapping JSON parse failed: %s", exc)
            return {
                field: {
                    "filed": "?",
                    "index": -1,
                    "confidence_reason": f"JSON parse failed: {exc}",
                }
                for field in expected_fields
            }
        mappings_list = parsed.get("mappings", [])
        header_by_norm = {h.strip().lower(): h for h in source_columns}
        result: dict[str, FieldMappingResult] = {}
        for item in mappings_list:
            if not isinstance(item, dict):
                continue
            field = str(item.get("field", "")).strip()
            if field not in expected_fields:
                continue
            filed = item.get("filed")
            reason = str(item.get("confidence_reason", "") or "No reason provided").strip()
            if filed is None or str(filed).strip().lower() in {"null", "none", ""}:
                result[field] = {"filed": "?", "index": -1, "confidence_reason": reason}
                continue
            filed_str = str(filed).strip()
            canonical = header_by_norm.get(filed_str.lower())
            if canonical is None:
                result[field] = {
                    "filed": "?",
                    "index": -1,
                    "confidence_reason": f"{reason} (invalid source column: {filed_str})",
                }
                continue
            idx = source_columns.index(canonical)
            index_raw = item.get("index", -1)
            if isinstance(index_raw, int) and 0 <= index_raw < len(source_columns):
                if source_columns[index_raw] == canonical:
                    idx = index_raw
            result[field] = {"filed": canonical, "index": idx, "confidence_reason": reason}
        for field in expected_fields:
            result.setdefault(
                field,
                {"filed": "?", "index": -1, "confidence_reason": "No mapping returned by model"},
            )
        return result


    def batch_match_all_fields(
        self,
        source_columns_data: list[SourceColumnData],
        yaml_field_names: list[str],
        *,
        prompt: str | None = None,
    ) -> tuple[dict[str, FieldMappingResult], str, str]:
        """Run one LLM call to map all template fields to source columns."""
        prompt_text = prompt or build_batch_field_mapping_prompt(
            source_columns_data,
            yaml_field_names,
        )
        response = self._generate(prompt_text, max_new_tokens=512, temperature=0.0)
        source_columns = [col["header"] for col in source_columns_data]
        mappings = self._parse_batch_mapping_result(response, source_columns, yaml_field_names)
        return mappings, prompt_text, response


    def _infer_expected_format(self, field_name: str) -> str:
        """Infer expected format from field name for mismatch detection."""
        field_lower = field_name.strip().lower()
        if field_lower in {"mm", "month"}:
            return "month as integer (e.g., 6)"
        if field_lower in {"dd", "day"}:
            return "day as integer (e.g., 2)"
        if field_lower in {"yyyy", "year"}:
            return "year as integer (e.g., 2026)"
        if "date" in field_lower:
            return "date string (e.g., '6/2/2026' or '2026-06-02')"
        if "no" in field_lower or "number" in field_lower or "id" in field_lower:
            return "alphanumeric ID"
        return "text value"


    def _matches_expected_format(self, value: str, expected_format: str) -> bool:
        """Simple format matching heuristic for mismatch detection."""
        v = value.strip()
        if not v:
            return False
        if "integer" in expected_format:
            return bool(re.match(r"^\d+$", v))
        if "date" in expected_format:
            return bool(re.search(r"\d+[/-]\d+", v))
        if "alphanumeric id" in expected_format.lower():
            return bool(re.match(r"^[A-Za-z0-9]+$", v))
        return True


    def detect_format_mismatches(
        self,
        mappings: dict[str, FieldMappingResult],
        sample_rows: list[dict[str, str]],
    ) -> dict[str, list[tuple[str, str]]]:
        """Detect fields whose mapped sample values do not match expected format."""
        mismatches: dict[str, list[tuple[str, str]]] = {}
        fields_by_column: dict[str, list[str]] = {}
        for field, mapping in mappings.items():
            filed = mapping.get("filed", "?")
            if filed and filed != "?":
                fields_by_column.setdefault(filed, []).append(field)
        for source_column, fields in fields_by_column.items():
            sample_values = [str(row.get(source_column, "") or "") for row in sample_rows[:5]]
            if not sample_values:
                continue
            for field in fields:
                expected = self._infer_expected_format(field)
                matches = sum(
                    1 for val in sample_values if self._matches_expected_format(val, expected)
                )
                if matches < max(1, int(len(sample_values) * 0.5)):
                    mismatches.setdefault(source_column, []).append((field, expected))
        return mismatches


    def _build_transformation_inference_prompt(
        self,
        source_column: str,
        sample_values: list[str],
        target_fields: list[tuple[str, str]],
    ) -> str:
        """Build second-stage prompt to infer transformations for mismatched formats."""
        samples_json = json.dumps(sample_values, ensure_ascii=False, indent=2)
        fields_info = "\n".join(
            f'{idx + 1}. "{name}" - expects {fmt}'
            for idx, (name, fmt) in enumerate(target_fields)
        )
        return f"""Given a source column with sample values, infer extraction patterns for target fields.
## Source Column
Name: "{source_column}"
Sample Values ({len(sample_values)} rows):
{samples_json}
## Target Fields
{fields_info}
## Task
Provide extraction instructions for each target field that can be derived from this source column.
For each extraction:
1. Identify the extraction method: "regex" (for pattern matching), "split" (for string splitting), "replace" (for simple replacements), or "constant" (for fixed values)
2. For regex: Provide the pattern with capture groups, and specify which group to extract
3. For split: Provide the delimiter and which part to take
4. For replace: Provide search/replace pairs
5. Explain your reasoning
## Rules
- Use standard Python regex syntax
- Test your pattern mentally against the sample values
- If a field cannot be extracted from this column, omit it from the result
- Prefer simple patterns over complex ones
- Escape special regex characters
Reply with JSON only (no markdown, no explanation):
{{
  "transformations": [
    {{
      "source_column": "{source_column}",
      "target_field": "field_name",
      "extraction_method": "regex",
      "pattern": "regex_pattern_here",
      "extract_group": 1,
      "explanation": "Your reasoning here"
    }}
  ]
}}"""


    def _parse_transformation_result(
        self,
        response_text: str,
        source_column: str,
    ) -> list[TransformationRule]:
        """Parse and minimally validate transformation JSON from LLM response."""
        json_match = re.search(r"\{[\s\S]*\"transformations\"[\s\S]*\}", response_text)
        if not json_match:
            return []
        try:
            parsed = json.loads(json_match.group(0))
        except json.JSONDecodeError:
            return []
        rules: list[TransformationRule] = []
        for item in parsed.get("transformations", []):
            if not isinstance(item, dict):
                continue
            method = str(item.get("extraction_method", "")).strip().lower()
            if method not in {"regex", "split", "replace", "constant"}:
                continue
            target_field = str(item.get("target_field", "")).strip()
            pattern = str(item.get("pattern", "") or "")
            if not target_field or (method == "regex" and not pattern):
                continue
            raw_group = item.get("extract_group")
            group = raw_group if isinstance(raw_group, int) else None
            rules.append(
                {
                    "source_column": str(item.get("source_column", source_column) or source_column),
                    "target_field": target_field,
                    "extraction_method": method,
                    "pattern": pattern,
                    "extract_group": group,
                    "explanation": str(item.get("explanation", "") or ""),
                }
            )
        return rules


    def validate_transformation(
        self,
        transformation: TransformationRule,
        sample_values: list[str],
    ) -> tuple[bool, float, list[str]]:
        """Validate transformation by applying it to sample values."""
        method = transformation["extraction_method"]
        extracted: list[str] = []
        success_count = 0
        if not sample_values:
            return False, 0.0, extracted
        if method == "regex":
            try:
                compiled = re.compile(transformation["pattern"])
            except re.error:
                return False, 0.0, []
            group = transformation.get("extract_group") or 0
            for value in sample_values:
                match = compiled.match(value)
                if not match:
                    extracted.append("")
                    continue
                try:
                    extracted_val = match.group(group)
                except IndexError:
                    extracted.append("")
                    continue
                extracted.append(extracted_val)
                success_count += 1
        else:
            return False, 0.0, []
        success_rate = success_count / len(sample_values)
        return success_rate >= 0.5, success_rate, extracted


    def infer_transformations_for_mismatches(
        self,
        mismatches: dict[str, list[tuple[str, str]]],
        sample_rows: list[dict[str, str]],
    ) -> dict[str, list[TransformationRule]]:
        """Infer and validate transformations for mismatched source columns."""
        result: dict[str, list[TransformationRule]] = {}
        for source_column, target_fields in mismatches.items():
            sample_values = [str(row.get(source_column, "") or "") for row in sample_rows[:5]]
            prompt = self._build_transformation_inference_prompt(
                source_column,
                sample_values,
                target_fields,
            )
            response = self._generate(prompt, max_new_tokens=512, temperature=0.0)
            parsed = self._parse_transformation_result(response, source_column)
            valid_rules: list[TransformationRule] = []
            for rule in parsed:
                ok, _, _ = self.validate_transformation(rule, sample_values)
                if ok:
                    valid_rules.append(rule)
            if valid_rules:
                result[source_column] = valid_rules
        return result


    def match_sheet_fields_to_yaml(
        self,
        sheet_row: dict[str, str],
        yaml_config: dict[str, Any],
        on_progress: ProgressCallback | None = None,
    ) -> dict[str, str]:
        """Match Sheet field values to YAML template fields, one field at a time."""
        result: dict[str, str] = {}
        for stage, partial in self.iter_match_sheet_fields_to_yaml(sheet_row, yaml_config):
            if on_progress:
                on_progress(stage, partial)
            result = partial
        return result


    def iter_match_sheet_fields_to_yaml(
        self,
        sheet_row: dict[str, str],
        yaml_config: dict[str, Any],
        on_progress: ProgressCallback | None = None,
    ) -> Iterator[tuple[str, dict[str, str]]]:
        """Yield (stage_message, cumulative_matches) after each template field."""
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
        # Match each template field to one sheet column
        for index, (template_field, hint, regex) in enumerate(fields, start=1):
            stage = f"正在匹配 {template_field} ({index}/{total})…"
            yield (stage, dict(result))
            if on_progress:
                on_progress("match", index, total, stage)
            available = [c for c in sheet_columns if c not in used_columns]
            column = self._try_exact_column_match(template_field, hint, available)
            if column is None:
                column = self._llm_match_column(template_field, hint, sheet_row, available)
            if column:
                used_columns.add(column)
                value = str(sheet_row.get(column, "") or "")
                value = self._apply_regex(value, regex)
                result[template_field] = value
            yield (stage, dict(result))
        final_stage = f"匹配完成：{len(result)}/{total} 个字段"
        if on_progress:
            on_progress("match", total, total, final_stage)
        yield (final_stage, dict(result))


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
        """Ask Gemma 4 which sheet column best matches a single template field."""
        if not available_columns:
            return None
        try:
            prompt = self._build_single_field_prompt(
                template_field, hint, sheet_row, available_columns
            )
            response_text = self._generate(prompt, max_new_tokens=128, temperature=0.0)
            logger.debug("Gemma 4 field %s response: %s", template_field, response_text)
            return self._parse_column_result(response_text, available_columns)
        except Exception as exc:
            logger.warning("Gemma 4 match failed for %s: %s", template_field, exc)
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
Reply with JSON only: {{"column": "<exact column name>"}} or {{"column": null}} if no match."""


    def _parse_column_result(
        self,
        response_text: str,
        available_columns: list[str],
    ) -> str | None:
        """Parse LLM response into a validated sheet column name."""
        text = response_text.strip()
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if json_match:
            text = json_match.group(1)
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
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


def create_field_matcher(
    model_path: str | Path | None = None,
    on_progress: ProgressCallback | None = None,
) -> Gemma4FieldMatcher | None:
    """Create field matcher instance with progress reporting."""
    global _last_load_error
    _last_load_error = None
    try:
        return Gemma4FieldMatcher(model_path, on_progress=on_progress)
    except (FileNotFoundError, ImportError, ModelLoadError) as exc:
        _last_load_error = str(exc)
        logger.warning("Gemma 4 model not available: %s", exc)
        return None


def get_or_create_field_matcher(
    on_progress: ProgressCallback | None = None,
) -> Gemma4FieldMatcher | None:
    """Get or create field matcher (singleton pattern, thread-safe)."""
    global _cached_matcher, _cached_matcher_lock
    if _cached_matcher is not None:
        logger.info("Reusing cached Gemma 4 model")
        if on_progress:
            on_progress("load_model", 10, 10, "模型已就绪（使用缓存）")
        return _cached_matcher
    if _cached_matcher_lock is None:
        import threading
        _cached_matcher_lock = threading.Lock()
    with _cached_matcher_lock:
        if _cached_matcher is not None:
            return _cached_matcher
        logger.info("Loading Gemma 4 model (first use)")
        _cached_matcher = create_field_matcher(on_progress=on_progress)
        return _cached_matcher


def clear_matcher_cache() -> None:
    """Clear cached matcher instance (for testing or manual reload)."""
    global _cached_matcher
    _cached_matcher = None
    logger.info("Cleared Gemma 4 model cache")
