"""Dataset shortcut and capture-source bias investigation.

Performs:
  1. Capture-source evidence: width, height, file size, bytes per pixel, format, EXIF make/model.
     Saved to ml/reports/capture_source.json.
  2. Single-feature AUCs: cross-validated AUC and 95% bootstrap CIs for each metadata feature.
  3. Standardisation: short-side resize to 256, centre-crop 224x224, in-memory JPEG re-encode (zero metadata).
     Side-by-side comparison of metadata and EfficientNet baselines before vs after.
  4. Shortcut probes on standardised images:
     (a) 8x8 colour thumbnail (192 features)
     (b) Border-only image (centre 60% masked out) EfficientNet embeddings
     (c) Centre 60% crop only EfficientNet embeddings
     (d) HSV colour statistics (mean and std per channel)
     Saved to ml/reports/shortcut_analysis.json.
"""

import io
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from PIL import Image
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix, roc_auc_score
from sklearn.preprocessing import StandardScaler
from torchvision import models

from ml.scripts.baselines import (
    CONFIDENCE_LEVEL,
    N_BOOTSTRAP,
    SEED,
    compute_group_bootstrap_ci,
    compute_metrics,
)


def get_distribution_stats(vals: List[float]) -> Dict[str, float]:
    arr = np.array(vals, dtype=float)
    return {
        "min": round(float(np.min(arr)), 4),
        "p25": round(float(np.percentile(arr, 25)), 4),
        "median": round(float(np.median(arr)), 4),
        "p75": round(float(np.percentile(arr, 75)), 4),
        "max": round(float(np.max(arr)), 4),
        "mean": round(float(np.mean(arr)), 4),
        "std": round(float(np.std(arr)), 4),
    }


def extract_camera_info(img: Image.Image) -> Tuple[bool, Optional[str], Optional[str]]:
    """Extract EXIF presence and Camera Make and Model ONLY.
    Never extracts or stores GPS or any other EXIF tag.
    """
    exif = img.getexif()
    if not exif or len(exif) == 0:
        return False, None, None
    # Tag 271 is Make, Tag 272 is Model
    make = exif.get(271)
    model = exif.get(272)
    has_exif = True
    make_str = str(make).strip() if make is not None else None
    model_str = str(model).strip() if model is not None else None
    return has_exif, make_str, model_str


def standardise_image(img: Image.Image, quality: int = 90) -> Tuple[Image.Image, int]:
    """Resize short side to 256, centre-crop 224x224, re-encode to JPEG in memory (no metadata).
    Returns (clean_pil_image, jpeg_byte_length).
    """
    img_rgb = img.convert("RGB")
    w, h = img_rgb.size
    if w < h:
        new_w = 256
        new_h = int(round(h * 256.0 / w))
    else:
        new_h = 256
        new_w = int(round(w * 256.0 / h))

    resized = img_rgb.resize((new_w, new_h), resample=Image.Resampling.BILINEAR)

    # Centre-crop 224x224
    left = (new_w - 224) // 2
    top = (new_h - 224) // 2
    crop = resized.crop((left, top, left + 224, top + 224))

    # Re-encode to JPEG in memory with fixed quality and no metadata
    buf = io.BytesIO()
    crop.save(buf, format="JPEG", quality=quality)
    jpeg_bytes = buf.getvalue()

    clean_img = Image.open(io.BytesIO(jpeg_bytes))
    clean_img.load()
    return clean_img, len(jpeg_bytes)


def create_border_only_image(img: Image.Image) -> Image.Image:
    """Mask out centre 60% of a 224x224 image (sets centre 134x134 pixels to black).
    Keeps only outer border and background context.
    """
    assert img.size == (224, 224), f"Expected 224x224, got {img.size}"
    arr = np.array(img.convert("RGB")).copy()
    # Centre 60% = 0.60 * 224 = 134.4 -> 134 pixels
    # Start: (224 - 134) // 2 = 45; End: 45 + 134 = 179
    arr[45:179, 45:179, :] = 0
    return Image.fromarray(arr)


