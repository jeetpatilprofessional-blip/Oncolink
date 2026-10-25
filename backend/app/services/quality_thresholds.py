"""
ONCOLINK Image Quality Gate Thresholds
======================================

Initial heuristic thresholds for automated image quality assessment.
All thresholds defined here are research prototype heuristics that must be calibrated
and tuned against real-world smartphone photographs collected in community screening camps.

Authoritative Quality Metric & Threshold Reference Table:
--------------------------------------------------------
| Metric Name | Constant Identifier | Threshold Value | Violation Reason Code | Description / Clinical Rationale |
|---|---|---|---|---|
| Minimum Width | MIN_WIDTH | 480 px | too_small | Minimum horizontal pixel dimension for adequate oral tissue resolution |
| Minimum Height | MIN_HEIGHT | 480 px | too_small | Minimum vertical pixel dimension for clinical inspection |
| Laplacian Variance | BLUR_LAPLACIAN_VAR_MIN | 100.0 | too_blurry | Variance of Laplacian on 512x512 normalized grayscale copy; rejects out-of-focus captures |
| Minimum Brightness | BRIGHTNESS_MEAN_MIN | 40.0 | too_dark | Lower limit on average pixel luminance (0-255 scale) |
| Max Crushed Shadows | SHADOW_FRACTION_MAX | 0.45 | too_dark | Maximum fraction of pixels with luminance <= 20 (underexposure) |
| Maximum Brightness | BRIGHTNESS_MEAN_MAX | 215.0 | too_bright | Upper limit on average pixel luminance (overexposure) |
| Max Blown Highlights | HIGHLIGHT_FRACTION_MAX | 0.40 | too_bright | Maximum fraction of pixels with luminance >= 240 (flash glare / specular saturation) |
| Minimum Detail / StdDev | DETAIL_STD_DEV_MIN | 12.0 | low_detail | Minimum standard deviation of grayscale intensities; rejects blank / uniform surfaces |
"""

# Resolution limits
MIN_WIDTH: int = 480
MIN_HEIGHT: int = 480

# Blur assessment (evaluated on 512x512 grayscale copy)
STANDARDIZED_RESIZE_DIM: tuple[int, int] = (512, 512)
BLUR_LAPLACIAN_VAR_MIN: float = 100.0

# Brightness & exposure bounds (0.0 to 255.0)
BRIGHTNESS_MEAN_MIN: float = 40.0
BRIGHTNESS_MEAN_MAX: float = 215.0

# Crushed shadow threshold & tolerance
SHADOW_CRUSHED_PIXEL_VALUE: int = 20
SHADOW_FRACTION_MAX: float = 0.45

# Blown highlight threshold & tolerance
HIGHLIGHT_BLOWN_PIXEL_VALUE: int = 240
HIGHLIGHT_FRACTION_MAX: float = 0.40

# Uniformity / Texture detail threshold
DETAIL_STD_DEV_MIN: float = 12.0

# Authoritative reason code keys (returned as translation keys for locales/en.json)
REASON_TOO_BLURRY: str = "too_blurry"
REASON_TOO_DARK: str = "too_dark"
REASON_TOO_BRIGHT: str = "too_bright"
REASON_TOO_SMALL: str = "too_small"
REASON_LOW_DETAIL: str = "low_detail"
