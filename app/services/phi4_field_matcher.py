"""
Phi-4 GGUF Field Matcher

Uses Phi-4-mini-instruct GGUF model to match Google Sheets fields to YAML configuration parameters.
Supports multiple quantization levels - automatically selects the downloaded version.
"""
import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Model directory
MODEL_DIR = Path("models/phi4")

# Supported quantization versions (in preference order)
QUANT_VERSIONS = ["Q8_0", "Q6_K", "Q5_K_M", "Q4_K_M", "Q3_K_M", "Q2_K"]


def find_model_file() -> Path | None:
    """
    Find the downloaded GGUF model file
    
    Returns:
        Path to the model file, or None if not found
    """
    if not MODEL_DIR.exists():
        return None
    
    # Try to find any quantized version
    for quant in QUANT_VERSIONS:
        model_file = MODEL_DIR / f"microsoft_Phi-4-mini-instruct-{quant}.gguf"
        if model_file.exists():
            logger.info(f"Found model: {model_file.name}")
            return model_file
    
    # Try legacy format
    legacy_file = MODEL_DIR / "Phi-4-mini-instruct-Q4_K_M.gguf"
    if legacy_file.exists():
        logger.info(f"Found legacy model: {legacy_file.name}")
        return legacy_file
    
    return None


class Phi4FieldMatcher:
    """
    Match Google Sheet fields to YAML parameters using Phi-4 GGUF model
    
    This class handles fuzzy field matching when Sheet column names don't exactly
    match the YAML `filed` parameters.
    """
    
    def __init__(self, model_path: str | Path | None = None):
        """
        Initialize Phi-4 field matcher
        
        Args:
            model_path: Path to Phi-4 GGUF model file. If None, auto-detects from MODEL_DIR.
        
        Raises:
            FileNotFoundError: If model file doesn't exist
            ImportError: If llama-cpp-python is not installed
        """
        try:
            from llama_cpp import Llama
        except ImportError as exc:
            raise ImportError(
                "llama-cpp-python is not installed. "
                "Please run: pip install llama-cpp-python"
            ) from exc
        
        # Auto-detect model path if not provided
        if model_path is None:
            model_path = find_model_file()
            if model_path is None:
                raise FileNotFoundError(
                    f"Phi-4 model not found in: {MODEL_DIR}\n"
                    f"Please run: python scripts/download_phi4_model.py"
                )
        else:
            model_path = Path(model_path)
            if not model_path.exists():
                raise FileNotFoundError(
                    f"Phi-4 model not found at: {model_path}\n"
                    f"Please run: python scripts/download_phi4_model.py"
                )
        
        logger.info(f"Loading Phi-4 model from: {model_path}")
        logger.info(f"Model size: {model_path.stat().st_size / (1024**3):.2f} GB")
        
        # Auto-detect optimal thread count (use half of CPU cores for efficiency)
        import os
        n_threads = max(1, os.cpu_count() // 2) if os.cpu_count() else 4
        
        self.model = Llama(
            model_path=str(model_path),
            n_ctx=4096,          # Context length
            n_threads=n_threads, # Auto-detected CPU threads
            n_gpu_layers=0,      # Force CPU-only (no GPU/NPU)
            verbose=False
        )
        
        logger.info(f"Phi-4 model loaded successfully (using {n_threads} CPU threads)")
    
    def match_sheet_fields_to_yaml(
        self,
        sheet_row: dict[str, str],
        yaml_config: dict[str, Any]
    ) -> dict[str, str]:
        """
        Match Sheet field values to YAML template fields
        
        Args:
            sheet_row: Google Sheet row data, e.g.:
                      {"PO Number": "12345", "Container": "ABCD123", ...}
            
            yaml_config: YAML field mapping config, e.g.:
                        {
                            "P.O. No.": [{"filed": "PO Number", ...}],
                            "Container No.": [{"filed": "Container", ...}],
                            ...
                        }
        
        Returns:
            Matched template field values, e.g.:
            {"P.O. No.": "12345", "Container No.": "ABCD123", ...}
        
        Notes:
            - Falls back to exact matching if LLM fails
            - Applies regex patterns from YAML if defined
            - Returns empty dict on error (logs warning)
        """
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
            
            # Generate with timeout
            response = self.model(
                prompt,
                max_tokens=1024,
                temperature=0.1,  # Low temperature for deterministic output
                top_p=0.9,
                stop=["```", "\n\n\n"]  # Stop tokens
            )
            
            response_text = response["choices"][0]["text"]
            logger.debug(f"Phi-4 response: {response_text}")
            
            # Parse JSON result
            matched = self._parse_matching_result(response_text)
            
            # Apply regex patterns if defined in YAML
            matched = self._apply_regex_patterns(matched, yaml_config)
            
            logger.info(f"Successfully matched {len(matched)} fields using Phi-4")
            return matched
            
        except Exception as e:
            logger.warning(f"Phi-4 matching failed: {e}. Falling back to exact match.")
            # Fallback to exact match on error
            return self._try_exact_match(sheet_row, yaml_config) or {}
    
    def _try_exact_match(
        self,
        sheet_row: dict[str, str],
        yaml_config: dict[str, Any]
    ) -> dict[str, str] | None:
        """
        Try exact field name matching (case-insensitive)
        
        Returns None if any field cannot be matched exactly
        """
        result = {}
        
        for template_field, rules in yaml_config.items():
            if isinstance(template_field, str) and template_field.startswith("_"):
                continue  # Skip metadata fields like _sections
            
            if not isinstance(rules, list) or not rules:
                continue
            
            # Get the first rule
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
                # Exact match failed for this field
                return None
            
            result[template_field] = matched_value
        
        return result
    
    def _build_matching_prompt(
        self,
        sheet_row: dict[str, str],
        yaml_config: dict[str, Any]
    ) -> str:
        """Build prompt for Phi-4 field matching"""
        
        # Extract YAML field mappings
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
        
        # Build sheet columns
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
        # Clean up response text
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
            
            # Convert all values to strings
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
                    # Use first capturing group if available, otherwise full match
                    result[template_field] = match.group(1) if match.groups() else match.group(0)
                    logger.debug(f"Applied regex to {template_field}: {value} -> {result[template_field]}")
            except re.error as e:
                logger.warning(f"Invalid regex pattern for {template_field}: {e}")
        
        return result


def create_field_matcher(model_path: str | Path | None = None) -> Phi4FieldMatcher | None:
    """
    Create field matcher instance, returning None if model is not available
    
    This allows the app to work without Phi-4 model (fallback to exact matching)
    """
    try:
        return Phi4FieldMatcher(model_path)
    except (FileNotFoundError, ImportError) as e:
        logger.warning(f"Phi-4 model not available: {e}")
        logger.warning("Field matching will use exact name matching only")
        return None
