"""
Phi-4 Field Matcher (Transformers + GGUF)

Uses Phi-4-mini-instruct via Transformers with GGUF support (pure Python, no compilation).
Automatically selects quantization based on available memory.
"""
import importlib.metadata
import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

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
    logger.info(
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
        logger.warning(
            "Limited memory (%.1f GB usable); using smallest quantization %s",
            usable_gb,
            selected[0],
        )

    quant_name, mem_req, desc = selected
    logger.info(
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
        logger.info("Model already present: %s", existing[1])
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
        logger.info("Model already present: %s", model_path)
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
    logger.info(
        "Download complete: %s (%.2f GB)",
        path,
        path.stat().st_size / (1024 ** 3),
    )
    return path


def find_model_file() -> tuple[str, Path] | None:
    """
    Find the downloaded GGUF model file
    
    Returns:
        (filename_on_hub, local_path) tuple, or None if not found
    """
    if not MODEL_DIR.exists():
        return None
    
    # Try to find any quantized version
    for quant in QUANT_VERSIONS:
        model_filename = f"microsoft_Phi-4-mini-instruct-{quant}.gguf"
        model_path = MODEL_DIR / model_filename
        if model_path.exists():
            logger.info(f"Found model: {model_filename}")
            return (model_filename, model_path)
    
    return None


class Phi4FieldMatcher:
    """
    Match Google Sheet fields to YAML parameters using Phi-4 via Transformers
    
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
        logger.info("Using local GGUF: %s (hub file: %s)", local_path, hub_filename)

        _ensure_gguf_hub_accessible(hub_filename)

        logger.info("Loading Phi-4 via Transformers GGUF (repo=%s)...", MODEL_REPO)

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
        logger.info("Phi-4 model loaded successfully (pure Python, CPU mode)")
    
    def match_sheet_fields_to_yaml(
        self,
        sheet_row: dict[str, str],
        yaml_config: dict[str, Any]
    ) -> dict[str, str]:
        """Match Sheet field values to YAML template fields"""
        if not sheet_row or not yaml_config:
            return {}
        
        # Try exact matching first (fast path)
        exact_match = self._try_exact_match(sheet_row, yaml_config)
        if exact_match:
            logger.info("Used exact field matching (no LLM needed)")
            return exact_match
        
        # Use LLM for fuzzy matching
        try:
            logger.info("Using Phi-4 for fuzzy field matching")
            prompt = self._build_matching_prompt(sheet_row, yaml_config)
            
            # Tokenize
            inputs = self.tokenizer(prompt, return_tensors="pt")
            
            # Generate
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=1024,
                temperature=0.1,
                do_sample=True,
                pad_token_id=self.tokenizer.eos_token_id
            )
            
            # Decode
            response_text = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
            
            # Extract only the new generated text (after prompt)
            response_text = response_text[len(prompt):].strip()
            
            logger.debug(f"Phi-4 response: {response_text}")
            
            # Parse JSON result
            matched = self._parse_matching_result(response_text)
            
            # Apply regex patterns if defined in YAML
            matched = self._apply_regex_patterns(matched, yaml_config)
            
            logger.info(f"Successfully matched {len(matched)} fields using Phi-4")
            return matched
            
        except Exception as e:
            logger.warning(f"Phi-4 matching failed: {e}. Falling back to exact match.")
            return self._try_exact_match(sheet_row, yaml_config) or {}
    
    def _try_exact_match(
        self,
        sheet_row: dict[str, str],
        yaml_config: dict[str, Any]
    ) -> dict[str, str] | None:
        """Try exact field name matching (case-insensitive)"""
        result = {}
        
        for template_field, rules in yaml_config.items():
            if isinstance(template_field, str) and template_field.startswith("_"):
                continue
            
            if not isinstance(rules, list) or not rules:
                continue
            
            rule = rules[0]
            if not isinstance(rule, dict):
                continue
            
            filed_name = rule.get("filed")
            if not filed_name:
                continue
            
            # Try exact match (case-insensitive)
            matched_value = None
            for sheet_col, sheet_val in sheet_row.items():
                if sheet_col.strip().lower() == filed_name.strip().lower():
                    matched_value = sheet_val
                    break
            
            if matched_value is None:
                return None
            
            result[template_field] = matched_value
        
        return result
    
    def _build_matching_prompt(
        self,
        sheet_row: dict[str, str],
        yaml_config: dict[str, Any]
    ) -> str:
        """Build prompt for Phi-4 field matching"""
        yaml_fields = []
        for template_field, rules in yaml_config.items():
            if isinstance(template_field, str) and template_field.startswith("_"):
                continue
            
            if not isinstance(rules, list) or not rules:
                continue
            
            rule = rules[0]
            if not isinstance(rule, dict):
                continue
            
            filed_name = rule.get("filed", "?")
            yaml_fields.append(f'  - Template field: "{template_field}", Sheet column hint: "{filed_name}"')
        
        yaml_fields_str = "\n".join(yaml_fields)
        
        sheet_cols = []
        for col, val in sheet_row.items():
            sheet_cols.append(f'  - "{col}": "{val}"')
        
        sheet_cols_str = "\n".join(sheet_cols)
        
        prompt = f"""You are a data mapping assistant. Match Google Sheet columns to template fields.

Google Sheet Columns and Values:
{sheet_cols_str}

Template Fields (with column name hints):
{yaml_fields_str}

Task: Output JSON mapping template fields to Sheet values.

Example output format:
{{
  "Template Field 1": "value from sheet",
  "Template Field 2": "value from sheet"
}}

Output ONLY valid JSON, no explanations:"""
        
        return prompt
    
    def _parse_matching_result(self, response_text: str) -> dict[str, str]:
        """Parse JSON result from Phi-4 response"""
        text = response_text.strip()
        
        # Try to extract JSON from code blocks
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if json_match:
            text = json_match.group(1)
        
        # Try to extract JSON object
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            text = json_match.group(0)
        
        try:
            result = json.loads(text)
            if not isinstance(result, dict):
                logger.warning(f"Phi-4 returned non-dict: {type(result)}")
                return {}
            
            return {k: str(v) for k, v in result.items() if v is not None}
            
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse Phi-4 JSON response: {e}")
            logger.debug(f"Response text: {text}")
            return {}
    
    def _apply_regex_patterns(
        self,
        matched: dict[str, str],
        yaml_config: dict[str, Any]
    ) -> dict[str, str]:
        """Apply regex extraction patterns from YAML config"""
        result = dict(matched)
        
        for template_field, rules in yaml_config.items():
            if not isinstance(rules, list) or not rules:
                continue
            
            rule = rules[0]
            if not isinstance(rule, dict):
                continue
            
            regex_pattern = rule.get("regex")
            if not regex_pattern or template_field not in matched:
                continue
            
            value = matched[template_field]
            try:
                match = re.search(regex_pattern, value)
                if match:
                    result[template_field] = match.group(1) if match.groups() else match.group(0)
                    logger.debug(f"Applied regex to {template_field}: {value} -> {result[template_field]}")
            except re.error as e:
                logger.warning(f"Invalid regex pattern for {template_field}: {e}")
        
        return result


def create_field_matcher(model_path: str | Path | None = None) -> Phi4FieldMatcher | None:
    """Create field matcher instance, returning None if model is not available."""
    global _last_load_error
    _last_load_error = None
    try:
        return Phi4FieldMatcher(model_path)
    except (FileNotFoundError, ImportError, ModelLoadError) as exc:
        _last_load_error = str(exc)
        logger.warning("Phi-4 model not available: %s", exc)
        logger.warning("Field matching will use exact name matching only")
        return None
