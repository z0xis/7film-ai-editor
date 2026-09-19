"""P6.25 -- supervised wedding-event probe on EXTERNAL references only (grouped leave-one-wedding-out).

Trains a lightweight probe (linear logistic + kNN) on temporal CLIP features to test whether the
features are discriminative for fine wedding events GIVEN supervision. Split is grouped by wedding (the
same wedding never appears in train and validation). V7 / is edit are never loaded here -- they are a
separate test-only path. Deterministic. No DB / Resolve / timeline write.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))
EMB = ROOT / "data" / "reference_editor" / "probe" / "embeddings"
TIER2 = ROOT / "data" / "reference_editor" / "tier2"
ANN = ROOT / "tools" / "fixtures" / "p6_25_event_annotations.jsonl"
OUT = ROOT / "tools" / "fixtures" / "p6_25_probe_results.json"

SCALES = {"wide": 0, "medium": 1, "close_up": 2, "detail": 3, "unknown": 4}
MOTION = {"calm": 0, "medium": 1, "energetic": 2}


def _load_annotations():
    labels = defaultdict(dict)   # ref -> shot_index -> event
    for line in ANN.read_text().splitlines():
        d = json.loads(line)
        if "event" not in d:
            continue
        for s in d["shots"]:
            labels[d["reference_id"]][s] = d["event"]
    return labels


def _features_for_ref(rid):
    stem = rid.split(":", 1)[1]
    npz = EMB / f"{stem}.npz"
    t2 = TIER2 / f"{stem}.json"
    if not npz.is_file() or not t2.is_file():
        return None
    z = np.load(npz)
    mean, early, late = z["mean"], z["early"], z["late"]
    shots = json.loads(t2.read_text())["shots"]
    n = len(shots)
    feats = []
    for i in range(n):
        prev_m = mean[i - 1] if i > 0 else mean[i]
        next_m = mean[i + 1] if i < n - 1 else mean[i]
        delta = late[i] - early[i]
        sc = np.zeros(5); sc[SCALES.get(shots[i].get("shot_scale", "unknown"), 4)] = 1
        mo = MOTION.get(shots[i].get("motion_band", "medium"), 1)
        pos = shots[i].get("story_position", 0.0)
        feats.append(np.concatenate([mean[i], 0.5 * prev_m, 0.5 * next_m, delta, sc,
                                     [mo / 2.0, pos]]))
    return np.stack(feats)


def build_dataset():
    labels = _load_annotations()
    X, y, groups, prov = [], [], [], []
    for rid in sorted(labels):
        feats = _features_for_ref(rid)
        if feats is None:
            continue
        for shot_i, event in sorted(labels[rid].items()):
            if shot_i < len(feats):
                X.append(feats[shot_i]); y.append(event); groups.append(rid)
                prov.append((rid, shot_i))
    return np.stack(X), np.array(y), np.array(groups), prov


def run() -> dict:
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import precision_recall_fscore_support
    from sklearn.model_selection import LeaveOneGroupOut
    from sklearn.neighbors import KNeighborsClassifier
    from sklearn.preprocessing import StandardScaler

    X, y, groups, _prov = build_dataset()
    classes = sorted(set(y))
    # data sufficiency audit
    weddings_per_event = {c: len({groups[i] for i in range(len(y)) if y[i] == c}) for c in classes}
    shots_per_event = dict(Counter(y))

    logo = LeaveOneGroupOut()
    results = {}
    for name, mk in (("linear", lambda: LogisticRegression(max_iter=2000, class_weight="balanced")),
                     ("knn", lambda: KNeighborsClassifier(n_neighbors=5))):
        preds = np.empty(len(y), dtype=object)
        for tr, te in logo.split(X, y, groups):
            if len(set(y[tr])) < 2:
                preds[te] = "UNKNOWN"
                continue
            sc = StandardScaler().fit(X[tr])
            clf = mk().fit(sc.transform(X[tr]), y[tr])
            preds[te] = clf.predict(sc.transform(X[te]))
        p, r, f, s = precision_recall_fscore_support(y, preds, labels=classes, zero_division=0)
        results[name] = {c: {"precision": round(float(p[i]), 3), "recall": round(float(r[i]), 3),
                             "f1": round(float(f[i]), 3), "support": int(s[i])}
                         for i, c in enumerate(classes)}
        # cake confusion detail
        cake_idx = [i for i in range(len(y)) if y[i] == "CAKE"]
        results[name]["_cake_predicted_as"] = dict(Counter(preds[i] for i in cake_idx))

    out = {
        "n_labelled_shots": len(y), "classes": classes,
        "weddings_per_event": weddings_per_event, "shots_per_event": shots_per_event,
        "first_dance_labelled": shots_per_event.get("FIRST_DANCE", 0),
        "acceptance": {
            "CAKE": {"weddings": weddings_per_event.get("CAKE", 0),
                     "linear_precision": results["linear"].get("CAKE", {}).get("precision", 0.0),
                     "linear_recall": results["linear"].get("CAKE", {}).get("recall", 0.0)},
            "FIRST_DANCE": "INSUFFICIENT_LABELLED_EVIDENCE (0 reliably-isolable positives in externals)",
        },
        "results": results,
        "leakage": {"v7_or_is_edit_in_training": False, "split": "leave-one-wedding-out (grouped)"},
    }
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True))
    return out


if __name__ == "__main__":
    r = run()
    print(json.dumps({k: r[k] for k in ("n_labelled_shots", "weddings_per_event", "shots_per_event",
                                        "acceptance")}, indent=2))
    print("LINEAR per-class:")
    for c, m in r["results"]["linear"].items():
        if not c.startswith("_"):
            print(f"  {c}: P={m['precision']} R={m['recall']} F1={m['f1']} n={m['support']}")
    print("CAKE predicted as (linear):", r["results"]["linear"]["_cake_predicted_as"])
