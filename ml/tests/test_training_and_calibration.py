"""Automated tests for CNN training, calibration, quarantine integrity, and probe metrics.
"""

import json
import os
import numpy as np
import pytest
import torch

from ml.scripts.train_experiments import (
    OralLesionDataset,
    compute_ece,
    create_model,
    set_seed,
)
from ml.scripts.analyze_shortcuts import (
    create_border_only_image,
    create_centre_crop_image,
)
from PIL import Image


def test_quarantine_integrity_during_training():
    """Verify out-of-fold predictions contain strictly the 259 development images and ZERO quarantined images."""
    with open("ml/data/splits.json") as f:
        splits = json.load(f)
    with open("ml/reports/oof_predictions.json") as f:
        oof = json.load(f)

    # 1. Total samples must be strictly 259
    assert len(oof) == 259, f"Expected 259 out-of-fold predictions, got {len(oof)}"

    # 2. Quarantined internal test set (64 images) must be completely disjoint
    internal_test = set(splits["internal_test"])
    assert len(internal_test) == 64
    oof_paths = set(oof.keys())
    assert oof_paths.isdisjoint(internal_test), "FATAL: Internal test images found in out-of-fold predictions"

    # 3. Quarantined external Kaggle set (103 images) must be completely disjoint
    for p in oof_paths:
        assert "kaggle_oral_cancer" not in p, f"FATAL: Kaggle external test image found in training pool: {p}"


def test_calibration_ece_and_brier_calculation():
    """Verify ECE calculation on synthetic perfectly calibrated vs overconfident distributions."""
    # Case 1: Perfectly calibrated probabilities
    # 100 samples with prob 0.2 (20 positive), 100 samples with prob 0.8 (80 positive)
    y_true_cal = np.array([1] * 20 + [0] * 80 + [1] * 80 + [0] * 20)
    y_prob_cal = np.array([0.2] * 100 + [0.8] * 100)

    ece_cal, bins_cal = compute_ece(y_true_cal, y_prob_cal, n_bins=2)
    assert ece_cal == 0.0, f"Expected ECE 0.0 for perfectly calibrated probabilities, got {ece_cal}"

    # Case 2: Overconfident probabilities (predicts 0.99 for all samples, but only 50% are positive)
    y_true_over = np.array([1] * 50 + [0] * 50)
    y_prob_over = np.array([0.99] * 100)

    ece_over, bins_over = compute_ece(y_true_over, y_prob_over, n_bins=2)
    # Expected gap: |0.50 - 0.99| = 0.49
    assert abs(ece_over - 0.49) < 0.01, f"Expected ECE ~0.49, got {ece_over}"


def test_training_reproducibility():
    """Verify fixed seed produces identical model weights upon initialization."""
    set_seed(42)
    m1 = create_model()
    w1 = m1.classifier[1].weight.clone()

    set_seed(42)
    m2 = create_model()
    w2 = m2.classifier[1].weight.clone()

    assert torch.allclose(w1, w2), "Model initialization with fixed seed is non-deterministic"


def test_shortcut_probe_pixel_coverage():
    """Verify border-only and centre-crop probe functions properly isolate peripheral vs central regions."""
    # Create image with black border and white center
    img = Image.new("RGB", (224, 224), color=(0, 0, 0))
    # Fill center 134x134 with white
    arr = np.array(img).copy()
    arr[45:179, 45:179, :] = 255
    input_img = Image.fromarray(arr)

    # 1. Border-only probe masks the center 134x134 box to 0
    border_img = create_border_only_image(input_img)
    border_arr = np.array(border_img)
    # The entire image should now be 0 (since border was 0 and center was zeroed out)
    assert np.all(border_arr == 0), "Border-only image failed to mask center"

    # 2. Centre-crop probe extracts the center 134x134 box (all 255) and resizes
    centre_img = create_centre_crop_image(input_img)
    centre_arr = np.array(centre_img)
    assert np.all(centre_arr == 255), "Centre-crop image failed to preserve center content"


def test_training_evaluation_report_completeness():
    """Verify training_evaluation.json contains all required metrics, CIs, calibration, and probe numbers."""
    with open("ml/reports/training_evaluation.json") as f:
        report = json.load(f)

    for arm in ["arm_1_standard", "arm_2_shortcut_regularized", "arm_3_background_suppression"]:
        assert arm in report, f"Missing arm {arm} in training_evaluation.json"
        arm_data = report[arm]

        # Folds
        assert len(arm_data["folds"]) == 5, f"Expected 5 fold metrics for {arm}"

        # Full image metrics
        full = arm_data["full_image"]
        assert 0.7 <= full["auc"]["point"] <= 1.0
        assert len(full["auc"]["ci_95"]) == 2
        assert full["auc"]["ci_95"][0] <= full["auc"]["point"] <= full["auc"]["ci_95"][1]
        assert "pr_auc" in full

        # Calibration
        cal = arm_data["calibration"]
        assert "brier_score_calibrated" in cal
        assert "ece_calibrated" in cal
        assert cal["ece_calibrated"] <= cal["ece_raw"], f"Expected calibration to improve ECE for {arm}"

        # Shortcut probes
        probes = arm_data["shortcut_probes"]
        assert "border_only_masked_centre" in probes
        assert "centre_only_crop" in probes
        b_auc = probes["border_only_masked_centre"]["auc"]["point"]
        c_auc = probes["centre_only_crop"]["auc"]["point"]
        assert 0.5 <= b_auc <= 1.0
        assert 0.5 <= c_auc <= 1.0
