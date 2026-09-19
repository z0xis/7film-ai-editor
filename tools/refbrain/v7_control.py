"""P6.25 -- V7 test-only positive control for the supervised event probe.

The probe is trained ONLY on external references (V7 never seen). Here we FREEZE it and apply it to V7,
whose known cake region (C7309, shot 51) is the positive control. V7 frames come from the 15A source
media (read-only). This is TEST-ONLY: no retraining on V7 errors. No DB/Resolve/timeline write.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))
DB = ROOT / "data" / "sevenfilm.sqlite3"
P15 = "29cd1e06-0af1-40c4-95bf-77f2add1159f"
V7 = ROOT / "data" / "reference_editor" / "raw" / "v7_trace.json"
OUT = ROOT / "tools" / "fixtures" / "p6_25_v7_control.json"
SCALES = {"wide": 0, "medium": 1, "close_up": 2, "detail": 3, "unknown": 4}


def _media_paths():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = con.execute("SELECT file_name, path FROM media_assets WHERE project_id=?", (P15,)).fetchall()
    con.close()
    return dict(rows)


def _scale_lookup():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """SELECT m.file_name, s.start_frame, s.duration_frames, s.shot_scale
           FROM shots s JOIN media_assets m ON m.id=s.asset_id WHERE m.project_id=?
           ORDER BY m.file_name, s.start_frame""", (P15,)).fetchall()
    con.close()
    by = {}
    for r in rows:
        by.setdefault(r["file_name"], []).append((r["start_frame"], r["duration_frames"], r["shot_scale"]))
    return by


def _scale_at(by, name, src_in):
    for st, du, sc in by.get(name, []):
        if st <= src_in < st + du:
            return sc or "unknown"
    return "unknown"


def _v7_features(clf):
    trace = json.loads(V7.read_text())
    start = trace["start"]
    paths = _media_paths()
    scales = _scale_lookup()
    fps = trace["fps"]
    items = trace["items"]
    total = (items[-1][1] - start + items[-1][2]) / fps
    mean, early, late, meta = [], [], [], []
    for i, (name, tl, dur, left) in enumerate(items):
        path = paths.get(name)
        embs = []
        if path and Path(path).is_file():
            cap = cv2.VideoCapture(path)
            src_fps = cap.get(cv2.CAP_PROP_FPS) or 50.0
            for frac in (0.2, 0.5, 0.8):
                cap.set(cv2.CAP_PROP_POS_MSEC, (left + dur * frac) / src_fps * 1000)
                ok, img = cap.read()
                embs.append(cv2.cvtColor(img, cv2.COLOR_BGR2RGB) if ok else None)
            cap.release()
        valid = [e for e in embs if e is not None]
        if valid:
            f = clf.encode(valid)
            m = f.mean(axis=0)
            e0 = f[0]; e2 = f[-1]
        else:
            m = e0 = e2 = np.zeros(512, dtype=np.float32)
        mean.append(m); early.append(e0); late.append(e2)
        meta.append({"shot": i, "source": name,
                     "scale": _scale_at(scales, name, left),
                     "pos": (tl - start) / fps / total if total else 0.0})
    mean = np.stack(mean); early = np.stack(early); late = np.stack(late)
    feats = []
    n = len(meta)
    for i in range(n):
        prev_m = mean[i - 1] if i > 0 else mean[i]
        next_m = mean[i + 1] if i < n - 1 else mean[i]
        sc = np.zeros(5); sc[SCALES.get(meta[i]["scale"], 4)] = 1
        feats.append(np.concatenate([mean[i], 0.5 * prev_m, 0.5 * next_m, late[i] - early[i], sc,
                                     [0.5, meta[i]["pos"]]]))
    return np.stack(feats), meta


def run() -> dict:
    from sevenfilm.services.vision import VisionClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    from tools.refbrain.event_probe import build_dataset
    X, y, _groups, _ = build_dataset()
    scaler = StandardScaler().fit(X)
    clf = LogisticRegression(max_iter=2000, class_weight="balanced").fit(scaler.transform(X), y)

    vc = VisionClassifier(); vc._load()
    Xv, meta = _v7_features(vc)
    preds = clf.predict(scaler.transform(Xv))
    proba = clf.predict_proba(scaler.transform(Xv))
    classes = list(clf.classes_)
    cake_i = classes.index("CAKE") if "CAKE" in classes else None

    from collections import Counter
    cake_shot = 51  # C7309, the verified V7 cake shot
    result = {
        "model_frozen_before_v7": True, "v7_in_training": False,
        "cake_positive_control": {
            "v7_cake_shot": cake_shot, "source": meta[cake_shot]["source"],
            "predicted": preds[cake_shot],
            "cake_probability": round(float(proba[cake_shot][cake_i]), 3) if cake_i is not None else None,
            "detected_as_cake": preds[cake_shot] == "CAKE",
        },
        "v7_shots_predicted_cake": [m["shot"] for m, p in zip(meta, preds) if p == "CAKE"],
        "v7_prediction_distribution": dict(Counter(preds)),
        "first_dance_note": "probe has no FIRST_DANCE class (0 external labels) -> cannot be tested",
    }
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True))
    return result


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
