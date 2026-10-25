"""Generate stratified group-aware splits and run authoritative leakage checks.

Outputs:
  - ml/data/splits.json (tracked)
  - ml/data/splits.sha256 (tracked)
"""

import hashlib
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold

SEED = 42


class LeakageError(Exception):
    """Raised when data leakage or group violation is detected."""
    pass


def compute_file_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def check_leakage(manifest_df: pd.DataFrame, splits_data: Dict[str, Any]) -> None:
    """Rigorous leakage check:
    1. Asserts train, val, and internal_test are pairwise disjoint for all folds.
    2. Asserts whole duplicate groups stay intact in a single partition (never split).
    3. Asserts no external_test image appears in any split.
    4. Asserts no external_test image shares a duplicate group with any train_pool image.
    """
    path_to_group = dict(zip(manifest_df["relative_path"], manifest_df["duplicate_group"]))
    path_to_role = dict(zip(manifest_df["relative_path"], manifest_df["role"]))
    external_test_paths = set(manifest_df[manifest_df["role"] == "external_test"]["relative_path"])
    external_test_groups = set(manifest_df[manifest_df["role"] == "external_test"]["duplicate_group"])
    train_pool_groups = set(manifest_df[manifest_df["role"] == "train_pool"]["duplicate_group"])

    # Cross-dataset duplicate group isolation
    cross_groups = external_test_groups.intersection(train_pool_groups)
    if cross_groups:
        raise LeakageError(
            f"Leakage detected: external_test shares duplicate group(s) with train_pool: {cross_groups}"
        )

    internal_test = set(splits_data["internal_test"])

    # Check external_test in internal_test
    ext_in_test = internal_test.intersection(external_test_paths)
    if ext_in_test:
        raise LeakageError(f"Leakage detected: external_test image(s) found in internal_test: {ext_in_test}")

    # Check internal_test group integrity
    test_groups = {path_to_group[p] for p in internal_test}

    for fold_info in splits_data["folds"]:
        fold_idx = fold_info["fold"]
        train = set(fold_info["train"])
        val = set(fold_info["val"])

        # Disjoint checks
        train_val = train.intersection(val)
        if train_val:
            raise LeakageError(f"Fold {fold_idx}: train and val overlap: {train_val}")

        train_test = train.intersection(internal_test)
        if train_test:
            raise LeakageError(f"Fold {fold_idx}: train and internal_test overlap: {train_test}")

        val_test = val.intersection(internal_test)
        if val_test:
            raise LeakageError(f"Fold {fold_idx}: val and internal_test overlap: {val_test}")

        # Check external test
        ext_in_train = train.intersection(external_test_paths)
        if ext_in_train:
            raise LeakageError(f"Fold {fold_idx}: external_test image(s) found in train: {ext_in_train}")
        ext_in_val = val.intersection(external_test_paths)
        if ext_in_val:
            raise LeakageError(f"Fold {fold_idx}: external_test image(s) found in val: {ext_in_val}")

        # Group integrity checks
        train_groups = {path_to_group[p] for p in train}
        val_groups = {path_to_group[p] for p in val}

        # Train and val groups must be disjoint
        group_overlap_tv = train_groups.intersection(val_groups)
        if group_overlap_tv:
            raise LeakageError(
                f"Fold {fold_idx}: duplicate group(s) split across train and val: {group_overlap_tv}"
            )

        # Train and test groups must be disjoint
        group_overlap_tt = train_groups.intersection(test_groups)
        if group_overlap_tt:
            raise LeakageError(
                f"Fold {fold_idx}: duplicate group(s) split across train and internal_test: {group_overlap_tt}"
            )

        # Val and test groups must be disjoint
        group_overlap_vt = val_groups.intersection(test_groups)
        if group_overlap_vt:
            raise LeakageError(
                f"Fold {fold_idx}: duplicate group(s) split across val and internal_test: {group_overlap_vt}"
            )


