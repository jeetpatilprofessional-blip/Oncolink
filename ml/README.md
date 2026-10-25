# ONCOLINK Machine Learning Module

This directory contains the machine learning data preparation pipeline, manifest generation, group-aware cross-validation splits, leakage verification gates, and baseline evaluation models as specified in Section 6 of `docs/SPEC.md` and Decisions 3, 17, and 19 of `docs/DECISIONS.md`.

In accordance with project rules, model training and retraining are manual and offline only. The runtime application loads locked, validated model weights without dynamic online retraining.

---

## 1. Environment & Infrastructure

The ML environment runs entirely on CPU inside a dedicated container managed by Docker Compose under the `ml` profile. Data files remain on the host disk and are bind-mounted at `/app/ml`.

* **Base Image:** `python:3.11.17-slim`
* **Profile:** `ml` (not started by default; run via `docker compose --profile ml run --rm ml <command>`)
* **Hardware:** 100% CPU execution (CPU-specific PyTorch wheels)
* **Pinned Dependencies (`ml/requirements.txt`):**
  * `torch==2.5.1+cpu`
  * `torchvision==0.20.1+cpu`
  * `numpy==2.1.3`
  * `scikit-learn==1.5.2`
  * `pandas==2.2.3`
  * `Pillow==11.0.0`
  * `imagehash==4.3.1`
  * `matplotlib==3.9.2`
  * `pytest==8.3.3`
* **Pretrained Weights Record:**
  * **Model Architecture:** EfficientNet-B0 (`models.EfficientNet_B0_Weights.DEFAULT`)
  * **Source URL:** `https://download.pytorch.org/models/efficientnet_b0_rwightman-7f5810bc.pth`
  * **SHA-256 Checksum:** `7f5810bc96def8f7552d5b7e68d53c4786f81167d28291b21c0d90e1fca14934`
  * **Cache Directory:** `ml/.cache/torch/hub/checkpoints/` (gitignored)

---

## 2. Dataset Provenance, Counts, & Roles

| Dataset | Raw Count | Exclusions | Retained Count | Class Mapping | Role in Pipeline |
|---|---|---|---|---|---|
| **Mendeley Karnataka** | 323 original<br>2,270 augmented | 2,270 augmented (strictly excluded) | **323 originals** | `benign_lesions` -> `benign_appearing` (165)<br>`malignant_lesions` -> `suspicious_for_malignancy` (158) | `train_pool` (held-out internal test + 5-fold CV) |
| **Kaggle Oral Cancer** | 131 raw | 2 conflicting labels<br>26 exact duplicates | **103 retained** | `non-cancer` -> `benign_appearing` (38)<br>`cancer` -> `suspicious_for_malignancy` (65) | `external_test` (strictly quarantined; never used in training/tuning) |
| **Total Active Manifest** | 454 raw | 2,298 excluded | **426 active** | `benign_appearing`: 203<br>`suspicious_for_malignancy`: 223 | Manifest tracked via `ml/data/manifest.sha256` |

### Kaggle Conflict & Duplicate Resolution
Within Kaggle, duplicate analysis revealed:
1. **Conflicting Label Group:** `1366.fig.1.png` appeared under both `cancer/` (`dataset_1366.fig.1.png`) and `non-cancer/` (`1366.fig.1.png`). Both files were permanently removed from the pipeline.
2. **Exact Duplicate Clusters:** 25 clusters of identical images (predominantly prefixed with `dataset_`) carried consistent labels. Each cluster was collapsed to one canonical image, removing 26 redundant copies.
3. Every excluded image, reason code, and detail is recorded in [`ml/reports/exclusions.json`](reports/exclusions.json).

---

## 3. Dual-Pass Duplicate & Near-Duplicate Grouping

Neither raw dataset contains patient or case identifiers (Decision 17). To prevent data leakage across train, validation, and test sets, images representing the same lesion or patient must be grouped together:

1. **Pass 1: Perceptual Hashing (pHash):**
   * Threshold: Hamming distance $\le 10$.
   * Found **1 multi-item near-duplicate pair** in Mendeley malignant lesions (`125.jpg` and `91.jpg`, Hamming distance 8).
