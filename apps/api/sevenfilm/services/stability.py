"""Conservative temporal camera-stability measurement.

This module is deliberately not wired into the production planner.  It estimates the global
camera transform between adjacent frames and asks whether the trajectory contains repeated,
high-frequency direction changes.  Smooth pans and tilts therefore remain usable even when their
total motion is large.  Weak/ambiguous tracks abstain instead of rejecting a shot.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise

import cv2  # type: ignore[import-not-found]
import numpy as np


class StabilityVerdict(StrEnum):
    STABLE = "stable"
    REVIEW = "review"
    UNSTABLE = "unstable"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class StabilityResult:
    verdict: StabilityVerdict
    confidence: float
    jitter: float
    rotation_jitter: float
    direction_reversal_rate: float
    valid_pairs: int
    total_pairs: int
    median_inlier_ratio: float
    reason: str


def _gray(frame: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    return cv2.resize(gray, size, interpolation=cv2.INTER_AREA)


def _global_steps(frames: list[np.ndarray], size: tuple[int, int]) -> tuple[list[np.ndarray], list[float]]:
    steps: list[np.ndarray] = []
    inliers: list[float] = []
    for first, second in pairwise(frames):
        a, b = _gray(first, size), _gray(second, size)
        points = cv2.goodFeaturesToTrack(a, 240, 0.01, 7, blockSize=7)
        if points is None or len(points) < 18:
            continue
        moved, status, _error = cv2.calcOpticalFlowPyrLK(
            a, b, points, None, winSize=(21, 21), maxLevel=3,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
        )
        if moved is None or status is None:
            continue
        keep = status.reshape(-1).astype(bool)
        source, target = points.reshape(-1, 2)[keep], moved.reshape(-1, 2)[keep]
        if len(source) < 15:
            continue
        matrix, mask = cv2.estimateAffinePartial2D(
            source, target, method=cv2.RANSAC, ransacReprojThreshold=2.0,
            maxIters=1000, confidence=0.995, refineIters=10,
        )
        if matrix is None or mask is None:
            continue
        ratio = float(mask.mean())
        if ratio < 0.45:
            continue
        rotation = math.degrees(math.atan2(float(matrix[1, 0]), float(matrix[0, 0])))
        steps.append(np.array([float(matrix[0, 2]), float(matrix[1, 2]), rotation]))
        inliers.append(ratio)
    return steps, inliers


def measure_camera_stability(
    frames: list[np.ndarray], *, analysis_size: tuple[int, int] = (320, 180)
) -> StabilityResult:
    """Classify only high-confidence shake; otherwise retain or abstain.

    Frames should be temporally dense and evenly spaced (roughly 8-15 fps).  Translation jerk is
    normalized by frame diagonal, making the thresholds resolution-independent.  Repeated velocity
    reversals distinguish shake from a smooth intentional pan/tilt.
    """
    total = max(0, len(frames) - 1)
    if len(frames) < 7:
        return StabilityResult(StabilityVerdict.UNKNOWN, 0.0, 0.0, 0.0, 0.0, 0, total, 0.0,
                               "too_few_temporal_frames")
    steps, inliers = _global_steps(frames, analysis_size)
    valid = len(steps)
    coverage = valid / total if total else 0.0
    median_inlier = float(np.median(inliers)) if inliers else 0.0
    if valid < 6 or coverage < 0.65 or median_inlier < 0.55:
        return StabilityResult(StabilityVerdict.UNKNOWN, round(coverage * median_inlier, 3),
                               0.0, 0.0, 0.0, valid, total, round(median_inlier, 3),
                               "insufficient_global_track")

    trajectory = np.cumsum(np.asarray(steps), axis=0)
    velocity = np.diff(trajectory, axis=0)
    acceleration = np.diff(velocity, axis=0)
    diagonal = math.hypot(*analysis_size)
    translation_jerk = np.linalg.norm(acceleration[:, :2], axis=1) / diagonal * 1000.0
    rotation_jerk = np.abs(acceleration[:, 2])
    jitter = float(np.percentile(translation_jerk, 75)) if len(translation_jerk) else 0.0
    rot_jitter = float(np.percentile(rotation_jerk, 75)) if len(rotation_jerk) else 0.0

    translations = velocity[:, :2]
    dots = np.sum(translations[1:] * translations[:-1], axis=1)
    magnitudes = np.linalg.norm(translations[1:], axis=1) * np.linalg.norm(translations[:-1], axis=1)
    meaningful = magnitudes > (0.0015 * diagonal) ** 2
    reversal = float(np.mean(dots[meaningful] < -0.25 * magnitudes[meaningful])) if meaningful.any() else 0.0

    confidence = min(1.0, coverage * median_inlier * 1.35)
    # Precision-first: both substantial jerk and repeated direction reversals are required.
    if confidence >= 0.72 and jitter >= 8.0 and reversal >= 0.28:
        verdict, reason = StabilityVerdict.UNSTABLE, "high_frequency_global_shake"
    elif jitter <= 3.0 and rot_jitter <= 0.18:
        verdict, reason = StabilityVerdict.STABLE, "smooth_global_trajectory"
    else:
        verdict, reason = StabilityVerdict.REVIEW, "ambiguous_camera_motion"
    return StabilityResult(verdict, round(confidence, 3), round(jitter, 3),
                           round(rot_jitter, 3), round(reversal, 3), valid, total,
                           round(median_inlier, 3), reason)
