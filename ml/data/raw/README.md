# ONCOLINK Raw Dataset Registry

This directory contains the original, raw oral cavity photography datasets evaluated for training and benchmarking ONCOLINK AI triage models in accordance with Section 6 of `docs/SPEC.md`.

## Registered Datasets

| Dataset Folder | Source | Images Checked | Verified Classes | License | Provenance Status |
|---|---|---|---|---|---|
| `mendeley_karnataka/` | Mendeley Data (DOI: 10.17632/mhjyrn35p4.2) | 323 original (165 benign, 158 malignant) [2,270 augmented excluded] | `benign_lesions` vs `malignant_lesions` | UNVERIFIED | Unverified authors, clinical sites, and ground-truth method |
| `kaggle_oral_cancer/` | Kaggle (`shivam17299/oral-cancer-lips-and-tongue-images`) | 131 clinical photos (87 cancer, 44 non-cancer) | `cancer` vs `non-cancer` | UNVERIFIED | Unverified contributors, license, and ground truth; 26 exact duplicate clusters identified |

## Data Rules & Clinical Integrity

1. **Provenance Honesty:** Authors, affiliations, licenses, and histopathology confirmation claims are marked `UNVERIFIED` until verified from source web pages.
2. **Clinical Photography Only:** Only macroscopic clinical photographs of oral mucosal lesions are included; histopathology slides are excluded.
3. **No Patient Identifiers:** Zero patient or case identifiers exist in either dataset. Patient-level splitting is impossible; near-duplicate groups must remain within the same split, and reported metrics may remain optimistic.
4. **Offline Augmented Data Excluded:** The Mendeley `augmented_data/` directory (2,270 images) is excluded from hashing and model training.
5. **Quality Verification:** All 454 original images across both datasets successfully decode with zero corrupt files.