2. **Pass 2: Pretrained EfficientNet-B0 Embedding Cosine Similarity:**
   * Features: 1280-dimensional $L_2$-normalized feature vectors from frozen EfficientNet-B0.
   * Empirical Pairwise Similarity Distribution ($N = 90,525$ pairs):
     * Mean: `0.4333`, Median: `0.4449`, p90: `0.6128`, p99: `0.7182`, p99.99: `0.8683`, Max: `0.9513`.
   * **Selected Threshold:** $\tau = 0.88$ (justified as falling in the top $0.01\%$ tail, $> 4.5$ standard deviations above the mean).
   * **Extra Groups Found:** Pass 2 found **7 extra multi-item groups** (8 total combined multi-item groups) linking reframed, cropped, and zoomed photograph series in Mendeley (`102/83`, `103/84`, `107/86`, `108/87`, `127/88`, `134/89` in benign lesions, and `110/119` in malignant lesions) that whole-image DCT pHash failed to connect.
   * **Connected Components:** All connected edges form unified `duplicate_group` identifiers in `manifest.csv`.

---

## 4. Splits & Leakage Verification

Splits are generated exclusively from `train_pool` (Mendeley originals):
1. **Held-Out Internal Test Set:**
   * 64 images (19.8% of `train_pool`: 33 `benign_appearing`, 31 `suspicious_for_malignancy`).
   * Stratified by class while keeping whole duplicate groups intact.
2. **5-Fold Cross-Validation Pool (Remaining 80%):**
   * 259 images partitioned via `StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42)`.
   * Fold sizes: 51, 50, 53, 53, 52 validation images.
   * Duplicate groups are guaranteed to never be split across train and validation.
3. **Authoritative Leakage Check (`ml.scripts.make_splits.check_leakage`):**
   * Verifies train, val, and internal test are pairwise disjoint.
   * Verifies duplicate groups are intact and never split.
   * Verifies zero `external_test` images appear in any split or share groups with `train_pool`.
   * Splits saved to `ml/data/splits.json` and tracked by `ml/data/splits.sha256`.

---

## 5. Cross-Validated Baselines & Critical Bias Finding

Evaluated across the 5 cross-validation folds (259 images) with 95% group bootstrap confidence intervals (1,000 iterations resampling whole duplicate groups):

| Baseline Model | Input Features | Cross-Validated AUC (95% CI) | Sensitivity (95% CI) | Specificity (95% CI) |
|---|---|---|---|---|
| **Majority Class** | Class prevalence | 0.4770 [0.4070, 0.5470] | 0.1890 [0.1194, 0.2500] | 0.7803 [0.7049, 0.8560] |
| **Metadata-Only (Logistic Regression)** | `width`, `height`, `aspect_ratio`, `file_size`, `bytes_per_pixel` | **0.7774 [0.7165, 0.8313]** | **0.6772 [0.5948, 0.7652]** | **0.7045 [0.6222, 0.7812]** |
| **Frozen EfficientNet-B0 (Logistic Regression)** | 1280-dim frozen embeddings | **0.8803 [0.8358, 0.9205]** | **0.8031 [0.7297, 0.8647]** | **0.8030 [0.7280, 0.8710]** |

> [!CAUTION]
> **CRITICAL DATASET ACQUISITION BIAS DETECTED**
> The metadata-only baseline achieves an **AUC of 0.7774 (95% CI: [0.7165, 0.8313])**, which is substantially and statistically significantly above chance ($0.50$).
>
> **Clinical Implication:** In the raw Mendeley dataset, image dimensions, aspect ratios, file sizes, and bytes-per-pixel strongly correlate with whether an image is labeled benign or malignant. This indicates that malignant and benign images were collected with different hardware, cropping protocols, or compression settings. Any uncalibrated computer vision model trained on this dataset is at high risk of learning non-clinical acquisition shortcuts rather than mucosal pathology.

---

## 6. How to Reproduce (PowerShell)

All commands are executed inside the Docker container:

```powershell
# 1. Build the ML container
docker compose --profile ml build ml

# 2. Build manifest, process Kaggle exclusions, and run dual-pass duplicate grouping
docker compose --profile ml run --rm ml python ml/scripts/build_manifest.py

# 3. Generate stratified group-aware splits and run authoritative leakage checks
docker compose --profile ml run --rm ml python ml/scripts/make_splits.py

# 4. Evaluate majority class, metadata, and frozen EfficientNet baselines
docker compose --profile ml run --rm ml python ml/scripts/baselines.py

# 5. Run automated unit test suite
docker compose --profile ml run --rm ml pytest ml/tests -v
```
