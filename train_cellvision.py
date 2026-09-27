"""Train CellVision's experimental RBC morphology model on RedTell DSE.

Dataset: Red Blood Cell RedTell Dataset, Zenodo 7801430, CC BY 4.0.
This trains morphology categories only; it does not diagnose anemia or disease.
Run with the project's virtual environment: python train_cellvision.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import urllib.request
import zipfile
from collections import Counter, defaultdict

import cv2
import numpy as np

from web_app import LinearSVM, MODEL_CLASSES_PATH, MODEL_DIR, MODEL_PATH, hog_descriptor

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data", "datasets")
ARCHIVE = os.path.join(DATA_DIR, "redtell_dse.zip")
DATA_URL = "https://zenodo.org/api/records/7801430/files/dse_data.zip/content"
EXPECTED_MD5 = "570dec91777dd0c77de008e0a6d81ed3"
SOURCE = "Red Blood Cell RedTell Dataset (Zenodo 7801430), dse_data.zip"
LICENSE = "CC BY 4.0"
CLASS_RULES = {
    "Discocyte": "Discocyte",
    "Stomatocyte1": "Stomatocyte", "Stomatocyte2": "Stomatocyte", "Stomatocyte3": "Stomatocyte",
    "Echinocyte1": "Echinocyte", "Echinocyte2": "Echinocyte", "Echinocyte3": "Echinocyte", "Echinocyte4": "Echinocyte",
}


def ensure_archive():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.isfile(ARCHIVE) or os.path.getsize(ARCHIVE) < 1000:
        print("Downloading RedTell DSE dataset (44.5 MB)...")
        request = urllib.request.Request(DATA_URL, headers={"User-Agent": "CellVisionAI/1.0 research-training"})
        with urllib.request.urlopen(request, timeout=120) as response, open(ARCHIVE, "wb") as out:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
    digest = hashlib.md5()
    with open(ARCHIVE, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != EXPECTED_MD5:
        raise ValueError(f"Dataset archive checksum mismatch: {digest.hexdigest()}")
    print(f"Dataset checksum OK: MD5 {digest.hexdigest()}")


def load_samples():
    features, labels, source_ids = [], [], []
    counts = Counter()
    with zipfile.ZipFile(ARCHIVE) as zf:
        available = set(zf.namelist())
        members = [n for n in zf.namelist() if "/coco_annotations/" in n and n.lower().endswith((".tif", ".tiff", ".png", ".jpg"))]
        if not members:
            raise ValueError("No annotated single-cell crops found in dse_data.zip")
        frame_cache = {}
        for index, member in enumerate(members, 1):
            name = os.path.basename(member)
            match = re.match(r"(\d+)_([^_]+)_\d+\.(?:tif|tiff|png|jpg)$", name, re.IGNORECASE)
            if not match or match.group(2) not in CLASS_RULES:
                continue
            source_id, raw_label = int(match.group(1)), match.group(2)
            if source_id not in frame_cache:
                raw_path = f"dse_data/images/{source_id}.tif"
                annotation_path = f"dse_data/annotations/{source_id}.tif"
                if raw_path not in available or annotation_path not in available:
                    continue
                raw = cv2.imdecode(np.frombuffer(zf.read(raw_path), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
                annotation = cv2.imdecode(np.frombuffer(zf.read(annotation_path), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
                if raw is None or annotation is None:
                    raise ValueError(f"Could not decode source frame {source_id}")
                frame_cache[source_id] = (raw, annotation)
            raw, annotation = frame_cache[source_id]

            # coco_annotations contains a binary instance mask, not a photo.
            # Locate the corresponding instance id, then crop the original frame.
            encoded = np.frombuffer(zf.read(member), dtype=np.uint8)
            instance_mask = cv2.imdecode(encoded, cv2.IMREAD_GRAYSCALE)
            if instance_mask is None:
                continue
            ys, xs = np.where(instance_mask > 0)
            if not len(xs):
                continue
            instance_values = annotation[ys, xs]
            instance_values = instance_values[instance_values > 0]
            if not len(instance_values):
                continue
            instance_id = int(np.bincount(instance_values).argmax())
            iy, ix = np.where(annotation == instance_id)
            if not len(ix):
                continue
            # Add a little context around the segmented cell for consistent HOG features.
            pad = max(4, int(max(ix.max() - ix.min(), iy.max() - iy.min()) * .18))
            x0, x1 = max(0, int(ix.min()) - pad), min(raw.shape[1], int(ix.max()) + pad + 1)
            y0, y1 = max(0, int(iy.min()) - pad), min(raw.shape[0], int(iy.max()) + pad + 1)
            image_crop = raw[y0:y1, x0:x1]
            if image_crop.size == 0:
                continue
            features.append(hog_descriptor(image_crop))
            labels.append(CLASS_RULES[raw_label])
            source_ids.append(source_id)
            counts[CLASS_RULES[raw_label]] += 1
            if index % 500 == 0:
                print(f"Read {index}/{len(members)} annotated crops...")
    if len(set(labels)) != 3:
        raise ValueError(f"Expected the 3 RedTell morphology classes; found {counts}")
    print("Annotated cell crops:", dict(counts))
    return np.asarray(features, np.float32), np.asarray(labels), np.asarray(source_ids)


def metrics(y_true, y_pred, classes):
    matrix = np.zeros((len(classes), len(classes)), dtype=np.int64)
    for actual, predicted in zip(y_true, y_pred):
        matrix[classes.index(actual), classes.index(predicted)] += 1
    recalls = [matrix[i, i] / max(1, matrix[i].sum()) for i in range(len(classes))]
    precisions = [matrix[i, i] / max(1, matrix[:, i].sum()) for i in range(len(classes))]
    f1 = [2 * p * r / max(1e-12, p + r) for p, r in zip(precisions, recalls)]
    return {
        "test_samples": int(matrix.sum()),
        "accuracy": float(np.trace(matrix) / max(1, matrix.sum())),
        "balanced_accuracy": float(np.mean(recalls)),
        "macro_f1": float(np.mean(f1)),
        "per_class": {name: {"support": int(matrix[i].sum()), "precision": float(precisions[i]), "recall": float(recalls[i]), "f1": float(f1[i])} for i, name in enumerate(classes)},
        "confusion_matrix": {"labels_order": classes, "values": matrix.tolist()},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epochs", type=int, default=16)
    args = parser.parse_args()
    ensure_archive()
    x, y_text, groups = load_samples()
    classes = sorted(np.unique(y_text).tolist())
    targets = np.asarray([classes.index(value) for value in y_text], dtype=np.int32)

    # Keep every cell from an original source frame together to reduce crop leakage.
    test_frames = {frame for frame in np.unique(groups) if frame % 5 == 0}
    test_mask = np.isin(groups, list(test_frames))
    train_mask = ~test_mask
    if len(set(y_text[test_mask])) < len(classes) or len(set(y_text[train_mask])) < len(classes):
        raise ValueError("Frame-wise split did not include every class; inspect the dataset labels.")
    print(f"Frames: {len(np.unique(groups))}; train frames: {len(set(groups[train_mask]))}; held-out frames: {len(test_frames)}")
    print(f"Training {int(train_mask.sum())} crops for {args.epochs} epochs...")
    model = LinearSVM(np.empty((0, x.shape[1]), np.float32), np.empty(0, np.float32))
    model.fit(x[train_mask], targets[train_mask], len(classes), epochs=args.epochs)
    predicted = np.asarray([classes[int(i)] for i in model.predict(x[test_mask]).reshape(-1)])
    report = metrics(y_text[test_mask].tolist(), predicted.tolist(), classes)
    report.update({
        "task": "single-cell morphology classification",
        "source": SOURCE, "license": LICENSE,
        "split": "held out by source-frame number modulo 5; no patient-level identifiers provided",
        "train_samples": int(train_mask.sum()), "train_frames": int(len(set(groups[train_mask]))),
        "test_frames": int(len(test_frames)), "class_counts_all": dict(Counter(y_text.tolist())),
        "epochs": args.epochs,
        "warning": "Research/visualization prototype. Morphology predictions are not a diagnosis and do not estimate anemia probability.",
    })
    os.makedirs(MODEL_DIR, exist_ok=True)
    # Do not put an untrustworthy model into the app's inference path.
    promoted = report["balanced_accuracy"] >= .60 and report["macro_f1"] >= .55
    report["promoted_to_app"] = promoted
    if promoted:
        np.savez_compressed(MODEL_PATH, weights=model.weights, bias=model.bias)
        with open(MODEL_CLASSES_PATH, "w", encoding="utf-8") as f:
            json.dump(classes, f, ensure_ascii=False, indent=2)
    else:
        print("Model did not meet the promotion threshold; keeping it out of the app inference path.")
    report_path = os.path.join(MODEL_DIR, "redtell_training_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("\nHeld-out frame evaluation:")
    print(json.dumps({k: report[k] for k in ("test_samples", "accuracy", "balanced_accuracy", "macro_f1", "per_class")}, ensure_ascii=False, indent=2))
    print(f"\nSaved model: {MODEL_PATH}")
    print(f"Saved classes: {MODEL_CLASSES_PATH}")
    print(f"Saved evaluation: {report_path}")


if __name__ == "__main__":
    main()
