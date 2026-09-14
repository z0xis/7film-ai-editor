"""Does DINOv2's own visual-change signal generalise as a candidate-neighbourhood generator?

Last round found this signal by accident, on one clip: DINOv2's pooled embedding, read as a
distance to its neighbour every half second, had its two largest jumps in the whole 78-second
"cutting" scene bracket the real cut almost exactly, with no language, no training and no
manual timing anywhere near it. This asks whether that was the clip or the method — across the
frozen 54-clip research set, blind to every manual cut until the very end.

DINOv2 is never asked what an event is. It has no event vocabulary at all; a distance between
two embeddings says only that the picture changed, not what changed or whether the change was
editorially anything. Whatever this file finds is a candidate-neighbourhood generator, not a
detector — its job, if it has one, is to throw most of a clip away cheaply so a slower semantic
pass only has to look at what is left.

Manual timing enters this file in exactly one place: the evaluation at the bottom, after every
candidate has already been generated. Nothing upstream of that point reads it.

Read-only. DINOv2 was already cached for the previous round; nothing is downloaded here.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics as st
import sys
from itertools import pairwise
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from semantic_probe import MEDIA, frame_at
from sevenfilm.config import database_path
from sevenfilm.db import Database
from sevenfilm.services.media import project_assets
from sevenfilm.services.windows import asset_windows
from shutter_audit import shutter_mode

STEP = 25  # half a second, the primary scale — the one used across all 54 clips
MULTI_SCALE = {"0.25s": 13, "0.5s": 25, "1.0s": 50}  # diagnostic, canonical clips only
SEED = 20260914
CONTROL_COUNT = 10
CONTROL_GAP = 3 * 50  # controls at least this many frames from any manual interval

# Reported, never picked. A change point is "large" at a threshold if its distance exceeds
# this multiple of the clip's own median step distance.
MULTIPLES = (1.5, 2.0, 2.5)
PRIMARY_MULTIPLE = 2.0

# How far past a change point a candidate neighbourhood extends, one side. Reported for all
# three; never chosen after seeing which recovers a particular clip's manual interval.
NEIGHBOURHOOD_SECONDS = (1, 2, 3)
TOP_K_VALUES = (1, 3, 5)


def cut_list(path: Path) -> dict[str, list[tuple[int, int]]]:
    out: dict[str, list[tuple[int, int]]] = {}
    for part in path.read_text().strip().split(";"):
        fields = part.split("|")
        if len(fields) < 5 or not fields[0].upper().endswith(".MP4"):
            continue
        clip, start, end, doubled, source = fields[:5]
        source, start, end = int(source), int(start), int(end)
        slowed = source > 0 and abs(int(doubled) - 2 * source) <= 8
        frames = max(1, (end - start) // (2 if slowed else 1))
        out.setdefault(clip, []).append((source, source + frames))
    return out


def dino_curve(capture, first: int, last: int, step: int, processor, model, torch) -> list[dict]:
    import cv2

    embeddings = {}
    for frame in range(max(0, first), last + 1, step):
        picture = frame_at(capture, frame, cv2)
        if picture is None:
            continue
        encoded = processor(images=[picture], return_tensors="pt")
        with torch.inference_mode():
            pooled = model(**encoded).pooler_output[0]
        embeddings[frame] = pooled / pooled.norm()
    frames = sorted(embeddings)
    points = []
    for a, b in pairwise(frames):
        distance = float(1.0 - (embeddings[a] @ embeddings[b]))
        points.append({"frame": b, "from": a, "distance": distance})
    return points


def top_k(curve: list[dict], k: int) -> list[dict]:
    return sorted(curve, key=lambda p: -p["distance"])[:k]


def neighbourhood(points: list[dict], seconds: int, fps: int = 50) -> list[tuple[int, int]]:
    span = seconds * fps
    windows = [(p["frame"] - span, p["frame"] + span) for p in points]
    windows.sort()
    merged: list[list[int]] = []
    for start, end in windows:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(a, b) for a, b in merged]


def overlaps(interval: tuple[int, int], windows: list[tuple[int, int]]) -> bool:
    a, b = interval
    return any(a < w[1] and b > w[0] for w in windows)


def local_max(curve: list[dict], centre: int, radius: int) -> float:
    nearby = [p["distance"] for p in curve if abs(p["frame"] - centre) <= radius]
    return max(nearby) if nearby else 0.0


def local_motion(database, project_id: str, clip_asset_id: str, frame: int, radius: int = 30):
    windows = asset_windows(database, project_id).get(clip_asset_id, ())
    near = [w.motion for w in windows if abs(w.asset_frame - frame) <= radius]
    return st.median(near) if near else None


def analyse_clip(clip: str, asset, cuts: list[tuple[int, int]], processor, model, torch,
                 database, project_id: str, rng: random.Random) -> dict | None:
    import cv2

    total_frames = asset.frame_rate.frames_from_seconds(asset.duration, rounding="floor")
    capture = cv2.VideoCapture(str(MEDIA / clip))
    try:
        curve = dino_curve(capture, 0, total_frames, STEP, processor, model, torch)
        if len(curve) < 4:
            return None
        baseline = st.median(p["distance"] for p in curve)

        controls = []
        guard = 0
        while len(controls) < CONTROL_COUNT and guard < 500:
            guard += 1
            pick = rng.randrange(0, max(1, total_frames))
            if all(abs(pick - c) >= CONTROL_GAP for start, end in cuts for c in (start, end)):
                controls.append(pick)

        manual_local = [local_max(curve, (a + b) // 2, 25) for a, b in cuts]
        manual_in_local = [local_max(curve, a, 25) for a, b in cuts]
        manual_out_local = [local_max(curve, b, 25) for a, b in cuts]
        control_local = [local_max(curve, c, 25) for c in controls]

        by_multiple = {}
        for multiple in MULTIPLES:
            points = [p for p in curve if p["distance"] > baseline * multiple]
            by_multiple[str(multiple)] = len(points)

        top_points = top_k(curve, max(TOP_K_VALUES))
        recall_by_k: dict[str, dict] = {}
        for k in TOP_K_VALUES:
            chosen = top_points[:k]
            recall_by_k[str(k)] = {}
            for seconds in NEIGHBOURHOOD_SECONDS:
                windows = neighbourhood(chosen, seconds)
                retained = sum(b - a for a, b in windows)
                hit = any(overlaps((a, b), windows) for a, b in cuts)
                recall_by_k[str(k)][str(seconds)] = {
                    "hit": hit,
                    "retained_frames": retained,
                    "retained_share": round(retained / total_frames, 4),
                }

        motions = []
        for point in top_points[:3]:
            m = local_motion(database, project_id, asset.id, point["frame"])
            motions.append(m)

        return {
            "total_frames": total_frames,
            "baseline_median": baseline,
            "cuts": cuts,
            "manual_local_max": manual_local,
            "manual_in_local_max": manual_in_local,
            "manual_out_local_max": manual_out_local,
            "control_positions": controls,
            "control_local_max": control_local,
            "spike_count_by_multiple": by_multiple,
            "top_points": top_points,
            "recall_by_k": recall_by_k,
            "top3_motion": motions,
            "curve_len": len(curve),
        }
    finally:
        capture.release()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compare", type=Path, required=True)
    parser.add_argument("--cuts", type=Path, required=True)
    parser.add_argument("--classes", type=Path, required=True)
    parser.add_argument("--shutter", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    import torch
    from transformers import AutoImageProcessor, AutoModel

    project_id = "df2a4a62-e821-40f7-86fc-b6a9259e9ee9"
    database = Database(database_path())
    assets = {a.name: a for a in project_assets(database, project_id)}
    names = sorted({row["clip"] for row in json.loads(args.compare.read_text())})
    cuts = cut_list(args.cuts)
    classes = json.loads(args.classes.read_text())
    shutter = json.loads(args.shutter.read_text())

    processor = AutoImageProcessor.from_pretrained("facebook/dinov2-base", local_files_only=True)
    model = AutoModel.from_pretrained("facebook/dinov2-base", local_files_only=True).eval()
    rng = random.Random(SEED)

    results = {}
    for index, clip in enumerate(names, 1):
        asset = assets.get(clip)
        if asset is None or clip not in cuts:
            continue
        result = analyse_clip(clip, asset, cuts[clip], processor, model, torch,
                              database, project_id, rng)
        if result is None:
            continue
        result["class"] = classes.get(clip, "CONTINUOUS_ACTION")
        mode, _exposure, _angle = shutter_mode(shutter.get(clip))
        result["shutter_mode"] = mode
        results[clip] = result
        print(f"{index:3d}/{len(names)}  {clip:12} {result['curve_len']:4d} points", flush=True)
        args.out.write_text(json.dumps(results, indent=1))

    args.out.write_text(json.dumps(results, indent=1))
    print(f"written {args.out}  {len(results)} clips")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
