"""P4.1.7 — compare random-seek vs sequential-decode strategies for reaching the same exact
target frames, on real 15 Ağustos footage. Read-only.

STRATEGY A (current production): cap.set(CAP_PROP_POS_FRAMES, target) then cap.read() for
every target, regardless of gap.

STRATEGY C (hybrid): if the gap since the last decoded frame position is small, decode forward
frame-by-frame with cap.grab() up to the target, then cap.retrieve(); otherwise seek. Falls
back to a seek whenever the position is not what was expected (first frame, or a gap too large
to be worth walking).

Frame identity is verified, not assumed: every returned frame's checksum is recorded, and the
two strategies' checksums are compared frame-for-frame at the end.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "apps" / "api"))

from sevenfilm.domain import Shot
from sevenfilm.services.windows import WINDOW_SECONDS
from sevenfilm.timebase import FrameRate, TimeRange


def _shot_from_row(row: dict) -> Shot:
    rate = FrameRate.parse(row["frame_rate"])
    return Shot(id=row["id"], asset_id=row["asset_id"],
                source_range=TimeRange(row["start_frame"], row["duration_frames"], rate))


def _targets(shots: list[Shot]) -> list[int]:
    targets: list[int] = []
    for shot in shots:
        rate = shot.source_range.rate
        step = max(1, rate.frames_from_seconds(WINDOW_SECONDS, rounding="nearest"))
        for offset in range(0, shot.source_range.duration_frames, step):
            targets.append(shot.source_range.start_frame + offset)
    return targets


def _checksum(frame) -> str:
    return hashlib.sha1(frame.tobytes()).hexdigest()[:12]


def strategy_seek(cv2, path: Path, targets: list[int]) -> tuple[float, list[str]]:
    capture = cv2.VideoCapture(str(path))
    checksums = []
    started = time.perf_counter()
    for target in targets:
        capture.set(cv2.CAP_PROP_POS_FRAMES, target)
        ok, frame = capture.read()
        checksums.append(_checksum(frame) if ok and frame is not None else "MISS")
    elapsed = time.perf_counter() - started
    capture.release()
    return elapsed, checksums


def strategy_hybrid(cv2, path: Path, targets: list[int], max_walk: int) -> tuple[float, list[str]]:
    capture = cv2.VideoCapture(str(path))
    checksums = []
    position = None  # frame index that will be returned by the *next* read/retrieve
    started = time.perf_counter()
    for target in targets:
        gap = None if position is None else target - position
        if gap is not None and 0 <= gap <= max_walk:
            for _ in range(gap):
                capture.grab()
            ok, frame = capture.read()
        else:
            capture.set(cv2.CAP_PROP_POS_FRAMES, target)
            ok, frame = capture.read()
        checksums.append(_checksum(frame) if ok and frame is not None else "MISS")
        position = target + 1 if ok else None
    elapsed = time.perf_counter() - started
    capture.release()
    return elapsed, checksums


def main() -> int:
    import cv2  # type: ignore[import-not-found]

    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--max-walk", type=int, default=150)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text())
    results = []
    for entry in manifest:
        shots = [_shot_from_row(row) for row in entry["shots"]]
        targets = _targets(shots)
        seek_time, seek_sums = strategy_seek(cv2, Path(entry["path"]), targets)
        hybrid_time, hybrid_sums = strategy_hybrid(cv2, Path(entry["path"]), targets, args.max_walk)
        identical = seek_sums == hybrid_sums
        results.append({
            "path": entry["path"], "targets": len(targets),
            "seek_seconds": round(seek_time, 3), "hybrid_seconds": round(hybrid_time, 3),
            "identical_frames": identical,
            "mismatches": [] if identical else [
                i for i, (a, b) in enumerate(zip(seek_sums, hybrid_sums)) if a != b],
        })
        print(json.dumps(results[-1], indent=2))

    total_seek = sum(r["seek_seconds"] for r in results)
    total_hybrid = sum(r["hybrid_seconds"] for r in results)
    all_identical = all(r["identical_frames"] for r in results)
    print(json.dumps({
        "total_seek_seconds": round(total_seek, 3),
        "total_hybrid_seconds": round(total_hybrid, 3),
        "all_frames_identical": all_identical,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
