"""P6.25 -- per-shot feature extraction for the supervised event probe (external references only).

For each shot: sample 3 frames (early/mid/late), CLIP-encode, store the mean embedding + the early/late
embeddings (for temporal deltas) and a thumbnail (for annotation contact sheets). Deterministic. Output
under data/reference_editor/probe/ (gitignored). No DB/Resolve write. V7/is edit are handled by a
separate test-only path so they never enter training.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))
MEDIA = ROOT / "data" / "references" / "media"
TIER2 = ROOT / "data" / "reference_editor" / "tier2"
OUT = ROOT / "data" / "reference_editor" / "probe"
EMB = OUT / "embeddings"
THUMBS = OUT / "thumbs"


def _extract(path: Path, enriched: dict, clf):
    scenes = [(s["start_s"], s["end_s"]) for s in enriched["shots"]]
    cap = cv2.VideoCapture(str(path))
    frames, owner, pos_in_shot = [], [], []
    thumbs = {}
    for i, (a, b) in enumerate(scenes):
        for k, t in enumerate((a + (b - a) * 0.2, (a + b) / 2, a + (b - a) * 0.8)):
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, img = cap.read()
            if ok:
                frames.append(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
                owner.append(i)
                pos_in_shot.append(k)
                if k == 1:
                    thumbs[i] = cv2.resize(img, (160, 90))
    cap.release()
    feats = clf.encode(frames)
    n = len(scenes)
    mean_emb = np.zeros((n, feats.shape[1]), dtype=np.float32)
    early = np.zeros_like(mean_emb)
    late = np.zeros_like(mean_emb)
    for i in range(n):
        idx = [j for j, o in enumerate(owner) if o == i]
        if not idx:
            continue
        mean_emb[i] = feats[idx].mean(axis=0)
        e = [j for j in idx if pos_in_shot[j] == 0]
        late_i = [j for j in idx if pos_in_shot[j] == 2]
        early[i] = feats[e[0]] if e else mean_emb[i]
        late[i] = feats[late_i[0]] if late_i else mean_emb[i]
    return mean_emb, early, late, thumbs, scenes


def _contact_sheet(thumbs, scenes, enriched, out_path, cols=10):
    n = len(scenes)
    rows = (n + cols - 1) // cols
    sheet = np.full((rows * 104, cols * 164, 3), 30, dtype=np.uint8)
    for i in range(n):
        r, c = divmod(i, cols)
        th = thumbs.get(i)
        if th is None:
            continue
        y, x = r * 104, c * 164
        sheet[y + 12:y + 102, x + 2:x + 162] = th
        cat = (enriched["shots"][i].get("category") or "?")[:6]
        cv2.putText(sheet, f"{i} {cat}", (x + 3, y + 10), cv2.FONT_HERSHEY_SIMPLEX, 0.32,
                    (0, 255, 0), 1, cv2.LINE_AA)
    cv2.imwrite(str(out_path), sheet)


def run(only: str | None = None):
    from sevenfilm.services.vision import VisionClassifier
    clf = VisionClassifier()
    if not clf._load():
        raise RuntimeError("CLIP unavailable")
    EMB.mkdir(parents=True, exist_ok=True)
    THUMBS.mkdir(parents=True, exist_ok=True)
    done = []
    for ef in sorted(TIER2.glob("*.json")):
        stem = ef.stem
        if only and stem != only:
            continue
        path = MEDIA / f"{stem}.mkv"
        if not path.is_file():
            continue
        enriched = json.loads(ef.read_text())
        mean_emb, early, late, thumbs, scenes = _extract(path, enriched, clf)
        np.savez(EMB / f"{stem}.npz", mean=mean_emb, early=early, late=late,
                 starts=np.array([a for a, _ in scenes]), ends=np.array([b for _, b in scenes]))
        _contact_sheet(thumbs, scenes, enriched, THUMBS / f"{stem}.jpg")
        done.append({"reference_id": f"ref:{stem}", "n_shots": len(scenes)})
    (OUT / "index.json").write_text(json.dumps(done, indent=1, sort_keys=True))
    return done


if __name__ == "__main__":
    only = sys.argv[1] if len(sys.argv) > 1 else None
    print(json.dumps(run(only), indent=2))
