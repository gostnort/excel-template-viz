"""OpenCV grid-line heuristic: table-like crops vs plain text strips."""

from __future__ import annotations

import numpy as np


def HasTableGrid(img: np.ndarray) -> bool:
    """Return True when horizontal and vertical rule lines suggest a table grid.

    Tolerates missing corners (partial grid). Thin single-line strips should be False.
    """
    import cv2
    if img is None or img.size == 0:
        return False
    height, width = int(img.shape[0]), int(img.shape[1])
    if height < 48 or width < 48:
        return False
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    bw = cv2.adaptiveThreshold(
        blur, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 15, 8,
    )
    h_len = max(width // 25, 12)
    v_len = max(height // 25, 12)
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (h_len, 1))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, v_len))
    horiz = cv2.morphologyEx(bw, cv2.MORPH_OPEN, h_kernel)
    vert = cv2.morphologyEx(bw, cv2.MORPH_OPEN, v_kernel)
    h_rows = _count_projection_peaks((horiz > 0).sum(axis=1), min_coverage=max(width // 8, 40))
    v_cols = _count_projection_peaks((vert > 0).sum(axis=0), min_coverage=max(height // 8, 24))
    # Table: at least two row bands and two column bands (partial grid OK).
    return h_rows >= 2 and v_cols >= 2



def _count_projection_peaks(projection: np.ndarray, *, min_coverage: int) -> int:
    """Count runs of ink along one axis that exceed min_coverage."""
    if projection.size == 0:
        return 0
    active = projection >= min_coverage
    peaks = 0
    in_run = False
    for flag in active:
        if flag and not in_run:
            peaks += 1
            in_run = True
        elif not flag:
            in_run = False
    return peaks
