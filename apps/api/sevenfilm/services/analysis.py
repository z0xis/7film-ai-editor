"""Shot and music analysis with deliberately explicit fallback behaviour."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterable
from fractions import Fraction
from pathlib import Path
from typing import Any

from ..db import Database, now
from ..domain import BeatGrid, MediaAsset, Shot
from ..timebase import FrameRate, TimeRange
from .media import project_assets
from .vision import VisionClassifier, measure_frames

LOGGER = logging.getLogger(__name__)


def _shot_frame_groups(asset: MediaAsset, ranges: list[TimeRange]) -> list[list[Any]]:
    """Read all shot samples while opening a source asset only once."""
    import cv2  # type: ignore[import-not-found]

    capture = cv2.VideoCapture(str(asset.path))
    groups: list[list[Any]] = []
    try:
        for source_range in ranges:
            frames = []
            frame_number = source_range.start_frame + round(source_range.duration_frames * 0.5)
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
            for sample_index in range(3):
                ok, frame = capture.read()
                if ok and frame is not None:
                    frames.append(frame)
                if sample_index < 2:
                    gap = max(1, min(round(float(asset.frame_rate.value) * 0.10), 6))
                    for _ in range(gap - 1):
                        if not capture.grab():
                            break
            groups.append(frames)
    finally:
        capture.release()
    return groups


def _fallback_ranges(asset: MediaAsset) -> Iterable[TimeRange]:
    """Use 2.5-second candidates when PySceneDetect cannot process the clip."""
    segment = max(asset.frame_rate.frames_from_seconds(Fraction(5, 2)), 1)
    total = asset.frame_rate.frames_from_seconds(asset.duration, rounding="floor")
    for start in range(0, total, segment):
        duration = min(segment, total - start)
        if duration >= asset.frame_rate.frames_from_seconds(Fraction(1, 2), rounding="ceil"):
            yield TimeRange(start, duration, asset.frame_rate)


def _scene_ranges(asset: MediaAsset) -> Iterable[TimeRange]:
    try:
        from scenedetect import ContentDetector, detect  # type: ignore[import-not-found]

        scenes = detect(str(asset.path), ContentDetector(threshold=27.0), start_in_scene=True)
        for start, end in scenes:
            start_frame = max(0, int(start.get_frames()))
            duration = max(0, int(end.get_frames()) - start_frame)
            if duration:
                yield TimeRange(start_frame, duration, asset.frame_rate)
    except (ImportError, OSError, RuntimeError):
        yield from _fallback_ranges(asset)


def row_to_shot(row: dict[str, object]) -> Shot:
    rate = FrameRate.parse(str(row["frame_rate"]))
    return Shot(
        id=str(row["id"]),
        asset_id=str(row["asset_id"]),
        source_range=TimeRange(int(row["start_frame"]), int(row["duration_frames"]), rate),
        category=str(row["category"]),
        shot_scale=str(row["shot_scale"]),
        technical_quality=float(row["technical_quality"]),
        aesthetic_score=float(row["aesthetic_score"]),
        motion_score=float(row["motion_score"]),
        confidence=float(row["confidence"]),
        duplicate_group=row.get("duplicate_group") and str(row["duplicate_group"]),
        labels=tuple(json.loads(str(row["labels_json"]))),
    )


def project_shots(database: Database, project_id: str) -> list[Shot]:
    rows = database.fetch_all(
        """SELECT shots.* FROM shots JOIN media_assets ON media_assets.id = shots.asset_id
           WHERE media_assets.project_id = ? ORDER BY media_assets.path, shots.start_frame""",
        (project_id,),
    )
    return [row_to_shot(row) for row in rows]


def analyze_shots(database: Database, project_id: str, job_id: str) -> list[Shot]:
    assets = project_assets(database, project_id)
    if not assets:
        raise ValueError("Önce ham görüntüleri indeksleyin.")
    classifier = VisionClassifier()
    for asset_index, asset in enumerate(assets, start=1):
        existing_rows = database.fetch_all(
            "SELECT start_frame, duration_frames, frame_rate, labels_json FROM shots "
            "WHERE asset_id = ? ORDER BY start_frame",
            (asset.id,),
        )
        if existing_rows and all("clip_vision" in str(row["labels_json"]) for row in existing_rows):
            database.update_job(
                job_id,
                status="running",
                progress=asset_index / len(assets),
                checkpoint={"last_asset_id": asset.id, "vision_cache": "clip_vision"},
            )
            continue
        ranges = [
            TimeRange(
                int(row["start_frame"]),
                int(row["duration_frames"]),
                FrameRate.parse(str(row["frame_rate"])),
            )
            for row in existing_rows
        ]
        if not ranges:
            ranges = list(_scene_ranges(asset))
        database.execute("DELETE FROM shots WHERE asset_id = ?", (asset.id,))
        frame_groups = _shot_frame_groups(asset, ranges)
        metrics = [measure_frames(frames) for frames in frame_groups]
        middle_frames = [frames[len(frames) // 2] if frames else None for frames in frame_groups]
        valid_positions = [index for index, frame in enumerate(middle_frames) if frame is not None]
        classifications = classifier.classify(
            [middle_frames[index] for index in valid_positions],
            [metrics[index] for index in valid_positions],
        )
        features_by_position = dict(zip(valid_positions, classifications))
        for ordinal, source_range in enumerate(ranges):
            measured = metrics[ordinal]
            features = features_by_position.get(ordinal) or classifier._fallback(measured)
            shot_id = str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"sevenfilm:{asset.id}:{source_range.start_frame}:{source_range.duration_frames}",
                )
            )
            database.insert(
                "shots",
                {
                    "id": shot_id,
                    "asset_id": asset.id,
                    "start_frame": source_range.start_frame,
                    "duration_frames": source_range.duration_frames,
                    "frame_rate": f"{source_range.rate.numerator}/{source_range.rate.denominator}",
                    "category": features["category"],
                    "shot_scale": features["shot_scale"],
                    "technical_quality": measured.technical_quality,
                    "aesthetic_score": features["aesthetic_score"],
                    "motion_score": measured.motion_score,
                    "confidence": features["confidence"],
                    "duplicate_group": f"visual:{measured.perceptual_hash}",
                    "labels_json": list(features["labels"]),
                    "created_at": now(),
                },
            )
        database.update_job(
            job_id,
            status="running",
            progress=asset_index / len(assets),
            checkpoint={"last_asset_id": asset.id},
        )
    shots = project_shots(database, project_id)
    LOGGER.info(json.dumps({"event": "shots_analyzed", "project_id": project_id, "count": len(shots)}))
    return shots


def _fallback_beats(duration: Fraction, bpm: float = 120.0) -> tuple[Fraction, ...]:
    interval = Fraction(60, 1) / Fraction(str(bpm))
    count = int(duration / interval)
    return tuple(interval * step for step in range(count + 1))


def analyze_music(database: Database, project_id: str, path: Path) -> BeatGrid:
    """Use librosa when installed; never invent an analysis for unsupported audio."""
    music_path = path.expanduser().resolve()
    if not music_path.is_file():
        raise ValueError(f"Müzik dosyası bulunamadı: {music_path}")
    try:
        import librosa  # type: ignore[import-not-found]
    except ImportError as error:
        raise RuntimeError("Müzik analizi için librosa bağımlılığı kurulmalıdır.") from error

    samples, sample_rate = librosa.load(str(music_path), sr=None, mono=True)
    tempo, beat_frames = librosa.beat.beat_track(y=samples, sr=sample_rate, units="frames")
    duration = Fraction(str(librosa.get_duration(y=samples, sr=sample_rate)))
    beat_times = librosa.frames_to_time(beat_frames, sr=sample_rate)
    bpm = float(tempo.item() if hasattr(tempo, "item") else tempo)
    beats = tuple(Fraction(str(float(value))) for value in beat_times)
    if not beats:
        beats = _fallback_beats(duration, bpm or 120.0)
    sections = _energy_sections(samples, sample_rate, duration)
    grid = BeatGrid(bpm=bpm or 120.0, beats=beats, duration=duration, sections=sections)
    music_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"sevenfilm:{project_id}:music:{music_path}"))
    database.execute("DELETE FROM music_tracks WHERE project_id = ? AND path = ?", (project_id, str(music_path)))
    database.insert(
        "music_tracks",
        {
            "id": music_id,
            "project_id": project_id,
            "path": str(music_path),
            "duration_seconds": str(duration),
            "bpm": grid.bpm,
            "beats_json": [str(beat) for beat in grid.beats],
            "sections_json": list(grid.sections),
            "created_at": now(),
        },
    )
    LOGGER.info(json.dumps({"event": "music_analyzed", "project_id": project_id, "bpm": grid.bpm}))
    return grid


def _energy_sections(samples: object, sample_rate: int, duration: Fraction) -> tuple[dict[str, object], ...]:
    """A compact, explainable low/medium/high energy curve for v0.1."""
    try:
        import librosa  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]

        rms = librosa.feature.rms(y=samples)[0]
        if len(rms) == 0:
            raise ValueError
        low, high = np.quantile(rms, [0.33, 0.66])
        boundaries = np.linspace(0, float(duration), num=5)
        sections = []
        for index in range(4):
            start_index = int(index * len(rms) / 4)
            end_index = int((index + 1) * len(rms) / 4)
            value = float(np.mean(rms[start_index:end_index]))
            level = "low" if value <= low else "high" if value >= high else "medium"
            sections.append({"start": str(Fraction(str(boundaries[index]))), "end": str(Fraction(str(boundaries[index + 1]))), "energy": level})
        return tuple(sections)
    except (ImportError, ValueError, TypeError, AttributeError):
        return ({"start": "0", "end": str(duration), "energy": "medium"},)


def latest_music(database: Database, project_id: str) -> BeatGrid | None:
    row = database.fetch_one(
        "SELECT * FROM music_tracks WHERE project_id = ? ORDER BY created_at DESC LIMIT 1", (project_id,)
    )
    if row is None:
        return None
    return BeatGrid(
        bpm=float(row["bpm"]),
        beats=tuple(Fraction(item) for item in json.loads(row["beats_json"])),
        duration=Fraction(row["duration_seconds"]),
        sections=tuple(json.loads(row["sections_json"])),
    )
