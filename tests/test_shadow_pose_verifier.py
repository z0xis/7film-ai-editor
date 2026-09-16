import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from shadow_pose_verifier import (
    KEYPOINT_SCORE_THRESHOLDS,
    MIN_USABLE_KEYPOINTS,
    ORIENTATION_COMPATIBLE_DEG,
    body_scale,
    phase1_recall,
    phase2_geometry,
    torso_orientation_deg,
    usable_keypoint_count,
)


def _kps(shoulder_l=(10, 10, 0.9), shoulder_r=(30, 10, 0.9), hip_l=(10, 40, 0.9), hip_r=(30, 40, 0.9)):
    kps = [[0, 0, 0.0]] * 17
    kps[5] = list(shoulder_l)
    kps[6] = list(shoulder_r)
    kps[11] = list(hip_l)
    kps[12] = list(hip_r)
    return kps


def test_frozen_thresholds_unchanged():
    assert KEYPOINT_SCORE_THRESHOLDS == [0.20, 0.35, 0.50]
    assert MIN_USABLE_KEYPOINTS == [4, 6, 8]
    assert ORIENTATION_COMPATIBLE_DEG == 30.0


def test_torso_orientation_unknown_when_shoulder_missing():
    kps = _kps(shoulder_l=(10, 10, 0.05))
    assert torso_orientation_deg(kps, 0.35) is None


def test_torso_orientation_computed_when_shoulders_present():
    kps = _kps()
    angle = torso_orientation_deg(kps, 0.35)
    assert angle is not None
    assert 0.0 <= angle <= 180.0


def test_body_scale_unknown_when_shoulders_missing():
    kps = _kps(shoulder_r=(30, 10, 0.05))
    assert body_scale(kps, 0.35) is None


def test_usable_keypoint_count_respects_threshold():
    kps = [[0, 0, 0.9]] * 4 + [[0, 0, 0.1]] * 13
    assert usable_keypoint_count(kps, 0.35) == 4
    assert usable_keypoint_count(kps, 0.05) == 17


def test_phase1_recall_takes_only_raw_detection():
    sig = inspect.signature(phase1_recall)
    assert list(sig.parameters) == ["detection"]


def test_phase2_geometry_no_ground_truth_parameter():
    sig = inspect.signature(phase2_geometry)
    assert list(sig.parameters) == ["detection", "kp_threshold"]


def test_zero_instances_is_recall_insufficient_not_contradiction():
    detection = {"boxes": [], "scores": [], "keypoints": [], "frame_w": 100, "frame_h": 100}
    g = phase2_geometry(detection, 0.35)
    assert g["recall_status"] == "RECALL_INSUFFICIENT"
    assert g["F4_mutual_facing_evidence"] == "UNKNOWN"


def test_one_instance_is_recall_insufficient():
    detection = {"boxes": [[0, 0, 40, 80]], "scores": [0.9], "keypoints": [_kps()],
                 "frame_w": 100, "frame_h": 100}
    g = phase2_geometry(detection, 0.35)
    assert g["recall_status"] == "RECALL_INSUFFICIENT"


def test_two_instances_with_shoulders_is_recall_sufficient():
    detection = {"boxes": [[0, 0, 40, 80], [50, 0, 90, 80]], "scores": [0.9, 0.85],
                 "keypoints": [_kps(), _kps(shoulder_l=(60, 10, 0.9), shoulder_r=(80, 10, 0.9),
                                            hip_l=(60, 40, 0.9), hip_r=(80, 40, 0.9))],
                 "frame_w": 100, "frame_h": 100}
    g = phase2_geometry(detection, 0.35)
    assert g["recall_status"] == "RECALL_SUFFICIENT"


def test_deterministic_geometry_computation():
    detection = {"boxes": [[0, 0, 40, 80], [50, 0, 90, 80]], "scores": [0.9, 0.85],
                 "keypoints": [_kps(), _kps(shoulder_l=(60, 10, 0.9), shoulder_r=(80, 10, 0.9),
                                            hip_l=(60, 40, 0.9), hip_r=(80, 40, 0.9))],
                 "frame_w": 100, "frame_h": 100}
    g1 = phase2_geometry(detection, 0.35)
    g2 = phase2_geometry(detection, 0.35)
    assert g1 == g2


def test_no_ground_truth_fields_reachable_by_geometry_functions():
    source = inspect.getsource(phase2_geometry) + inspect.getsource(phase1_recall)
    for forbidden in ("human_verdict", "event", "case_id"):
        assert forbidden not in source