def make_splits():
    print("=" * 70)
    print("ONCOLINK ML DATASET SPLITTING")
    print("=" * 70)

    manifest_path = "ml/data/manifest.csv"
    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"Manifest not found at {manifest_path}. Run build_manifest.py first.")

    manifest_df = pd.read_csv(manifest_path)
    print(f"Loaded manifest: {len(manifest_df)} total images")

    # Filter train_pool only (Mendeley original images)
    train_pool_df = manifest_df[manifest_df["role"] == "train_pool"].copy().reset_index(drop=True)
    n_train_pool = len(train_pool_df)
    print(f"train_pool images: {n_train_pool}")
    print(f"  - benign_appearing: {(train_pool_df['mapped_label'] == 'benign_appearing').sum()}")
    print(f"  - suspicious_for_malignancy: {(train_pool_df['mapped_label'] == 'suspicious_for_malignancy').sum()}")

    # 1. Held-out internal test set (~20% of train_pool, stratified by label, keeping duplicate groups intact)
    # Use StratifiedGroupKFold(n_splits=5) on train_pool to carve out a clean ~20% test partition
    sgkf_test = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=SEED)
    X_pool = np.arange(n_train_pool)
    y_pool = (train_pool_df["mapped_label"] == "suspicious_for_malignancy").astype(int).values
    groups_pool = train_pool_df["duplicate_group"].values

    # Select the first fold as internal_test
    rem_idx, test_idx = next(sgkf_test.split(X_pool, y_pool, groups=groups_pool))

    internal_test_paths = sorted(train_pool_df.iloc[test_idx]["relative_path"].tolist())
    rem_df = train_pool_df.iloc[rem_idx].copy().reset_index(drop=True)

    print(f"\nHeld-out internal_test set: {len(internal_test_paths)} images ({len(internal_test_paths) / n_train_pool * 100:.1f}%)")
    test_labels = train_pool_df.iloc[test_idx]["mapped_label"].value_counts().to_dict()
    print(f"  Internal test distribution: {test_labels}")
    print(f"Remaining 80% pool: {len(rem_df)} images")

    # 2. 5-fold StratifiedGroupKFold on remaining 80% pool
    sgkf_folds = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=SEED)
    X_rem = np.arange(len(rem_df))
    y_rem = (rem_df["mapped_label"] == "suspicious_for_malignancy").astype(int).values
    groups_rem = rem_df["duplicate_group"].values

    folds = []
    for fold_idx, (train_split_idx, val_split_idx) in enumerate(sgkf_folds.split(X_rem, y_rem, groups=groups_rem)):
        train_paths = sorted(rem_df.iloc[train_split_idx]["relative_path"].tolist())
        val_paths = sorted(rem_df.iloc[val_split_idx]["relative_path"].tolist())
        folds.append({
            "fold": fold_idx,
            "train": train_paths,
            "val": val_paths,
        })
        train_dist = rem_df.iloc[train_split_idx]["mapped_label"].value_counts().to_dict()
        val_dist = rem_df.iloc[val_split_idx]["mapped_label"].value_counts().to_dict()
        print(f"  Fold {fold_idx}: train={len(train_paths)} {train_dist}, val={len(val_paths)} {val_dist}")

    splits_data = {
        "seed": SEED,
        "internal_test": internal_test_paths,
        "folds": folds,
    }

    # 3. Authoritative Leakage Check
    print("\nExecuting authoritative leakage check...")
    check_leakage(manifest_df, splits_data)
    print("Leakage check PASSED: All folds and internal test are strictly disjoint, whole duplicate groups are intact, and external_test is isolated.")

    # 4. Save splits.json and compute splits.sha256
    splits_path = "ml/data/splits.json"
    with open(splits_path, "w", encoding="utf-8") as f:
        json.dump(splits_data, f, indent=2)

    splits_sha256 = compute_file_sha256(splits_path)
    with open("ml/data/splits.sha256", "w", encoding="utf-8") as f:
        f.write(f"{splits_sha256}  splits.json\n")

    print(f"\nSaved {splits_path}")
    print(f"Splits SHA-256: {splits_sha256}")
    print("Saved ml/data/splits.sha256")
    return splits_data


if __name__ == "__main__":
    make_splits()
