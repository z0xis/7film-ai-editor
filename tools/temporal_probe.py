"""Read what changes around the editor's in and out points, and around the search's own.

Measures the media a quarter second at a time either side of each boundary, so the question
"what changed here" can be asked of the picture rather than guessed. Motion turns out to be
the strongest thing in it: the editor's frames sit where the picture has settled, at a mean
12.3 against 24.5 at random positions in the same clip, and that measurement is already
stored and never scored.

Measures the media with the production measures. Writes one JSON. Touches nothing else.
Sampling and controls are fixed in PREREGISTRATION-35.md.
"""
from __future__ import annotations

import json
import os
import random
import sys

import cv2
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "apps", "api"))
from sevenfilm.services.windows import (
    BYSTANDER_RATIO,
    BYSTANDER_SCORE,
    _face_framing,
    _sharpness,
)

HERE = os.path.dirname(os.path.abspath(__file__))
MEDIA = os.environ.get("SEVENFILM_MEDIA", "")
MODEL = os.path.join(REPO, "apps", "api", "sevenfilm", "models",
                     "face_detection_yunet_2023mar.onnx")
FPS = 50
SEED = 20260913

FINE = [round(x * 0.25 - 2.0, 2) for x in range(17)]      # -2.0 .. +2.0 by 0.25 s
COARSE = [round(x * 0.5 - 2.0, 2) for x in range(9)]      # -2.0 .. +2.0 by 0.5 s
CONTROLS = 10
CONTROL_GAP = 3 * FPS

ROWS_PATH = os.environ.get("SEVENFILM_COMPARE", "shadow_compare.json")
with open(ROWS_PATH) as fh:
    ROWS = json.load(fh)


def read(cap, det, w, h, frames, total):
    out, prev = {}, None
    for f in sorted(set(frames)):
        if f < 0 or f >= total:
            continue
        cap.set(cv2.CAP_PROP_POS_FRAMES, f)
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = []
        if det is not None:
            _ok, found = det.detect(frame)
            if found is not None:
                faces = list(found)
        ratio, edge, bys = 0.0, 0.0, 0
        if faces:
            big = max(faces, key=lambda b: b[2] * b[3])
            ratio, edge = _face_framing(big, w, h)
            area = float(big[2] * big[3])
            bys = sum(1 for b in faces if float(b[2] * b[3]) < area * BYSTANDER_RATIO)
        small = cv2.resize(grey, (160, 90)).astype(np.int16)
        motion = 0.0 if prev is None else float(np.abs(small - prev).mean())
        prev = small
        out[f] = {"f": f, "sharpness": round(_sharpness(cv2, grey), 2),
                  "face_ratio": ratio, "face_edge": edge,
                  "face_count": len(faces), "bystanders": bys,
                  "motion": round(motion, 3)}
    return out


def main() -> int:
    result = []
    for index, row in enumerate(ROWS, 1):
        path = os.path.join(MEDIA, row["clip"])
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            continue
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        det = None
        if hasattr(cv2, "FaceDetectorYN") and os.path.exists(MODEL):
            det = cv2.FaceDetectorYN.create(MODEL, "", (w, h),
                                            score_threshold=BYSTANDER_SCORE,
                                            nms_threshold=0.3)

        man_in = row["manual_in"]
        man_out = man_in + row["frames"]
        e1 = row["e_in"]

        rng = random.Random(SEED + index)
        controls = []
        guard = 0
        while len(controls) < CONTROLS and guard < 400:
            guard += 1
            pick = rng.randrange(10, max(11, total - row["frames"] - 10))
            if abs(pick - man_in) >= CONTROL_GAP:
                controls.append(pick)

        wanted = (
            [man_in + int(o * FPS) for o in FINE]
            + [man_out + int(o * FPS) for o in FINE]
            + [e1 + int(o * FPS) for o in COARSE]
            + controls
        )
        got = read(cap, det, w, h, wanted, total)
        cap.release()

        result.append({
            "clip": row["clip"], "category": row["category"],
            "manual_in": man_in, "manual_out": man_out, "e1_in": e1,
            "a_in": row["a_in"], "d_in": row["d_in"], "frames": row["frames"],
            "in_strip": [got.get(man_in + int(o * FPS)) for o in FINE],
            "out_strip": [got.get(man_out + int(o * FPS)) for o in FINE],
            "e1_strip": [got.get(e1 + int(o * FPS)) for o in COARSE],
            "controls": [got.get(c) for c in controls],
            "offsets_fine": FINE, "offsets_coarse": COARSE,
        })
        print(f"{index:3d}/{len(ROWS)}  {row['clip']:11} "
              f"in {sum(1 for x in result[-1]['in_strip'] if x):2d} "
              f"out {sum(1 for x in result[-1]['out_strip'] if x):2d} "
              f"ctrl {sum(1 for x in result[-1]['controls'] if x):2d}", flush=True)

    with open(os.environ.get("SEVENFILM_STRIPS", "temporal_strips.json"), "w") as fh:
        json.dump(result, fh)
    print("written", len(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
