"""Shot and music analysis with deliberately explicit fallback behaviour."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import asdict
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

from ..db import Database, now, raise_if_cancelled
from ..domain import BeatGrid, MediaAsset, Shot
from ..timebase import FrameRate, TimeRange
from . import windows as windows_module
from .media import project_assets
from .music import MusicTrack
from .vision import (
    SEMANTIC_BACKEND_CLIP,
    SEMANTIC_BACKEND_FALLBACK,
    FrameMetrics,
    VisionClassifier,
    measure_frames,
)
from .windows import measure_windows, store_windows

LOGGER = logging.getLogger(__name__)
# Bumped whenever measuring or labelling changes in a way that makes older rows worse rather
# than merely different. "2" added the highlight and flatness vetoes, the five second shot cap,
# the CLIP prompt prior, and energy sections that follow the track instead of its four quarters.
# "3" takes that prompt prior off the shot scale as well, which is what put close-ups back in
# reach: uncorrected, CLIP gave "medium" 60.8% of the probability on average against 3.9% for
# the close-up phrase, and no close-up survived into the edit.
# "4" keeps the face box the detector already produced: how much of the frame the subject
# fills, and whether the frame cuts it. Both are things a viewer sees at once and nothing here
# could measure — a couple across a hotel atrium read as a couple, and a head against the frame
# edge was held for four seconds.
ANALYSIS_VERSION = "4"
# A continuous take is detected as one scene, and judging it by three frames at its midpoint
# throws the whole clip away when that midpoint happens to be a blurred pan, and lets a clip in
# when only its midpoint is good. Long scenes are split into segments this size so each part of
# a clip is measured, scored and accepted or rejected on its own.
MAX_SHOT_SECONDS = Fraction(5)
# Energy is read in short windows and merged, so a drop is found where it is rather than
# smeared across a quarter of the song. Levels are relative to the track's own loud passages.
ENERGY_WINDOW_SECONDS = 4
ENERGY_SMOOTHING_WINDOWS = 2
HIGH_ENERGY_RATIO = 0.70
LOW_ENERGY_RATIO = 0.30
# Levels are read as a position between the track's quiet floor and its loud peak. A song with
# almost no dynamic range has no quiet or loud passages to find, and reading one window as
# "at the peak" there would cut the whole edit fast for no musical reason.
MIN_DYNAMIC_RANGE = 0.15


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
            yield from _split_long_range(TimeRange(start, duration, asset.frame_rate))


def _split_long_range(
    source_range: TimeRange, max_seconds: Fraction = MAX_SHOT_SECONDS
) -> Iterable[TimeRange]:
    """Cut an over-long scene into equal segments, none longer than max_seconds."""
    rate = source_range.rate
    limit = max(1, rate.frames_from_seconds(max_seconds, rounding="floor"))
    total = source_range.duration_frames
    if total <= limit:
        yield source_range
        return
    parts = -(-total // limit)
    base, remainder = divmod(total, parts)
    offset = 0
    for index in range(parts):
        length = base + (1 if index < remainder else 0)
        yield TimeRange(source_range.start_frame + offset, length, rate)
        offset += length


def _scene_ranges(asset: MediaAsset) -> Iterable[TimeRange]:
    try:
        from scenedetect import ContentDetector, detect  # type: ignore[import-not-found]

        scenes = detect(str(asset.path), ContentDetector(threshold=27.0), start_in_scene=True)
        for start, end in scenes:
            start_frame = max(0, int(start.get_frames()))
            duration = max(0, int(end.get_frames()) - start_frame)
            if duration:
                yield from _split_long_range(TimeRange(start_frame, duration, asset.frame_rate))
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
        brightness=float(row.get("brightness") or 0.0),
        saturation=float(row.get("saturation") or 0.0),
        highlight_clipping=float(row.get("highlight_clipping") or 0.0),
        face_ratio=float(row.get("face_ratio") or 0.0),
        face_edge=float(row.get("face_edge") or 0.0),
    )


def project_shots(database: Database, project_id: str) -> list[Shot]:
    rows = database.fetch_all(
        """SELECT shots.* FROM shots JOIN media_assets ON media_assets.id = shots.asset_id
           WHERE media_assets.project_id = ? ORDER BY media_assets.path, shots.start_frame""",
        (project_id,),
    )
    return [row_to_shot(row) for row in rows]


def _shot_id(asset_id: str, source_range: TimeRange) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"sevenfilm:{asset_id}:{source_range.start_frame}:{source_range.duration_frames}",
        )
    )


def _store_features(
    database: Database,
    asset: MediaAsset,
    ranges: list[TimeRange],
    metrics: list[FrameMetrics],
    embeddings: dict[int, Any],
) -> None:
    """Replace this asset's `shot_features` rows, all of them or none of them.

    `_asset_features` below reads "does this asset have any `shot_features` rows" as "has this
    asset already been encoded" and skips it if so; that reading is only true if a row can never
    exist half-written. `Database.replace_rows` is one transaction for the delete and every
    insert together, so an interruption partway through (a cooperative cancellation, a crash, an
    exception from a bad embedding) leaves either the asset's previous rows untouched or its new
    ones complete -- never a mix a later run could mistake for "done".
    """
    rows = [
        {
            "shot_id": _shot_id(asset.id, source_range),
            "asset_id": asset.id,
            "start_frame": source_range.start_frame,
            "duration_frames": source_range.duration_frames,
            "frame_rate": f"{source_range.rate.numerator}/{source_range.rate.denominator}",
            "embedding": (
                embeddings[ordinal].astype(np.float32).tobytes()
                if embeddings.get(ordinal) is not None else None
            ),
            "metrics_json": asdict(metrics[ordinal]),
            "created_at": now(),
        }
        for ordinal, source_range in enumerate(ranges)
    ]
    database.replace_rows("shot_features", "asset_id", asset.id, rows)


def _encode_asset(database: Database, classifier: VisionClassifier, asset: MediaAsset) -> None:
    """Decode, measure and encode one asset. This is the slow half, and it runs once."""
    existing_rows = database.fetch_all(
        "SELECT start_frame, duration_frames, frame_rate FROM shots WHERE asset_id = ? ORDER BY start_frame",
        (asset.id,),
    )
    ranges = [
        segment
        for row in existing_rows
        for segment in _split_long_range(
            TimeRange(
                int(row["start_frame"]),
                int(row["duration_frames"]),
                FrameRate.parse(str(row["frame_rate"])),
            )
        )
    ]
    if not ranges:
        ranges = list(_scene_ranges(asset))
    frame_groups = _shot_frame_groups(asset, ranges)
    metrics = [measure_frames(frames) for frames in frame_groups]
    middle_frames = [frames[len(frames) // 2] if frames else None for frames in frame_groups]
    positions = [index for index, frame in enumerate(middle_frames) if frame is not None]
    encoded = classifier.encode([middle_frames[index] for index in positions])
    embeddings = {} if encoded is None else dict(zip(positions, encoded))
    _store_features(database, asset, ranges, metrics, embeddings)


def _asset_features(database: Database, asset_id: str) -> list[dict[str, Any]]:
    return database.fetch_all(
        "SELECT * FROM shot_features WHERE asset_id = ? ORDER BY start_frame", (asset_id,)
    )


def _project_prior(database: Database, classifier: VisionClassifier, project_id: str):
    """The prompt priors, measured over every encoded frame in the project."""
    rows = database.fetch_all(
        """SELECT shot_features.embedding FROM shot_features
           JOIN media_assets ON media_assets.id = shot_features.asset_id
           WHERE media_assets.project_id = ? AND shot_features.embedding IS NOT NULL""",
        (project_id,),
    )
    if not rows:
        return None
    stacked = np.stack([np.frombuffer(row["embedding"], dtype=np.float32) for row in rows])
    LOGGER.info(json.dumps(
        {"event": "prompt_priors_measured", "project_id": project_id, "frames": len(stacked)}
    ))
    return classifier.prompt_priors(stacked)


def _label_asset(database: Database, classifier: VisionClassifier, asset: MediaAsset, priors) -> None:
    """Turn stored measurements into shots. Cheap, so it re-runs whenever the priors move."""
    rows = _asset_features(database, asset.id)
    if not rows:
        return
    metrics = [FrameMetrics(**json.loads(row["metrics_json"])) for row in rows]
    positions = [index for index, row in enumerate(rows) if row["embedding"] is not None]
    encoded = (
        np.stack([np.frombuffer(rows[index]["embedding"], dtype=np.float32) for index in positions])
        if positions
        else None
    )
    classifications = classifier.classify_features(
        encoded, [metrics[index] for index in positions], priors
    )
    features_by_position = dict(zip(positions, classifications))
    # Built fully in memory before anything is deleted: a failure while preparing a row (a bad
    # classification, a malformed metrics_json) must leave the old shots untouched, not a table
    # already emptied by a DELETE with nothing yet written to replace it.
    new_rows = []
    for ordinal, row in enumerate(rows):
        measured = metrics[ordinal]
        features = features_by_position.get(ordinal) or classifier._fallback(measured)
        new_rows.append(
            {
                "id": row["shot_id"],
                "asset_id": asset.id,
                "start_frame": row["start_frame"],
                "duration_frames": row["duration_frames"],
                "frame_rate": row["frame_rate"],
                "category": features["category"],
                "shot_scale": features["shot_scale"],
                "technical_quality": measured.technical_quality,
                "aesthetic_score": features["aesthetic_score"],
                "motion_score": measured.motion_score,
                "confidence": features["confidence"],
                "duplicate_group": f"visual:{measured.perceptual_hash}",
                "labels_json": list(features["labels"]),
                "analysis_version": ANALYSIS_VERSION,
                "brightness": measured.brightness,
                "saturation": measured.saturation,
                "highlight_clipping": measured.highlight_clipping,
                "face_ratio": measured.face_ratio,
                "face_edge": measured.face_edge,
                "created_at": now(),
            }
        )
    # One transaction for the delete and every insert together -- see `replace_rows`'s own
    # docstring for the gap this closes: a crash or cancellation partway through a delete-then-
    # insert-loop used to leave some of an asset's shots written and the rest not, which is
    # exactly the window that can leave a shot a timeline still references missing.
    database.replace_rows("shots", "asset_id", asset.id, new_rows)


def analyze_shots(database: Database, project_id: str, job_id: str) -> list[Shot]:
    """Measure and label every shot, in two passes over the project.

    Categories and shot scales are read against priors measured across the whole shoot, so
    nothing can be labelled until everything is encoded. The encoding is persisted as it goes, which keeps the
    job resumable across a crash and makes the second pass cheap enough to re-run whenever the
    priors move.
    """
    assets = project_assets(database, project_id)
    if not assets:
        raise ValueError("Önce ham görüntüleri indeksleyin.")
    classifier = VisionClassifier()
    for index, asset in enumerate(assets, start=1):
        # Checked before the expensive part of this iteration, not after: a cancellation seen
        # here means the asset this call would have encoded next never starts, rather than
        # being abandoned half done.
        raise_if_cancelled(database, job_id)
        database.touch_heartbeat(job_id)
        if not _asset_features(database, asset.id):
            _encode_asset(database, classifier, asset)
        # `update_job_progress`, not the plain `update_job` this used to be: `processed`/`total`
        # here are the honest unit of work (assets encoded, out of all of them), not a fraction
        # of the whole job pre-baked to imply the windows pass barely exists. See
        # `_overall_progress` in api.py for how a stage's own progress becomes the number the
        # UI shows.
        database.update_job_progress(
            job_id, stage="encode", processed=index, total=len(assets),
            checkpoint={"last_asset_id": asset.id, "current_asset_display": asset.name,
                        "pass": "encode"},
        )
    priors = _project_prior(database, classifier, project_id)
    for index, asset in enumerate(assets, start=1):
        raise_if_cancelled(database, job_id)
        database.touch_heartbeat(job_id)
        _label_asset(database, classifier, asset, priors)
        database.update_job_progress(
            job_id, stage="label", processed=index, total=len(assets),
            checkpoint={"last_asset_id": asset.id, "current_asset_display": asset.name,
                        "pass": "label"},
        )
    shots = project_shots(database, project_id)
    _measure_shot_windows(database, project_id, assets, shots, job_id=job_id)
    if job_id is not None:
        # A real stage, not a free 1.0: `_measure_shot_windows` is the last unit of *measured*
        # work, but `analyze_shots` still has to return and `_run_job` still has to write
        # `completed` above it. Nothing here does real work -- it exists so a caller watching
        # `stage` sees "finalize", never sees `windows` at 100% and nothing after it, and never
        # sees this job's own `progress` read 1.0 before `_run_job` actually marks it done.
        database.update_job_progress(
            job_id, stage="finalize", processed=1, total=1,
            checkpoint={"pass": "finalize"},
        )
    LOGGER.info(json.dumps({"event": "shots_analyzed", "project_id": project_id, "count": len(shots)}))
    return shots


def _measure_shot_windows(
    database: Database, project_id: str, assets: Sequence[MediaAsset], shots: Sequence[Shot],
    *, job_id: str | None = None,
) -> None:
    """Walk every shot half a second at a time, so the planner can choose the moment.

    Read off the originals, which costs 661 milliseconds a frame on this footage and is worth
    it. The proxies were tried first and measured wrong: a man standing in a doorway behind a
    couple is fifteen ten-thousandths of the frame, and the face detector finds him in every
    frame of the 4K original and in none of the 1280x720 proxy. Upscaling the proxy two and
    three times does not bring him back, because the information is not in it.

    A failure here leaves the shot unmeasured rather than failing the job: without windows the
    planner cuts the way it did before, which is worse but not broken.

    This used to be the one pass in this whole job that wrote neither progress nor a heartbeat
    -- the exact reason a job sitting here for hours, CPU busy and `shot_windows` rows landing,
    read as "not responding" past `STALLED_JOB_SECONDS`. `processed`/`total` here count shots
    *walked*, never `shot_windows` rows written: one shot can produce several windows, or none
    at all on a failure or an unreadable stretch, and neither says anything about how far
    through the shot list this call actually is.

    P4: `shots` arrives grouped by asset -- `project_shots` orders by `media_assets.path,
    shots.start_frame` -- so consecutive shots of the same asset share one `AssetWindowMeasurer`
    (one open file, one loaded face-detection model) instead of each opening and releasing its
    own, the repeated-open-per-shot cost a static audit found here. The measurer is keyed by
    `asset_id` and reopened whenever that changes, which stays correct even if a caller ever
    hands this an unsorted `shots` list -- it would just stop sharing across the gap, never
    measure anything wrong.
    """
    by_id = {asset.id: asset for asset in assets}
    total = len(shots)
    current_asset_id: str | None = None
    measurer: windows_module.AssetWindowMeasurer | None = None
    try:
        for index, shot in enumerate(shots, start=1):
            if job_id is not None:
                raise_if_cancelled(database, job_id)
                # A heartbeat *before* the expensive part of this iteration, not folded into the
                # progress write after it: the two can be minutes apart on this shoot's slowest
                # shots, and a caller asking "is anyone still there" deserves an answer that isn't
                # gated on the shot in progress actually finishing. See `touch_heartbeat`'s own
                # docstring for the limitation this does not solve -- a single very long decode or
                # inference call inside `measure_windows` still cannot be interrupted mid-call.
                database.touch_heartbeat(job_id)
            asset = by_id.get(shot.asset_id)
            if asset is None:
                if job_id is not None:
                    database.update_job_progress(
                        job_id, stage="windows", processed=index, total=total,
                        checkpoint={"last_shot_id": shot.id, "last_shot_index": index, "pass": "windows"},
                    )
                continue
            if asset.id != current_asset_id:
                if measurer is not None:
                    measurer.close()
                measurer = windows_module.AssetWindowMeasurer(asset)
                current_asset_id = asset.id
            try:
                windows = measurer.measure(shot)
            except Exception:
                LOGGER.exception(json.dumps({"event": "shot_windows_failed", "shot_id": shot.id}))
                windows = None
            if windows:
                store_windows(database, shot.id, windows)
            # Written after the shot's own work (the `measurer.measure`/`store_windows` above),
            # not before: a crash between the heartbeat and here leaves this shot's `processed`
            # count exactly where it was -- unfinished, not falsely counted as done. See the
            # module docstring on `Database.replace_rows` for the same ordering argument applied
            # to `shot_features`.
            if job_id is not None:
                database.update_job_progress(
                    job_id, stage="windows", processed=index, total=total,
                    checkpoint={"last_shot_id": shot.id, "last_shot_index": index,
                                "current_asset_id": asset.id, "current_asset_display": asset.name,
                                "pass": "windows"},
                )
    finally:
        if measurer is not None:
            measurer.close()


def _fallback_beats(duration: Fraction, bpm: float = 120.0) -> tuple[Fraction, ...]:
    interval = Fraction(60, 1) / Fraction(str(bpm))
    count = int(duration / interval)
    return tuple(interval * step for step in range(count + 1))


def analyze_music(
    database: Database, project_id: str, path: Path, position: int = 0
) -> BeatGrid:
    """Use librosa when installed; never invent an analysis for unsupported audio.

    `position` is where this song sits in the running order the editor chose, so an edit can
    open on one song and move to another. A single song leaves it at 0.
    """
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
            "position": position,
            "analysis_version": ANALYSIS_VERSION,
            "created_at": now(),
        },
    )
    LOGGER.info(json.dumps({"event": "music_analyzed", "project_id": project_id, "bpm": grid.bpm}))
    return grid


# How much a section's energy has to move across itself before it counts as rising or falling.
#
# Read as a share of the track's own floor-to-peak range, so it travels to a quiet song and a
# loud one alike. A tenth of that range is small enough to catch a build and large enough that
# the smoothing noise inside one passage does not flip the label.
SECTION_DIRECTION_RATIO = 0.10


def _energy_sections(samples: object, sample_rate: int, duration: Fraction) -> tuple[dict[str, object], ...]:
    """Follow the track's own dynamics instead of splitting it into four equal quarters.

    Quarters smear structure: a ten second drop inside a calm song used to mark a full
    thirty seconds as high energy, and label identical calm passages differently depending
    on which quarter they fell in. Narrow windows are placed between the track's own quiet
    floor and loud peak, and adjacent windows of the same level are merged, so the sections
    that come out are the ones the song actually has.
    """
    del sample_rate  # Energy is measured on the RMS envelope, which carries its own timing.
    try:
        import librosa  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]

        rms = librosa.feature.rms(y=samples)[0]
        if len(rms) == 0:
            raise ValueError
        windows = max(1, min(len(rms), round(float(duration) / ENERGY_WINDOW_SECONDS)))
        loudness = []
        for index in range(windows):
            start_index = int(index * len(rms) / windows)
            end_index = max(start_index + 1, int((index + 1) * len(rms) / windows))
            # The loudest part of a window, not its average: averaging a chorus over a long
            # window drags it down until no passage in the song ever reads as high energy.
            loudness.append(float(np.quantile(rms[start_index:end_index], 0.75)))
        # The reference points are the song's own quietest and loudest passages. Reading them
        # off the windows rather than off every RMS frame is what lets a short drop count: a
        # ten second chorus in a four minute track sits below the 95th percentile of the track.
        floor, peak = float(np.quantile(loudness, 0.10)), float(max(loudness))
        if peak <= 0 or (peak - floor) / peak < MIN_DYNAMIC_RANGE:
            return ({"start": "0", "end": str(duration), "energy": "medium"},)
        levels = [(value - floor) / (peak - floor) for value in loudness]
        # A median over neighbouring windows removes single-window flicker, which would
        # otherwise change the cut pacing every few seconds inside one musical passage.
        smoothed = [
            float(np.median(levels[max(0, index - ENERGY_SMOOTHING_WINDOWS): index + ENERGY_SMOOTHING_WINDOWS + 1]))
            for index in range(windows)
        ]
        sections: list[dict[str, object]] = []
        for index, level in enumerate(smoothed):
            energy = (
                "high" if level >= HIGH_ENERGY_RATIO
                else "low" if level <= LOW_ENERGY_RATIO
                else "medium"
            )
            end = duration * Fraction(index + 1, windows)
            if sections and sections[-1]["energy"] == energy:
                sections[-1]["end"] = str(end)
                sections[-1]["levels"].append(level)
                continue
            sections.append({
                "start": str(duration * Fraction(index, windows)),
                "end": str(end),
                "energy": energy,
                "levels": [level],
            })
        # Three labels are not enough to pace an edit. Measured on one wedding the editor cut
        # by hand: the song's quiet opening and its breakdown both read as "low", but the shots
        # in them run 1.52 and 2.40 seconds. What separates them is how far below the track's
        # own peak they sit, and which way the energy is moving.
        #
        # So each section also carries the level it actually reached and the direction the
        # energy took across it. Both are measured off this song, never written down here:
        # a different track produces different numbers from the same code.
        for index, section in enumerate(sections):
            levels = section.pop("levels")
            section["level"] = round(float(np.mean(levels)), 4)
            if len(levels) >= 2:
                half = max(1, len(levels) // 2)
                rise = float(np.mean(levels[half:]) - np.mean(levels[:half]))
            else:
                previous = sections[index - 1]["level"] if index else None
                rise = 0.0 if previous is None else float(section["level"] - previous)
            section["direction"] = (
                "rising" if rise > SECTION_DIRECTION_RATIO
                else "falling" if rise < -SECTION_DIRECTION_RATIO
                else "steady"
            )
            section["rise"] = round(rise, 4)
        return tuple(sections)
    except (ImportError, ValueError, TypeError, AttributeError):
        return ({"start": "0", "end": str(duration), "energy": "medium"},)


def stale_analysis(database: Database, project_id: str) -> dict[str, bool]:
    """Which stored analyses were produced by semantics this version has moved on from.

    Nothing about a stale row looks wrong: a music track analysed before the energy sections
    followed the song still has beats and sections, and simply cuts the edit twice as fast as
    the references do. Saying so is the only way anyone would know to run it again.
    """
    shots = database.fetch_one(
        """SELECT COUNT(*) AS total FROM shots JOIN media_assets ON media_assets.id = shots.asset_id
           WHERE media_assets.project_id = ? AND shots.analysis_version != ?""",
        (project_id, ANALYSIS_VERSION),
    )
    music = database.fetch_one(
        "SELECT COUNT(*) AS total FROM music_tracks WHERE project_id = ? AND analysis_version != ?",
        (project_id, ANALYSIS_VERSION),
    )
    return {
        "shots": bool(shots and shots["total"]),
        "music": bool(music and music["total"]),
    }


# Story-vocabulary categories (`ceremony`, `party`, `bride_prep`, `groom_prep`, `groom`) can
# only ever come from `SEMANTIC_BACKEND_CLIP`; the OpenCV fallback's `_fallback` reads a face
# count and nothing else, and cannot produce them by construction. A project whose shots were
# not analysed by CLIP is missing the vocabulary a wedding rough cut is planned from, however
# clean its technical measurements are -- see the 15 Ağustos forensic audit this closes: 2638
# shots, all `opencv_fallback`, still produced a 129-clip rough cut with none of ceremony,
# party, bride_prep, groom_prep or groom in it, because nothing checked before planning ran.
READY_FOR_ROUGH_CUT = "FULL"
NOT_READY_FOR_ROUGH_CUT = "DEGRADED"


def semantic_readiness(database: Database, project_id: str) -> dict[str, Any]:
    """How many of this project's shots carry semantic-vocabulary labels a rough cut can
    actually be planned from, versus the OpenCV fallback's face-count-only categories.

    Read off `labels_json`'s last entry, the provenance `classify_features`/`_fallback` have
    always stamped there -- no schema change, no new column, just reading back what was always
    written. A row from before that convention existed (or any other value) counts as
    `unknown`, not `full`: a status this consequential has to be earned, not assumed.

    `status` is `FULL` only when every shot is `clip_vision` and none are unknown -- a project
    that is only partly analysed by CLIP (a resumed run, a version mixed with an older one) is
    exactly the case precision requires failing loud on rather than silently blending two
    semantic vocabularies into one rough cut; see the P5 package this belongs to.
    """
    rows = database.fetch_all(
        """SELECT shots.labels_json FROM shots JOIN media_assets ON media_assets.id = shots.asset_id
           WHERE media_assets.project_id = ?""",
        (project_id,),
    )
    full = degraded = unknown = 0
    for row in rows:
        labels = json.loads(row["labels_json"])
        tag = labels[-1] if labels else None
        if tag == SEMANTIC_BACKEND_CLIP:
            full += 1
        elif tag == SEMANTIC_BACKEND_FALLBACK:
            degraded += 1
        else:
            unknown += 1
    total = full + degraded + unknown
    status = READY_FOR_ROUGH_CUT if total and degraded == 0 and unknown == 0 else NOT_READY_FOR_ROUGH_CUT
    return {"status": status, "full": full, "degraded": degraded, "unknown": unknown, "total": total}


def project_music(database: Database, project_id: str) -> list[MusicTrack]:
    """Every song of this project, in the running order the editor chose."""
    rows = database.fetch_all(
        "SELECT * FROM music_tracks WHERE project_id = ? ORDER BY position, created_at",
        (project_id,),
    )
    return [
        MusicTrack(
            path=Path(row["path"]),
            grid=BeatGrid(
                bpm=float(row["bpm"]),
                beats=tuple(Fraction(item) for item in json.loads(row["beats_json"])),
                duration=Fraction(row["duration_seconds"]),
                sections=tuple(json.loads(row["sections_json"])),
            ),
        )
        for row in rows
    ]


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


def measure_missing_windows(
    database: Database, project_id: str, *, limit: int | None = None,
) -> dict[str, int]:
    """Measure the shots of a project that have no windows yet, and only those.

    A moment search over a whole clip is blind across any stretch that was never measured, and
    850 of this project's 2255 shots were analysed before windows existed. This fills those in
    without touching the 9374 already stored: a shot that has rows is skipped, so the pass is
    resumable and an interrupted run costs nothing.
    """
    from .windows import unmeasured_shots

    pending = unmeasured_shots(database, project_id)
    if limit is not None:
        pending = pending[:limit]
    if not pending:
        return {"pending": 0, "measured": 0, "windows": 0, "failed": 0}

    wanted = set(pending)
    shots = [shot for shot in project_shots(database, project_id) if shot.id in wanted]
    by_id = {asset.id: asset for asset in project_assets(database, project_id)}

    measured = failed = written = 0
    for shot in shots:
        asset = by_id.get(shot.asset_id)
        if asset is None:
            failed += 1
            continue
        try:
            windows = measure_windows(asset, shot, asset.path)
        except Exception:
            LOGGER.exception(json.dumps(
                {"event": "shot_windows_failed", "shot_id": shot.id}))
            failed += 1
            continue
        if windows:
            store_windows(database, shot.id, windows)
            measured += 1
            written += len(windows)
    return {"pending": len(pending), "measured": measured,
            "windows": written, "failed": failed}
