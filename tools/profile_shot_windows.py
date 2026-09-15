"""P4.1 — fine-grained per-operation profiling of `AssetWindowMeasurer.measure`, against the
same real P4 benchmark corpus. Read-only, no production DB, no mutation.

Instruments every named sub-operation (seek, decode, colour conversion, sharpness, face
detection, motion, resize) with its own wall-clock accounting, so the 70-second total can be
explained operation by operation rather than lumped as "decode+inference".
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Self

sys.path.insert(0, str(Path(__file__).parent.parent / "apps" / "api"))

from sevenfilm.domain import Shot
from sevenfilm.services.windows import (
    BYSTANDER_RATIO,
    BYSTANDER_SCORE,
    SHARPNESS_WIDTH,
    _face_framing,
)
from sevenfilm.timebase import FrameRate, TimeRange

TIMES: dict[str, list[float]] = defaultdict(list)


class _Timer:
    def __init__(self, name: str) -> None:
        self.name = name

    def __enter__(self) -> Self:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        TIMES[self.name].append(time.perf_counter() - self._start)


def _shot_from_row(row: dict) -> Shot:
    rate = FrameRate.parse(row["frame_rate"])
    return Shot(id=row["id"], asset_id=row["asset_id"],
                source_range=TimeRange(row["start_frame"], row["duration_frames"], rate))


def profile_asset(cv2, np, asset_path: Path, shots: list[Shot]) -> dict:
    from sevenfilm.services.windows import WINDOW_SECONDS

    model = Path(__file__).parent.parent / "apps" / "api" / "sevenfilm" / "models" / \
        "face_detection_yunet_2023mar.onnx"

    with _Timer("open_capture"):
        capture = cv2.VideoCapture(str(asset_path))
    if not capture.isOpened():
        return {}
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    with _Timer("detector_create"):
        detector = cv2.FaceDetectorYN.create(
            str(model), "", (width, height),
            score_threshold=BYSTANDER_SCORE, nms_threshold=0.3)

    previous = None
    windows_seen = 0
    for shot in shots:
        rate = shot.source_range.rate
        step = max(1, rate.frames_from_seconds(WINDOW_SECONDS, rounding="nearest"))
        for offset in range(0, shot.source_range.duration_frames, step):
            with _Timer("seek"):
                capture.set(cv2.CAP_PROP_POS_FRAMES, shot.source_range.start_frame + offset)
            with _Timer("decode_read"):
                ok, frame = capture.read()
            if not ok or frame is None:
                break
            with _Timer("color_convert_grey"):
                grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            with _Timer("sharpness"):
                h, w = grey.shape[:2]
                measured = grey
                if w > SHARPNESS_WIDTH:
                    scale = SHARPNESS_WIDTH / w
                    measured = cv2.resize(grey, (SHARPNESS_WIDTH, max(1, round(h * scale))),
                                          interpolation=cv2.INTER_AREA)
                float(cv2.Laplacian(measured, cv2.CV_64F).var())
            with _Timer("face_detect"):
                _ok, detected = detector.detect(frame)
            faces = list(detected) if detected is not None else []
            if faces:
                with _Timer("face_framing"):
                    largest = max(faces, key=lambda box: box[2] * box[3])
                    _face_framing(largest, width, height)
                    area = float(largest[2] * largest[3])
                    sum(1 for box in faces if float(box[2] * box[3]) < area * BYSTANDER_RATIO)
            with _Timer("motion_resize_and_diff"):
                small = cv2.resize(grey, (160, 90)).astype(np.int16)
                if previous is not None:
                    float(np.abs(small - previous).mean())
                previous = small
            windows_seen += 1
    capture.release()
    return {"windows": windows_seen}


def summarize(name: str) -> dict:
    values = TIMES.get(name, [])
    if not values:
        return {"count": 0, "total": 0, "mean": 0, "median": 0, "p90": 0, "p99": 0, "max": 0}
    ordered = sorted(values)

    def pct(p: float) -> float:
        return ordered[min(len(ordered) - 1, int(len(ordered) * p))]

    return {
        "count": len(values), "total": round(sum(values), 4),
        "mean": round(statistics.mean(values), 5), "median": round(statistics.median(values), 5),
        "p90": round(pct(0.90), 5), "p99": round(pct(0.99), 5), "max": round(max(values), 5),
    }


def main() -> int:
    import cv2  # type: ignore[import-not-found]
    import numpy as np

    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text())
    wall_started = time.perf_counter()
    total_windows = 0
    for entry in manifest:
        shots = [_shot_from_row(row) for row in entry["shots"]]
        result = profile_asset(cv2, np, Path(entry["path"]), shots)
        total_windows += result.get("windows", 0)
    wall_total = time.perf_counter() - wall_started

    ops = ["open_capture", "detector_create", "seek", "decode_read", "color_convert_grey",
           "sharpness", "face_detect", "face_framing", "motion_resize_and_diff"]
    breakdown = {op: summarize(op) for op in ops}
    accounted = sum(breakdown[op]["total"] for op in ops)

    report = {
        "wall_total_seconds": round(wall_total, 3),
        "total_windows": total_windows,
        "accounted_seconds": round(accounted, 3),
        "unaccounted_seconds": round(wall_total - accounted, 3),
        "breakdown": breakdown,
    }
    text = json.dumps(report, indent=2)
    if args.out:
        args.out.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
