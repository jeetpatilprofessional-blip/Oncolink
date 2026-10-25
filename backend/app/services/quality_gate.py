import io
from typing import Any

import cv2
import numpy as np
from PIL import Image

from app.services.quality_thresholds import (
    BLUR_LAPLACIAN_VAR_MIN,
    BRIGHTNESS_MEAN_MAX,
    BRIGHTNESS_MEAN_MIN,
    DETAIL_STD_DEV_MIN,
    HIGHLIGHT_BLOWN_PIXEL_VALUE,
    HIGHLIGHT_FRACTION_MAX,
    MIN_HEIGHT,
    MIN_WIDTH,
    REASON_LOW_DETAIL,
    REASON_TOO_BLURRY,
    REASON_TOO_BRIGHT,
    REASON_TOO_DARK,
    REASON_TOO_SMALL,
    SHADOW_CRUSHED_PIXEL_VALUE,
    SHADOW_FRACTION_MAX,
    STANDARDIZED_RESIZE_DIM,
)


def evaluate_image_quality(image_bytes: bytes) -> tuple[str, list[str], dict[str, Any]]:
    """
    Evaluates image quality against standardized clinical photographic criteria.
    Used both at photo upload (advisory feedback) and at case submission (authoritative gate).

    Checks performed:
    1. Minimum Resolution (width >= 480, height >= 480) -> 'too_small'
    2. Blur assessment via Laplacian variance on standardized 512x512 grayscale copy -> 'too_blurry'
    3. Exposure & Lighting via mean brightness and crushed shadow fraction -> 'too_dark'
    4. Glare & Overexposure via mean brightness and blown highlight fraction -> 'too_bright'
    5. Information content & Uniformity via grayscale pixel intensity standard deviation -> 'low_detail'

    Returns:
    - quality_status: 'passed' or 'rejected'
    - reason_codes: list of message key strings (for frontend locales/en.json mapping)
    - scores: dictionary containing computed metrics
    """
    img = Image.open(io.BytesIO(image_bytes))
    width, height = img.size
    reason_codes: list[str] = []

    # 1. Minimum Resolution Check
    if width < MIN_WIDTH or height < MIN_HEIGHT:
        reason_codes.append(REASON_TOO_SMALL)

    # 2. Convert to Grayscale Numpy Array
    gray_img = img.convert("L")
    gray_arr = np.array(gray_img, dtype=np.uint8)

    # 3. Blur Assessment (Standardized 512x512 resize to ensure scale invariance)
    resized_gray = cv2.resize(gray_arr, STANDARDIZED_RESIZE_DIM, interpolation=cv2.INTER_AREA)
    laplacian = cv2.Laplacian(resized_gray, cv2.CV_64F)
    laplacian_var = float(laplacian.var())
    if laplacian_var < BLUR_LAPLACIAN_VAR_MIN:
        reason_codes.append(REASON_TOO_BLURRY)

    # 4. Exposure & Brightness Assessment
    mean_brightness = float(np.mean(gray_arr))
    shadow_fraction = float(np.mean(gray_arr <= SHADOW_CRUSHED_PIXEL_VALUE))
    highlight_fraction = float(np.mean(gray_arr >= HIGHLIGHT_BLOWN_PIXEL_VALUE))

    if mean_brightness < BRIGHTNESS_MEAN_MIN or shadow_fraction > SHADOW_FRACTION_MAX:
        reason_codes.append(REASON_TOO_DARK)

    if mean_brightness > BRIGHTNESS_MEAN_MAX or highlight_fraction > HIGHLIGHT_FRACTION_MAX:
        reason_codes.append(REASON_TOO_BRIGHT)

    # 5. Detail & Texture Assessment (detects near-uniform / blank captures)
    std_dev = float(np.std(gray_arr))
    if std_dev < DETAIL_STD_DEV_MIN:
        reason_codes.append(REASON_LOW_DETAIL)

    quality_status = "passed" if len(reason_codes) == 0 else "rejected"

    scores = {
        "laplacian_var": round(laplacian_var, 2),
        "mean_brightness": round(mean_brightness, 2),
        "shadow_fraction": round(shadow_fraction, 4),
        "highlight_fraction": round(highlight_fraction, 4),
        "std_dev": round(std_dev, 2),
        "width": width,
        "height": height,
    }

    return quality_status, reason_codes, scores
