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
| **Majority Class (Corrected)** | Predicts constant training majority | **0.5000 [0.5000, 0.5000]** | **0.0000 [0.0000, 0.0000]** | **1.0000 [1.0000, 1.0000]** |
| **Metadata-Only (Logistic Regression)** | `width`, `height`, `aspect_ratio`, `file_size`, `bytes_per_pixel` | **0.7774 [0.7165, 0.8313]** | **0.6772 [0.5948, 0.7652]** | **0.7045 [0.6222, 0.7812]** |
| **Frozen EfficientNet-B0 (Logistic Regression)** | 1280-dim frozen embeddings | **0.8803 [0.8358, 0.9205]** | **0.8031 [0.7297, 0.8647]** | **0.8030 [0.7280, 0.8710]** |

> [!CAUTION]
> **CRITICAL DATASET ACQUISITION BIAS DETECTED**
> The metadata-only baseline achieves an **AUC of 0.7774 (95% CI: [0.7165, 0.8313])**, which is substantially and statistically significantly above chance ($0.50$).
>
> **Clinical Implication:** In the raw Mendeley dataset, image dimensions, aspect ratios, file sizes, and bytes-per-pixel strongly correlate with whether an image is labeled benign or malignant. This indicates that malignant and benign images were collected with different hardware, cropping protocols, or compression settings. Any uncalibrated computer vision model trained on this dataset is at high risk of learning non-clinical acquisition shortcuts rather than mucosal pathology.

---

## 6. Dataset Shortcut Investigation & Non-Lesion Signal Analysis

A dedicated investigation ([`ml/scripts/analyze_shortcuts.py`](scripts/analyze_shortcuts.py), tracked in [`ml/reports/shortcut_analysis.json`](reports/shortcut_analysis.json) and [`ml/reports/capture_source.json`](reports/capture_source.json)) dissected the root causes of the dataset bias:

### 6.1 Single-Feature Metadata Drivers
Evaluating each metadata property on its own across the 5 cross-validation folds:
* `bytes_per_pixel`: **AUC = 0.7707** [0.7100, 0.8248] (primary driver)
* `height`: **AUC = 0.7634** [0.7008, 0.8254]
* `width`: **AUC = 0.7576** [0.6935, 0.8173]
* `file_size`: **AUC = 0.6799** [0.6116, 0.7458]
* `aspect_ratio`: **AUC = 0.4655** [0.3962, 0.5359]
* `exif_present`: **AUC = 0.5285** [0.4618, 0.5977]
* `format_is_jpeg`: **AUC = 0.5000** [0.5000, 0.5000] (100% JPEG)

**Root Cause:** EXIF inspection reveals benign images were collected primarily using modern smartphones (Samsung Galaxy M31 64MP sensor, median 620x646px up to 9248px), whereas malignant images are heavily downsampled crops acquired with older budget devices (Samsung Galaxy Core Prime 5MP sensor, median 426x415px).

### 6.2 Standardisation Before & After
Standardisation (resizing short side to 256, centre-cropping 224x224, re-encoding to JPEG at quality 90 in memory, stripping all EXIF):
* **Metadata Baseline:** Drops from **AUC 0.7774 [0.7165, 0.8313]** before standardisation to **AUC 0.5599 [0.4928, 0.6308]** after standardisation (confidence interval crosses chance 0.50).
* **Frozen EfficientNet-B0 Baseline:** **AUC 0.8803 [0.8358, 0.9205]** before standardisation $\rightarrow$ **AUC 0.8717 [0.8241, 0.9092]** after standardisation.

### 6.3 Shortcut Probes on Standardised Images
Probing non-lesion visual signals across the 5 folds:
1. **Probe (a) - 8x8 Colour Thumbnail (192 features):** AUC = **0.5919** [0.5172, 0.6592].
2. **Probe (b) - Border-Only / Centre 60% Masked Out:** AUC = **0.8338** [0.7780, 0.8827].
3. **Probe (c) - Centre 60% Crop Only:** AUC = **0.8428** [0.7911, 0.8873].
4. **Probe (d) - HSV Colour Statistics (6 features):** AUC = **0.6730** [0.6053, 0.7312].

> [!WARNING]
> **SEVERE NON-LESION SHORTCUT FINDING**
> When the centre 60% of the image (the lesion itself) is completely blacked out, frozen EfficientNet-B0 embeddings still achieve **AUC = 0.8338**, almost identical to the centre lesion crop (**AUC = 0.8428**). Furthermore, 6 global HSV colour statistics achieve **AUC = 0.6730**.
>
> **What This Implies for Later Models:** Any deep neural network trained on this dataset can discriminate benign from malignant with > 0.83 AUC using strictly peripheral background lighting falloff, mucosal tint, and capture-source artifacts without ever learning lesion morphology. All subsequent modeling must apply aggressive spatial and color augmentations, background masking, and strict evaluation against out-of-distribution external datasets.
>
> **Limitation:** All findings remain limited by the total absence of patient identifiers in the source dataset (Decision 17). Even though near-duplicate groups were preserved, cross-validation metrics may still be optimistic due to unlabelled patient overlap across remaining images.

