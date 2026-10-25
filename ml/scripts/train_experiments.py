"""Train, calibrate, and evaluate controlled transfer-learning experiments on OncoLink.

Authorized by Decision 21 in docs/DECISIONS.md.
Evaluates 3 experimental arms across the authorized 259-image development pool (5 folds):
  - Arm 1: Standard Transfer Learning (minimal augmentation)
  - Arm 2: Shortcut-Regularized Transfer Learning (ColorJitter, RandomResizedCrop, Rotation)
  - Arm 3: Background-Suppression Training (RandomBorderMasking, ColorJitter)

Outputs:
  - ml/reports/training_evaluation.json
  - ml/reports/oof_predictions.json
  - ml/reports/plots/*.png (gitignored)
"""

import copy
import io
import json
import math
import os
import random
import sys
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
    precision_recall_curve,
)
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset
from torchvision import models, transforms

from ml.scripts.analyze_shortcuts import (
    create_border_only_image,
    create_centre_crop_image,
    standardise_image,
)
from ml.scripts.baselines import (
    CONFIDENCE_LEVEL,
    N_BOOTSTRAP,
    SEED,
    compute_group_bootstrap_ci,
    compute_metrics,
)

# Set random seeds for reproducibility
def set_seed(seed=SEED):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)

set_seed(SEED)

DEVICE = torch.device("cpu")


class RandomBorderMasking:
    """Mask peripheral borders with probability p to force lesion attention."""
    def __init__(self, p: float = 0.7, border_fraction: float = 0.15):
        self.p = p
        self.border_fraction = border_fraction

    def __call__(self, img: Image.Image) -> Image.Image:
        if random.random() > self.p:
            return img
        arr = np.array(img).copy()
        h, w, _ = arr.shape
        bh = int(round(h * self.border_fraction))
        bw = int(round(w * self.border_fraction))
        arr[:bh, :, :] = 0
        arr[-bh:, :, :] = 0
        arr[:, :bw, :] = 0
        arr[:, -bw:, :] = 0
        return Image.fromarray(arr)


class OralLesionDataset(Dataset):
    def __init__(
        self,
        image_records: List[Dict[str, Any]],
        transform: Optional[transforms.Compose] = None,
        probe_mode: str = "full", # 'full', 'border_only', 'centre_only'
    ):
        self.records = image_records
        self.transform = transform
        self.probe_mode = probe_mode
        self.cache = {}
        for r in self.records:
            p = r["relative_path"]
            with Image.open(p) as raw_img:
                clean_img, _ = standardise_image(raw_img, quality=90)
                if self.probe_mode == "border_only":
                    clean_img = create_border_only_image(clean_img)
                elif self.probe_mode == "centre_only":
                    clean_img = create_centre_crop_image(clean_img)
                self.cache[p] = clean_img

    def __len__(self):
        return len(self.records)

    def __getitem__(self, idx):
        rec = self.records[idx]
        img = self.cache[rec["relative_path"]].copy()
        if self.transform:
            img_tensor = self.transform(img)
        else:
            img_tensor = transforms.ToTensor()(img)
        target = rec["target"]
        return img_tensor, target, rec["relative_path"], rec["duplicate_group"]


def get_transforms(arm: str, is_train: bool) -> transforms.Compose:
    norm = transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
    if not is_train:
        return transforms.Compose([transforms.ToTensor(), norm])

    if arm == "arm_1_standard":
        return transforms.Compose([
            transforms.RandomHorizontalFlip(p=0.5),
            transforms.ToTensor(),
            norm,
        ])
    elif arm == "arm_2_shortcut_regularized":
        return transforms.Compose([
            transforms.RandomResizedCrop(224, scale=(0.7, 1.0), ratio=(0.9, 1.1)),
            transforms.RandomHorizontalFlip(p=0.5),
            transforms.RandomVerticalFlip(p=0.2),
            transforms.RandomRotation(degrees=15),
            transforms.ColorJitter(brightness=0.3, contrast=0.3, saturation=0.3, hue=0.1),
            transforms.ToTensor(),
            norm,
        ])
    elif arm == "arm_3_background_suppression":
        return transforms.Compose([
            RandomBorderMasking(p=0.7, border_fraction=0.15),
            transforms.RandomHorizontalFlip(p=0.5),
            transforms.ColorJitter(brightness=0.2, contrast=0.2),
            transforms.ToTensor(),
            norm,
        ])
    else:
        raise ValueError(f"Unknown arm: {arm}")


