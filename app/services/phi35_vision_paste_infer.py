from __future__ import annotations

import io
import re
from dataclasses import dataclass

from PIL import Image

from app.services.paste_parse_config import (
    config_to_yaml,
    extract_yaml_text,
    validate_mapping_yaml,
)
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
        "\nYour previous answer was not valid YAML. Output ONLY the YAML mapping block.\n"
        if retry
        else ""
    )
    user_text = f"""<|image_1|>
{retry_note}
The image shows a SOURCE spreadsheet (header row + data rows). Users will paste tab-separated ROWS copied from this sheet into a form.

Your task: produce a YAML mapping that tells the app how each template field maps to a source column.

Output ONLY valid YAML. Do NOT wrap in markdown code fences. No prose, no bullets, no explanation.

Schema rules:
1. Top-level key `determiner` must be "tab" (tab-separated paste rows).
2. Optional top-level `order` lists discovered source headers as {{filed, index}} entries.
3. Each template field name below is a top-level YAML key; its value MUST be a YAML list.
4. CRITICAL: Every rule line MUST start with "-" (dash). Never output a bare mapping without "-".
5. Each rule item has:
   - `filed`: source column header text from the image (use "?" if unknown)
   - `index`: 0-based source column index (leftmost column is 0); use **-1** when `filed` is "?" (do not split from paste)
   - optional `regex`: Python regex to extract from the full cell string (first match wins)
   - optional `ID: true` on the ID lookup field (usually P.O. No.)
6. Mapped columns use 0-based index. Unmapped / manual fields use `filed: "?"` and `index: -1`.
7. Omit template fields with no plausible mapping, or use `filed: "?"` with `index: -1` when the field is filled manually.
8. For date fields (MM, DD, Receiving Date, YY), you may reuse the same `index` with different `regex` values.
9. Put regex patterns in single quotes, e.g. regex: '(\\d{{1,2}}\\/\\d{{1,2}})'.
10. Regex should match dates inside noisy text (e.g. "pickup 5/28, tdi 5/29").

Example shape (values are illustrative):
```yaml
determiner: "tab"
P.O. No.:
  - ID: true
    filed: "PO"
    index: 0
MM:
  - filed: "recv. date"
    index: 12
    regex: "(\\\\d{{1,2}})(?=\\\\/\\\\d{{1,2}})"
Receiving Date:
  - filed: "recv. date"
    index: 12
    regex: "(\\\\d{{1,2}}\\\\/\\\\d{{1,2}})"
```

Template fields to map:
{header_lines}"""
    messages = [{"role": "user", "content": user_text}]
    return processor.tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)


def _looks_like_mapping_yaml(raw_response: str, template_headers: list[str]) -> bool:
    if "determiner:" not in raw_response and "determiner :" not in raw_response:
        return False
    hits = 0
    for header in template_headers:
        if re.search(rf"^\s*{re.escape(header)}\s*:", raw_response, flags=re.MULTILINE):
            hits += 1
    return hits >= 1


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
    last_error = "Model did not return valid mapping YAML"
    for retry in (False, True, True):
        raw_response = _generate_once(processor, ov_model, image, template_headers, retry=retry)
        raw_parts.append(raw_response)
        if not _looks_like_mapping_yaml(raw_response, template_headers):
            last_error = "Model output is empty or missing mapping YAML"
            continue
        yaml_text = extract_yaml_text(raw_response)
        if not yaml_text:
            last_error = "Could not extract YAML from model output"
            continue
        try:
            config = validate_mapping_yaml(yaml_text, template_headers)
            return VisionInferenceResult(
                yaml_text=config_to_yaml(config),
                raw_response="\n---\n".join(raw_parts),
            )
        except ValueError as exc:
            last_error = str(exc)
    raise VisionInferenceError(last_error, raw_response="\n---\n".join(raw_parts))


def infer_paste_mapping_from_image(image_bytes: bytes, template_headers: list[str]) -> str:
    return _run_vision_generate(image_bytes, template_headers).yaml_text


def infer_paste_mapping_from_image_debug(image_bytes: bytes, template_headers: list[str]) -> VisionInferenceResult:
    return _run_vision_generate(image_bytes, template_headers)
