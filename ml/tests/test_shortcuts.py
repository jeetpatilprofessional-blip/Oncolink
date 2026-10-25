"""Unit tests for dataset shortcut investigation, standardisation, masking, and single-feature AUCs.
"""

import io
import json
import os
import numpy as np
import pandas as pd
import pytest
from PIL import Image

from ml.scripts.analyze_shortcuts import (
    create_border_only_image,
    create_centre_crop_image,
    extract_camera_info,
    extract_hsv_features,
    standardise_image,
)
from ml.scripts.baselines import compute_metrics


def test_standardisation_output_size_and_metadata_removal():
    """Standardisation must yield strictly 224x224 RGB image with zero EXIF metadata."""
    # Create non-square test image (400x300) with synthetic EXIF tag
    raw_img = Image.new("RGB", (400, 300), color=(180, 120, 90))
    exif = raw_img.getexif()
    exif[271] = "TestCameraMake"
    exif[272] = "TestCameraModel"

    buf = io.BytesIO()
    raw_img.save(buf, format="JPEG", exif=exif)
    buf.seek(0)
    input_img = Image.open(buf)

    # Verify input has EXIF
    has_exif, make, model = extract_camera_info(input_img)
    assert has_exif is True
    assert make == "TestCameraMake"

    # Standardise
    clean_img, byte_len = standardise_image(input_img, quality=90)

    # 1. Size must be strictly (224, 224)
    assert clean_img.size == (224, 224)
    assert clean_img.mode == "RGB"
    assert byte_len > 0

    # 2. Metadata must be completely removed
    clean_exif = clean_img.getexif()
    assert len(clean_exif) == 0, f"Expected 0 EXIF tags after standardisation, got {len(clean_exif)}"
    has_exif_after, make_after, model_after = extract_camera_info(clean_img)
    assert has_exif_after is False
    assert make_after is None
    assert model_after is None


def test_masking_functions():
    """create_border_only_image must set centre 60% (134x134) strictly to 0, leaving borders intact."""
    # Create uniform white 224x224 image
    img = Image.new("RGB", (224, 224), color=(255, 255, 255))

    # Border-only image
    border_img = create_border_only_image(img)
    border_arr = np.array(border_img)

    # 1. Centre 60% box (x: 45..178, y: 45..178) must be strictly 0 (black)
    centre_box = border_arr[45:179, 45:179, :]
    assert np.all(centre_box == 0), "Centre 60% region is not completely masked to 0"
    assert centre_box.shape == (134, 134, 3)

    # 2. Border regions must remain 255 (white)
    assert np.all(border_arr[:45, :, :] == 255), "Top border was modified"
    assert np.all(border_arr[179:, :, :] == 255), "Bottom border was modified"
    assert np.all(border_arr[:, :45, :] == 255), "Left border was modified"
    assert np.all(border_arr[:, 179:, :] == 255), "Right border was modified"

    # Centre-crop image
    centre_img = create_centre_crop_image(img)
    assert centre_img.size == (224, 224)


def test_corrected_majority_baseline():
    """Corrected majority baseline must predict a constant class, giving AUC 0.5 and sensitivity 0.0 or 1.0."""
    with open("ml/reports/baselines.json") as f:
        baselines = json.load(f)["baselines"]

    maj = baselines["majority_class"]
    assert maj["auc"]["point"] == 0.5
    assert maj["auc"]["ci_95"] == [0.5, 0.5]
    assert maj["sensitivity"]["point"] in [0.0, 1.0]
    assert maj["specificity"]["point"] in [0.0, 1.0]


def test_single_feature_auc_on_handmade_array():
    """Verify AUC metric behaves correctly on perfectly separable and random hand-crafted arrays."""
    # Perfectly separable feature
    y_true = np.array([0, 0, 0, 0, 1, 1, 1, 1])
    y_prob_perfect = np.array([0.1, 0.2, 0.3, 0.4, 0.6, 0.7, 0.8, 0.9])
    res_perfect = compute_metrics(y_true, y_prob_perfect)
    assert res_perfect["auc"] == 1.0
    assert res_perfect["sensitivity"] == 1.0
    assert res_perfect["specificity"] == 1.0

    # Constant probability (majority baseline) -> AUC strictly 0.5
    y_prob_const = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    res_const = compute_metrics(y_true, y_prob_const)
    assert res_const["auc"] == 0.5
    assert res_const["sensitivity"] == 0.0
    assert res_const["specificity"] == 1.0

    # Inverted feature
    y_prob_inverted = np.array([0.9, 0.8, 0.7, 0.6, 0.4, 0.3, 0.2, 0.1])
    res_inverted = compute_metrics(y_true, y_prob_inverted)
    assert res_inverted["auc"] == 0.0