def create_model() -> nn.Module:
    weights = models.EfficientNet_B0_Weights.DEFAULT
    model = models.efficientnet_b0(weights=weights)
    # Freeze initial feature stages, fine-tune top stages and head
    for param in model.parameters():
        param.requires_grad = False

    # Unfreeze top stages (stage 6, 7, 8) and classifier head
    for block in model.features[6:]:
        for param in block.parameters():
            param.requires_grad = True

    in_features = model.classifier[1].in_features
    model.classifier = nn.Sequential(
        nn.Dropout(p=0.3, inplace=True),
        nn.Linear(in_features, 2),
    )
    return model


def compute_ece(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 5) -> Tuple[float, List[Dict[str, float]]]:
    """Compute Expected Calibration Error using quantile binning."""
    quantiles = np.linspace(0, 1, n_bins + 1)
    bin_edges = np.quantile(y_prob, quantiles)
    bin_edges[0] = 0.0
    bin_edges[-1] = 1.0 + 1e-7

    ece = 0.0
    bin_details = []
    n = len(y_true)

    for i in range(n_bins):
        low, high = bin_edges[i], bin_edges[i + 1]
        mask = (y_prob >= low) & (y_prob < high)
        if np.sum(mask) == 0:
            continue
        bin_conf = float(np.mean(y_prob[mask]))
        bin_acc = float(np.mean(y_true[mask]))
        bin_size = int(np.sum(mask))
        weight = bin_size / n
        ece += weight * abs(bin_acc - bin_conf)
        bin_details.append({
            "bin": i,
            "range": [round(float(low), 4), round(float(high), 4)],
            "count": bin_size,
            "mean_confidence": round(bin_conf, 4),
            "accuracy": round(bin_acc, 4),
            "gap": round(abs(bin_acc - bin_conf), 4),
        })

    return round(float(ece), 4), bin_details


