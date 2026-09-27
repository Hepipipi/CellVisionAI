"""Train a whole-smear exploratory classifier from AneRBC-I original images.

Download/extract AneRBC-I from Mendeley Data (CC BY 4.0), then run:
  .venv\\Scripts\\python.exe train_anemia_image.py --root data/datasets/AneRBC-I
Expected folders: Anemic_individuals/Original_images/*_a.png and
Healthy_individuals/Original_images/*_h.png. Only original full smears are used.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter

import cv2
import numpy as np

from web_app import LinearSVM, hog_descriptor

ROOT = os.path.dirname(os.path.abspath(__file__))
IMAGE_MODEL_PATH = os.path.join(ROOT, "data", "models", "anemia_image_svm.npz")
REPORT_PATH = os.path.join(ROOT, "data", "models", "anerbc_image_report.json")


def split_groups(paths, labels, seed=29):
    rng = np.random.default_rng(seed)
    groups_by_class = {}
    for label in sorted(set(labels)):
        group_ids = sorted({re.sub(r"_\d+$", "", os.path.splitext(os.path.basename(p))[0][:-2]) for p, y in zip(paths, labels) if y == label})
        rng.shuffle(group_ids)
        n = len(group_ids)
        n_test, n_val = max(1, round(n * .15)), max(1, round(n * .15))
        groups_by_class[label] = (set(group_ids[n_test+n_val:]), set(group_ids[n_test:n_test+n_val]), set(group_ids[:n_test]))
    return groups_by_class


def group_id(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    return re.sub(r"_\d+$", "", stem[:-2])


def get_metrics(y_true, probs, threshold=.5):
    pred = (probs >= threshold).astype(int)
    tp = int(np.sum((y_true == 1) & (pred == 1)))
    tn = int(np.sum((y_true == 0) & (pred == 0)))
    fp = int(np.sum((y_true == 0) & (pred == 1)))
    fn = int(np.sum((y_true == 1) & (pred == 0)))
    order = np.argsort(probs)
    ranks = np.empty(len(probs), dtype=float); ranks[order] = np.arange(1, len(probs)+1)
    positives = int(y_true.sum()); negatives = len(y_true)-positives
    auc = (float((ranks[y_true == 1].sum() - positives*(positives+1)/2) / max(1, positives*negatives)))
    return {"test_images": len(y_true), "accuracy": float((tp+tn)/max(1,len(y_true))),
            "sensitivity": float(tp/max(1,tp+fn)), "specificity": float(tn/max(1,tn+fp)),
            "roc_auc": auc, "brier_score": float(np.mean((probs-y_true)**2)),
            "confusion_matrix": [[tn,fp],[fn,tp]], "threshold": threshold}


def fit_platt(scores, targets):
    a, b = 0.0, float(np.log((targets.mean()+1e-5)/(1-targets.mean()+1e-5)))
    for _ in range(3000):
        z = np.clip(a*scores+b, -25, 25)
        p = 1/(1+np.exp(-z))
        err = p-targets
        da = float(np.mean(err*scores)) + 1e-4*a
        db = float(np.mean(err))
        a -= .03*da; b -= .03*db
    return a, b


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="Extracted AneRBC-I folder")
    parser.add_argument("--epochs", type=int, default=18)
    args = parser.parse_args()
    paths, names = [], []
    for dirpath, _, files in os.walk(args.root):
        if "original_images" not in dirpath.lower():
            continue
        for name in files:
            match = re.fullmatch(r"(.+)_([ah])\.(png|jpg|jpeg|tif|tiff)", name, re.I)
            if not match:
                continue
            paths.append(os.path.join(dirpath, name))
            names.append("anemia_like" if match.group(2).lower() == "a" else "healthy")
    if len(set(names)) != 2 or min(Counter(names).values()) < 10:
        raise SystemExit("Не найдено достаточно оригинальных *_a и *_h снимков AneRBC-I.")
    classes = ["healthy", "anemia_like"]
    print("Original full-smear images:", dict(Counter(names)))
    features = []
    for i, path in enumerate(paths, 1):
        image = cv2.imread(path, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"Cannot read {path}")
        features.append(hog_descriptor(image))
        if i % 100 == 0:
            print(f"Processed {i}/{len(paths)} full images")
    x = np.asarray(features, np.float32)
    targets = np.asarray([classes.index(label) for label in names], np.int32)
    splits = split_groups(paths, names)
    masks = {k: np.asarray([group_id(p) in splits[y][idx] for p,y in zip(paths,names)]) for idx,k in enumerate(("train","validation","test"))}
    # Each original image/case identifier stays within a single split.
    for name, mask in masks.items():
        if mask.sum() == 0 or len(set(targets[mask])) != 2:
            raise ValueError(f"Split {name} lacks one class; provide more independent image IDs.")
    model = LinearSVM(np.zeros((2,x.shape[1]),np.float32), np.zeros(2,np.float32))
    model.fit(x[masks["train"]], targets[masks["train"]], 2, epochs=args.epochs)
    def margin(mask):
        xx=x[mask].copy(); xx/=np.maximum(np.linalg.norm(xx,axis=1,keepdims=True),1e-6)
        return (xx@model.weights.T+model.bias)[:,1]-(xx@model.weights.T+model.bias)[:,0]
    calibration_scores=margin(masks["validation"])
    platt_a, platt_b=fit_platt(calibration_scores,(targets[masks["validation"]]==1).astype(float))
    test_scores=margin(masks["test"])
    test_probs=1/(1+np.exp(-np.clip(platt_a*test_scores+platt_b,-25,25)))
    report=get_metrics((targets[masks["test"]]==1).astype(int),test_probs)
    report.update({"classes":classes,"source":"AneRBC-I, Mendeley Data v1, CC BY 4.0",
        "task":"exploratory full-smear image classification against AneRBC healthy/anemic dataset labels",
        "split":"70/15/15 by original image ID; the dataset does not publish patient IDs, so patient independence is not guaranteed",
        "train_images":int(masks["train"].sum()),"validation_images":int(masks["validation"].sum()),
        "epochs":args.epochs,"probability_calibration":"Platt sigmoid fitted on validation images",
        "warning":"Not a clinical diagnosis; dataset label probability only, no anemia cause/severity and no external clinical validation."})
    os.makedirs(os.path.dirname(IMAGE_MODEL_PATH),exist_ok=True)
    np.savez_compressed(IMAGE_MODEL_PATH,weights=model.weights,bias=model.bias,classes=np.asarray(classes),platt_a=platt_a,platt_b=platt_b)
    with open(REPORT_PATH,"w",encoding="utf-8") as f: json.dump(report,f,ensure_ascii=False,indent=2)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    print("Saved whole-smear model:",IMAGE_MODEL_PATH)


if __name__ == "__main__":
    main()
