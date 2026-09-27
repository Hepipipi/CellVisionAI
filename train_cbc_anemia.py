"""Train an adult CBC-only probability model on CDC NHANES 2021–2023.

The target is Hb below the chosen WHO adult cutoff (not physician-diagnosed cause).
Predictors deliberately exclude Hb to avoid target leakage. Requires pyreadstat.
Run: .venv\\Scripts\\python.exe train_cbc_anemia.py
"""
from __future__ import annotations

import json
import os
import urllib.request

import numpy as np
import pyreadstat

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data", "datasets")
MODEL = os.path.join(ROOT, "data", "models", "cbc_anemia_logistic.npz")
REPORT = os.path.join(ROOT, "data", "models", "cbc_anemia_report.json")
FILES = {
    "CBC_L.xpt": "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2021/DataFiles/CBC_L.xpt",
    "DEMO_L.xpt": "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2021/DataFiles/DEMO_L.xpt",
}
FEATURES = ["LBXRBCSI", "LBXMCVSI", "LBXRDW", "RIDAGEYR", "RIAGENDR"]


def logistic(z):
    return 1 / (1 + np.exp(-np.clip(z, -30, 30)))


def download_files():
    os.makedirs(DATA, exist_ok=True)
    for filename, url in FILES.items():
        path = os.path.join(DATA, filename)
        if not os.path.isfile(path) or os.path.getsize(path) < 1000:
            print("Downloading CDC NHANES", filename)
            request = urllib.request.Request(url, headers={"User-Agent": "CellVisionAI/1.0 research"})
            with urllib.request.urlopen(request, timeout=90) as response, open(path, "wb") as out:
                out.write(response.read())


def read_data():
    cbc, _ = pyreadstat.read_xport(os.path.join(DATA, "CBC_L.xpt"), output_format="dict", encoding="latin1")
    demo, _ = pyreadstat.read_xport(os.path.join(DATA, "DEMO_L.xpt"), output_format="dict", encoding="latin1")
    demographics = {int(seq): i for i, seq in enumerate(demo["SEQN"]) if seq is not None}
    rows, labels = [], []
    for i, seq in enumerate(cbc["SEQN"]):
        if seq is None or int(seq) not in demographics:
            continue
        j = demographics[int(seq)]
        age, gender, pregnant = demo["RIDAGEYR"][j], demo["RIAGENDR"][j], demo.get("RIDEXPRG", [None]*len(demo["SEQN"]))[j]
        # Restrict to non-pregnant adults represented by the app's adult groups.
        if age is None or gender not in (1.0, 2.0) or not 15 <= age <= 65 or pregnant == 1:
            continue
        hb = cbc["LBXHGB"][i]
        vals = [cbc[name][i] for name in FEATURES[:3]] + [age, gender]
        if hb is None or any(v is None for v in vals):
            continue
        vals = np.asarray(vals, dtype=np.float64)
        if not np.isfinite(vals).all() or vals[0] < 1 or vals[1] < 50 or vals[1] > 150 or vals[2] < 5 or vals[2] > 40:
            continue
        cutoff = 13.0 if gender == 1.0 else 12.0  # NHANES Hb is g/dL; WHO adult non-pregnant cutoffs.
        rows.append(vals)
        labels.append(int(hb < cutoff))
    return np.asarray(rows, np.float64), np.asarray(labels, np.float64)


def metrics(y, p):
    pred = p >= .5
    tp, tn = int(np.sum((y == 1)&pred)), int(np.sum((y == 0)&~pred))
    fp, fn = int(np.sum((y == 0)&pred)), int(np.sum((y == 1)&~pred))
    order=np.argsort(p); ranks=np.empty(len(p)); ranks[order]=np.arange(1,len(p)+1)
    positives=int(y.sum()); negatives=len(y)-positives
    auc=float((ranks[y==1].sum()-positives*(positives+1)/2)/max(1,positives*negatives))
    return {"n":len(y),"prevalence":float(y.mean()),"accuracy":float((tp+tn)/max(1,len(y))),
        "sensitivity":float(tp/max(1,tp+fn)),"specificity":float(tn/max(1,tn+fp)),"roc_auc":auc,
        "brier_score":float(np.mean((p-y)**2)),"confusion_matrix":[[tn,fp],[fn,tp]],"threshold":.5}


def main():
    download_files()
    x, y = read_data()
    if len(y) < 500 or len(np.unique(y)) < 2:
        raise RuntimeError("Too few eligible adult records or one target class missing.")
    rng=np.random.default_rng(2026); indices=rng.permutation(len(y))
    n_test=max(1,round(.2*len(y))); n_val=max(1,round(.15*len(y)))
    itest=indices[:n_test]; ival=indices[n_test:n_test+n_val]; itrain=indices[n_test+n_val:]
    mean=x[itrain].mean(axis=0); scale=x[itrain].std(axis=0); scale[scale<1e-8]=1
    z=(x-mean)/scale
    # Balanced weighted logistic regression; validation calibration restores cohort prevalence.
    ytrain=y[itrain]; pos=max(1,float(ytrain.sum())); neg=max(1,float(len(ytrain)-pos))
    weights=np.where(ytrain==1,len(ytrain)/(2*pos),len(ytrain)/(2*neg))
    w=np.zeros(z.shape[1]); b=0.0; rate=.04; reg=.01
    for _ in range(6000):
        p=logistic(z[itrain]@w+b); err=(p-ytrain)*weights
        w-=rate*(z[itrain].T@err/len(ytrain)+reg*w); b-=rate*float(err.mean())
    raw_val=z[ival]@w+b
    # Platt calibration on the held-out validation subset.
    a=1.0; c=float(np.log((y[ival].mean()+1e-5)/(1-y[ival].mean()+1e-5)))
    for _ in range(2500):
        p=logistic(a*raw_val+c); e=p-y[ival]
        a-=.025*(float(np.mean(e*raw_val))+.001*a); c-=.025*float(e.mean())
    ptest=logistic(a*(z[itest]@w+b)+c)
    report={"task":"probability of Hb below adult WHO cutoff based on CBC indices excluding Hb",
        "source":"CDC NHANES August 2021–August 2023, CBC_L + DEMO_L", "n_eligible":len(y),
        "train_n":len(itrain),"validation_n":len(ival),"test_n":len(itest),"positive_prevalence":float(y.mean()),
        "test_metrics":metrics(y[itest],ptest),"features":FEATURES,"hb_cutoffs_g_dl":{"male":13.0,"female_nonpregnant":12.0},
        "split":"random record-level 65/15/20 split; no repeated records per participant in this NHANES cycle",
        "limitations":"US survey cohort; adult, non-pregnant only; proxy label is thresholded Hb, not clinician-confirmed cause; not validated in Kyrgyzstan; output is research probability, not a diagnosis."}
    os.makedirs(os.path.dirname(MODEL),exist_ok=True)
    np.savez_compressed(MODEL,weights=w.astype(np.float32),bias=np.asarray([b],np.float32),mean=mean.astype(np.float32),
        scale=scale.astype(np.float32),platt_a=np.asarray([a],np.float32),platt_b=np.asarray([c],np.float32),features=np.asarray(FEATURES))
    with open(REPORT,"w",encoding="utf-8") as f: json.dump(report,f,ensure_ascii=False,indent=2)
    print(json.dumps(report,ensure_ascii=False,indent=2)); print("Saved CBC model:",MODEL)


if __name__=="__main__": main()
