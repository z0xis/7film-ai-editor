"""Give every measured window the content vector that only whole shots have.

The shoot already has CLIP vectors, one per detected shot, and the planner reads them. A shot
runs three and a half seconds at the median, so a vector per shot cannot say which half second
of it the editor used — which is the question this round is asking. This encodes the same model
over the same window positions the measurements already use, so content can be compared on the
grid everything else is compared on.

No model is downloaded. This is the classifier already cached under the project runtime, loaded
the way the analyser loads it, run on more frames. Frames go in exactly as they come off the
file, because `encode` undoes the S-Log3 curve itself — CLIP changes its mind about a third of
this shoot's frames when it is shown the log picture instead of the graded one, and doing it
twice would be as wrong as not doing it at all.

Read-only with respect to everything else: it writes one file of vectors and touches no table,
no plan and no timeline.

Usage: tools/window_embeddings.py <project-id> --clips shadow_compare7.json --out vectors.npz
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from sevenfilm.config import database_path
from sevenfilm.db import Database
from sevenfilm.services.media import project_assets
from sevenfilm.services.windows import asset_windows

MEDIA = Path("/Users/ibrahimsoylu/Desktop/ELENORA MUSTAFA/KLIP/CLIP")
BATCH = 32


def main() -> int:
    import cv2
    from sevenfilm.services.vision import VisionClassifier

    parser = argparse.ArgumentParser()
    parser.add_argument("project_id")
    parser.add_argument("--clips", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    wanted = {row["clip"] for row in json.loads(args.clips.read_text())}
    database = Database(database_path())
    assets = {asset.name: asset for asset in project_assets(database, args.project_id)}
    by_asset = asset_windows(database, args.project_id)

    classifier = VisionClassifier()
    if not classifier._load():
        print("the vision model is not available in this runtime")
        return 1

    keys: list[str] = []
    vectors: list[np.ndarray] = []
    for index, clip in enumerate(sorted(wanted), 1):
        asset = assets.get(clip)
        if asset is None:
            continue
        windows = sorted(by_asset.get(asset.id, ()), key=lambda w: w.asset_frame)
        source = MEDIA / clip
        capture = cv2.VideoCapture(str(source))
        if not capture.isOpened():
            print(f"  {clip}: cannot open")
            continue
        frames, labels = [], []
        try:
            for window in windows:
                capture.set(cv2.CAP_PROP_POS_FRAMES, window.asset_frame)
                ok, frame = capture.read()
                if not ok or frame is None:
                    continue
                frames.append(frame)
                labels.append(f"{clip}:{window.asset_frame}")
                if len(frames) >= BATCH:
                    encoded = classifier.encode(frames)
                    if encoded is not None:
                        vectors.extend(encoded)
                        keys.extend(labels)
                    frames, labels = [], []
            if frames:
                encoded = classifier.encode(frames)
                if encoded is not None:
                    vectors.extend(encoded)
                    keys.extend(labels)
        finally:
            capture.release()
        print(f"{index:3d}/{len(wanted)}  {clip:12} {len(windows):4d} windows  "
              f"{len(keys):5d} vectors so far", flush=True)

    stacked = np.stack(vectors) if vectors else np.zeros((0, 512), dtype=np.float32)
    np.savez_compressed(args.out, keys=np.array(keys), vectors=stacked)
    print(f"written {args.out}  {stacked.shape}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