def create_centre_crop_image(img: Image.Image) -> Image.Image:
    """Extract centre 60% of a 224x224 image and resize back to 224x224."""
    assert img.size == (224, 224), f"Expected 224x224, got {img.size}"
    crop = img.crop((45, 45, 179, 179))
    return crop.resize((224, 224), resample=Image.Resampling.BILINEAR)


def extract_hsv_features(img: Image.Image) -> np.ndarray:
    """Extract 6 colour statistics: mean and std for each channel in HSV."""
    hsv = np.array(img.convert("HSV"), dtype=float)
    feats = []
    for c in range(3):
        feats.append(float(np.mean(hsv[:, :, c])))
        feats.append(float(np.std(hsv[:, :, c])))
    return np.array(feats, dtype=float)


def run_cross_validation_probe(
    X: np.ndarray,
    y: np.ndarray,
    splits_folds: List[Dict[str, Any]],
    pool_paths: List[str],
    duplicate_groups: List[str],
    scale: bool = True,
) -> Dict[str, Any]:
    """Train logistic regression across the 5 cross-validation folds and compute 95% group bootstrap CIs."""
    path_to_idx = {p: i for i, p in enumerate(pool_paths)}
    oof_preds = np.zeros(len(pool_paths), dtype=float)

    for fold_info in splits_folds:
        train_p = fold_info["train"]
        val_p = fold_info["val"]

        train_idx = [path_to_idx[p] for p in train_p]
        val_idx = [path_to_idx[p] for p in val_p]

        X_train, y_train = X[train_idx], y[train_idx]
        X_val = X[val_idx]

        if scale:
            scaler = StandardScaler()
            X_train = scaler.fit_transform(X_train)
            X_val = scaler.transform(X_val)

        clf = LogisticRegression(max_iter=1000, random_state=SEED)
        clf.fit(X_train, y_train)
        probs = clf.predict_proba(X_val)[:, 1]
        oof_preds[val_idx] = probs

    # Build evaluation dataframe
    eval_df = pd.DataFrame({
        "relative_path": pool_paths,
        "target": y,
        "duplicate_group": duplicate_groups,
        "pred": oof_preds,
    })

    point_metrics = compute_metrics(y, oof_preds)
    ci_metrics = compute_group_bootstrap_ci(eval_df, "pred")

    return {
        "auc": {"point": point_metrics["auc"], "ci_95": list(ci_metrics["auc"])},
        "sensitivity": {"point": point_metrics["sensitivity"], "ci_95": list(ci_metrics["sensitivity"])},
        "specificity": {"point": point_metrics["specificity"], "ci_95": list(ci_metrics["specificity"])},
    }


