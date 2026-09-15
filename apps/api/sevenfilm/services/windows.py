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

Sharpness is read at a fixed width rather than at whatever the source happens to be — see
SHARPNESS_WIDTH. At 4K the measure reads sensor noise instead of focus, which is how two
cuts the editor called blurred came through at the 45th percentile.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Self

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


# Sharpness is measured on a frame scaled to this width, never on the full 4K frame.
#
# At 4K the Laplacian variance measures sensor noise, not focus. Measured on 60 cuts of this
# edit, the same frames ranked at full resolution and at 640 pixels agree at a Spearman of
# only 0.52 — and the disagreements are exactly the ones the editor picked out. The film's
# opening, a neon sign that is sharp and clean, sat in the bottom 1% at full resolution; two
# cuts of the bride the editor called blurred sat at the 45th percentile. Both come right at
# 640: the sign is the sharpest frame in the film and the blurred cuts are the softest.
#
# It also explains a finding that had no explanation. Across eleven features the clips the
# editor rejected measured *better* than the clips kept, sharpness 25.2 against 23.0, and
# noise is what that number was reading.
SHARPNESS_WIDTH = 640


def _sharpness(cv2: Any, grey: Any) -> float:
    """How much of the frame is in focus, read at a fixed width so noise cannot stand in."""
    height, width = grey.shape[:2]
    if width > SHARPNESS_WIDTH:
        scale = SHARPNESS_WIDTH / width
        grey = cv2.resize(
            grey, (SHARPNESS_WIDTH, max(1, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    return float(cv2.Laplacian(grey, cv2.CV_64F).var())


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


def _measure_shot_on_open_capture(
    cv2: Any, capture: Any, detector: Any, width: int, height: int, shot: Shot,
) -> list[ShotWindow]:
    """The per-shot measurement loop, unchanged from before this was split out -- given an
    already-open capture and an already-built detector rather than opening/building its own.
    Every seek, read, and computed value is identical to what a fresh `measure_windows` call
    would have produced for this shot; only the open/init work above it is shared now."""
    import numpy as np

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
        sharpness = _sharpness(cv2, grey)
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


def measure_windows(asset: MediaAsset, shot: Shot, source: Path) -> list[ShotWindow]:
    """Walk a shot half a second at a time and report what each window holds.

    Opens its own capture and its own face detector, measures the one shot, and releases both.
    Correct on its own and still used that way by anything measuring a single shot in isolation
    (the shadow research tooling, tests); `AssetWindowMeasurer` below is the batched form
    `_measure_shot_windows` actually calls in production, for assets with more than one shot to
    measure.
    """
    import cv2  # type: ignore[import-not-found]

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
        return _measure_shot_on_open_capture(cv2, capture, detector, width, height, shot)
    finally:
        capture.release()


class AssetWindowMeasurer:
    """`measure_windows`, batched across every shot of one asset that share it: one
    `cv2.VideoCapture` and one `cv2.FaceDetectorYN`, opened once and reused, instead of a fresh
    pair per shot.

    Nothing about *what* is measured changes -- every shot still seeks and reads exactly the
    frames `measure_windows` would have, in the same order, and produces the same
    `ShotWindow` values; see `test_windows.py`'s equivalence tests. What changes is that
    `_measure_shot_windows` (whose shots already arrive grouped by asset -- `project_shots`
    orders by `media_assets.path, shots.start_frame`) no longer pays a fresh file-open and a
    fresh ONNX-model load for every one of an asset's shots, only for the asset itself.

    A shot whose own measurement raises still leaves this measurer usable for the next shot of
    the same asset -- the capture and detector are this object's, not the failed call's, and
    nothing here closes them on a per-shot exception. Cancellation between shots is the caller's
    job, same as before: this only holds the capture open across calls, it does not loop itself.
    """

    def __init__(self, asset: MediaAsset) -> None:
        import cv2  # type: ignore[import-not-found]

        self._cv2 = cv2
        model = Path(__file__).parent.parent / "models" / "face_detection_yunet_2023mar.onnx"
        self._capture = cv2.VideoCapture(str(asset.path))
        self._usable = self._capture.isOpened()
        self._width = 0
        self._height = 0
        self._detector = None
        if self._usable:
            self._width = int(self._capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            self._height = int(self._capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
            if self._width <= 0 or self._height <= 0:
                self._usable = False
            elif hasattr(cv2, "FaceDetectorYN") and model.exists():
                self._detector = cv2.FaceDetectorYN.create(
                    str(model), "", (self._width, self._height),
                    score_threshold=BYSTANDER_SCORE, nms_threshold=0.3,
                )

    def measure(self, shot: Shot) -> list[ShotWindow]:
        """The same result `measure_windows(asset, shot, asset.path)` would return -- an
        asset whose file could not be opened or has no readable dimensions returns `[]` for
        every shot, exactly as a fresh `measure_windows` call would have for each of them."""
        if not self._usable:
            return []
        return _measure_shot_on_open_capture(
            self._cv2, self._capture, self._detector, self._width, self._height, shot)

    def close(self) -> None:
        self._capture.release()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


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


@dataclass(frozen=True)
class AssetWindow:
    """A measured window placed on its asset's timeline rather than on its shot's.

    The same measurement as ShotWindow, re-based so the moment search can look past the
    boundary the scene detector happened to draw. `asset_frame` is the window's first frame
    counted from the start of the media file; `category` is the category of the shot the
    window was measured in, so a window keeps the treatment it would have had there.
    """

    shot_id: str
    asset_frame: int
    category: str
    sharpness: float
    motion: float
    face_ratio: float
    face_edge: float
    face_count: int
    bystanders: int

    def as_shot_window(self) -> ShotWindow:
        """The same window in the shape the scorer already takes."""
        return ShotWindow(
            shot_id=self.shot_id,
            offset_frames=self.asset_frame,
            sharpness=self.sharpness,
            motion=self.motion,
            face_ratio=self.face_ratio,
            face_edge=self.face_edge,
            face_count=self.face_count,
            bystanders=self.bystanders,
        )


def asset_windows(database: Database, project_id: str) -> dict[str, list[AssetWindow]]:
    """Every measured window of a project, by asset, in order along the media file.

    Windows are measured a shot at a time and stored with an offset from the shot's start,
    which is why a moment search given only `windows_by_shot` cannot see past the shot it was
    handed. This is the same rows, re-based onto the asset, so a search can be given the whole
    clip instead. Nothing is measured again.
    """
    rows = database.fetch_all(
        """SELECT shot_windows.*, shots.asset_id AS asset_id, shots.category AS category,
                  shots.start_frame AS shot_start
           FROM shot_windows
           JOIN shots ON shots.id = shot_windows.shot_id
           JOIN media_assets ON media_assets.id = shots.asset_id
           WHERE media_assets.project_id = ?
           ORDER BY shots.asset_id, shots.start_frame, shot_windows.offset_frames""",
        (project_id,),
    )
    by_asset: dict[str, list[AssetWindow]] = {}
    for row in rows:
        by_asset.setdefault(str(row["asset_id"]), []).append(AssetWindow(
            shot_id=str(row["shot_id"]),
            asset_frame=int(row["shot_start"]) + int(row["offset_frames"]),
            category=str(row["category"]),
            sharpness=float(row["sharpness"]),
            motion=float(row["motion"]),
            face_ratio=float(row["face_ratio"]),
            face_edge=float(row["face_edge"]),
            face_count=int(row["face_count"]),
            bystanders=int(row["bystanders"]),
        ))
    for windows in by_asset.values():
        windows.sort(key=lambda window: window.asset_frame)
    return by_asset


def unmeasured_shots(database: Database, project_id: str) -> list[str]:
    """The shots of a project that have no windows stored, in a stable order.

    A shot analysed before windows existed has none, and a moment search over its asset is
    blind across that stretch. Measuring is resumable: a shot that already has rows is never
    returned here, so an interrupted pass picks up where it stopped.
    """
    rows = database.fetch_all(
        """SELECT shots.id AS id FROM shots
           JOIN media_assets ON media_assets.id = shots.asset_id
           LEFT JOIN shot_windows ON shot_windows.shot_id = shots.id
           WHERE media_assets.project_id = ? AND shot_windows.shot_id IS NULL
           GROUP BY shots.id
           ORDER BY shots.asset_id, shots.start_frame""",
        (project_id,),
    )
    return [str(row["id"]) for row in rows]
