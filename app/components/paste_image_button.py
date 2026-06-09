from __future__ import annotations

import base64
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import streamlit as st
import streamlit.components.v1 as components
from PIL import Image

_FRONTEND_DIR = (Path(__file__).parent / "paste_image_button_frontend").resolve()
_component_func = components.declare_component(
    "excel_template_viz_paste_image_button",
    path=str(_FRONTEND_DIR),
)


@dataclass
class PasteResult:
    image_data: Image.Image | None = None


def _data_url_to_image(data_url: str) -> Image.Image:
    _, encoded = data_url.split(";base64,")
    return Image.open(io.BytesIO(base64.b64decode(encoded)))


def paste_image_button(
    label: str,
    *,
    text_color: Optional[str] = "#ffffff",
    background_color: Optional[str] = "#3498db",
    hover_background_color: Optional[str] = "#2980b9",
    key: Optional[str] = "paste_button",
    errors: Optional[str] = "ignore",
) -> PasteResult:
    component_value = _component_func(
        label=label,
        text_color=text_color,
        background_color=background_color,
        hover_background_color=hover_background_color,
        key=key,
        default=None,
    )
    if component_value is None:
        return PasteResult()
    if str(component_value).startswith("error"):
        if errors == "raise":
            if str(component_value).startswith("error: no image"):
                st.error("**Error**: No image found in clipboard", icon="🚨")
            else:
                st.error(re.sub(r"error: (.+)(: .+)", r"**\1**\2", str(component_value)), icon="🚨")
        return PasteResult()
    return PasteResult(image_data=_data_url_to_image(str(component_value)))
