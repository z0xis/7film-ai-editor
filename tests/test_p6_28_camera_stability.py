from __future__ import annotations

import sqlite3
from pathlib import Path

import cv2
import numpy as np
from sevenfilm.services.stability import StabilityVerdict, measure_camera_stability


def _scene() -> np.ndarray:
    rng = np.random.default_rng(17)
    image = rng.integers(0, 256, (240, 420, 3), dtype=np.uint8)
    image = cv2.GaussianBlur(image, (5, 5), 0)
    cv2.rectangle(image, (80, 55), (180, 175), (250, 245, 230), 3)
    cv2.circle(image, (300, 120), 48, (20, 30, 240), 4)
    return image


def _sequence(offsets: list[tuple[float, float]]) -> list[np.ndarray]:
    base = _scene()
    return [cv2.warpAffine(base, np.float32([[1, 0, x], [0, 1, y]]), (420, 240),
                           borderMode=cv2.BORDER_REFLECT) for x, y in offsets]


def test_smooth_intentional_pan_is_not_rejected():
    result = measure_camera_stability(_sequence([(i * 2.0, i * 0.25) for i in range(18)]))
    assert result.verdict == StabilityVerdict.STABLE


def test_high_frequency_jitter_is_rejected():
    offsets = [(0, 0), (5, -3), (-5, 4), (6, -4), (-6, 3), (5, -4), (-5, 4),
               (6, -3), (-6, 4), (5, -4), (-5, 3), (6, -4), (-6, 4), (5, -3)]
    result = measure_camera_stability(_sequence(offsets))
    assert result.verdict == StabilityVerdict.UNSTABLE
    assert result.direction_reversal_rate >= 0.28


def test_low_confidence_abstains():
    blank = [np.full((180, 320, 3), 127, np.uint8) for _ in range(12)]
    result = measure_camera_stability(blank)
    assert result.verdict == StabilityVerdict.UNKNOWN


def test_result_is_deterministic():
    frames = _sequence([(i * 1.5, 0) for i in range(15)])
    assert measure_camera_stability(frames) == measure_camera_stability(frames)


def test_shadow_measurement_does_not_write_database(tmp_path: Path):
    db = tmp_path / "proof.sqlite3"
    with sqlite3.connect(db) as connection:
        connection.execute("create table sentinel(value text)")
        connection.execute("insert into sentinel values ('unchanged')")
    before = db.read_bytes()
    measure_camera_stability(_sequence([(i, 0) for i in range(10)]))
    assert db.read_bytes() == before


def test_module_has_no_planner_or_resolve_dependency():
    from sevenfilm.services import stability

    source = Path(stability.__file__).read_text()
    assert "build_timeline" not in source
    assert "DaVinciResolve" not in source
