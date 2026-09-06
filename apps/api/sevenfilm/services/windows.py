"""What a shot looks like along its length, rather than at one point in its middle.

A shot used to be judged on three frames spanning 0.2 seconds, and its framing on the single
frame between them. The planner then cut a segment out of it by arithmetic, starting a fixed
handle after the shot began and running forward. Neither step ever asked which part of the
shot was the part worth using.

Measured on six clips the editor picked out, the moment they objected to was inside the cut
and the stored measurement had never looked at it:

    C2075  head against the frame edge  edge 0.76 at the cut's start, 0.00 half a second in
    C2076  the same                     edge 1.00 at the start, 0.00 half a second in
    C2155  a whip                       sharpness 9 against the shoot's 45-78
    C2181  no usable moment at all      edge 1.00 across the whole cut, 6 to 9 faces
    C1968  a bystander in a doorway     3 faces where the rest of the shot has 2

The cut began at the bad moment in every one, which is not luck: it began where the scene
detector had just cut, and that is exactly where framing is still settling.

Windows are measured off the proxy when there is one. The source here is 4K 10-bit S-Log3
with no hardware decode on this machine, and nothing measured below depends on the grade.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from ..db import Database
from ..domain import MediaAsset, Shot

# Half a second: short enough to sit inside the shortest cut the planner makes, long enough
# that measuring a 150 clip shoot stays cheap.
WINDOW_SECONDS = Fraction(1, 2)
# Below the threshold the detector is used at elsewhere, because a bystander is small, dark
# and turned away. At 0.35 the man standing in C1968's doorway is found (0.38 and 0.42 on the
# two frames he is in) and the couple stay at 0.89 and above, so the two do not blur together.
BYSTANDER_SCORE = 0.35
# A face this much smaller than the largest one in frame is someone else's.
BYSTANDER_RATIO = 0.25


@dataclass(frozen=True)
class ShotWindow:
    """One half second of a shot."""

    shot_id: str
    offset_frames: int
    sharpness: float
    motion: float
    face_ratio: float
    face_edge: float
    face_count: int
    bystanders: int


def _face_framing(box: Any, width: int, height: int) -> tuple[float, float]:
    x, y, w, h = (float(box[index]) for index in range(4))
    ratio = max(0.0, min(1.0, w * h / (width * height)))
    margin_x, margin_y = width / 20, height / 20
    gaps = (x, y, width - (x + w), height - (y + h))
    margins = (margin_x, margin_y, margin_x, margin_y)
    edge = max(
        max(0.0, min(1.0, 1.0 - gap / margin))
        for gap, margin in zip(gaps, margins, strict=True)
    )
    return round(ratio, 5), round(edge, 3)


def measure_windows(asset: MediaAsset, shot: Shot, source: Path) -> list[ShotWindow]:
    """Walk a shot half a second at a time and report what each window holds."""
    import cv2  # type: ignore[import-not-found]
    import numpy as np

    model = Path(__file__).parent.parent / "models" / "face_detection_yunet_2023mar.onnx"
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        return []
    try:
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if width <= 0 or height <= 0:
            return []
        detector = None
        if hasattr(cv2, "FaceDetectorYN") and model.exists():
            detector = cv2.FaceDetectorYN.create(
                str(model), "", (width, height),
                score_threshold=BYSTANDER_SCORE, nms_threshold=0.3,
            )
        rate = shot.source_range.rate
        step = max(1, rate.frames_from_seconds(WINDOW_SECONDS, rounding="nearest"))
        windows: list[ShotWindow] = []
        previous = None
        for offset in range(0, shot.source_range.duration_frames, step):
            capture.set(cv2.CAP_PROP_POS_FRAMES, shot.source_range.start_frame + offset)
            ok, frame = capture.read()
            if not ok or frame is None:
                break
            grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            sharpness = float(cv2.Laplacian(grey, cv2.CV_64F).var())
            faces: list[Any] = []
            if detector is not None:
                _ok, detected = detector.detect(frame)
                if detected is not None:
                    faces = list(detected)
            ratio, edge, bystanders = 0.0, 0.0, 0
            if faces:
                largest = max(faces, key=lambda box: box[2] * box[3])
                ratio, edge = _face_framing(largest, width, height)
                area = float(largest[2] * largest[3])
                bystanders = sum(
                    1 for box in faces if float(box[2] * box[3]) < area * BYSTANDER_RATIO
                )
            small = cv2.resize(grey, (160, 90)).astype(np.int16)
            motion = 0.0 if previous is None else float(np.abs(small - previous).mean())
            previous = small
            windows.append(ShotWindow(
                shot_id=shot.id,
                offset_frames=offset,
                sharpness=round(sharpness, 2),
                motion=round(motion, 3),
                face_ratio=ratio,
                face_edge=edge,
                face_count=len(faces),
                bystanders=bystanders,
            ))
        return windows
    finally:
        capture.release()


def store_windows(database: Database, shot_id: str, windows: list[ShotWindow]) -> None:
    """Replace a shot's windows, so a re-measure never leaves half of an older pass behind."""
    database.execute("DELETE FROM shot_windows WHERE shot_id = ?", (shot_id,))
    for window in windows:
        database.insert("shot_windows", {
            "shot_id": window.shot_id,
            "offset_frames": window.offset_frames,
            "sharpness": window.sharpness,
            "motion": window.motion,
            "face_ratio": window.face_ratio,
            "face_edge": window.face_edge,
            "face_count": window.face_count,
            "bystanders": window.bystanders,
        })


def project_windows(database: Database, project_id: str) -> dict[str, list[ShotWindow]]:
    """Every measured window of a project, by shot, in offset order.

    A shot with no rows is absent rather than empty, so the planner can tell "not measured"
    from "measured and there is nothing here".
    """
    rows = database.fetch_all(
        """SELECT shot_windows.* FROM shot_windows
           JOIN shots ON shots.id = shot_windows.shot_id
           JOIN media_assets ON media_assets.id = shots.asset_id
           WHERE media_assets.project_id = ?
           ORDER BY shot_windows.shot_id, shot_windows.offset_frames""",
        (project_id,),
    )
    by_shot: dict[str, list[ShotWindow]] = {}
    for row in rows:
        by_shot.setdefault(str(row["shot_id"]), []).append(ShotWindow(
            shot_id=str(row["shot_id"]),
            offset_frames=int(row["offset_frames"]),
            sharpness=float(row["sharpness"]),
            motion=float(row["motion"]),
            face_ratio=float(row["face_ratio"]),
            face_edge=float(row["face_edge"]),
            face_count=int(row["face_count"]),
            bystanders=int(row["bystanders"]),
        ))
    return by_shot
