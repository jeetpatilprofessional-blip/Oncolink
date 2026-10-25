# ONCOLINK Machine Learning Module

This directory is reserved for the offline model training pipeline, model weights, evaluation notebooks, and calibration artifacts as specified in Section 6 of `docs/SPEC.md`.

## Contents & Scope

- **Baseline Model:** EfficientNet-B0 transfer learning for multi-class oral lesion triage.
- **Explainability:** Real Grad-CAM attention maps extracted from convolutional layers.
- **Calibration:** Temperature scaling for calibrated probability estimates.
- **Evaluation:** Offline evaluation notebook generating ROC/AUC, confusion matrices, subgroup analysis (lighting, camera), and Cohen's kappa clinician agreement.
- **Model Locking:** Version freezing with SHA-256 hashes recorded with every inference run.

*Note: In accordance with project rules, model training and retraining are manual and offline only. The runtime backend loads locked, validated model weights without dynamic online retraining.*
