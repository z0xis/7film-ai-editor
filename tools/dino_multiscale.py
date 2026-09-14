"""Repeat the DINOv2 change-point read at three fixed temporal scales, on the two canonical clips.

A quarter second, half a second, one second — chosen before this ran, never after seeing which
one flatters a result. The question is whether the C2075 finding survives changing the
sampling interval, and whether C1987's silence does too.
"""
from __future__ import annotations

import argparse
import json
import sys
from itertools import pairwise
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from semantic_probe import MEDIA, frame_at

SCALES = {"0.25s": 13, "0.5s": 25, "1.0s": 50}
CLIPS = {"C2075.MP4": (0, 4400), "C1987.MP4": (0, 528)}


def curve_at(capture, first, last, step, processor, model, torch):
    import cv2
    embeddings = {}
    for frame in range(first, last + 1, step):
        picture = frame_at(capture, frame, cv2)
        if picture is None:
            continue
        encoded = processor(images=[picture], return_tensors="pt")
        with torch.inference_mode():
            pooled = model(**encoded).pooler_output[0]
        embeddings[frame] = pooled / pooled.norm()
    frames = sorted(embeddings)
    return [{"frame": b, "from": a, "distance": float(1.0 - (embeddings[a] @ embeddings[b]))}
            for a, b in pairwise(frames)]


def main() -> int:
    import cv2
    import torch
    from transformers import AutoImageProcessor, AutoModel

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    processor = AutoImageProcessor.from_pretrained("facebook/dinov2-base", local_files_only=True)
    model = AutoModel.from_pretrained("facebook/dinov2-base", local_files_only=True).eval()

    results = {}
    for clip, (first, last) in CLIPS.items():
        results[clip] = {}
        capture = cv2.VideoCapture(str(MEDIA / clip))
        try:
            for name, step in SCALES.items():
                curve = curve_at(capture, first, last, step, processor, model, torch)
                top = sorted(curve, key=lambda p: -p["distance"])[:5]
                results[clip][name] = {"curve_len": len(curve), "top5": top}
                print(f"{clip} {name}: top5 frames = {[p['frame'] for p in top]}", flush=True)
        finally:
            capture.release()
        args.out.write_text(json.dumps(results, indent=1))
    print(f"written {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
