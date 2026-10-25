# ONCOLINK Raw Dataset Registry

This directory contains the original, raw oral cavity photography datasets used for training and evaluating the ONCOLINK AI triage models in accordance with Section 6 of `docs/SPEC.md`.

## Registered Datasets

| Dataset Folder | Source | Images | Classes | License | Hardware / Site |
|---|---|---|---|---|---|
| `mendeley_karnataka/` | Mendeley Data (DOI: 10.17632/mhjyrn35p4.2) | 323 original (165 benign, 158 malignant) + 2,270 augmented | Benign vs Malignant | CC BY 4.0 | Mobile phones & intraoral cameras (Karnataka, India) |
| `kaggle_oral_cancer/` | Kaggle (`shivam17299/oral-cancer-lips-and-tongue-images`) | 131 clinical photos (87 cancer, 44 non-cancer) | Cancer vs Non-Cancer | Open Access / Kaggle | Mobile phones & clinical digital cameras (Lips & Tongue) |

## Data Rules & Clinical Integrity

1. **Provenance:** Each dataset subfolder maintains a dedicated `SOURCE.txt` tracking its creators, DOI/URL, licensing, clinical diagnostic basis, and image breakdown.
2. **Clinical Photography Only:** As mandated by SPEC Section 6, only macroscopic clinical photography of the oral cavity is included; histopathology slides are excluded.
3. **Internal vs Outside-Image Evaluation:** `mendeley_karnataka` forms the primary split cohort, while `kaggle_oral_cancer` provides the distinct outside-image validation benchmark to test real-world generalization across different clinics and sensors.
4. **No Synthetic / Fabricated Data:** Raw files are verified against published repositories.
