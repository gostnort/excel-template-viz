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
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, TypedDict

logger = logging.getLogger(__name__)

# Progress stages
ProgressStage = Literal[
    "download",        # 模型下载
    "load_tokenizer",  # 加载 Tokenizer
    "load_model",      # 加载模型权重
    "warmup",          # 模型预热
    "match"            # 字段匹配
]

# Progress callback signature: (stage, current, total, message)
ProgressCallback = Callable[[ProgressStage, int, int, str], None]


@dataclass
class FieldMatchResult:
    """Single field matching result"""
    filed: str              # Sheet column name
    index: int              # Column index (base 0)
    regex: str | None       # Extraction regex
    similarity: float       # Semantic similarity score
    matched_value: str      # Matched cell value
    regex_suggested: bool   # Whether regex was auto-suggested
    ID: bool = False        # Whether this is an ID field


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


# Last load failure message for UI feedback (set by create_field_matcher).
_last_load_error: str | None = None

# Cached matcher instance (singleton pattern)
_cached_matcher: "Phi4FieldMatcher | None" = None
_cached_matcher_lock = None  # Will be initialized when needed

# Model configuration (GGUF weights + base model tokenizer)
MODEL_REPO = "Vocabook/Phi-4-mini-instruct-GGUF"
TOKENIZER_REPO = "microsoft/Phi-4-mini-instruct"
MODEL_DIR = Path("models/phi4")
LEGACY_GGUF_PREFIX = "microsoft_Phi-4-mini-instruct-"

# Quantization versions available on Vocabook/Phi-4-mini-instruct-GGUF (preference order)
QUANT_VERSIONS = ["Q8_0", "Q6_K", "Q4_K_M", "Q3_K_L"]

# (name, memory_gb, description)
QUANT_SPECS: list[tuple[str, float, str]] = [
    ("Q8_0", 5.5, "Best quality, highest memory"),
    ("Q6_K", 4.5, "Very good quality"),
    ("Q4_K_M", 3.5, "Balanced (recommended)"),
    ("Q3_K_L", 3.0, "Lower quality, smaller"),
]


