"""Ask whether a motion burst is spread across the whole frame or sitting in one place.

The router's motion feature is a single number — the mean absolute difference between two
160x90 downscaled frames, exactly as `windows.py` computes it for production. A number that
size cannot tell a camera whipping the whole picture from a bride spinning inside an otherwise
still one; both can produce the same mean. This keeps the diff as a small 2D map instead of
collapsing it, using the identical 160x90 downscale so nothing about the underlying measurement
changes.

Two coarse readings off that map (coverage — the share of the map that changed by more than a
fixed fraction of its own peak; concentration — how much of the change sits in the single
most-changed ninth on a 3x3 grid) turned out not to separate anything: the confirmed whip-pan
and a genuine cake-cutting event score within a few points of each other on both, and
concentration barely varies across any candidate tried.

What does separate them is simpler: `center_border_ratio`, the mean change per pixel inside the
middle half of the frame divided by the mean change per pixel in the ring around it. One
is a physically motivated split, not a fitted one — a value under 1.0 means the border of the
frame is changing faster than its middle, which a subject moving in the middle of the frame
cannot produce and a camera sweep, or a shot boundary the scene detector missed, can. 1.0 is
the neutral point, chosen for being the point where the two halves move equally, not for
matching any candidate's score.

Read-only. No model of any kind; two frames per candidate, downscaled exactly as production
already does.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from semantic_probe import MEDIA, frame_at

STEP = 25  # the production window step, half a second
GRID = 3   # a 3x3 split of the 160x90 map — nine cells, one "most-changed" cell per candidate
COVERAGE_FRACTION = 0.25  # a cell counts as "changed" above this share of the map's own peak


def diff_map(before, after):
    import cv2
    import numpy as np

    def prep(picture):
        # frame_at hands back a PIL image (RGB, already gamma-lifted); convert to grey the same
        # way the production feature does, then match its 160x90 downscale exactly.
        grey = cv2.cvtColor(np.array(picture), cv2.COLOR_RGB2GRAY)
        return cv2.resize(grey, (160, 90)).astype("int16")

    return abs(prep(after) - prep(before))


def spatial_features(diff) -> dict:
    total = diff.sum()
    peak = diff.max()
    height, width = diff.shape
    if peak == 0 or total == 0:
        return {"coverage": 0.0, "concentration": 0.0, "mean": 0.0, "center_border_ratio": None}
    changed = (diff > COVERAGE_FRACTION * peak).mean()
    cell_h, cell_w = height // GRID, width // GRID
    cell_sums = []
    for row in range(GRID):
        for col in range(GRID):
            cell = diff[row * cell_h:(row + 1) * cell_h, col * cell_w:(col + 1) * cell_w]
            cell_sums.append(float(cell.sum()))
    top_cell_share = max(cell_sums) / total if total else 0.0

    # The middle half of the frame against the ring around it, each read as a per-pixel mean
    # so the two halves' different areas do not bias the comparison.
    cy0, cy1 = int(height * 0.25), int(height * 0.75)
    cx0, cx1 = int(width * 0.25), int(width * 0.75)
    centre_sum = float(diff[cy0:cy1, cx0:cx1].sum())
    centre_area = (cy1 - cy0) * (cx1 - cx0)
    border_sum = total - centre_sum
    border_area = height * width - centre_area
    centre_density = centre_sum / centre_area if centre_area else 0.0
    border_density = border_sum / border_area if border_area else 0.0
    ratio = (centre_density / border_density) if border_density else None

    return {"coverage": round(float(changed), 4), "concentration": round(top_cell_share, 4),
            "mean": round(float(diff.mean()), 3),
            "center_border_ratio": round(ratio, 3) if ratio is not None else None}


def audit(clip: str, peak_frame: int) -> dict:
    import cv2

    capture = cv2.VideoCapture(str(MEDIA / clip))
    try:
        before = frame_at(capture, max(0, peak_frame - STEP), cv2)
        after = frame_at(capture, peak_frame, cv2)
        if before is None or after is None:
            return {"error": "could not read frames"}
        diff = diff_map(before, after)
        return {"peak_frame": peak_frame, **spatial_features(diff)}
    finally:
        capture.release()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, required=True,
                        help='JSON {"clip.MP4": peak_frame, ...}')
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    candidates = json.loads(args.candidates.read_text())
    results = {}
    for clip, frame in candidates.items():
        results[clip] = audit(clip, frame)
        print(f"{clip:12} frame {frame:5d}  coverage {results[clip].get('coverage'):.3f}  "
              f"concentration {results[clip].get('concentration'):.3f}  "
              f"mean {results[clip].get('mean')}", flush=True)

    args.out.write_text(json.dumps(results, indent=1))
    print(f"\nwritten {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
