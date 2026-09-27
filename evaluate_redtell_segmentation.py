"""Exploratory pixel-mask comparison on RedTell DSE held-out source frames.

Uses the same frame-ID modulo-5 holdout as train_cellvision.py. This evaluates
CellVision's current Watershed mask against the dataset's instance-mask TIFFs;
it is not a clinical or patient-independent validation.
"""
from __future__ import annotations

import json
import os
import re
import zipfile

import cv2
import numpy as np

from web_app import analyze

ROOT = os.path.dirname(os.path.abspath(__file__))
ARCHIVE = os.path.join(ROOT, "data", "datasets", "redtell_dse.zip")
OUT_DIR = os.path.join(ROOT, "data", "reports")
MODEL_REPORT = os.path.join(ROOT, "data", "models", "redtell_training_report.json")


def decode_tiff(zf: zipfile.ZipFile, name: str, flag=cv2.IMREAD_GRAYSCALE):
    value = cv2.imdecode(np.frombuffer(zf.read(name), np.uint8), flag)
    if value is None:
        raise ValueError(f"Cannot decode {name}")
    return value


def main():
    class_names = {"Discocyte", "Stomatocyte1", "Stomatocyte2", "Stomatocyte3",
                   "Echinocyte1", "Echinocyte2", "Echinocyte3", "Echinocyte4"}
    per_frame = []
    examples = []
    with zipfile.ZipFile(ARCHIVE) as zf:
        members = [n for n in zf.namelist() if "/coco_annotations/" in n and n.lower().endswith(".tif")]
        available = set(zf.namelist())
        held_out = set()
        for name in members:
            match = re.match(r"(\d+)_([^_]+)_\d+\.tif$", os.path.basename(name), re.I)
            if (match and match.group(2) in class_names and int(match.group(1)) % 5 == 0
                    and f"dse_data/images/{int(match.group(1))}.tif" in available
                    and f"dse_data/annotations/{int(match.group(1))}.tif" in available):
                held_out.add(int(match.group(1)))
        if not held_out:
            raise SystemExit("No held-out source frames found in RedTell archive")

        for frame_id in sorted(held_out):
            image_path = f"dse_data/images/{frame_id}.tif"
            mask_path = f"dse_data/annotations/{frame_id}.tif"
            gray = decode_tiff(zf, image_path)
            reference = decode_tiff(zf, mask_path)
            detected, _, _, predicted = analyze(cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR), classify=False)
            truth = reference > 0
            prediction = predicted > 0
            intersection = int(np.count_nonzero(truth & prediction))
            truth_count = int(np.count_nonzero(truth))
            prediction_count = int(np.count_nonzero(prediction))
            union = int(np.count_nonzero(truth | prediction))
            dice = 2 * intersection / max(1, truth_count + prediction_count)
            iou = intersection / max(1, union)
            tp = intersection
            fp = int(np.count_nonzero(prediction & ~truth))
            fn = int(np.count_nonzero(truth & ~prediction))
            gt_cells = int(len(np.unique(reference)) - 1)
            per_frame.append({"frame_id": frame_id, "cells_reference": gt_cells,
                              "cells_detected": len(detected), "count_error": len(detected)-gt_cells,
                              "dice": dice, "iou": iou,
                              "pixel_precision": tp/max(1,tp+fp), "pixel_recall": tp/max(1,tp+fn),
                              "reference_foreground_percent": 100*truth.mean(),
                              "predicted_foreground_percent": 100*prediction.mean()})
            if len(examples) < 3:
                examples.append((frame_id, gray, reference, predicted))

    os.makedirs(OUT_DIR, exist_ok=True)
    vals = lambda key: np.asarray([row[key] for row in per_frame], dtype=float)
    report = {
        "title": "CellVision Watershed vs RedTell DSE instance-mask reference",
        "source": "Red Blood Cell RedTell Dataset, Zenodo record 7801430, dse_data.zip",
        "license": "CC BY 4.0; cite dataset authors and DOI 10.5281/zenodo.7801430",
        "split": "source-frame IDs divisible by 5, matching the morphology model's held-out source-frame rule",
        "test_frames": len(per_frame),
        "image_dimensions": "572 x 572 grayscale brightfield frames",
        "metrics": {
            "dice_pixel_mean": float(vals("dice").mean()), "dice_pixel_median": float(np.median(vals("dice"))),
            "iou_pixel_mean": float(vals("iou").mean()), "iou_pixel_median": float(np.median(vals("iou"))),
            "pixel_precision_mean": float(vals("pixel_precision").mean()),
            "pixel_recall_mean": float(vals("pixel_recall").mean()),
            "cell_count_mae": float(np.abs(vals("count_error")).mean()),
            "cell_count_bias_mean_detected_minus_reference": float(vals("count_error").mean()),
            "reference_cells_total": int(sum(row["cells_reference"] for row in per_frame)),
            "detected_cells_total": int(sum(row["cells_detected"] for row in per_frame)),
        },
        "limitations": [
            "Exploratory comparison on a single public dataset; RedTell DSE images represent healthy control cells.",
            "No patient identifiers are supplied, so the frame-level holdout is not patient-independent.",
            "Pixel scores compare binary foreground masks; they do not establish clinical accuracy or anemia probability.",
            "The saved per-frame table exposes variability; frame selection and thresholds were not independently preregistered.",
            "This is not a comparison between two human annotators. The in-app reviewer agreement feature needs two actual independent raters.",
        ],
        "per_frame": per_frame,
    }
    report_path = os.path.join(OUT_DIR, "redtell_segmentation_evaluation.json")
    with open(report_path, "w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
    public_report = os.path.join(ROOT, "web", "assets", "redtell_segmentation_evaluation.json")
    with open(public_report, "w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)

    tile_w, tile_h = 572, 572
    canvas = np.full((len(examples)*(tile_h+58)+68, tile_w*3, 3), 245, np.uint8)
    cv2.putText(canvas, "REDTELL DSE REAL FRAMES · EXPLORATORY HELD-OUT COMPARISON", (12, 26),
                cv2.FONT_HERSHEY_SIMPLEX, .48, (35, 55, 45), 1, cv2.LINE_AA)
    cv2.putText(canvas, "Source: Makhro et al., Zenodo 7801430, CC BY 4.0 · green = reference only; red = CV only; yellow = overlap",
                (12, 44), cv2.FONT_HERSHEY_SIMPLEX, .33, (65, 75, 68), 1, cv2.LINE_AA)
    labels = ["Original micrograph", "Reference mask · green", "Overlay · reference green / CV red"]
    for row_index, (frame_id, gray, reference, predicted) in enumerate(examples):
        y = 50 + row_index*(tile_h+58)
        rgb = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        truth = reference > 0
        pred = predicted > 0
        ref_view = rgb.copy(); ref_view[truth] = (70, 205, 100)
        overlay = rgb.copy()
        overlay[truth & ~pred] = (45, 190, 70)  # missed / reference only
        overlay[pred & ~truth] = (30, 70, 235)   # extra / prediction only
        overlay[truth & pred] = (40, 205, 205)  # agreement
        for col, panel in enumerate((rgb, ref_view, overlay)):
            canvas[y:y+tile_h, col*tile_w:(col+1)*tile_w] = panel
            cv2.putText(canvas, labels[col], (col*tile_w+9, y+tile_h+20),
                        cv2.FONT_HERSHEY_SIMPLEX, .43, (35, 55, 45), 1, cv2.LINE_AA)
        row = per_frame[row_index]
        cv2.putText(canvas, f"Frame {frame_id} · Dice {row['dice']:.3f} · IoU {row['iou']:.3f} · count {row['cells_detected']}/{row['cells_reference']}",
                    (12, y+tile_h+43), cv2.FONT_HERSHEY_SIMPLEX, .43, (35, 55, 45), 1, cv2.LINE_AA)
    sheet_path = os.path.join(OUT_DIR, "redtell_segmentation_examples.jpg")
    ok, encoded = cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        raise RuntimeError("Could not encode the example contact sheet")
    with open(sheet_path, "wb") as file:
        file.write(encoded.tobytes())
    public_sheet = os.path.join(ROOT, "web", "assets", "redtell_segmentation_examples.jpg")
    with open(public_sheet, "wb") as file:
        file.write(encoded.tobytes())
    print(json.dumps({"frames": len(per_frame), **report["metrics"], "report": report_path,
                      "contact_sheet": sheet_path, "web_asset": public_sheet,
                      "public_report": public_report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
