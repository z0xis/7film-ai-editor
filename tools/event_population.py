"""Narrow a coarse scene run to the few seconds that are actually the event inside it.

Last round found that "cutting" is a scene label, not an event label: SmolVLM calls a couple
standing near a cake "cutting" almost as readily as it calls the actual cut that, so a keyword
run built from a 2-second identity scan came out 78 seconds wide, fifty-two times the real
event. This round asks what narrows that — and, per this round's brief, it may not be the
state probe that was used to evaluate the earlier result, because using the evaluation signal
to do the discovery would not be a separate finding.

Two things are tried, both already in the project's cache, neither downloaded for this:

  DENSE IDENTITY   the same free-text question SmolVLM was already asked, at ten times the
                   sampling rate, to see whether the caption itself starts to vary once it is
                   asked often enough — or whether it really is one scene label the whole way
                   through, which is a different, useful finding on its own
  CHANGE-POINT     DINOv2's own pooled embedding, one per sampled frame, read as a distance to
                   its neighbour — a purely visual signal with no language and no editorial
                   framing, looking for where the picture itself changes rather than where a
                   caption changes

Neither is optimised against the manual answer: gap thresholds are reported as a sensitivity
table across four fixed values, never picked after looking, and the change-point rule is one
fixed multiple of the clip's own median step-to-step distance, read off the clip being measured
rather than written in here as a number.

Manual timing is read only in the report this produces, never inside this file's own logic.

Read-only. No model is downloaded; DINOv2 and CLIP were already cached for earlier rounds.
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from itertools import pairwise
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from event_pipeline import free_text, keyword
from semantic_probe import MEDIA, Probe, frame_at

STEP = 25  # half a second, the grid every other measurement in this project uses

# The dense second pass runs at ten times the original sparse rate on each clip, bounded so a
# whole-file rescan stays affordable: a fifth of a second on the 78-second coarse run (fixed
# before it was seen how far that would carry), a tenth of a second on the 10.6-second clip,
# where the earlier round's miss was a matter of a few frames and only a short clip needs to be
# resampled that fine to afford it.
DENSE_GAP = {"C2075.MP4": STEP // 2, "C1987.MP4": 5}

IDENTITY_PROMPT = ("In a few words, what is the one most distinct thing a person is doing in "
                   "this picture?")

# Fixed before any clip in this round was looked at. Reported as a sensitivity table, never
# picked after seeing which one narrows a particular clip best.
GAP_THRESHOLDS_SECONDS = (0.5, 1.0, 2.0, 4.0)

# How far past a change-point candidate's own step the rule is willing to call it "large": a
# fixed multiple of the clip's own median neighbour-to-neighbour distance, read off the clip
# rather than written as an absolute number here.
CHANGE_MULTIPLE = 2.0


def dense_identity_scan(probe: Probe, capture, first: int, last: int, gap: int) -> list[dict]:
    import cv2

    samples = []
    for frame in range(max(0, first), last + 1, gap):
        picture = frame_at(capture, frame, cv2)
        if picture is None:
            continue
        description = free_text(probe, picture, IDENTITY_PROMPT, words=16)
        samples.append({"frame": frame, "description": description, "keyword": keyword(description)})
    return samples


def dino_embeddings(capture, frames: list[int], processor, model, torch):
    import cv2

    out = {}
    for frame in frames:
        picture = frame_at(capture, frame, cv2)
        if picture is None:
            continue
        encoded = processor(images=[picture], return_tensors="pt")
        with torch.inference_mode():
            pooled = model(**encoded).pooler_output[0]
        norm = pooled / pooled.norm()
        out[frame] = norm
    return out


def change_curve(embeddings: dict[int, object]) -> list[dict]:
    frames = sorted(embeddings)
    points = []
    for a, b in pairwise(frames):
        distance = float(1.0 - (embeddings[a] @ embeddings[b]))
        points.append({"frame": b, "distance": distance, "from": a})
    return points


def change_points(curve: list[dict], multiple: float) -> list[int]:
    if not curve:
        return []
    baseline = st.median(p["distance"] for p in curve)
    if baseline <= 0:
        return []
    return [p["frame"] for p in curve if p["distance"] > baseline * multiple]


def gap_cluster(frames: list[int], gap_frames: int) -> list[tuple[int, int]]:
    """Contiguous runs of frames no further apart than `gap_frames`, purely by source time."""
    if not frames:
        return []
    ordered = sorted(frames)
    runs = [[ordered[0]]]
    for frame in ordered[1:]:
        if frame - runs[-1][-1] <= gap_frames:
            runs[-1].append(frame)
        else:
            runs.append([frame])
    return [(run[0], run[-1]) for run in runs]


def sensitivity_table(positive_frames: list[int], fps: int) -> dict:
    table = {}
    for seconds in GAP_THRESHOLDS_SECONDS:
        runs = gap_cluster(positive_frames, int(seconds * fps))
        table[str(seconds)] = {
            "run_count": len(runs),
            "runs": runs,
            "widest_seconds": round(max((b - a) / fps for a, b in runs), 2) if runs else 0,
            "median_seconds": (round(st.median([(b - a) / fps for a, b in runs]), 2)
                              if runs else 0),
        }
    return table


def analyse_clip(probe: Probe, dino_processor, dino_model, torch_module, clip: str,
                 scan_first: int, scan_last: int, target_keyword: str, fps: int = 50) -> dict:
    import cv2

    capture = cv2.VideoCapture(str(MEDIA / clip))
    try:
        dense = dense_identity_scan(probe, capture, scan_first, scan_last, DENSE_GAP[clip])
        positives = [s["frame"] for s in dense if s["keyword"] == target_keyword]

        distinct_keywords = sorted({s["keyword"] for s in dense})
        keyword_share = {
            kw: round(sum(1 for s in dense if s["keyword"] == kw) / len(dense), 3)
            for kw in distinct_keywords
        } if dense else {}

        embeddings = dino_embeddings(
            capture, list(range(scan_first, scan_last + 1, STEP)),
            dino_processor, dino_model, torch_module)
        curve = change_curve(embeddings)
        boundaries = change_points(curve, CHANGE_MULTIPLE)

        table = sensitivity_table(positives, fps)
    finally:
        capture.release()
    return {
        "scan_range": [scan_first, scan_last],
        "dense_samples": dense,
        "distinct_keywords": distinct_keywords,
        "keyword_share": keyword_share,
        "target_keyword": target_keyword,
        "positive_frames": positives,
        "gap_sensitivity": table,
        "change_curve": curve,
        "change_boundaries": boundaries,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    import torch
    from transformers import AutoImageProcessor, AutoModel

    probe = Probe()
    dino_processor = AutoImageProcessor.from_pretrained(
        "facebook/dinov2-base", local_files_only=True)
    dino_model = AutoModel.from_pretrained("facebook/dinov2-base", local_files_only=True).eval()

    results = {}
    print("C2075.MP4 — dense rescan of the coarse 'cutting' run (0-4400)")
    results["C2075.MP4"] = analyse_clip(
        probe, dino_processor, dino_model, torch, "C2075.MP4", 0, 4400, "cutting")
    args.out.write_text(json.dumps(results, indent=1))
    print("  done")

    print("C1987.MP4 — dense rescan of the whole clip (0-528)")
    results["C1987.MP4"] = analyse_clip(
        probe, dino_processor, dino_model, torch, "C1987.MP4", 0, 528, "kissing")
    args.out.write_text(json.dumps(results, indent=1))
    print("  done")

    print(f"written {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