def gguf_filename(quant_name: str) -> str:
    """Hub/local filename for a Vocabook Phi-4 GGUF checkpoint."""
    return f"Phi-4-mini-instruct-{quant_name}.gguf"

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
    on_progress: ProgressCallback | None = None,
) -> Path:
    """
    Ensure a local Phi-4 GGUF model exists, downloading from Hugging Face if needed.

    Args:
        auto_mode: Auto-select quantization based on available memory
        force_redownload: Force re-download even if file exists
        quant_name: Specific quantization to download (overrides auto_mode)
        on_progress: Progress callback function

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

    model_filename = gguf_filename(quant_name)
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
        from tqdm.auto import tqdm

        class DownloadProgressTqdm(tqdm):
            """Custom tqdm class that forwards progress to callback."""

            def __init__(self, callback: ProgressCallback | None, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.callback = callback

            def update(self, n: int = 1):
                super().update(n)
                if self.callback:
                    current = self.n
                    total = self.total or 1
                    speed = self.format_dict.get("rate", 0) or 0
                    msg = f"下载中... {current/1024/1024:.1f}MB / {total/1024/1024:.1f}MB ({speed/1024/1024:.1f}MB/s)"
                    self.callback("download", current, total, msg)

        tqdm_class = (
            lambda *args, **kwargs: DownloadProgressTqdm(on_progress, *args, **kwargs)
            if on_progress
            else tqdm(*args, **kwargs)
        )

        downloaded_path = hf_hub_download(
            repo_id=MODEL_REPO,
            filename=model_filename,
            local_dir=MODEL_DIR,
            local_dir_use_symlinks=False,
            resume_download=True,
            tqdm_class=tqdm_class,
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
        model_filename = gguf_filename(quant)
        model_path = MODEL_DIR / model_filename
        if model_path.exists():
            logger.debug("Found model: %s", model_filename)
            return (model_filename, model_path)

    for quant in QUANT_VERSIONS:
        legacy_filename = f"{LEGACY_GGUF_PREFIX}{quant}.gguf"
        legacy_path = MODEL_DIR / legacy_filename
        if legacy_path.exists():
            logger.debug("Found legacy model: %s", legacy_filename)
            return (legacy_filename, legacy_path)

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


class Phi4FieldMatcher:
    """
    Match Google Sheet fields to YAML template fields using Phi-4 via Transformers

    Uses pure Python Transformers library with GGUF support - no compilation required.
    """

    def __init__(
        self,
        model_path: str | Path | None = None,
        on_progress: ProgressCallback | None = None,
    ):
        """
        Initialize Phi-4 field matcher with progress reporting

        Args:
            model_path: Path to local GGUF file. If None, auto-detects under MODEL_DIR.
            on_progress: Progress callback function

        Raises:
            FileNotFoundError: If model file doesn't exist
            ImportError: If transformers/gguf/torch are not installed
            ModelLoadError: If GGUF loading fails
        """
        # Stage 1: Check GGUF version (10%)
        if on_progress:
            on_progress("load_model", 1, 10, "检查 GGUF 版本")
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

        # Stage 2: Resolve model file (20%)
        if on_progress:
            on_progress("load_model", 2, 10, "定位模型文件")
        hub_filename, local_path = _resolve_gguf_source(model_path)
        logger.debug("Using local GGUF: %s (hub file: %s)", local_path, hub_filename)

        # Stage 3: Ensure Hub cache (30%)
        if on_progress:
            on_progress("load_model", 3, 10, "确认 Hub 缓存")
        _ensure_gguf_hub_accessible(hub_filename)

        logger.info("Loading Phi-4 model...")

        load_kwargs = {
            "gguf_file": hub_filename,
            "device_map": "cpu",
            "trust_remote_code": True,
            "low_cpu_mem_usage": True,
        }

        # Stage 4: Load Tokenizer (50%)
        if on_progress:
            on_progress("load_tokenizer", 5, 10, "加载 Tokenizer")

        try:
            self.tokenizer = AutoTokenizer.from_pretrained(
                TOKENIZER_REPO,
                trust_remote_code=True,
            )

            # Stage 5: Load model weights (90%)
            if on_progress:
                on_progress("load_model", 9, 10, "加载模型权重")
            self.model = AutoModelForCausalLM.from_pretrained(MODEL_REPO, **load_kwargs)
        except Exception as exc:
            raise ModelLoadError(
                f"GGUF 加载失败 ({hub_filename}): {exc}. "
                "请确认已安装 torch、transformers>=5.0、gguf>=0.10.0，"
                "并重新运行 install.bat。"
            ) from exc

        # Stage 6: Model ready (100%)
        self.model.eval()
        if on_progress:
            on_progress("load_model", 10, 10, "模型就绪")
        logger.info("Phi-4 model ready")

    def _generate(self, prompt: str, max_new_tokens: int = 64, temperature: float = 0.0) -> str:
        """
        Generate text using Phi-4.

        Args:
            prompt: Input prompt
            max_new_tokens: Maximum tokens to generate
            temperature: Sampling temperature

        Returns:
            Generated text (prompt removed)
        """
        inputs = self.tokenizer(prompt, return_tensors="pt")
        do_sample = temperature > 0
        gen_kwargs: dict[str, Any] = {
            "max_new_tokens": max_new_tokens,
            "do_sample": do_sample,
            "pad_token_id": self.tokenizer.eos_token_id,
        }
        if do_sample:
            gen_kwargs["temperature"] = temperature
        outputs = self.model.generate(**inputs, **gen_kwargs)
        response_text = self.tokenizer.decode(
            outputs[0], skip_special_tokens=True
        )
        # Remove prompt from response
        return response_text[len(prompt):].strip()

    def _build_batch_field_mapping_prompt(
        self,
        source_columns_data: list[SourceColumnData],
        yaml_field_names: list[str],
    ) -> str:
        """Build one-shot prompt that maps all YAML fields to all source columns."""
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
}}
JSON:"""

    def _parse_batch_mapping_result(
        self,
        response_text: str,
        source_columns: list[str],
        expected_fields: list[str],
    ) -> dict[str, FieldMappingResult]:
        """Parse batch JSON response into validated field mapping dictionary."""
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
    ) -> tuple[dict[str, FieldMappingResult], str, str]:
        """Run one LLM call to map all template fields to source columns."""
        prompt = self._build_batch_field_mapping_prompt(source_columns_data, yaml_field_names)
        response = self._generate(prompt, max_new_tokens=1024, temperature=0.0)
        source_columns = [col["header"] for col in source_columns_data]
        mappings = self._parse_batch_mapping_result(response, source_columns, yaml_field_names)
        return mappings, prompt, response

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
}}
JSON:"""

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
            # Keep non-regex methods parseable but conservative for validation.
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
            response = self._generate(prompt, max_new_tokens=1024, temperature=0.0)
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
        on_progress: ProgressCallback | None = None,
    ) -> Iterator[tuple[str, dict[str, str]]]:
        """
        Yield (stage_message, cumulative_matches) after each template field.

        Args:
            sheet_row: Sample row from sheet with column values
            yaml_config: YAML configuration dictionary
            on_progress: Progress callback function

        Yields:
            (stage_message, cumulative_matches) tuples

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

            if on_progress:
                on_progress("match", index, total, stage)

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


def create_field_matcher(
    model_path: str | Path | None = None,
    on_progress: ProgressCallback | None = None,
) -> Phi4FieldMatcher | None:
    """
    Create field matcher instance with progress reporting.
    
    Args:
        model_path: Path to local GGUF file
        on_progress: Progress callback function
    
    Returns:
        Phi4FieldMatcher instance or None if model is not available
    """
    global _last_load_error
    _last_load_error = None
    try:
        return Phi4FieldMatcher(model_path, on_progress=on_progress)
    except (FileNotFoundError, ImportError, ModelLoadError) as exc:
        _last_load_error = str(exc)
        logger.warning("Phi-4 model not available: %s", exc)
        return None


def get_or_create_field_matcher(
    on_progress: ProgressCallback | None = None
) -> Phi4FieldMatcher | None:
    """
    Get or create field matcher (singleton pattern, thread-safe).

    Returns cached matcher after first load for performance.

    Args:
        on_progress: Progress callback function (only used for first load)

    Returns:
        Phi4FieldMatcher instance or None if model is not available
    """
    global _cached_matcher, _cached_matcher_lock

    if _cached_matcher is not None:
        logger.info("Reusing cached Phi-4 model")
        # Notify caller that model is ready (even when cached)
        if on_progress:
            on_progress("load_model", 10, 10, "模型已就绪（使用缓存）")
        return _cached_matcher

    # Initialize lock on first use
    if _cached_matcher_lock is None:
        import threading
        _cached_matcher_lock = threading.Lock()

    with _cached_matcher_lock:
        # Double-check pattern
        if _cached_matcher is not None:
            return _cached_matcher

        logger.info("Loading Phi-4 model (first use)")
        _cached_matcher = create_field_matcher(on_progress=on_progress)
        return _cached_matcher


def clear_matcher_cache():
    """Clear cached matcher instance (for testing or manual reload)."""
    global _cached_matcher
    _cached_matcher = None
    logger.info("Cleared Phi-4 model cache")