---

## 7. Controlled Transfer-Learning Experiments (Prompt 5c / Decision 21)

Authorized under **Decision 21**, three controlled transfer-learning arms were trained and evaluated across the 259-image development pool using 5-fold cross-validation, with the 64-image internal test set and 103-image Kaggle external set strictly quarantined:

* **Arm 1 (Standard Transfer Learning):** Pretrained EfficientNet-B0 with standard data augmentation (horizontal flip).
* **Arm 2 (Shortcut-Regularized):** Pretrained EfficientNet-B0 with aggressive Colour Jitter ($\pm 0.3$), Random Resized Crop ($0.7 \text{ to } 1.0$), and Rotation ($\pm 15^\circ$).
* **Arm 3 (Background-Suppression):** Pretrained EfficientNet-B0 trained with peripheral border masking ($p=0.7$, 15% outer border masked) to disrupt background reliance.

### 7.1 Cross-Validated Performance, Calibration, & Shortcut Probes (N = 259)

| Metric | Baseline (Frozen EffNet) | Arm 1 (Standard Transfer) | Arm 2 (Shortcut-Regularized) | Arm 3 (Background-Suppression) |
|---|---|---|---|---|
| **Full Image AUC (95% CI)** | 0.8717 [0.8241, 0.9092] | **0.8775 [0.8307, 0.9131]** | **0.8713 [0.8229, 0.9119]** | **0.8988 [0.8588, 0.9323]** |
| **Precision-Recall AUC** | 0.8654 | **0.8726** | **0.8651** | **0.8942** |
| **Sensitivity at 0.5** | 0.7953 | 0.8425 | 0.8425 | 0.8425 |
| **Specificity at 0.5** | 0.7879 | 0.7652 | 0.8030 | 0.8106 |
| **Balanced Accuracy at 0.5** | 0.7916 | 0.8038 | 0.8228 | 0.8266 |
| **Brier Score (Raw $\rightarrow$ Calibrated)** | N/A | 0.1430 $\rightarrow$ 0.1430 | 0.1444 $\rightarrow$ 0.1434 | 0.1332 $\rightarrow$ 0.1296 |
| **ECE (Raw $\rightarrow$ Calibrated)** | N/A | 0.0389 $\rightarrow$ **0.0369** | 0.0369 $\rightarrow$ **0.0303** | 0.0500 $\rightarrow$ **0.0414** |
| **Triage Threshold ($\text{Sens} \ge 85\%$)** | N/A | $\tau^* = 0.4892$<br>(Sens 0.8504, Spec 0.7576) | $\tau^* = 0.5298$<br>(Sens 0.8504, Spec 0.7879) | $\tau^* = 0.4605$<br>(Sens 0.8504, Spec 0.7727) |
| **Border-Only Probe AUC (Centre Masked)** | **0.8338 [0.7780, 0.8827]** | **0.7696 [0.7129, 0.8277]** | **0.8219 [0.7677, 0.8675]** | **0.8453 [0.7951, 0.8884]** |
| **Centre-Crop Probe AUC (Lesion Only)** | **0.8428 [0.7911, 0.8873]** | **0.7686 [0.7078, 0.8268]** | **0.8005 [0.7427, 0.8524]** | **0.8487 [0.8008, 0.8906]** |

> [!CAUTION]
> **CRITICAL SHORTCUT SURVIVAL FINDING**
> 1. In all three arms, the model achieves **AUC between 0.7696 and 0.8453 on pure background borders with the lesion completely blacked out**.
> 2. Augmentations (Arm 2) and border masking (Arm 3) slightly improved full-image AUC (0.8713 to 0.8988) and calibration (ECE 0.0303), but **failed to eliminate the background shortcut**.
> 3. The dataset's pervasive acquisition differences (ambient illumination, device sensor characteristics, camera flash geometry, and oral tissue retraction depth) remain deeply entangled with diagnostic labels.

---

## 8. How to Reproduce (PowerShell)

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

# 5. Run dataset shortcut analysis and single-feature probes
docker compose --profile ml run --rm ml python ml/scripts/analyze_shortcuts.py

# 6. Run controlled transfer-learning experiments (Decision 21)
docker compose --profile ml run --rm ml python ml/scripts/train_experiments.py

# 7. Run complete automated unit test suite (15 tests)
docker compose --profile ml run --rm ml pytest ml/tests -v
```

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
