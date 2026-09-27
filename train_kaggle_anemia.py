"""Train a small CBC-index screening model on the public Kaggle anemia CSV.

The model predicts the dataset's Result label from sex and red-cell indices,
excluding Hemoglobin to avoid direct target leakage. Research prototype only.
"""
from __future__ import annotations

import csv
import json
import os

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data", "datasets", "anemia_kaggle.csv")
MODEL = os.path.join(ROOT, "data", "models", "cbc_anemia_logistic.npz")
REPORT = os.path.join(ROOT, "data", "models", "cbc_anemia_report.json")
FEATURES = ["Gender", "MCH", "MCHC", "MCV"]


def sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def read_data():
    if not os.path.isfile(DATA):
        raise FileNotFoundError(f"Скачайте Kaggle anemia.csv и сохраните как {DATA}")
    with open(DATA, newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        required = set(FEATURES + ["Hemoglobin", "Result"])
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"Ожидаемые колонки: {', '.join(sorted(required))}")
        rows, labels = [], []
        for row in reader:
            values = [float(row[key]) for key in FEATURES]
            hb, label = float(row["Hemoglobin"]), int(float(row["Result"]))
            if label not in (0, 1) or not np.isfinite(values + [hb]).all():
                continue
            if values[0] not in (0, 1) or not 5 <= hb <= 25:
                continue
            rows.append(values)
            labels.append(label)
    return np.asarray(rows, np.float64), np.asarray(labels, np.float64)


def split_data(y):
    rng = np.random.default_rng(2026)
    train, val, test = [], [], []
    for label in (0, 1):
        ids = rng.permutation(np.flatnonzero(y == label))
        n_test = max(1, round(.2 * len(ids)))
        n_val = max(1, round(.15 * (len(ids) - n_test)))
        test.extend(ids[:n_test])
        val.extend(ids[n_test:n_test + n_val])
        train.extend(ids[n_test + n_val:])
    return tuple(np.asarray(part, dtype=int) for part in (train, val, test))


def metrics(y, p):
    pred = p >= .5
    tp = int(np.sum((y == 1) & pred)); tn = int(np.sum((y == 0) & ~pred))
    fp = int(np.sum((y == 0) & pred)); fn = int(np.sum((y == 1) & ~pred))
    order = np.argsort(p); ranks = np.empty(len(p)); ranks[order] = np.arange(1, len(p) + 1)
    pos = int(y.sum()); neg = len(y) - pos
    auc = float((ranks[y == 1].sum() - pos * (pos + 1) / 2) / max(1, pos * neg))
    return {"n": len(y), "prevalence": float(y.mean()), "accuracy": float((tp + tn) / len(y)),
            "sensitivity": float(tp / max(1, tp + fn)), "specificity": float(tn / max(1, tn + fp)),
            "roc_auc": auc, "brier_score": float(np.mean((p - y) ** 2)),
            "confusion_matrix": [[tn, fp], [fn, tp]], "threshold": .5}


def main():
    x, y = read_data()
    if len(y) < 100 or len(np.unique(y)) < 2:
        raise RuntimeError("Недостаточно строк или отсутствует один из классов.")
    itrain, ival, itest = split_data(y)
    mean = x[itrain].mean(axis=0); scale = x[itrain].std(axis=0); scale[scale < 1e-8] = 1
    z = (x - mean) / scale
    w = np.zeros(z.shape[1]); b = 0.0; rate = .04; reg = .03
    for _ in range(5000):
        p = sigmoid(z[itrain] @ w + b); err = p - y[itrain]
        w -= rate * (z[itrain].T @ err / len(itrain) + reg * w)
        b -= rate * float(err.mean())
    raw_val = z[ival] @ w + b
    # Calibrate on the validation split, not on the held-out test set.
    a, c = 1.0, float(np.log((y[ival].mean() + 1e-5) / (1 - y[ival].mean() + 1e-5)))
    for _ in range(2500):
        p = sigmoid(a * raw_val + c); err = p - y[ival]
        a -= .025 * (float(np.mean(err * raw_val)) + .001 * a)
        c -= .025 * float(err.mean())
    test_p = sigmoid(a * (z[itest] @ w + b) + c)
    report = {"task": "Kaggle Result label from CBC red-cell indices excluding Hb",
              "source": "Kaggle anemia-dataset (1,421 records; public mirror of anemia.csv)",
              "n": len(y), "class_counts": {"0": int(np.sum(y == 0)), "1": int(np.sum(y == 1))},
              "train_n": len(itrain), "validation_n": len(ival), "test_n": len(itest),
              "features": FEATURES, "excluded_feature": "Hemoglobin",
              "test_metrics": metrics(y[itest], test_p),
              "split": "fixed-seed stratified random row split 65/15/20; no patient IDs available",
              "limitations": "Kaggle dataset documentation does not establish clinical adjudication, participant demographics, or label-generation method. No image data, age, RBC count, or RDW. Test results are internal and do not establish clinical validity or transfer to Kyrgyzstan."}
    os.makedirs(os.path.dirname(MODEL), exist_ok=True)
    np.savez_compressed(MODEL, weights=w.astype(np.float32), bias=np.asarray([b], np.float32),
                        mean=mean.astype(np.float32), scale=scale.astype(np.float32),
                        platt_a=np.asarray([a], np.float32), platt_b=np.asarray([c], np.float32),
                        features=np.asarray(FEATURES))
    with open(REPORT, "w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("Saved model:", MODEL)


if __name__ == "__main__":
    main()
