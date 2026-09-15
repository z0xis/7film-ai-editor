"""P4 — deterministic benchmark for `measure_windows`, against a fixed, small real-footage
corpus (see `p4_benchmark_manifest.json`). Read-only: opens real source files for decode, never
writes to them, never touches the production database.

Counts VideoCapture constructions, seeks (`.set(CAP_PROP_POS_FRAMES, ...)`), and frame reads
(`.read()`) by wrapping the real `cv2.VideoCapture` class, so the operation counts this reports
are exact, not estimated.

Usage:
    python tools/benchmark_shot_windows.py <manifest.json> [--out results.json]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "apps" / "api"))

from sevenfilm.domain import MediaAsset, Shot
from sevenfilm.services import windows as windows_module
from sevenfilm.timebase import FrameRate, TimeRange


class _Counters:
    opens = 0
    seeks = 0
    reads = 0
    detector_inits = 0


def _install_counting_capture(cv2):
    real_capture = cv2.VideoCapture
    real_set = real_capture.set
    real_read = real_capture.read

    class CountingCapture(real_capture):
        def __init__(self, *args, **kwargs):
            _Counters.opens += 1
            super().__init__(*args, **kwargs)

        def set(self, *args, **kwargs):
            _Counters.seeks += 1
            return real_set(self, *args, **kwargs)

        def read(self, *args, **kwargs):
            _Counters.reads += 1
            return real_read(self, *args, **kwargs)

    cv2.VideoCapture = CountingCapture

    if hasattr(cv2, "FaceDetectorYN"):
        real_create = cv2.FaceDetectorYN.create

        def counting_create(*args, **kwargs):
            _Counters.detector_inits += 1
            return real_create(*args, **kwargs)

        cv2.FaceDetectorYN.create = staticmethod(counting_create)


def _load_manifest(path: Path) -> list[dict]:
    return json.loads(path.read_text())


def _shot_from_row(row: dict) -> Shot:
    rate = FrameRate.parse(row["frame_rate"])
    return Shot(
        id=row["id"], asset_id=row["asset_id"],
        source_range=TimeRange(row["start_frame"], row["duration_frames"], rate),
    )


def run(manifest_path: Path, mode: str = "baseline") -> dict:
    import cv2  # type: ignore[import-not-found]

    _install_counting_capture(cv2)

    manifest = _load_manifest(manifest_path)
    per_shot_seconds: list[float] = []
    per_asset: list[dict] = []
    total_windows = 0
    started = time.perf_counter()

    for entry in manifest:
        asset_path = Path(entry["path"])
        asset = MediaAsset(
            id=entry["asset_id"], project_id="benchmark", path=asset_path, name=asset_path.name,
            duration=0, frame_rate=FrameRate.parse(entry["shots"][0]["frame_rate"]),
            width=0, height=0,
        )
        asset_started = time.perf_counter()
        asset_windows = 0
        if mode == "grouped":
            # The production path since P4: one AssetWindowMeasurer per asset, reused across
            # every shot of it -- the same measurement, shared open file and detector.
            with windows_module.AssetWindowMeasurer(asset) as measurer:
                for row in entry["shots"]:
                    shot = _shot_from_row(row)
                    shot_started = time.perf_counter()
                    result = measurer.measure(shot)
                    per_shot_seconds.append(time.perf_counter() - shot_started)
                    asset_windows += len(result)
        else:
            # The pre-P4 path: a fresh VideoCapture and a fresh face detector per shot.
            for row in entry["shots"]:
                shot = _shot_from_row(row)
                shot_started = time.perf_counter()
                result = windows_module.measure_windows(asset, shot, asset.path)
                per_shot_seconds.append(time.perf_counter() - shot_started)
                asset_windows += len(result)
        per_asset.append({
            "path": str(asset_path), "shots": len(entry["shots"]),
            "windows": asset_windows, "seconds": round(time.perf_counter() - asset_started, 3),
        })
        total_windows += asset_windows

    total_seconds = time.perf_counter() - started

    def pct(data: list[float], p: float) -> float:
        if not data:
            return 0.0
        ordered = sorted(data)
        idx = min(len(ordered) - 1, int(len(ordered) * p))
        return ordered[idx]

    return {
        "total_seconds": round(total_seconds, 3),
        "total_shots": len(per_shot_seconds),
        "total_windows": total_windows,
        "per_shot_seconds": {
            "min": round(min(per_shot_seconds), 4) if per_shot_seconds else 0,
            "median": round(statistics.median(per_shot_seconds), 4) if per_shot_seconds else 0,
            "mean": round(statistics.mean(per_shot_seconds), 4) if per_shot_seconds else 0,
            "p90": round(pct(per_shot_seconds, 0.90), 4),
            "p99": round(pct(per_shot_seconds, 0.99), 4),
            "max": round(max(per_shot_seconds), 4) if per_shot_seconds else 0,
        },
        "operation_counts": {
            "video_capture_opens": _Counters.opens,
            "seeks": _Counters.seeks,
            "frame_reads": _Counters.reads,
            "face_detector_inits": _Counters.detector_inits,
        },
        "per_asset": per_asset,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--mode", choices=["baseline", "grouped"], default="baseline")
    args = parser.parse_args()
    result = run(args.manifest, mode=args.mode)
    text = json.dumps(result, indent=2)
    if args.out:
        args.out.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
