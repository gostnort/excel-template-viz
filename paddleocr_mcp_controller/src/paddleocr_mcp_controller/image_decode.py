"""Decode image bytes/paths and crop with OpenCV ROI semantics."""

from __future__ import annotations

from pathlib import Path

import numpy as np


class ImageDecodeError(ValueError):
    """Raised when bytes/path cannot be decoded to an image array."""


class CropBoxError(ValueError):
    """Raised when crop_box is illegal or clamps to empty area."""


_HEIC_SUFFIXES = (".heic", ".heif")


def _is_heic_bytes(data: bytes) -> bool:
    if len(data) < 12:
        return False
    if data[4:8] != b"ftyp":
        return False
    brand = data[8:12]
    return brand in (b"heic", b"heif", b"mif1", b"msf1", b"heim", b"heis", b"hevx")


def _decode_heic_bytes(data: bytes) -> np.ndarray:
    import pillow_heif
    heif = pillow_heif.open_heif(data, convert_hdr_to_8bit=True, bgr_mode=True)
    # 中文注释：显式 copy，避免 pillow_heif 内部缓冲被 GC 后 view 悬空
    arr = np.array(heif, copy=True)
    if arr.ndim == 2:
        import cv2
        arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
    elif arr.ndim == 3 and arr.shape[2] == 4:
        import cv2
        arr = cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
    return arr


def _decode_with_cv2(data: bytes) -> np.ndarray | None:
    import cv2
    buf = np.frombuffer(data, dtype=np.uint8)
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def is_heic(image: bytes | Path | str) -> bool:
    """
    函数名: is_heic
    作用: 判断输入是否为 HEIC/HEIF 图片。
    输入:
        image (bytes|Path|str): 图片原始字节或文件路径。
    输出:
        bool: True=HEIC/HEIF。
    """
    if isinstance(image, (str, Path)):
        if Path(image).suffix.lower() in _HEIC_SUFFIXES:
            return True
        path = Path(image)
        if not path.is_file():
            return False
        data = path.read_bytes()
    elif isinstance(image, (bytes, bytearray, memoryview)):
        data = bytes(image)
    else:
        return False
    return _is_heic_bytes(data)


def decode_image(image: bytes | Path | str | np.ndarray) -> np.ndarray:
    """Return BGR uint8 ndarray. Accepts bytes, path, or already-decoded array."""
    if isinstance(image, np.ndarray):
        if image.size == 0:
            raise ImageDecodeError("empty array")
        return image
    if isinstance(image, (str, Path)):
        path = Path(image)
        if not path.is_file():
            raise ImageDecodeError("missing file")
        data = path.read_bytes()
    elif isinstance(image, (bytes, bytearray, memoryview)):
        data = bytes(image)
    else:
        raise ImageDecodeError("unsupported type")
    if not data:
        raise ImageDecodeError("empty bytes")
    suffix_heic = False
    if isinstance(image, (str, Path)):
        suffix_heic = Path(image).suffix.lower() in _HEIC_SUFFIXES
    if suffix_heic or _is_heic_bytes(data):
        try:
            return _decode_heic_bytes(data)
        except Exception as exc:
            raise ImageDecodeError("heic decode failed") from exc
    img = _decode_with_cv2(data)
    if img is None:
        try:
            return _decode_heic_bytes(data)
        except Exception as exc:
            raise ImageDecodeError("cv2 decode failed") from exc
    return img


def apply_crop_box(
    img: np.ndarray,
    crop_box: tuple[int, int, int, int] | None,
) -> np.ndarray:
    """Crop with OpenCV ROI (x, y, w, h). Returns a contiguous BGR copy for predict."""
    if crop_box is None:
        return np.ascontiguousarray(img)
    if len(crop_box) != 4:
        raise CropBoxError("need 4 ints")
    x, y, w, h = (int(v) for v in crop_box)
    if w <= 0 or h <= 0:
        raise CropBoxError("non-positive size")
    height, width = img.shape[:2]
    x0 = max(0, min(x, width))
    y0 = max(0, min(y, height))
    x1 = max(0, min(x + w, width))
    y1 = max(0, min(y + h, height))
    if x1 <= x0 or y1 <= y0:
        raise CropBoxError("empty after clamp")
    return np.ascontiguousarray(img[y0:y1, x0:x1])


def prepare_for_predict(img: np.ndarray) -> np.ndarray:
    """Normalize array before PaddleOCR.predict (contiguous BGR uint8)."""
    if img.dtype != np.uint8:
        img = img.astype(np.uint8)
    if not img.flags["C_CONTIGUOUS"]:
        img = np.ascontiguousarray(img)
    return img


def min_side_target_size(width: int, height: int, min_side: int) -> tuple[int, int]:
    """
    函数名: min_side_target_size
    作用: 短边大于阈值则等比缩到短边==阈值；否则原尺寸（不放大）。
    输入:
        width (int): 原图宽。
        height (int): 原图高。
        min_side (int): 短边目标上限。
    输出:
        tuple[int, int]: (new_width, new_height)。
    """
    w = int(width)
    h = int(height)
    limit = int(min_side)
    if w <= 0 or h <= 0 or min(w, h) <= limit:
        return (w, h)
    scale = limit / float(min(w, h))
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    return (new_w, new_h)


def scale_min_side(img: np.ndarray, min_side: int) -> np.ndarray:
    """
    函数名: scale_min_side
    作用: 对 BGR ndarray 做短边预处理：仅缩小、不放大。
    输入:
        img (np.ndarray): BGR 图。
        min_side (int): 短边目标上限。
    输出:
        np.ndarray: 预处理后的图；无需缩放时返回入参本身。
    """
    height, width = img.shape[:2]
    new_w, new_h = min_side_target_size(int(width), int(height), int(min_side))
    if new_w == int(width) and new_h == int(height):
        return img
    import cv2
    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
    return np.ascontiguousarray(resized)


def load_for_ocr(
    pic: bytes | Path | str | np.ndarray,
    rectangle: tuple[int, int, int, int] | None,
) -> np.ndarray:
    """Decode path/bytes, apply OpenCV ROI, return contiguous BGR for predict."""
    img = decode_image(pic)
    img = apply_crop_box(img, rectangle)
    return prepare_for_predict(img)
