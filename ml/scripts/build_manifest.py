"""Build dataset manifest with duplicate and near-duplicate grouping.

Outputs:
  - ml/data/manifest.csv (gitignored)
  - ml/data/manifest.sha256 (tracked)
  - ml/reports/exclusions.json
"""

import csv
import glob
import hashlib
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import imagehash
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from torchvision import models

# Seed for reproducibility
SEED = 42

# Pretrained EfficientNet-B0 weights metadata
WEIGHTS_URL = "https://download.pytorch.org/models/efficientnet_b0_rwightman-7f5810bc.pth"
WEIGHTS_EXPECTED_SHA256 = "7f5810bc96def8f7552d5b7e68d53c4786f81167d28291b21c0d90e1fca14934"

# Similarity thresholds
PHASH_HAMMING_THRESHOLD = 10
# Embedding cosine similarity threshold justified by distribution:
# Mean: 0.4333, p99.99: 0.8683. Threshold 0.88 is in the top 0.01% tail,
# capturing reframed/cropped lesion pairs while avoiding false positives.
EMBEDDING_COSINE_THRESHOLD = 0.88


def compute_file_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        if self.parent[i] == i:
            return i
        self.parent[i] = self.find(self.parent[i])
        return self.parent[i]

    def union(self, i: int, j: int):
        root_i = self.find(i)
        root_j = self.find(j)
        if root_i != root_j:
            self.parent[root_i] = root_j


