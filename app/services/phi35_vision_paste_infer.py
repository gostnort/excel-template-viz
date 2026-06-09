from __future__ import annotations

import io
import re
from dataclasses import dataclass

from PIL import Image

from app.services.paste_mapping_infer import extract_sample_line, infer_paste_mapping_yaml
from app.services.paste_parse_config import config_to_yaml, validate_mapping_yaml
from app.services.phi35_vision_model import get_phi35_vision_bundle

_MIN_IMAGE_HEIGHT = 480
_MAX_NEW_TOKENS = 1600


class VisionInferenceError(RuntimeError):
    def __init__(self, message: str, *, raw_response: str = "") -> None:
        super().__init__(message)
        self.raw_response = raw_response


@dataclass(frozen=True)
class VisionInferenceResult:
    yaml_text: str
    raw_response: str


def _prepare_image(image: Image.Image) -> Image.Image:
    rgb = image.convert("RGB")
    if rgb.height >= _MIN_IMAGE_HEIGHT:
        return rgb
    scale = _MIN_IMAGE_HEIGHT / rgb.height
    return rgb.resize((max(1, int(rgb.width * scale)), _MIN_IMAGE_HEIGHT), Image.Resampling.LANCZOS)


def _build_vision_prompt(processor, template_headers: list[str], *, retry: bool = False) -> str:
    header_lines = "\n".join(f"- {name}" for name in template_headers)
    retry_note = (
        "\nYour previous answer did not include a usable table. "
        "Output ONLY a table with headers and data rows.\n"
        if retry
        else ""
    )
    user_text = f"""<|image_1|>
{retry_note}
The image shows a SOURCE spreadsheet (blue header row + data). Users will later paste tab-separated ROWS from this sheet.

Your task: output a table (Markdown or HTML) that mirrors the source header row and at least one data row.
Do NOT explain. Do NOT output YAML. Do NOT add bullets or prose.

Rules:
1. Output only a table (Markdown or HTML).
2. Include the header row.
3. Include at least one data row.
4. Keep the column order the same as the image.

Template fields (for reference only, do not output them):
{header_lines}"""
    messages = [{"role": "user", "content": user_text}]
    return processor.tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)


def _collect_targets(config: dict[str, object]) -> set[str]:
    targets: set[str] = set()
    for rule in config.get("fields", []):
        if not isinstance(rule, dict):
            continue
        if rule.get("target"):
            targets.add(str(rule["target"]))
        derive = rule.get("derive")
        if isinstance(derive, dict) and derive.get("target"):
            targets.add(str(derive["target"]))
        for sub in rule.get("fields", []):
            if isinstance(sub, dict) and sub.get("target"):
                targets.add(str(sub["target"]))
    return targets


_LOGISTICS_DEFAULTS: dict[str, int] = {
    "P.O. No.": 1,
    "Supplier": 3,
    "Container No.": 5,
    "Product Description": 14,
}


def _fill_missing_logistics_fields(
    merged: dict[str, object],
    template_headers: list[str],
) -> dict[str, object]:
    fields = [rule for rule in merged.get("fields", []) if isinstance(rule, dict)]
    has_layout = any(
        rule.get("target") == "Container No." and rule.get("field_index", rule.get("index")) == 5
        for rule in fields
    )
    if not has_layout:
        return merged
    allowed = set(template_headers)
    present = _collect_targets(merged)
    simple_fields = [rule for rule in fields if "split" not in rule]
    nested_fields = [rule for rule in fields if "split" in rule]
    for target, index in _LOGISTICS_DEFAULTS.items():
        if target not in allowed or target in present:
            continue
        simple_fields.append({"target": target, "field_index": index})
        present.add(target)
    simple_fields.sort(key=lambda item: int(item.get("field_index", item.get("index", 999))))
    merged["fields"] = simple_fields + nested_fields
    return merged


def _merge_mapping_configs(configs: list[dict[str, object]]) -> dict[str, object]:
    merged_fields: list[dict[str, object]] = []
    seen_targets: set[str] = set()
    nested_date_rule: dict[str, object] | None = None
    for config in configs:
        for rule in config.get("fields", []):
            if not isinstance(rule, dict):
                continue
            if "split" in rule and "fields" in rule:
                nested_date_rule = rule
                continue
            target = rule.get("target")
            if not target:
                continue
            target_name = str(target)
            if target_name in seen_targets:
                continue
            seen_targets.add(target_name)
            merged_fields.append(rule)
    if nested_date_rule is not None:
        merged_fields.append(nested_date_rule)
    merged_fields.sort(key=lambda item: int(item.get("field_index", item.get("index", 999))))
    return {"delimiter": "tab", "index_base": 1, "fields": merged_fields}


def _looks_like_data_dump(raw_response: str, template_headers: list[str]) -> bool:
    if "fields:" in raw_response:
        return False
    hits = 0
    for header in template_headers:
        if re.search(rf"^\s*{re.escape(header)}\s*:", raw_response, flags=re.MULTILINE):
            hits += 1
    return hits >= 2


def _generate_once(
    processor,
    ov_model,
    image: Image.Image,
    template_headers: list[str],
    *,
    retry: bool,
) -> str:
    prompt = _build_vision_prompt(processor, template_headers, retry=retry)
    inputs = ov_model.preprocess_inputs(text=prompt, image=image, processor=processor)
    generate_ids = ov_model.generate(
        **inputs,
        max_new_tokens=_MAX_NEW_TOKENS,
        do_sample=False,
        eos_token_id=processor.tokenizer.eos_token_id,
    )
    prompt_len = inputs["input_ids"].shape[1]
    generated = generate_ids[:, prompt_len:]
    return processor.batch_decode(
        generated,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )[0]


def _run_vision_generate(image_bytes: bytes, template_headers: list[str]) -> VisionInferenceResult:
    processor, ov_model = get_phi35_vision_bundle()
    image = _prepare_image(Image.open(io.BytesIO(image_bytes)))
    raw_parts: list[str] = []
    last_error = "模型未返回可解析的表格"
    for retry in (False, True, True):
        raw_response = _generate_once(processor, ov_model, image, template_headers, retry=retry)
        raw_parts.append(raw_response)
        sample_line = extract_sample_line(str(raw_response))
        if not sample_line:
            last_error = "模型输出为空或无法识别表格"
            continue
        try:
            yaml_text = infer_paste_mapping_yaml(sample_line, template_headers)
            validate_mapping_yaml(yaml_text, template_headers)
            return VisionInferenceResult(yaml_text=yaml_text, raw_response="\n---\n".join(raw_parts))
        except ValueError as exc:
            last_error = str(exc)
    raise VisionInferenceError(last_error, raw_response="\n---\n".join(raw_parts))


def infer_paste_mapping_from_image(image_bytes: bytes, template_headers: list[str]) -> str:
    result = _run_vision_generate(image_bytes, template_headers)
    config = validate_mapping_yaml(result.yaml_text, template_headers)
    return config_to_yaml(config)


def infer_paste_mapping_from_image_debug(image_bytes: bytes, template_headers: list[str]) -> VisionInferenceResult:
    result = _run_vision_generate(image_bytes, template_headers)
    config = validate_mapping_yaml(result.yaml_text, template_headers)
    return VisionInferenceResult(yaml_text=config_to_yaml(config), raw_response=result.raw_response)
