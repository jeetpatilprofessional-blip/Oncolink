"""Generate contact sheets and visual inspection records for Mendeley originals.

Saves contact sheets to ml/reports/private/ (gitignored).
"""

import os
import glob
import random
from PIL import Image, ImageDraw, ImageFont
import pandas as pd
import numpy as np

SEED = 42

def create_grid(image_paths, titles, out_path, grid_size=(4, 6), thumb_size=(200, 200)):
    """Assemble images into a grid contact sheet with labels."""
    cols, rows = grid_size
    padding = 10
    text_height = 25
    cell_w = thumb_size[0] + padding * 2
    cell_h = thumb_size[1] + text_height + padding * 2

    canvas_w = cols * cell_w
    canvas_h = rows * cell_h

    canvas = Image.new("RGB", (canvas_w, canvas_h), color=(240, 240, 240))
    draw = ImageDraw.Draw(canvas)

    for idx, (path, title) in enumerate(zip(image_paths, titles)):
        if idx >= cols * rows:
            break
        r = idx // cols
        c = idx % cols

        x0 = c * cell_w + padding
        y0 = r * cell_h + padding

        try:
            with Image.open(path) as img:
                img_rgb = img.convert("RGB")
                img_rgb.thumbnail(thumb_size)
                # Center thumbnail in cell
                offset_x = x0 + (thumb_size[0] - img_rgb.width) // 2
                offset_y = y0 + (thumb_size[1] - img_rgb.height) // 2
                canvas.paste(img_rgb, (offset_x, offset_y))
        except Exception as e:
            draw.rectangle([x0, y0, x0 + thumb_size[0], y0 + thumb_size[1]], fill=(200, 100, 100))

        # Draw label
        draw.text((x0, y0 + thumb_size[1] + 2), title, fill=(0, 0, 0))

    canvas.save(out_path, format="PNG")
    print(f"Saved contact sheet to {out_path}")


def main():
    os.makedirs("ml/reports/private", exist_ok=True)
    manifest = pd.read_csv("ml/data/manifest.csv")
    mendeley = manifest[manifest["dataset"] == "mendeley_karnataka"].copy()

    benign = mendeley[mendeley["mapped_label"] == "benign_appearing"].copy()
    malignant = mendeley[mendeley["mapped_label"] == "suspicious_for_malignancy"].copy()

    # 1. 24 random per class
    benign_24 = benign.sample(n=24, random_state=SEED)
    malignant_24 = malignant.sample(n=24, random_state=SEED)

    create_grid(
        benign_24["relative_path"].tolist(),
        [f"{os.path.basename(p)} ({w}x{h})" for p, w, h in zip(benign_24["relative_path"], benign_24["width"], benign_24["height"])],
        "ml/reports/private/contact_sheet_random_benign.png",
        grid_size=(6, 4)
    )

    create_grid(
        malignant_24["relative_path"].tolist(),
        [f"{os.path.basename(p)} ({w}x{h})" for p, w, h in zip(malignant_24["relative_path"], malignant_24["width"], malignant_24["height"])],
        "ml/reports/private/contact_sheet_random_malignant.png",
        grid_size=(6, 4)
    )

    # 2. 12 smallest and 12 largest per class (by pixel area width*height)
    benign["area"] = benign["width"] * benign["height"]
    malignant["area"] = malignant["width"] * malignant["height"]

    benign_small = benign.sort_values("area").head(12)
    benign_large = benign.sort_values("area", ascending=False).head(12)
    benign_extrema = pd.concat([benign_small, benign_large])

    malignant_small = malignant.sort_values("area").head(12)
    malignant_large = malignant.sort_values("area", ascending=False).head(12)
    malignant_extrema = pd.concat([malignant_small, malignant_large])

    create_grid(
        benign_extrema["relative_path"].tolist(),
        [f"{os.path.basename(p)} ({w}x{h}, {sz//1024}k)" for p, w, h, sz in zip(benign_extrema["relative_path"], benign_extrema["width"], benign_extrema["height"], benign_extrema["file_size"])],
        "ml/reports/private/contact_sheet_extrema_benign.png",
        grid_size=(6, 4)
    )

    create_grid(
        malignant_extrema["relative_path"].tolist(),
        [f"{os.path.basename(p)} ({w}x{h}, {sz//1024}k)" for p, w, h, sz in zip(malignant_extrema["relative_path"], malignant_extrema["width"], malignant_extrema["height"], malignant_extrema["file_size"])],
        "ml/reports/private/contact_sheet_extrema_malignant.png",
        grid_size=(6, 4)
    )

    print("Contact sheet generation complete.")


if __name__ == "__main__":
    main()