def build_manifest():
    print("=" * 70)
    print("ONCOLINK ML MANIFEST GENERATION")
    print("=" * 70)

    # 1. Discover raw images
    # Mendeley: original_data only; augmented_data is strictly excluded
    mendeley_raw = sorted(
        glob.glob(
            "ml/data/raw/mendeley_karnataka/Oral Images Dataset/original_data/**/*.*",
            recursive=True,
        )
    )
    mendeley_raw = [
        f.replace("\\", "/")
        for f in mendeley_raw
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    ]
    print(f"Discovered Mendeley original images: {len(mendeley_raw)}")

    # Kaggle: raw images
    kaggle_raw = sorted(
        glob.glob(
            "ml/data/raw/kaggle_oral_cancer/OralCancer/**/*.*",
            recursive=True,
        )
    )
    kaggle_raw = [
        f.replace("\\", "/")
        for f in kaggle_raw
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    ]
    print(f"Discovered Kaggle raw images: {len(kaggle_raw)}")

    # 2. Process Kaggle exact duplicates and exclusions
    # Compute pHash for all Kaggle images to detect exact duplicate groups (pHash Hamming dist = 0)
    kaggle_phash_map = defaultdict(list)
    for path in kaggle_raw:
        with Image.open(path) as img:
            ph = str(imagehash.phash(img))
        kaggle_phash_map[ph].append(path)

    exclusions = []
    retained_kaggle = []
    conflicting_count = 0
    collapsed_count = 0

    for ph, flist in sorted(kaggle_phash_map.items()):
        if len(flist) == 1:
            retained_kaggle.append(flist[0])
            continue

        # Check for conflicting labels
        labels = set()
        for f in flist:
            if "/cancer/" in f:
                labels.add("cancer")
            elif "/non-cancer/" in f:
                labels.add("non-cancer")

        if len(labels) > 1:
            # Entire duplicate group carries conflicting labels: remove all copies
            conflicting_count += len(flist)
            for f in sorted(flist):
                exclusions.append({
                    "path": f,
                    "reason": "conflicting_label_in_duplicate_group",
                    "details": (
                        f"pHash {ph} identical match contains conflicting labels "
                        f"{sorted(labels)} across copies. Entire group excluded."
                    ),
                })
        else:
            # Consistent labels: collapse duplicate group to single canonical image
            # Canonical choice: shortest basename, then alphabetical
            flist_sorted = sorted(flist, key=lambda x: (len(os.path.basename(x)), x))
            canonical = flist_sorted[0]
            retained_kaggle.append(canonical)
            collapsed_count += len(flist_sorted) - 1
            for f in flist_sorted[1:]:
                exclusions.append({
                    "path": f,
                    "reason": "exact_duplicate_in_kaggle",
                    "details": (
                        f"Exact pHash duplicate of canonical image {canonical}; "
                        "collapsed to single representative."
                    ),
                })

    retained_kaggle = sorted(retained_kaggle)
    print(f"Kaggle exclusions: {len(exclusions)} total")
    print(f"  - Conflicting label group removals: {conflicting_count}")
    print(f"  - Redundant duplicate copies collapsed: {collapsed_count}")
    print(f"Retained Kaggle images (role=external_test): {len(retained_kaggle)}")

    # Save exclusions report
    os.makedirs("ml/reports", exist_ok=True)
    with open("ml/reports/exclusions.json", "w") as f:
        json.dump(
            {
                "summary": {
                    "raw_kaggle_total": len(kaggle_raw),
                    "conflicting_label_removals": conflicting_count,
                    "exact_duplicate_collapsed": collapsed_count,
                    "total_excluded": len(exclusions),
                    "retained_external_test": len(retained_kaggle),
                },
                "exclusions": exclusions,
            },
            f,
            indent=2,
        )
    print("Saved ml/reports/exclusions.json")

    # 3. Assemble active image list
    active_images = []
    # Mendeley images (role=train_pool)
    for p in mendeley_raw:
        if "/benign_lesions/" in p:
            orig_lbl = "benign_lesions"
            map_lbl = "benign_appearing"
        elif "/malignant_lesions/" in p:
            orig_lbl = "malignant_lesions"
            map_lbl = "suspicious_for_malignancy"
        else:
            raise ValueError(f"Unknown Mendeley label for path: {p}")

        active_images.append({
            "dataset": "mendeley_karnataka",
            "path": p,
            "original_label": orig_lbl,
            "mapped_label": map_lbl,
            "role": "train_pool",
        })

    # Kaggle retained images (role=external_test)
    for p in retained_kaggle:
        if "/cancer/" in p:
            orig_lbl = "cancer"
            map_lbl = "suspicious_for_malignancy"
        elif "/non-cancer/" in p:
            orig_lbl = "non-cancer"
            map_lbl = "benign_appearing"
        else:
            raise ValueError(f"Unknown Kaggle label for path: {p}")

        active_images.append({
            "dataset": "kaggle_oral_cancer",
            "path": p,
            "original_label": orig_lbl,
            "mapped_label": map_lbl,
            "role": "external_test",
        })

    n_images = len(active_images)
    print(f"Total active manifest images: {n_images}")

    # 4. Extract image metadata, sha256, and pHash
    print("Computing hashes and extracting image metadata...")
    phashes = []
    for item in active_images:
        path = item["path"]
        item["file_size"] = os.path.getsize(path)
        item["sha256"] = compute_file_sha256(path)
        with Image.open(path) as img:
            item["width"], item["height"] = img.size
            ph = imagehash.phash(img)
            item["phash"] = str(ph)
            phashes.append(ph)

    # 5. Near-duplicate detection: Pass 1 (pHash Hamming distance <= 10)
    print("\n--- Pass 1: pHash near-duplicate matching (Hamming <= 10) ---")
    uf_pass1 = UnionFind(n_images)
    pass1_edges = []
    for i in range(n_images):
        for j in range(i + 1, n_images):
            if phashes[i] - phashes[j] <= PHASH_HAMMING_THRESHOLD:
                pass1_edges.append((i, j))
                uf_pass1.union(i, j)

    groups_pass1_counts = defaultdict(list)
    for i in range(n_images):
        groups_pass1_counts[uf_pass1.find(i)].append(i)
    multi_groups_pass1 = [g for g in groups_pass1_counts.values() if len(g) > 1]
    print(f"Pass 1 found {len(pass1_edges)} edge(s), forming {len(multi_groups_pass1)} multi-item group(s).")
    for g in multi_groups_pass1:
        names = [os.path.basename(active_images[idx]["path"]) for idx in g]
        print(f"  Pass 1 group ({len(g)}): {names}")

    # 6. Near-duplicate detection: Pass 2 (EfficientNet-B0 embedding cosine similarity)
    print("\n--- Pass 2: Pretrained EfficientNet-B0 embedding cosine similarity ---")
    print(f"Loading pretrained weights from {WEIGHTS_URL}...")
    weights = models.EfficientNet_B0_Weights.DEFAULT
    model = models.efficientnet_b0(weights=weights)
    model.classifier = torch.nn.Identity()
    model.eval()
    preprocess = weights.transforms()

    embeddings = []
    with torch.no_grad():
        for item in active_images:
            with Image.open(item["path"]) as img:
                tensor = preprocess(img.convert("RGB")).unsqueeze(0)
                emb = F.normalize(model(tensor), p=2, dim=-1)
                embeddings.append(emb)

    embeddings_cat = torch.cat(embeddings, dim=0)
    sim_matrix = torch.mm(embeddings_cat, embeddings_cat.t()).numpy()

    pass2_edges = []
    for i in range(n_images):
        for j in range(i + 1, n_images):
            if sim_matrix[i, j] >= EMBEDDING_COSINE_THRESHOLD:
                pass2_edges.append((i, j, float(sim_matrix[i, j])))

    print(f"Pass 2 found {len(pass2_edges)} high-similarity edge(s) (>= {EMBEDDING_COSINE_THRESHOLD}).")

    # Combine Pass 1 and Pass 2 edges into unified connected components
    uf_combined = UnionFind(n_images)
    for i, j in pass1_edges:
        uf_combined.union(i, j)
    for i, j, _ in pass2_edges:
        uf_combined.union(i, j)

    groups_combined_counts = defaultdict(list)
    for i in range(n_images):
        groups_combined_counts[uf_combined.find(i)].append(i)

    multi_groups_combined = [g for g in groups_combined_counts.values() if len(g) > 1]
    extra_groups_found = len(multi_groups_combined) - len(multi_groups_pass1)

    print(f"Combined multi-item duplicate groups: {len(multi_groups_combined)}")
    print(f"Extra multi-item groups found by Pass 2: {extra_groups_found}")
    for g in multi_groups_combined:
        names = [os.path.basename(active_images[idx]["path"]) for idx in g]
        roles = {active_images[idx]["role"] for idx in g}
        labels = {active_images[idx]["mapped_label"] for idx in g}
        print(f"  Combined group ({len(g)}): {names} | roles={roles} | labels={labels}")

    # 7. Assign deterministic duplicate_group IDs to all images
    # Sort groups so group numbering is deterministic
    root_to_id = {}
    next_group_idx = 1
    # Assign multi-item groups first
    for g in sorted(multi_groups_combined, key=lambda g: sorted(active_images[idx]["path"] for idx in g)[0]):
        root = uf_combined.find(g[0])
        root_to_id[root] = f"dup_group_{next_group_idx:04d}"
        next_group_idx += 1

    # Assign singletons their own group ID
    for i in range(n_images):
        root = uf_combined.find(i)
        if root not in root_to_id:
            root_to_id[root] = f"dup_group_{next_group_idx:04d}"
            next_group_idx += 1

    # 8. Assign deterministic image IDs and write manifest.csv
    # Format: dataset prefix + index
    mendeley_idx = 1
    kaggle_idx = 1
    for i, item in enumerate(active_images):
        if item["dataset"] == "mendeley_karnataka":
            item["id"] = f"mendeley_{mendeley_idx:04d}"
            mendeley_idx += 1
        else:
            item["id"] = f"kaggle_{kaggle_idx:04d}"
            kaggle_idx += 1
        item["duplicate_group"] = root_to_id[uf_combined.find(i)]

    # Write manifest.csv
    os.makedirs("ml/data", exist_ok=True)
    manifest_path = "ml/data/manifest.csv"
    fieldnames = [
        "id",
        "dataset",
        "relative_path",
        "original_label",
        "mapped_label",
        "width",
        "height",
        "file_size",
        "sha256",
        "phash",
        "duplicate_group",
        "role",
    ]

    with open(manifest_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for item in active_images:
            writer.writerow({
                "id": item["id"],
                "dataset": item["dataset"],
                "relative_path": item["path"],
                "original_label": item["original_label"],
                "mapped_label": item["mapped_label"],
                "width": item["width"],
                "height": item["height"],
                "file_size": item["file_size"],
                "sha256": item["sha256"],
                "phash": item["phash"],
                "duplicate_group": item["duplicate_group"],
                "role": item["role"],
            })

    manifest_sha256 = compute_file_sha256(manifest_path)
    with open("ml/data/manifest.sha256", "w", encoding="utf-8") as f:
        f.write(f"{manifest_sha256}  manifest.csv\n")

    print(f"\nSuccessfully generated {manifest_path} ({n_images} rows).")
    print(f"Manifest SHA-256: {manifest_sha256}")
    print("Saved ml/data/manifest.sha256")
    return {
        "total_images": n_images,
        "mendeley_count": len(mendeley_raw),
        "kaggle_retained": len(retained_kaggle),
        "pass1_groups": len(multi_groups_pass1),
        "pass2_extra_groups": extra_groups_found,
        "combined_groups": len(multi_groups_combined),
    }


if __name__ == "__main__":
    build_manifest()
