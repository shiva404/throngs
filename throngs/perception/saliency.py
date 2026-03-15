"""Phase 2 — Computer Vision Saliency Layer ("Eye-Tracking" Profile).

Predicts where the human eye is naturally drawn based on pixel data.
The default implementation uses the Spectral Residual algorithm
(Hou & Zhang 2007) — fast, model-free, and requires only numpy + PIL.

Output: a grayscale heatmap (same viewport dimensions) where intensity
0-255 represents predicted visual attention.
  • 200-255  →  Visually loud — immediate eye fixation
  • 0-50    →  Visually quiet — completely ignored on first scan
"""

from __future__ import annotations

import io
import logging

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

_FFT_SIZE = 64
_RESIDUAL_KERNEL = 3
_SMOOTH_KERNEL = 7
_HIGH_INTENSITY_THRESHOLD = 200


def compute_saliency_map(
    screenshot_bytes: bytes,
    viewport_width: int,
    viewport_height: int,
) -> np.ndarray:
    """Return a saliency heatmap (H×W, uint8 0-255) for the viewport."""
    image = Image.open(io.BytesIO(screenshot_bytes)).convert("L")
    small = np.array(
        image.resize((_FFT_SIZE, _FFT_SIZE), Image.BILINEAR), dtype=np.float64
    )

    fft = np.fft.fft2(small)
    log_amp = np.log(np.abs(fft) + 1e-10)
    phase = np.angle(fft)

    avg_log_amp = _mean_filter_2d(log_amp, _RESIDUAL_KERNEL)
    residual = log_amp - avg_log_amp

    saliency_small = np.abs(np.fft.ifft2(np.exp(residual + 1j * phase))) ** 2

    peak = saliency_small.max()
    if peak > 0:
        saliency_small = saliency_small / peak * 255.0

    saliency_small = _mean_filter_2d(saliency_small, _SMOOTH_KERNEL)

    peak = saliency_small.max()
    if peak > 0:
        saliency_small = saliency_small / peak * 255.0

    heatmap_pil = Image.fromarray(saliency_small.astype(np.uint8))
    heatmap_full = np.array(
        heatmap_pil.resize((viewport_width, viewport_height), Image.BILINEAR)
    )
    return heatmap_full


def region_mean_intensity(
    heatmap: np.ndarray, x: float, y: float, w: float, h: float
) -> float:
    """Average saliency intensity within a bounding box (0-255)."""
    hm_h, hm_w = heatmap.shape[:2]
    x0 = max(int(x), 0)
    y0 = max(int(y), 0)
    x1 = min(int(x + w), hm_w)
    y1 = min(int(y + h), hm_h)

    if x1 <= x0 or y1 <= y0:
        return 0.0

    region = heatmap[y0:y1, x0:x1]
    return float(np.mean(region))


def high_intensity_percentage(heatmap: np.ndarray) -> float:
    """Percentage of pixels above the high-intensity threshold."""
    total = heatmap.size
    if total == 0:
        return 0.0
    loud = int(np.sum(heatmap > _HIGH_INTENSITY_THRESHOLD))
    return loud / total * 100.0


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _mean_filter_2d(arr: np.ndarray, kernel_size: int) -> np.ndarray:
    """Simple uniform mean filter using padded slicing (no scipy)."""
    pad = kernel_size // 2
    padded = np.pad(arr, pad, mode="reflect")
    result = np.zeros_like(arr, dtype=np.float64)
    for di in range(kernel_size):
        for dj in range(kernel_size):
            result += padded[di : di + arr.shape[0], dj : dj + arr.shape[1]]
    return result / (kernel_size * kernel_size)