def train_single_fold(
    arm: str,
    fold_idx: int,
    train_records: List[Dict[str, Any]],
    val_records: List[Dict[str, Any]],
    epochs: int = 15,
    batch_size: int = 16,
    lr: float = 1e-4,
    weight_decay: float = 1e-2,
) -> Tuple[nn.Module, List[Dict[str, float]], Dict[str, Any]]:
    set_seed(SEED + fold_idx)
    train_ds = OralLesionDataset(train_records, transform=get_transforms(arm, is_train=True))
    val_ds = OralLesionDataset(val_records, transform=get_transforms(arm, is_train=False))

    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False)

    model = create_model().to(DEVICE)
    trainable_params = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(trainable_params, lr=lr, weight_decay=weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    criterion = nn.CrossEntropyLoss()

    history = []
    best_loss = float("inf")
    best_state = None

    for epoch in range(1, epochs + 1):
        model.train()
        train_loss = 0.0
        for x, y, _, _ in train_loader:
            x, y = x.to(DEVICE), y.to(DEVICE)
            optimizer.zero_grad()
            out = model(x)
            loss = criterion(out, y)
            loss.backward()
            optimizer.step()
            train_loss += loss.item() * len(y)
        train_loss /= len(train_ds)
        scheduler.step()

        # Validation evaluation
        model.eval()
        val_loss = 0.0
        val_preds = []
        val_targets = []
        with torch.no_grad():
            for x, y, _, _ in val_loader:
                x, y = x.to(DEVICE), y.to(DEVICE)
                out = model(x)
                loss = criterion(out, y)
                val_loss += loss.item() * len(y)
                probs = F.softmax(out, dim=-1)[:, 1]
                val_preds.extend(probs.cpu().numpy())
                val_targets.extend(y.cpu().numpy())
        val_loss /= len(val_ds)
        val_auc = roc_auc_score(val_targets, val_preds) if len(np.unique(val_targets)) > 1 else 0.5

        history.append({
            "epoch": epoch,
            "train_loss": round(train_loss, 4),
            "val_loss": round(val_loss, 4),
            "val_auc": round(val_auc, 4),
        })

        if val_loss < best_loss:
            best_loss = val_loss
            best_state = copy.deepcopy(model.state_dict())

    # Load best checkpoint
    model.load_state_dict(best_state)
    model.eval()

    # Final validation inference with best model
    val_logits = []
    val_probs = []
    val_y = []
    val_paths = []
    with torch.no_grad():
        for x, y, paths, _ in val_loader:
            x = x.to(DEVICE)
            out = model(x)
            logits = out[:, 1] - out[:, 0]
            probs = F.softmax(out, dim=-1)[:, 1]
            val_logits.extend(logits.cpu().numpy().tolist())
            val_probs.extend(probs.cpu().numpy().tolist())
            val_y.extend(y.numpy().tolist())
            val_paths.extend(paths)

    val_eval = {
        "paths": val_paths,
        "y_true": val_y,
        "logits": val_logits,
        "probs": val_probs,
    }
    return model, history, val_eval


def evaluate_model_on_probe(
    model: nn.Module,
    records: List[Dict[str, Any]],
    probe_mode: str,
) -> Dict[str, float]:
    val_ds = OralLesionDataset(records, transform=get_transforms("arm_1_standard", is_train=False), probe_mode=probe_mode)
    loader = DataLoader(val_ds, batch_size=16, shuffle=False)
    model.eval()
    probs = []
    y_true = []
    with torch.no_grad():
        for x, y, _, _ in loader:
            x = x.to(DEVICE)
            out = model(x)
            prob = F.softmax(out, dim=-1)[:, 1]
            probs.extend(prob.cpu().numpy().tolist())
            y_true.extend(y.numpy().tolist())
    auc = roc_auc_score(y_true, probs) if len(np.unique(y_true)) > 1 else 0.5
    return {"y_true": y_true, "probs": probs, "auc": float(auc)}


def main():
    print("=" * 70)
    print("ONCOLINK CONTROLLED TRANSFER-LEARNING EXPERIMENTS (DECISION 21)")
    print("=" * 70)

    # 1. Load manifest and splits
    manifest = pd.read_csv("ml/data/manifest.csv")
    with open("ml/data/splits.json") as f:
        splits = json.load(f)

    # STRICT QUARANTINE ASSERTION
    internal_test_set = set(splits["internal_test"])
    external_test_paths = set(manifest[manifest["role"] == "external_test"]["relative_path"])
    print(f"Quarantined internal test set: {len(internal_test_set)} images (isolated)")
    print(f"Quarantined external Kaggle set: {len(external_test_paths)} images (isolated)")

    # Build pool records for the 259 development images only
    path_to_row = {row["relative_path"]: row for _, row in manifest.iterrows()}
    pool_paths_set = set()
    for f in splits["folds"]:
        pool_paths_set.update(f["val"])
    pool_paths = sorted(list(pool_paths_set))
    assert len(pool_paths) == 259, f"Expected 259 development images, got {len(pool_paths)}"

    # Double check that no quarantined image enters pool
    assert pool_paths_set.isdisjoint(internal_test_set), "FATAL: internal_test image found in development pool"
    assert pool_paths_set.isdisjoint(external_test_paths), "FATAL: external_test image found in development pool"
    print(f"Development pool verified: {len(pool_paths)} images strictly from train_pool")

    pool_records = []
    for p in pool_paths:
        row = path_to_row[p]
        target = 1 if row["mapped_label"] == "suspicious_for_malignancy" else 0
        pool_records.append({
            "relative_path": p,
            "target": target,
            "duplicate_group": row["duplicate_group"],
        })
    path_to_rec = {r["relative_path"]: r for r in pool_records}

    arms = [
        "arm_1_standard",
        "arm_2_shortcut_regularized",
        "arm_3_background_suppression",
    ]

    all_arm_results = {}
    oof_predictions_all = {p: {"target": path_to_rec[p]["target"], "duplicate_group": path_to_rec[p]["duplicate_group"]} for p in pool_paths}
    training_histories = {}

    for arm in arms:
        print(f"\n" + "=" * 60)
        print(f"STARTING EXPERIMENTAL ARM: {arm.upper()}")
        print("=" * 60)

        arm_oof_logits = {}
        arm_oof_probs = {}
        arm_border_probs = {}
        arm_centre_probs = {}
        fold_results = []
        arm_histories = []

        for fold_info in splits["folds"]:
            fold_idx = fold_info["fold"]
            train_records = [path_to_rec[p] for p in fold_info["train"]]
            val_records = [path_to_rec[p] for p in fold_info["val"]]

            print(f"Training Fold {fold_idx} (train={len(train_records)}, val={len(val_records)})...")
            trained_model, hist, val_eval = train_single_fold(
                arm=arm,
                fold_idx=fold_idx,
                train_records=train_records,
                val_records=val_records,
                epochs=15,
                batch_size=16,
                lr=1e-4,
                weight_decay=1e-2,
            )
            arm_histories.append({"fold": fold_idx, "history": hist})

            # Record standard out-of-fold predictions
            for p, logit, prob in zip(val_eval["paths"], val_eval["logits"], val_eval["probs"]):
                arm_oof_logits[p] = logit
                arm_oof_probs[p] = prob

            # Run shortcut probes on validation fold
            border_probe = evaluate_model_on_probe(trained_model, val_records, "border_only")
            centre_probe = evaluate_model_on_probe(trained_model, val_records, "centre_only")
            for p, prob in zip(val_eval["paths"], border_probe["probs"]):
                arm_border_probs[p] = prob
            for p, prob in zip(val_eval["paths"], centre_probe["probs"]):
                arm_centre_probs[p] = prob

            fold_auc = roc_auc_score(val_eval["y_true"], val_eval["probs"])
            fold_results.append({
                "fold": fold_idx,
                "val_auc": round(float(fold_auc), 4),
                "val_border_auc": round(float(border_probe["auc"]), 4),
                "val_centre_auc": round(float(centre_probe["auc"]), 4),
            })
            print(f"  Fold {fold_idx} Done: Full AUC = {fold_auc:.4f} | Border AUC = {border_probe['auc']:.4f} | Centre AUC = {centre_probe['auc']:.4f}")

        training_histories[arm] = arm_histories

        # Assemble full out-of-fold array
        y_all = np.array([path_to_rec[p]["target"] for p in pool_paths])
        groups_all = [path_to_rec[p]["duplicate_group"] for p in pool_paths]
        logits_arr = np.array([arm_oof_logits[p] for p in pool_paths])
        raw_probs_arr = np.array([arm_oof_probs[p] for p in pool_paths])
        border_probs_arr = np.array([arm_border_probs[p] for p in pool_paths])
        centre_probs_arr = np.array([arm_centre_probs[p] for p in pool_paths])

        # ---------------------------------------------------------------------
        # Probability Calibration (Platt Scaling via Out-of-Fold Fitting)
        # ---------------------------------------------------------------------
        # Fit univariate logistic regression on logits to produce calibrated probabilities
        calibrator = LogisticRegression(C=1.0, solver="lbfgs")
        calibrator.fit(logits_arr.reshape(-1, 1), y_all)
        calibrated_probs_arr = calibrator.predict_proba(logits_arr.reshape(-1, 1))[:, 1]

        # Record into oof_predictions_all
        for p in pool_paths:
            oof_predictions_all[p][f"{arm}_logit"] = float(arm_oof_logits[p])
            oof_predictions_all[p][f"{arm}_raw_prob"] = float(arm_oof_probs[p])
            oof_predictions_all[p][f"{arm}_cal_prob"] = float(calibrator.predict_proba([[arm_oof_logits[p]]])[0, 1])
            oof_predictions_all[p][f"{arm}_border_prob"] = float(arm_border_probs[p])
            oof_predictions_all[p][f"{arm}_centre_prob"] = float(arm_centre_probs[p])

        # Evaluate Metrics
        eval_df = pd.DataFrame({
            "relative_path": pool_paths,
            "target": y_all,
            "duplicate_group": groups_all,
            "raw_prob": raw_probs_arr,
            "cal_prob": calibrated_probs_arr,
            "border_prob": border_probs_arr,
            "centre_prob": centre_probs_arr,
        })

        # 1. Full Image Performance
        full_metrics = compute_metrics(y_all, calibrated_probs_arr)
        full_ci = compute_group_bootstrap_ci(eval_df, "cal_prob")
        pr_auc = float(average_precision_score(y_all, calibrated_probs_arr))

        # 2. Calibration Metrics
        brier_uncal = float(np.mean((raw_probs_arr - y_all) ** 2))
        brier_cal = float(np.mean((calibrated_probs_arr - y_all) ** 2))
        nll_uncal = float(log_loss(y_all, np.clip(raw_probs_arr, 1e-7, 1.0 - 1e-7)))
        nll_cal = float(log_loss(y_all, np.clip(calibrated_probs_arr, 1e-7, 1.0 - 1e-7)))
        ece_uncal, ece_uncal_bins = compute_ece(y_all, raw_probs_arr, n_bins=5)
        ece_cal, ece_cal_bins = compute_ece(y_all, calibrated_probs_arr, n_bins=5)

        # 3. Operating Threshold Selection (targeting >= 85% Sensitivity on OOF data)
        # Find threshold where sensitivity >= 0.85 with maximum specificity
        fpr, tpr, thresholds = roc_curve(y_all, calibrated_probs_arr)
        eligible_thresh = [th for th, sens in zip(thresholds, tpr) if sens >= 0.85]
        # In roc_curve thresholds descend; eligible_thresh[0] is the highest threshold achieving >= 85% sensitivity
        selected_thresh = float(eligible_thresh[0]) if eligible_thresh else 0.5
        selected_thresh = round(selected_thresh, 4)

        y_pred_50 = (calibrated_probs_arr >= 0.5).astype(int)
        y_pred_opt = (calibrated_probs_arr >= selected_thresh).astype(int)

        tn50, fp50, fn50, tp50 = confusion_matrix(y_all, y_pred_50, labels=[0, 1]).ravel()
        tn_opt, fp_opt, fn_opt, tp_opt = confusion_matrix(y_all, y_pred_opt, labels=[0, 1]).ravel()

        # 4. Shortcut Probes
        border_metrics = compute_metrics(y_all, border_probs_arr)
        border_ci = compute_group_bootstrap_ci(eval_df, "border_prob")
        centre_metrics = compute_metrics(y_all, centre_probs_arr)
        centre_ci = compute_group_bootstrap_ci(eval_df, "centre_prob")

        arm_summary = {
            "folds": fold_results,
            "full_image": {
                "auc": {"point": full_metrics["auc"], "ci_95": list(full_ci["auc"])},
                "pr_auc": round(pr_auc, 4),
                "sensitivity": {"point": full_metrics["sensitivity"], "ci_95": list(full_ci["sensitivity"])},
                "specificity": {"point": full_metrics["specificity"], "ci_95": list(full_ci["specificity"])},
                "metrics_at_0_5": {
                    "confusion_matrix": {"tn": int(tn50), "fp": int(fp50), "fn": int(fn50), "tp": int(tp50)},
                    "precision": round(float(precision_score(y_all, y_pred_50, zero_division=0)), 4),
                    "recall_sensitivity": round(float(recall_score(y_all, y_pred_50, zero_division=0)), 4),
                    "specificity": round(float(tn50 / (tn50 + fp50)), 4),
                    "f1": round(float(f1_score(y_all, y_pred_50, zero_division=0)), 4),
                    "balanced_accuracy": round(float(balanced_accuracy_score(y_all, y_pred_50)), 4),
                },
                "triage_operating_threshold": {
                    "threshold": selected_thresh,
                    "target_criterion": "sensitivity >= 0.85 on development pool",
                    "confusion_matrix": {"tn": int(tn_opt), "fp": int(fp_opt), "fn": int(fn_opt), "tp": int(tp_opt)},
                    "precision": round(float(precision_score(y_all, y_pred_opt, zero_division=0)), 4),
                    "sensitivity": round(float(recall_score(y_all, y_pred_opt, zero_division=0)), 4),
                    "specificity": round(float(tn_opt / (tn_opt + fp_opt)), 4),
                    "f1": round(float(f1_score(y_all, y_pred_opt, zero_division=0)), 4),
                    "balanced_accuracy": round(float(balanced_accuracy_score(y_all, y_pred_opt)), 4),
                },
            },
            "calibration": {
                "brier_score_raw": round(brier_uncal, 4),
                "brier_score_calibrated": round(brier_cal, 4),
                "log_loss_raw": round(nll_uncal, 4),
                "log_loss_calibrated": round(nll_cal, 4),
                "ece_raw": ece_uncal,
                "ece_calibrated": ece_cal,
                "bins_calibrated": ece_cal_bins,
            },
            "shortcut_probes": {
                "border_only_masked_centre": {
                    "description": "Centre 60% masked to black; peripheral background only",
                    "auc": {"point": border_metrics["auc"], "ci_95": list(border_ci["auc"])},
                },
                "centre_only_crop": {
                    "description": "Centre 60% crop resized to 224x224; lesion region only",
                    "auc": {"point": centre_metrics["auc"], "ci_95": list(centre_ci["auc"])},
                },
            },
        }

        all_arm_results[arm] = arm_summary
        print(f"\n--- {arm.upper()} SUMMARY ---")
        print(f"  Full Image AUC:    {full_metrics['auc']:.4f}  (95% CI: [{full_ci['auc'][0]:.4f}, {full_ci['auc'][1]:.4f}])")
        print(f"  Border-Only AUC:   {border_metrics['auc']:.4f}  (95% CI: [{border_ci['auc'][0]:.4f}, {border_ci['auc'][1]:.4f}])")
        print(f"  Centre-Crop AUC:   {centre_metrics['auc']:.4f}  (95% CI: [{centre_ci['auc'][0]:.4f}, {centre_ci['auc'][1]:.4f}])")
        print(f"  ECE (Raw -> Cal):  {ece_uncal:.4f} -> {ece_cal:.4f}")
        print(f"  Brier (Raw -> Cal): {brier_uncal:.4f} -> {brier_cal:.4f}")

    # -------------------------------------------------------------------------
    # Save Reports
    # -------------------------------------------------------------------------
    os.makedirs("ml/reports", exist_ok=True)
    os.makedirs("ml/reports/plots", exist_ok=True)

    with open("ml/reports/training_evaluation.json", "w", encoding="utf-8") as f:
        json.dump(all_arm_results, f, indent=2)
    print("\nSaved ml/reports/training_evaluation.json")

    with open("ml/reports/oof_predictions.json", "w", encoding="utf-8") as f:
        json.dump(oof_predictions_all, f, indent=2)
    print("Saved ml/reports/oof_predictions.json")

    # -------------------------------------------------------------------------
    # Generate Diagnostic Plots (saved under ml/reports/plots/, gitignored)
    # -------------------------------------------------------------------------
    print("Generating diagnostic plots in ml/reports/plots/...")
    # Plot 1: Training & Validation Loss curves
    fig, axes = plt.subplots(1, 3, figsize=(16, 4), sharey=True)
    for ax, arm in zip(axes, arms):
        for fold_data in training_histories[arm]:
            epochs_x = [h["epoch"] for h in fold_data["history"]]
            t_loss = [h["train_loss"] for h in fold_data["history"]]
            v_loss = [h["val_loss"] for h in fold_data["history"]]
            ax.plot(epochs_x, t_loss, linestyle="--", alpha=0.5, label="Train" if fold_data["fold"] == 0 else "")
            ax.plot(epochs_x, v_loss, linestyle="-", label=f"Fold {fold_data['fold']}")
        ax.set_title(arm.replace("arm_", "Arm ").replace("_", " ").title())
        ax.set_xlabel("Epoch")
        ax.set_ylabel("CrossEntropy Loss")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig("ml/reports/plots/training_curves.png", dpi=150)
    plt.close()

    # Plot 2: ROC Curves
    y_all = np.array([path_to_rec[p]["target"] for p in pool_paths])
    plt.figure(figsize=(7, 6))
    plt.plot([0, 1], [0, 1], "k--", label="Chance (AUC = 0.50)")
    for arm in arms:
        probs = np.array([oof_predictions_all[p][f"{arm}_cal_prob"] for p in pool_paths])
        fpr, tpr, _ = roc_curve(y_all, probs)
        auc_val = all_arm_results[arm]["full_image"]["auc"]["point"]
        ci_str = f"[{all_arm_results[arm]['full_image']['auc']['ci_95'][0]:.3f}, {all_arm_results[arm]['full_image']['auc']['ci_95'][1]:.3f}]"
        plt.plot(fpr, tpr, label=f"{arm} (AUC = {auc_val:.3f} {ci_str})")
    plt.xlabel("False Positive Rate (1 - Specificity)")
    plt.ylabel("True Positive Rate (Sensitivity)")
    plt.title("Out-of-Fold ROC Curves (5-Fold CV, N = 259)")
    plt.legend(loc="lower right", fontsize=8)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig("ml/reports/plots/roc_curves.png", dpi=150)
    plt.close()

    # Plot 3: Precision-Recall Curves
    plt.figure(figsize=(7, 6))
    for arm in arms:
        probs = np.array([oof_predictions_all[p][f"{arm}_cal_prob"] for p in pool_paths])
        prec, rec, _ = precision_recall_curve(y_all, probs)
        pr_auc = all_arm_results[arm]["full_image"]["pr_auc"]
        plt.plot(rec, prec, label=f"{arm} (PR-AUC = {pr_auc:.3f})")
    plt.xlabel("Recall (Sensitivity)")
    plt.ylabel("Precision (PPV)")
    plt.title("Out-of-Fold Precision-Recall Curves")
    plt.legend(loc="lower left", fontsize=8)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig("ml/reports/plots/pr_curves.png", dpi=150)
    plt.close()

    # Plot 4: Shortcut Probes Comparison Bar Chart
    plt.figure(figsize=(9, 5))
    x_indices = np.arange(len(arms))
    width = 0.25

    full_aucs = [all_arm_results[a]["full_image"]["auc"]["point"] for a in arms]
    border_aucs = [all_arm_results[a]["shortcut_probes"]["border_only_masked_centre"]["auc"]["point"] for a in arms]
    centre_aucs = [all_arm_results[a]["shortcut_probes"]["centre_only_crop"]["auc"]["point"] for a in arms]

    plt.bar(x_indices - width, full_aucs, width=width, label="Full Standardised Image", color="#2b5c8f")
    plt.bar(x_indices, border_aucs, width=width, label="Border-Only (Centre Masked)", color="#d9534f")
    plt.bar(x_indices + width, centre_aucs, width=width, label="Centre-Crop Only", color="#5cb85c")
    plt.axhline(0.5, color="black", linestyle="--", alpha=0.7, label="Chance (0.50)")
    plt.xticks(x_indices, [a.replace("arm_", "Arm ").replace("_", " ").title() for a in arms])
    plt.ylabel("Cross-Validated AUC")
    plt.title("Shortcut Probes: Full vs Border vs Centre Lesion Signal")
    plt.ylim(0.4, 1.0)
    plt.legend(loc="upper right", fontsize=8)
    plt.grid(True, axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig("ml/reports/plots/shortcut_probes_comparison.png", dpi=150)
    plt.close()

    # Plot 5: Calibration Reliability Diagram (Arm 2 as representative)
    plt.figure(figsize=(6, 6))
    arm2_bins = all_arm_results["arm_2_shortcut_regularized"]["calibration"]["bins_calibrated"]
    confidences = [b["mean_confidence"] for b in arm2_bins]
    accuracies = [b["accuracy"] for b in arm2_bins]
    plt.plot([0, 1], [0, 1], "k--", label="Perfect Calibration")
    plt.plot(confidences, accuracies, "s-", color="#2b5c8f", label="Arm 2 (Platt Calibrated)")
    plt.xlabel("Mean Predicted Confidence")
    plt.ylabel("Observed Fraction of Positives")
    plt.title("Reliability Diagram (Arm 2 Quantile Bins)")
    plt.legend(loc="upper left")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig("ml/reports/plots/calibration_curves.png", dpi=150)
    plt.close()

    print("All plots generated successfully under ml/reports/plots/.")
    print("=" * 70)
    print("EXPERIMENTS COMPLETE.")
    print("=" * 70)


if __name__ == "__main__":
    main()
