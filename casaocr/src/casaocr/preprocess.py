"""Image preprocessing — the biggest single accuracy lever in OCR.

A short OpenCV pipeline: grayscale -> denoise -> deskew -> adaptive threshold.
Most OCR wrappers skip this and lose accuracy on real-world scans (phone photos,
faxes, skewed pages). It is on by default and can be turned off per request
(some engines prefer the raw colour image).

OpenCV and numpy are imported lazily so decoding an already-clean image, or
running the tests, does not require them.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def _deskew(gray, np, cv2):
    """Estimate the dominant text skew angle and rotate it flat."""
    inverted = cv2.bitwise_not(gray)
    thresh = cv2.threshold(inverted, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    coords = cv2.findNonZero(thresh)
    if coords is None:
        return gray
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = 90 + angle
    # Ignore tiny angles — rotating by <0.5deg only adds interpolation blur.
    if abs(angle) < 0.5:
        return gray
    h, w = gray.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(
        gray, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )


def preprocess_image(image):
    """Return a cleaned image ready for recognition.

    Accepts and returns a numpy array. On any failure it logs and returns the
    input unchanged — preprocessing should never be the reason a page fails to
    OCR at all.
    """
    try:
        import cv2
        import numpy as np
    except ImportError as exc:  # pragma: no cover
        log.warning("opencv/numpy unavailable, skipping preprocessing: %s", exc)
        return image

    try:
        arr = np.array(image)
        if arr.ndim == 3 and arr.shape[2] >= 3:
            gray = cv2.cvtColor(arr[:, :, :3], cv2.COLOR_RGB2GRAY)
        elif arr.ndim == 3:
            gray = arr[:, :, 0]
        else:
            gray = arr

        gray = cv2.fastNlMeansDenoising(gray, h=10)
        gray = _deskew(gray, np, cv2)
        binary = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15
        )
        return binary
    except Exception as exc:  # noqa: BLE001 — never fail the whole read on prep
        log.warning("preprocessing failed, using raw image: %s", exc)
        return image


__all__ = ["preprocess_image"]
