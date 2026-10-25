import os
import json
import hashlib
from pathlib import Path
from PIL import Image
import imagehash

WORKSPACE_ROOT = Path("C:/OncoLink")
DATA_RAW = WORKSPACE_ROOT / "ml" / "data" / "raw"
REPORTS_DIR = WORKSPACE_ROOT / "ml" / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

KAGGLE_DIR = DATA_RAW / "kaggle_oral_cancer"
MENDELEY_DIR = DATA_RAW / "mendeley_karnataka"

def verify_and_hash():
    print("=" * 70)
    print("ONCOLINK DATASET VERIFICATION & DUPLICATE DETECTION")
    print("=" * 70)

    # 1. Collect files
    # Exclude mendeley augmented_data
    kaggle_files = []
    mendeley_files = []

    for p in KAGGLE_DIR.rglob("*"):
        if p.is_file() and p.name != "SOURCE.txt":
            kaggle_files.append(p)

    for p in MENDELEY_DIR.rglob("*"):
        if p.is_file() and p.name != "SOURCE.txt":
            # Exclude augmented_data folder
            if "augmented_data" in p.parts:
                continue
            mendeley_files.append(p)

    print(f"Discovered Kaggle files (excluding SOURCE.txt): {len(kaggle_files)}")
    print(f"Discovered Mendeley files (excluding augmented_data & SOURCE.txt): {len(mendeley_files)}")

    # Check image decoding and compute hashes
    corrupt_files = []
    dataset_records = {} # path_str -> {dataset, label, phash, sha256}

    all_targets = [("kaggle", f) for f in kaggle_files] + [("mendeley", f) for f in mendeley_files]

    for ds_name, file_path in all_targets:
        rel_path = file_path.relative_to(WORKSPACE_ROOT).as_posix()
        try:
            with Image.open(file_path) as img:
                # Fully decode image pixels to catch truncation/corruption
                img.load()
                # Compute perceptual hash
                ph = imagehash.phash(img)
                ph_str = str(ph)

            with open(file_path, "rb") as bf:
                sha = hashlib.sha256(bf.read()).hexdigest()

            label = file_path.parent.name
            dataset_records[rel_path] = {
                "dataset": ds_name,
                "label": label,
                "phash": ph_str,
                "phash_obj": ph,
                "sha256": sha,
            }
        except Exception as e:
            corrupt_files.append({"path": rel_path, "error": str(e)})

    print(f"\nVerification Results:")
    print(f"Total images checked: {len(all_targets)}")
    print(f"Successfully decoded images: {len(dataset_records)}")
    print(f"Corrupt or unreadable images: {len(corrupt_files)}")
    if corrupt_files:
        for c in corrupt_files:
            print(f"  [CORRUPT] {c['path']}: {c['error']}")
    else:
        print("  [OK] All images successfully decoded with zero corrupt files.")

    # 2. Check counts by class
    kaggle_counts = {}
    for r in dataset_records.values():
        if r["dataset"] == "kaggle":
            kaggle_counts[r["label"]] = kaggle_counts.get(r["label"], 0) + 1
    mendeley_counts = {}
    for r in dataset_records.values():
        if r["dataset"] == "mendeley":
            mendeley_counts[r["label"]] = mendeley_counts.get(r["label"], 0) + 1

    print("\nClass Counts:")
    print("  Kaggle Oral Cancer:", kaggle_counts, f"Total: {sum(kaggle_counts.values())}")
    print("  Mendeley Karnataka (Original only):", mendeley_counts, f"Total: {sum(mendeley_counts.values())}")

    # Also count Mendeley augmented folder just for reference
    mendeley_augmented_files = [p for p in MENDELEY_DIR.rglob("*") if p.is_file() and "augmented_data" in p.parts]
    aug_counts = {}
    for p in mendeley_augmented_files:
        lbl = p.parent.name
        aug_counts[lbl] = aug_counts.get(lbl, 0) + 1
    print("  Mendeley Karnataka (Augmented, excluded from hash analysis):", aug_counts, f"Total: {sum(aug_counts.values())}")

    # 3. Check for Patient / Case identifiers in filenames or directories
    print("\nPatient / Case Identifier Search:")
    kaggle_filenames = [f.name for f in kaggle_files]
    mendeley_filenames = [f.name for f in mendeley_files]
    print(f"  Sample Kaggle filenames (first 5): {kaggle_filenames[:5]}")
    print(f"  Sample Mendeley filenames (first 5): {mendeley_filenames[:5]}")

    # 4. Find exact and near duplicates
    # Exact duplicates: pHash distance == 0 (or identical sha256)
    # Near duplicates: pHash distance <= 4 or <= 6
    records_list = list(dataset_records.items())
    n = len(records_list)

    exact_duplicates = []
    near_duplicates = []

    # Map pHash -> list of paths
    phash_groups = {}
    for path, data in dataset_records.items():
        h = data["phash"]
        phash_groups.setdefault(h, []).append(path)

    for h, paths in phash_groups.items():
        if len(paths) > 1:
            exact_duplicates.append({
                "hash": h,
                "files": paths
            })

    # Pairwise comparison for near duplicates (distance between 1 and 6)
    # Also record whether intra-dataset or inter-dataset
    intra_kaggle_exact = 0
    intra_kaggle_near = 0
    intra_mendeley_exact = 0
    intra_mendeley_near = 0
    cross_dataset_exact = 0
    cross_dataset_near = 0

    for i in range(n):
        path_a, data_a = records_list[i]
        hash_a = data_a["phash_obj"]
        ds_a = data_a["dataset"]
        for j in range(i + 1, n):
            path_b, data_b = records_list[j]
            hash_b = data_b["phash_obj"]
            ds_b = data_b["dataset"]

            dist = hash_a - hash_b
            if dist == 0:
                if ds_a == "kaggle" and ds_b == "kaggle":
                    intra_kaggle_exact += 1
                elif ds_a == "mendeley" and ds_b == "mendeley":
                    intra_mendeley_exact += 1
                else:
                    cross_dataset_exact += 1
            elif 1 <= dist <= 10:
                if ds_a == "kaggle" and ds_b == "kaggle":
                    intra_kaggle_near += 1
                elif ds_a == "mendeley" and ds_b == "mendeley":
                    intra_mendeley_near += 1
                else:
                    cross_dataset_near += 1

                near_duplicates.append({
                    "file_1": path_a,
                    "hash_1": data_a["phash"],
                    "file_2": path_b,
                    "hash_2": data_b["phash"],
                })

    print(f"\nDuplicate Analysis Summary (pHash):")
    print(f"  Exact duplicate clusters (distance == 0): {len(exact_duplicates)}")
    print(f"    - Intra-Kaggle exact duplicate pairs: {intra_kaggle_exact}")
    print(f"    - Intra-Mendeley exact duplicate pairs: {intra_mendeley_exact}")
    print(f"    - Cross-dataset exact duplicate pairs: {cross_dataset_exact}")
    print(f"  Near duplicate pairs (1 <= distance <= 10): {len(near_duplicates)}")
    print(f"    - Intra-Kaggle near duplicate pairs: {intra_kaggle_near}")
    print(f"    - Intra-Mendeley near duplicate pairs: {intra_mendeley_near}")
    print(f"    - Cross-dataset near duplicate pairs: {cross_dataset_near}")

    # Build report for duplicates.json containing file paths and hashes only
    # Per prompt: "Save ml/reports/duplicates.json containing file paths and hashes only."
    report_data = {
        "exact_duplicates": exact_duplicates,
        "near_duplicates": near_duplicates,
    }

    out_file = REPORTS_DIR / "duplicates.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)

    print(f"\nSaved duplicates report to {out_file} ({out_file.stat().st_size} bytes)")

if __name__ == "__main__":
    verify_and_hash()
