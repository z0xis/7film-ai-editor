"""Frozen P6.29 shadow pass over P6.20, followed by a V7 post-hoc comparison.

Only local 15A proxies and a read-only SQLite connection are opened.  V7 is loaded after every
source-in decision has been frozen and is used only by `_v7_benchmark`.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import statistics as st
import sys
from collections import Counter
from itertools import pairwise
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from sevenfilm.services.action_start_shadow import (
    TemporalEvidence,
    candidate_starts,
    rank_cut_in,
)
from sevenfilm.services.stability import (
    StabilityVerdict,
    measure_camera_stability,
)

DB = ROOT / "data" / "sevenfilm.sqlite3"
MANIFEST = ROOT / "tools" / "fixtures" / "p6_20_candidate_manifest.json"
V7 = ROOT / "data" / "reference_editor" / "raw" / "v7_trace.json"
OUT = ROOT / "tools" / "fixtures" / "p6_29_action_start_shadow.json"
STILL_CATEGORIES = {"detail", "venue"}


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _read_range(path: str, first: int, last: int, fps: float) -> tuple[list[int], list[np.ndarray]]:
    capture = cv2.VideoCapture(path)
    step = max(1, round(fps / 10))
    capture.set(cv2.CAP_PROP_POS_FRAMES, first)
    indexes, frames = [], []
    for frame_index in range(first, last + 1):
        ok, frame = capture.read()
        if not ok:
            break
        if (frame_index - first) % step == 0 or frame_index == last:
            indexes.append(frame_index)
            frames.append(cv2.resize(frame, (320, 180), interpolation=cv2.INTER_AREA))
    capture.release()
    return indexes, frames


def _nearest(indexes: list[int], frames: list[np.ndarray], target: int) -> np.ndarray:
    return frames[min(range(len(indexes)), key=lambda idx: abs(indexes[idx] - target))]


def _sharpness(frame: np.ndarray) -> float:
    return float(cv2.Laplacian(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())


def _face(detector, frame: np.ndarray) -> tuple[float, float]:
    _ok, faces = detector.detect(frame)
    if faces is None:
        return 0.0, 1.0
    x, y, width, height = max(faces, key=lambda item: item[2] * item[3])[:4]
    ratio = float(width * height / (frame.shape[0] * frame.shape[1]))
    gap = min(x, y, frame.shape[1] - x - width, frame.shape[0] - y - height)
    edge = _clamp(1 - gap / 12)
    return ratio, edge


def _local_motion(frames: list[np.ndarray]) -> float:
    values = []
    for first, second in pairwise(frames):
        a, b = cv2.cvtColor(first, cv2.COLOR_BGR2GRAY), cv2.cvtColor(second, cv2.COLOR_BGR2GRAY)
        points = cv2.goodFeaturesToTrack(a, 180, .01, 6)
        if points is None:
            continue
        moved, status, _error = cv2.calcOpticalFlowPyrLK(a, b, points, None)
        if moved is None or status is None:
            continue
        keep = status.reshape(-1).astype(bool)
        matrix, _mask = cv2.estimateAffinePartial2D(points.reshape(-1, 2)[keep],
                                                    moved.reshape(-1, 2)[keep],
                                                    method=cv2.RANSAC)
        if matrix is None:
            continue
        warped = cv2.warpAffine(a, matrix, (a.shape[1], a.shape[0]))
        values.append(float(cv2.absdiff(warped, b).mean()))
    return st.median(values) if values else 0.0


def _continuity(first: np.ndarray, second: np.ndarray) -> float:
    histograms = []
    for frame in (first, second):
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [24, 24], [0, 180, 0, 256])
        histograms.append(cv2.normalize(hist, hist).flatten())
    return _clamp((cv2.compareHist(histograms[0], histograms[1], cv2.HISTCMP_CORREL) + 1) / 2)


def _evidence(starts, indexes, frames, fps, detector) -> tuple[TemporalEvidence, ...]:
    all_sharp = [_sharpness(frame) for frame in frames]
    sharp_bar = max(1.0, float(np.percentile(all_sharp, 75)))
    result = []
    for start in starts:
        pre = [_nearest(indexes, frames, start - round(fps * delta)) for delta in (.4, .3, .2, .1)]
        post = [_nearest(indexes, frames, start + round(fps * delta))
                for delta in (0, .1, .2, .3, .4, .5, .6)]
        face_values = [_face(detector, frame) for frame in post]
        ratios, edges = zip(*face_values, strict=True)
        post_sharp = st.median(_sharpness(frame) for frame in post)
        baseline_motion, post_motion = _local_motion(pre), _local_motion(post)
        stability = measure_camera_stability(post)
        settle = .5
        if stability.verdict == StabilityVerdict.STABLE:
            settle = _clamp(1 - stability.jitter / 8)
        elif stability.verdict == StabilityVerdict.UNSTABLE:
            settle = 0.0
        readiness = .5 if not any(ratios) else _clamp(.65 * (st.median(ratios) / .035)
                                                       + .35 * (1 - st.median(edges)))
        action = _clamp((post_motion - baseline_motion * .7) / 12)
        technical = _clamp(post_sharp / sharp_bar)
        obstruction = _clamp(.6 * technical + .4 * (1 - st.median(edges)))
        confidence = _clamp(len(set(indexes)) / 12) * (.8 if stability.verdict == StabilityVerdict.UNKNOWN else 1)
        result.append(TemporalEvidence(
            start_frame=start, subject_readiness=readiness, action_onset=action,
            camera_settle=settle, technical_usability=technical,
            obstruction_clearance=obstruction,
            semantic_continuity=_continuity(post[0], post[-1]), confidence=confidence))
    return tuple(result)


def _v7_benchmark(rows: list[dict], shots: dict[str, sqlite3.Row]) -> dict:
    trace = json.loads(V7.read_text())
    human: dict[str, list[int]] = {}
    for name, _tl_start, _duration, source_in in trace["items"]:
        human.setdefault(name, []).append(source_in)
    mapped = []
    for row in rows:
        shot = shots[row["shot_id"]]
        refs = [value for value in human.get(row["source_name"], [])
                if shot["start_frame"] <= value < shot["start_frame"] + shot["duration_frames"]]
        if not refs:
            continue
        reference = min(refs, key=lambda value: abs(value - row["original_start"]))
        effective = row["proposed_start"] or row["original_start"]
        baseline_error, proposal_error = abs(row["original_start"] - reference), abs(effective - reference)
        mapped.append((baseline_error, proposal_error))
    return {
        "method_frozen_first": True, "mapped_items": len(mapped),
        "closer": sum(after < before for before, after in mapped),
        "farther": sum(after > before for before, after in mapped),
        "unchanged": sum(after == before for before, after in mapped),
        "baseline_median_frames": st.median(x[0] for x in mapped) if mapped else None,
        "proposal_median_frames": st.median(x[1] for x in mapped) if mapped else None,
    }


def run() -> dict:
    before = _hash(DB)
    manifest = json.loads(MANIFEST.read_text())
    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    assets = {row["id"]: row for row in connection.execute(
        "SELECT id, proxy_path FROM media_assets")}
    shots = {row["id"]: row for row in connection.execute(
        "SELECT id, start_frame, duration_frames, category, frame_rate FROM shots")}
    connection.close()
    model = ROOT / "apps" / "api" / "sevenfilm" / "models" / "face_detection_yunet_2023mar.onnx"
    detector = cv2.FaceDetectorYN.create(str(model), "", (320, 180), score_threshold=.6)
    rows = []
    for item in manifest["items"]:
        shot = shots[item["shot_id"]]
        numerator, denominator = map(int, shot["frame_rate"].split("/"))
        fps = numerator / denominator
        shot_end = shot["start_frame"] + shot["duration_frames"]
        starts = candidate_starts(original_start=item["src_start_frame"], shot_end=shot_end,
                                  required_source_frames=item["src_dur_frames"], fps=fps)
        if not starts:
            evidence = ()
        else:
            indexes, frames = _read_range(assets[item["asset_id"]]["proxy_path"],
                                          max(shot["start_frame"], starts[0] - round(.5 * fps)),
                                          min(shot_end - 1, starts[-1] + round(.7 * fps)), fps)
            evidence = _evidence(starts, indexes, frames, fps, detector) if len(frames) >= 7 else ()
        decision = rank_cut_in(original_start=item["src_start_frame"], evidence=evidence,
                               intentional_still=shot["category"] in STILL_CATEGORIES)
        rows.append({
            "shot_id": item["shot_id"], "source_name": item["source_name"],
            "timeline_start_s": round(item["tl_start_frame"] / manifest["rate"], 2),
            "original_start": decision.original_start,
            "proposed_start": decision.proposed_start, "delta_frames": decision.delta_frames,
            "delta_s": round(decision.delta_frames / fps, 3), "verdict": decision.verdict.value,
            "confidence": decision.confidence, "components": decision.components,
            "reason": decision.reason, "speed": item["speed"],
        })
    counts = Counter(row["verdict"] for row in rows)
    trims = sorted((row for row in rows if row["verdict"] == "TRIM_PROPOSAL"),
                   key=lambda row: (-row["confidence"], -row["delta_frames"]))
    deltas = sorted(row["delta_s"] for row in trims)
    after = _hash(DB)
    result = {
        "p6_20_plan_hash": manifest["plan_hash"], "items": len(rows),
        "verdict_counts": dict(sorted(counts.items())),
        "trim_delta_s": {"median": st.median(deltas) if deltas else None,
                           "p90": deltas[math.floor(.9 * (len(deltas) - 1))] if deltas else None,
                           "max": max(deltas) if deltas else None},
        "top_trim_proposals": trims[:12], "rows": rows,
        "v7_posthoc": _v7_benchmark(rows, shots),
        "c7309": {"v7_human_action_start": 3332,
                   "scope_note": "different detected shot/phase; P6.29 never replaces selected shot",
                   "p6_20_rows": [row for row in rows if row["source_name"] == "C7309.MP4"]},
        "db_unchanged": before == after, "db_sha256": before,
        "resolve_calls": 0, "timeline_writes": 0, "build_timeline_changes": 0,
    }
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    report = run()
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}, indent=2))