def main():
    print("=" * 70)
    print("ONCOLINK DATASET SHORTCUT & CAPTURE-SOURCE INVESTIGATION")
    print("=" * 70)

    # Load manifest and splits
    manifest = pd.read_csv("ml/data/manifest.csv")
    with open("ml/data/splits.json") as f:
        splits = json.load(f)

    # Filter Mendeley originals (323 images)
    mendeley = manifest[manifest["dataset"] == "mendeley_karnataka"].copy().reset_index(drop=True)
    print(f"Loaded Mendeley originals: {len(mendeley)} images")

    # -------------------------------------------------------------------------
    # 1. Capture-Source Evidence Table (ml/reports/capture_source.json)
    # -------------------------------------------------------------------------
    print("\n--- 1. Computing Capture-Source Evidence ---")
    by_class_data = {}

    for label in ["benign_appearing", "suspicious_for_malignancy"]:
        sub = mendeley[mendeley["mapped_label"] == label].copy()
        widths = sub["width"].tolist()
        heights = sub["height"].tolist()
        file_sizes = sub["file_size"].tolist()
        aspect_ratios = [w / h for w, h in zip(widths, heights)]
        bpps = [sz / (w * h) for sz, w, h in zip(file_sizes, widths, heights)]

        formats = Counter()
        exif_present_count = 0
        makes = Counter()
        models_count = Counter()

        for p in sub["relative_path"]:
            with Image.open(p) as img:
                fmt = img.format if img.format else "UNKNOWN"
                formats[fmt] += 1
                has_exif, make, model = extract_camera_info(img)
                if has_exif:
                    exif_present_count += 1
                    if make:
                        makes[make] += 1
                    if model:
                        models_count[model] += 1

        by_class_data[label] = {
            "count": len(sub),
            "formats": dict(formats),
            "width": get_distribution_stats(widths),
            "height": get_distribution_stats(heights),
            "aspect_ratio": get_distribution_stats(aspect_ratios),
            "file_size_bytes": get_distribution_stats(file_sizes),
            "bytes_per_pixel": get_distribution_stats(bpps),
            "exif": {
                "present_count": exif_present_count,
                "absent_count": len(sub) - exif_present_count,
                "camera_makes": dict(makes),
                "camera_models": dict(models_count),
            },
        }

    os.makedirs("ml/reports", exist_ok=True)
    with open("ml/reports/capture_source.json", "w", encoding="utf-8") as f:
        json.dump(by_class_data, f, indent=2)
    print("Saved ml/reports/capture_source.json")

    # -------------------------------------------------------------------------
    # 2. Single-Feature AUCs (Existing 5 Folds, 259 images)
    # -------------------------------------------------------------------------
    print("\n--- 2. Computing Single-Feature Metadata AUCs ---")
    # Identify unique pool images from splits
    pool_paths_set = set()
    for f in splits["folds"]:
        pool_paths_set.update(f["val"])
    pool_paths = sorted(list(pool_paths_set))
    print(f"5-fold cross-validation pool size: {len(pool_paths)} images")

    path_to_row = {row["relative_path"]: row for _, row in mendeley.iterrows()}
    targets = np.array([1 if path_to_row[p]["mapped_label"] == "suspicious_for_malignancy" else 0 for p in pool_paths])
    groups = [path_to_row[p]["duplicate_group"] for p in pool_paths]

    # Precompute single features for all 259 images
    feature_dict = {}
    for p in pool_paths:
        row = path_to_row[p]
        w, h, sz = row["width"], row["height"], row["file_size"]
        with Image.open(p) as img:
            fmt_is_jpeg = 1.0 if img.format == "JPEG" else 0.0
            has_exif, _, _ = extract_camera_info(img)
            exif_val = 1.0 if has_exif else 0.0

        feature_dict[p] = {
            "width": float(w),
            "height": float(h),
            "aspect_ratio": float(w / h),
            "file_size": float(sz),
            "bytes_per_pixel": float(sz / (w * h)),
            "format_is_jpeg": fmt_is_jpeg,
            "exif_present": exif_val,
        }

    single_feature_results = {}
    metadata_features = ["width", "height", "aspect_ratio", "file_size", "bytes_per_pixel", "format_is_jpeg", "exif_present"]

    for feat_name in metadata_features:
        feat_vals = np.array([[feature_dict[p][feat_name]] for p in pool_paths])
        # If feature is constant across dataset, AUC is 0.5
        if np.std(feat_vals) == 0:
            res = {
                "auc": {"point": 0.5, "ci_95": [0.5, 0.5]},
                "sensitivity": {"point": 0.0, "ci_95": [0.0, 0.0]},
                "specificity": {"point": 1.0, "ci_95": [1.0, 1.0]},
            }
        else:
            res = run_cross_validation_probe(
                feat_vals, targets, splits["folds"], pool_paths, groups, scale=True
            )
        single_feature_results[feat_name] = res
        print(f"  Feature '{feat_name}': AUC = {res['auc']['point']:.4f}  (95% CI: [{res['auc']['ci_95'][0]:.4f}, {res['auc']['ci_95'][1]:.4f}])")

    # -------------------------------------------------------------------------
    # 3. Standardisation & Before / After Baselines
    # -------------------------------------------------------------------------
    print("\n--- 3. Standardising Images & Evaluating Before/After Baselines ---")
    standardised_imgs = {}
    std_file_sizes = {}
    for p in pool_paths:
        with Image.open(p) as raw_img:
            clean_img, byte_len = standardise_image(raw_img, quality=90)
            standardised_imgs[p] = clean_img
            std_file_sizes[p] = byte_len

    # Standardised metadata baseline: width (all 224), height (all 224), file_size (re-encoded), bytes_per_pixel (re-encoded)
    std_meta_matrix = []
    for p in pool_paths:
        sz = float(std_file_sizes[p])
        bpp = sz / (224.0 * 224.0)
        # width and height are constant 224, aspect ratio is constant 1.0
        # We include file_size and bytes_per_pixel
        std_meta_matrix.append([sz, bpp])
    std_meta_matrix = np.array(std_meta_matrix)

    std_meta_probe = run_cross_validation_probe(
        std_meta_matrix, targets, splits["folds"], pool_paths, groups, scale=True
    )
    print(f"Standardised Metadata Baseline: AUC = {std_meta_probe['auc']['point']:.4f} (95% CI: [{std_meta_probe['auc']['ci_95'][0]:.4f}, {std_meta_probe['auc']['ci_95'][1]:.4f}])")

    # Frozen EfficientNet-B0 on standardised images
    print("Extracting frozen EfficientNet-B0 embeddings on standardised images...")
    weights = models.EfficientNet_B0_Weights.DEFAULT
    model = models.efficientnet_b0(weights=weights)
    model.classifier = torch.nn.Identity()
    model.eval()
    preprocess = weights.transforms()

    std_embeddings = []
    with torch.no_grad():
        for p in pool_paths:
            img = standardised_imgs[p]
            tensor = preprocess(img).unsqueeze(0)
            emb = F.normalize(model(tensor), p=2, dim=-1)
            std_embeddings.append(emb.cpu().numpy().squeeze(0))
    std_embeddings = np.array(std_embeddings)

    std_effnet_probe = run_cross_validation_probe(
        std_embeddings, targets, splits["folds"], pool_paths, groups, scale=False
    )
    print(f"Standardised EfficientNet-B0 Baseline: AUC = {std_effnet_probe['auc']['point']:.4f} (95% CI: [{std_effnet_probe['auc']['ci_95'][0]:.4f}, {std_effnet_probe['auc']['ci_95'][1]:.4f}])")

    # -------------------------------------------------------------------------
    # 4. Shortcut Probes on Standardised Images
    # -------------------------------------------------------------------------
    print("\n--- 4. Evaluating Shortcut Probes on Standardised Images ---")

    # Probe (a): 8x8 colour thumbnail (192 features)
    print("Running Probe (a): 8x8 colour thumbnail...")
    thumb_matrix = []
    for p in pool_paths:
        thumb = standardised_imgs[p].resize((8, 8), resample=Image.Resampling.BILINEAR)
        thumb_arr = np.array(thumb, dtype=float).flatten() / 255.0
        thumb_matrix.append(thumb_arr)
    thumb_matrix = np.array(thumb_matrix)
    probe_a_results = run_cross_validation_probe(
        thumb_matrix, targets, splits["folds"], pool_paths, groups, scale=True
    )
    print(f"  Probe (a) 8x8 Thumbnail: AUC = {probe_a_results['auc']['point']:.4f} (95% CI: [{probe_a_results['auc']['ci_95'][0]:.4f}, {probe_a_results['auc']['ci_95'][1]:.4f}])")

    # Probe (b): Border-only image (centre 60% masked out) EfficientNet embeddings
    print("Running Probe (b): Border-only (centre 60% masked) embeddings...")
    border_embeddings = []
    with torch.no_grad():
        for p in pool_paths:
            b_img = create_border_only_image(standardised_imgs[p])
            tensor = preprocess(b_img).unsqueeze(0)
            emb = F.normalize(model(tensor), p=2, dim=-1)
            border_embeddings.append(emb.cpu().numpy().squeeze(0))
    border_embeddings = np.array(border_embeddings)
    probe_b_results = run_cross_validation_probe(
        border_embeddings, targets, splits["folds"], pool_paths, groups, scale=False
    )
    print(f"  Probe (b) Border-Only (Centre Masked): AUC = {probe_b_results['auc']['point']:.4f} (95% CI: [{probe_b_results['auc']['ci_95'][0]:.4f}, {probe_b_results['auc']['ci_95'][1]:.4f}])")

    # Probe (c): Centre 60% crop only EfficientNet embeddings
    print("Running Probe (c): Centre 60% crop embeddings...")
    centre_embeddings = []
    with torch.no_grad():
        for p in pool_paths:
            c_img = create_centre_crop_image(standardised_imgs[p])
            tensor = preprocess(c_img).unsqueeze(0)
            emb = F.normalize(model(tensor), p=2, dim=-1)
            centre_embeddings.append(emb.cpu().numpy().squeeze(0))
    centre_embeddings = np.array(centre_embeddings)
    probe_c_results = run_cross_validation_probe(
        centre_embeddings, targets, splits["folds"], pool_paths, groups, scale=False
    )
    print(f"  Probe (c) Centre 60% Crop: AUC = {probe_c_results['auc']['point']:.4f} (95% CI: [{probe_c_results['auc']['ci_95'][0]:.4f}, {probe_c_results['auc']['ci_95'][1]:.4f}])")

    # Probe (d): HSV colour statistics (6 features: mean and std per channel)
    print("Running Probe (d): HSV colour statistics...")
    hsv_matrix = np.array([extract_hsv_features(standardised_imgs[p]) for p in pool_paths])
    probe_d_results = run_cross_validation_probe(
        hsv_matrix, targets, splits["folds"], pool_paths, groups, scale=True
    )
    print(f"  Probe (d) HSV Colour Stats: AUC = {probe_d_results['auc']['point']:.4f} (95% CI: [{probe_d_results['auc']['ci_95'][0]:.4f}, {probe_d_results['auc']['ci_95'][1]:.4f}])")

    # -------------------------------------------------------------------------
    # 5. Assemble and Save Results (ml/reports/shortcut_analysis.json)
    # -------------------------------------------------------------------------
    # Load previous baseline results for side-by-side comparison
    with open("ml/reports/baselines.json") as f:
        prev_baselines = json.load(f)["baselines"]

    shortcut_analysis_data = {
        "dataset_evaluated": "mendeley_karnataka (80% train_pool, 5 folds, 259 images)",
        "single_feature_aucs": single_feature_results,
        "standardisation_comparison": {
            "metadata_baseline": {
                "raw_before": prev_baselines["metadata_only"],
                "standardised_after": std_meta_probe,
            },
            "efficientnet_b0_baseline": {
                "raw_before": prev_baselines["frozen_efficientnet_b0"],
                "standardised_after": std_effnet_probe,
            },
        },
        "shortcut_probes": {
            "probe_a_8x8_thumbnail": {
                "description": "Logistic regression on 8x8 RGB colour thumbnail (192 features)",
                "results": probe_a_results,
            },
            "probe_b_border_only_masked_centre": {
                "description": "Frozen EfficientNet-B0 embeddings with centre 60% masked out to black (border & background only)",
                "results": probe_b_results,
            },
            "probe_c_centre_crop_only": {
                "description": "Frozen EfficientNet-B0 embeddings on centre 60% crop resized to 224x224",
                "results": probe_c_results,
            },
            "probe_d_hsv_colour_stats": {
                "description": "Logistic regression on 6 HSV colour statistics (mean and std for H, S, V channels)",
                "results": probe_d_results,
            },
        },
    }

    with open("ml/reports/shortcut_analysis.json", "w", encoding="utf-8") as f:
        json.dump(shortcut_analysis_data, f, indent=2)

    print("\nSuccessfully saved ml/reports/shortcut_analysis.json")


if __name__ == "__main__":
    main()
