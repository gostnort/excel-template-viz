"""Decode image bytes/paths and crop with OpenCV ROI semantics."""

from __future__ import annotations

from pathlib import Path

import numpy as np


class ImageDecodeError(ValueError):
    """Raised when bytes/path cannot be decoded to an image array."""



class CropBoxError(ValueError):
    """Raised when crop_box is illegal or clamps to empty area."""



def _is_heic_bytes(data: bytes) -> bool:
    if len(data) < 12:
        return False
    # ISO BMFF: size(4) + 'ftyp' + brand
    if data[4:8] != b"ftyp":
        return False
    brand = data[8:12]
    return brand in (b"heic", b"heif", b"mif1", b"msf1", b"heim", b"heis", b"hevx")


def _decode_heic_bytes(data: bytes) -> np.ndarray:
    # Optional dependency; ImportError means OCR install incomplete.
    import pillow_heif
    heif = pillow_heif.open_heif(data, convert_hdr_to_8bit=True, bgr_mode=True)
    arr = np.asarray(heif)
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
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    return img


def decode_image(image: bytes | Path | str | np.ndarray) -> np.ndarray:
    """Return BGR uint8 ndarray. Accepts bytes, path, or already-decoded array."""
    if isinstance(image, np.ndarray):
        if image.size == 0:
            raise ImageDecodeError("empty array")
        return image
    data: bytes
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
        suffix_heic = Path(image).suffix.lower() in (".heic", ".heif")
    if suffix_heic or _is_heic_bytes(data):
        try:
            return _decode_heic_bytes(data)
        except Exception as exc:
            raise ImageDecodeError("heic decode failed") from exc
    img = _decode_with_cv2(data)
    if img is None:
        # Fallback: some HEIC mislabeled without ftyp brand match
        try:
            return _decode_heic_bytes(data)
        except Exception as exc:
            raise ImageDecodeError("cv2 decode failed") from exc
    return img


def tlbr_to_xywh(
    top_left: tuple[int, int],
    bottom_right: tuple[int, int],
) -> tuple[int, int, int, int]:
    """Convert UI top-left / bottom-right pixels to OpenCV ROI (x, y, w, h)."""
    x0, y0 = int(top_left[0]), int(top_left[1])
    x1, y1 = int(bottom_right[0]), int(bottom_right[1])
    return (min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))


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
    # Always copy: numpy views are often non-contiguous and confuse PaddleX.
    return np.ascontiguousarray(img[y0:y1, x0:x1])


def prepare_for_predict(img: np.ndarray) -> np.ndarray:
    """Normalize array before PaddleOCR.predict (contiguous BGR uint8)."""
    if img.dtype != np.uint8:
        img = img.astype(np.uint8)
    if not img.flags["C_CONTIGUOUS"]:
        img = np.ascontiguousarray(img)
    return img
