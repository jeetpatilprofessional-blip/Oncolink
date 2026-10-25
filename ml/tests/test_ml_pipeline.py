"""Unit tests for ML pipeline data preparation, manifest, splits, leakage checks, and baselines.
"""

import copy
import json
import os
import numpy as np
import pandas as pd
import pytest

from ml.scripts.baselines import compute_group_bootstrap_ci, compute_metrics
from ml.scripts.make_splits import LeakageError, check_leakage, make_splits


@pytest.fixture(scope="module")
def manifest_df():
    manifest_path = "ml/data/manifest.csv"
    assert os.path.exists(manifest_path), "manifest.csv must exist before running tests"
    return pd.read_csv(manifest_path)


@pytest.fixture(scope="module")
def splits_data():
    splits_path = "ml/data/splits.json"
    assert os.path.exists(splits_path), "splits.json must exist before running tests"
    with open(splits_path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_manifest_no_mendeley_augmented_files(manifest_df):
    """Manifest must contain zero augmented images from Mendeley."""
    paths = manifest_df["relative_path"].tolist()
    augmented = [p for p in paths if "augmented_data" in p or "augmented_" in p]
    assert len(augmented) == 0, f"Found {len(augmented)} augmented images in manifest: {augmented[:5]}"

    # Verify counts
    mendeley_rows = manifest_df[manifest_df["dataset"] == "mendeley_karnataka"]
    kaggle_rows = manifest_df[manifest_df["dataset"] == "kaggle_oral_cancer"]
    assert len(mendeley_rows) == 323, f"Expected 323 Mendeley originals, got {len(mendeley_rows)}"
    assert len(kaggle_rows) == 103, f"Expected 103 retained Kaggle images, got {len(kaggle_rows)}"
    assert len(manifest_df) == 426, f"Expected 426 total images in manifest, got {len(manifest_df)}"


def test_splits_disjoint_and_groups_intact(manifest_df, splits_data):
    """Splits must be pairwise disjoint and duplicate groups must remain intact."""
    path_to_group = dict(zip(manifest_df["relative_path"], manifest_df["duplicate_group"]))
    internal_test = set(splits_data["internal_test"])
    assert len(internal_test) > 0, "internal_test cannot be empty"

    test_groups = {path_to_group[p] for p in internal_test}

    # Verify all members of test_groups in train_pool are completely within internal_test
    train_pool_paths = set(manifest_df[manifest_df["role"] == "train_pool"]["relative_path"])
    for g in test_groups:
        all_group_members = set(manifest_df[manifest_df["duplicate_group"] == g]["relative_path"])
        pool_group_members = all_group_members.intersection(train_pool_paths)
        assert pool_group_members.issubset(internal_test), (
            f"Duplicate group {g} is partially in internal_test and partially elsewhere"
        )

    for fold_info in splits_data["folds"]:
        fold_idx = fold_info["fold"]
        train = set(fold_info["train"])
        val = set(fold_info["val"])

        # Pairwise disjoint
        assert train.isdisjoint(val), f"Fold {fold_idx}: train and val overlap: {train.intersection(val)}"
        assert train.isdisjoint(internal_test), f"Fold {fold_idx}: train and test overlap: {train.intersection(internal_test)}"
        assert val.isdisjoint(internal_test), f"Fold {fold_idx}: val and test overlap: {val.intersection(internal_test)}"

        # Whole duplicate groups intact
        train_groups = {path_to_group[p] for p in train}
        val_groups = {path_to_group[p] for p in val}

        assert train_groups.isdisjoint(val_groups), (
            f"Fold {fold_idx}: group overlap between train and val: {train_groups.intersection(val_groups)}"
        )
        assert train_groups.isdisjoint(test_groups), (
            f"Fold {fold_idx}: group overlap between train and test: {train_groups.intersection(test_groups)}"
        )
        assert val_groups.isdisjoint(test_groups), (
            f"Fold {fold_idx}: group overlap between val and test: {val_groups.intersection(test_groups)}"
        )


def test_splits_deterministic():
    """Generating splits with the same seed produces identical output."""
    splits1 = make_splits()
    splits2 = make_splits()

    assert splits1["internal_test"] == splits2["internal_test"]
    assert len(splits1["folds"]) == len(splits2["folds"])
    for f1, f2 in zip(splits1["folds"], splits2["folds"]):
        assert f1["fold"] == f2["fold"]
        assert f1["train"] == f2["train"]
        assert f1["val"] == f2["val"]


def test_no_external_test_in_splits(manifest_df, splits_data):
    """External test images (Kaggle) must never appear in internal_test, train, or val."""
    external_test_paths = set(manifest_df[manifest_df["role"] == "external_test"]["relative_path"])
    assert len(external_test_paths) == 103

    internal_test = set(splits_data["internal_test"])
    assert internal_test.isdisjoint(external_test_paths), (
        f"external_test images found in internal_test: {internal_test.intersection(external_test_paths)}"
    )

    for fold_info in splits_data["folds"]:
        train = set(fold_info["train"])
        val = set(fold_info["val"])
        assert train.isdisjoint(external_test_paths), (
            f"Fold {fold_info['fold']}: external_test images found in train: {train.intersection(external_test_paths)}"
        )
        assert val.isdisjoint(external_test_paths), (
            f"Fold {fold_info['fold']}: external_test images found in val: {val.intersection(external_test_paths)}"
        )


def test_leakage_check_catches_planted_duplicate(manifest_df, splits_data):
    """Authoritative leakage check must raise LeakageError when an image or group is planted across partitions."""
    # 1. Baseline check should pass
    check_leakage(manifest_df, splits_data)

    # 2. Plant train image into val
    corrupted_splits = copy.deepcopy(splits_data)
    first_train_img = corrupted_splits["folds"][0]["train"][0]
    corrupted_splits["folds"][0]["val"].append(first_train_img)
    with pytest.raises(LeakageError, match="train and val overlap"):
        check_leakage(manifest_df, corrupted_splits)

    # 3. Plant internal_test image into train
    corrupted_splits2 = copy.deepcopy(splits_data)
    test_img = corrupted_splits2["internal_test"][0]
    corrupted_splits2["folds"][0]["train"].append(test_img)
    with pytest.raises(LeakageError, match="train and internal_test overlap"):
        check_leakage(manifest_df, corrupted_splits2)

    # 4. Plant external_test image into val
    corrupted_splits3 = copy.deepcopy(splits_data)
    ext_img = manifest_df[manifest_df["role"] == "external_test"]["relative_path"].iloc[0]
    corrupted_splits3["folds"][0]["val"].append(ext_img)
    with pytest.raises(LeakageError, match="external_test image"):
        check_leakage(manifest_df, corrupted_splits3)

    # 5. Plant duplicate group across train and val (by splitting a multi-item group)
    multi_groups = manifest_df[manifest_df["role"] == "train_pool"].groupby("duplicate_group").filter(lambda g: len(g) > 1)
    sample_group = multi_groups["duplicate_group"].iloc[0]
    group_paths = multi_groups[multi_groups["duplicate_group"] == sample_group]["relative_path"].tolist()
    assert len(group_paths) >= 2

    corrupted_splits4 = copy.deepcopy(splits_data)
    # Remove one member from wherever it is, and put it in the opposite split of fold 0
    corrupted_splits4["folds"][0]["train"] = [p for p in corrupted_splits4["folds"][0]["train"] if p != group_paths[1]]
    corrupted_splits4["folds"][0]["val"] = [p for p in corrupted_splits4["folds"][0]["val"] if p != group_paths[0]]
    corrupted_splits4["folds"][0]["train"].append(group_paths[0])
    corrupted_splits4["folds"][0]["val"].append(group_paths[1])

    with pytest.raises(LeakageError, match="duplicate group.*split across"):
        check_leakage(manifest_df, corrupted_splits4)


def test_bootstrap_confidence_intervals_sensible():
    """Bootstrap confidence intervals behave sensibly on synthetic arrays."""
    # Case 1: Perfect classifier (AUC = 1.0, Sens = 1.0, Spec = 1.0)
    df_perfect = pd.DataFrame({
        "relative_path": [f"img_{i}" for i in range(20)],
        "target": [0] * 10 + [1] * 10,
        "pred": [0.1] * 10 + [0.9] * 10,
        "duplicate_group": [f"grp_{i // 2}" for i in range(20)],
    })

    ci_perfect = compute_group_bootstrap_ci(df_perfect, "pred", n_bootstrap=200, random_state=42)
    assert ci_perfect["auc"] == (1.0, 1.0)
    assert ci_perfect["sensitivity"] == (1.0, 1.0)
    assert ci_perfect["specificity"] == (1.0, 1.0)

    # Case 2: Inverted/noisy classifier with non-trivial variance
    rng = np.random.RandomState(42)
    df_noisy = pd.DataFrame({
        "relative_path": [f"img_{i}" for i in range(100)],
        "target": [0] * 50 + [1] * 50,
        "pred": rng.uniform(0.0, 1.0, size=100),
        "duplicate_group": [f"grp_{i // 2}" for i in range(100)],
    })

    ci_noisy = compute_group_bootstrap_ci(df_noisy, "pred", n_bootstrap=300, random_state=42)

    for metric in ["auc", "sensitivity", "specificity"]:
        lower, upper = ci_noisy[metric]
        assert 0.0 <= lower <= 1.0, f"{metric} lower bound {lower} out of range [0, 1]"
        assert 0.0 <= upper <= 1.0, f"{metric} upper bound {upper} out of range [0, 1]"
        assert lower <= upper, f"{metric} lower bound {lower} > upper bound {upper}"
