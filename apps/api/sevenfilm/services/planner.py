"""Explainable, constraint-aware v0.1 rough-cut planner."""

from __future__ import annotations

import json
import random
import uuid
from collections.abc import Iterable, Mapping
from fractions import Fraction
from pathlib import Path

from ..db import Database, now
from ..domain import BeatGrid, MediaAsset, Shot, TimelineItem, TimelinePlan
from ..timebase import FrameRate, TimeRange

MIN_TARGET_DURATION = Fraction(120, 1)


class InsufficientFootageError(ValueError):
    pass


def _energy_at(grid: BeatGrid, second: Fraction) -> str:
    for section in grid.sections:
        if Fraction(str(section["start"])) <= second < Fraction(str(section["end"])):
            return str(section["energy"])
    return "medium"


def _preferred_categories(progress: float) -> tuple[str, ...]:
    if progress < 0.10:
        return ("venue", "detail")
    if progress < 0.28:
        return ("bride", "groom", "detail")
    if progress < 0.42:
        return ("family", "ceremony", "venue")
    if progress < 0.62:
        return ("ceremony", "couple", "family")
    if progress < 0.82:
        return ("couple", "bride", "groom")
    if progress < 0.95:
        return ("party", "family", "couple")
    return ("couple", "venue", "detail")


def _preferred_scales(progress: float) -> tuple[str, ...]:
    if progress < 0.15:
        return ("wide", "medium", "detail")
    if progress < 0.75:
        return ("medium", "close_up", "wide", "detail")
    return ("wide", "close_up", "medium", "detail")


def _beats_per_cut(energy: str, style_profile: Mapping[str, object] | None = None) -> int:
    defaults = {"low": 4, "medium": 2, "high": 1}
    configured = style_profile and style_profile.get("beats_per_cut")
    if isinstance(configured, dict):
        value = configured.get(energy)
        if isinstance(value, (int, float)):
            return max(1, min(16, round(value)))
    return defaults.get(energy, 2)


def _duration_from_beats(
    grid: BeatGrid,
    start: Fraction,
    energy: str,
    style_profile: Mapping[str, object] | None = None,
) -> Fraction:
    future = [beat for beat in grid.beats if beat > start]
    desired_index = _beats_per_cut(energy, style_profile) - 1
    if len(future) > desired_index:
        return future[desired_index] - start
    return {"low": Fraction(14, 5), "medium": Fraction(9, 5), "high": Fraction(9, 10)}.get(
        energy, Fraction(9, 5)
    )


def _available_duration(shot: Shot) -> Fraction:
    handle = min(shot.source_range.duration_frames // 8, shot.source_range.rate.frames_from_seconds(Fraction(1, 5)))
    usable = max(0, shot.source_range.duration_frames - handle * 2)
    return shot.source_range.rate.seconds_from_frames(usable)


def _remaining_source_frames(shot: Shot, consumed_frames: int) -> int:
    rate = shot.source_range.rate
    handle = min(shot.source_range.duration_frames // 8, rate.frames_from_seconds(Fraction(1, 5)))
    return max(0, shot.source_range.duration_frames - handle * 2 - consumed_frames)


def _source_range_for_duration(
    shot: Shot,
    wanted: Fraction,
    *,
    consumed_frames: int = 0,
) -> TimeRange | None:
    rate = shot.source_range.rate
    handle = min(shot.source_range.duration_frames // 8, rate.frames_from_seconds(Fraction(1, 5)))
    usable = _remaining_source_frames(shot, consumed_frames)
    requested_frames = rate.frames_from_seconds(wanted, rounding="nearest")
    frames = min(usable, requested_frames)
    minimum = min(rate.frames_from_seconds(Fraction(1, 2), rounding="ceil"), requested_frames)
    if frames < minimum:
        return None
    return TimeRange(shot.source_range.start_frame + handle + consumed_frames, frames, rate)


def _score_candidate(
    shot: Shot,
    *,
    preferred_categories: tuple[str, ...],
    preferred_scales: tuple[str, ...],
    energy: str,
    recent: tuple[TimelineItem, ...],
    desired_duration: Fraction,
    random_jitter: float,
) -> tuple[float, dict[str, float]]:
    category_rank = preferred_categories.index(shot.category) if shot.category in preferred_categories else -1
    raw_story_relevance = (1.0, 0.85, 0.7)[category_rank] if 0 <= category_rank < 3 else 0.35
    semantic_trust = max(0.4, min(1.0, shot.confidence * 2.0))
    story_relevance = 0.35 + (raw_story_relevance - 0.35) * semantic_trust
    style_fit = 1.0 if shot.shot_scale in preferred_scales else 0.4
    target_motion = {"low": 0.3, "medium": 0.55, "high": 0.78}.get(energy, 0.55)
    music_fit = max(0.0, 1.0 - abs(shot.motion_score - target_motion))
    sequence_continuity = 1.0
    duplicate_penalty = 0.0
    jump_cut_penalty = 0.0
    previous = recent[-1] if recent else None
    if previous is not None:
        if previous.shot.category == shot.category and previous.shot.shot_scale == shot.shot_scale:
            jump_cut_penalty = 0.28
        elif previous.shot.category == shot.category:
            jump_cut_penalty = 0.16
        if previous.shot.asset_id == shot.asset_id:
            jump_cut_penalty += 0.30
        if previous.shot.duplicate_group and previous.shot.duplicate_group == shot.duplicate_group:
            duplicate_penalty = 0.65
        sequence_continuity = 0.8 if jump_cut_penalty else 1.0
    recent_category_count = sum(item.shot.category == shot.category for item in recent)
    jump_cut_penalty += 0.09 * recent_category_count
    available = _available_duration(shot)
    duration_fit = max(0.0, 1.0 - float(abs(available - desired_duration) / max(desired_duration, Fraction(1, 2))))
    music_fit = music_fit * 0.7 + duration_fit * 0.3
    score = (
        0.25 * shot.technical_quality
        + 0.20 * shot.aesthetic_score
        + 0.20 * story_relevance
        + 0.15 * music_fit
        + 0.10 * style_fit
        + 0.10 * sequence_continuity
        - duplicate_penalty
        - jump_cut_penalty
        + random_jitter
    )
    return score, {
        "technical_quality": shot.technical_quality,
        "aesthetic_score": shot.aesthetic_score,
        "story_relevance": story_relevance,
        "music_fit": music_fit,
        "style_fit": style_fit,
        "sequence_continuity": sequence_continuity,
        "duplicate_penalty": duplicate_penalty,
        "jump_cut_penalty": jump_cut_penalty,
    }


def build_timeline(
    *,
    project_id: str,
    assets: Iterable[MediaAsset],
    shots: Iterable[Shot],
    music: BeatGrid,
    frame_rate: FrameRate,
    target_duration: Fraction,
    style_profile: Mapping[str, object] | None = None,
    seed: int = 1,
    name: str = "AI Rough Cut",
) -> TimelinePlan:
    """Plan a varied edit and retain each score's human-readable rationale."""
    if target_duration < MIN_TARGET_DURATION:
        raise ValueError("Hedef süre v0.1 için en az 120 saniye olmalıdır.")
    if music.duration < target_duration:
        raise ValueError("Seçilen müzik hedef süreden kısa; müzik edit noktası seçin veya hedefi azaltın.")
    asset_by_id = {asset.id: asset for asset in assets}
    candidates = [shot for shot in shots if shot.asset_id in asset_by_id and _available_duration(shot) >= Fraction(1, 2)]
    if not candidates:
        raise InsufficientFootageError("Kullanılabilir shot adayı bulunamadı.")
    total_candidate_duration = sum((_available_duration(shot) for shot in candidates), Fraction(0, 1))
    if total_candidate_duration < target_duration:
        raise InsufficientFootageError(
            f"Yeterli benzersiz görüntü yok: {float(total_candidate_duration):.1f} sn kullanılabilir, "
            f"{float(target_duration):.1f} sn gerekli."
        )

    rng = random.Random(seed)
    plan = TimelinePlan(
        id=str(uuid.uuid4()),
        project_id=project_id,
        name=name,
        frame_rate=frame_rate,
        target_duration=target_duration,
        seed=seed,
    )
    reference_count = style_profile and style_profile.get("reference_count")
    if isinstance(reference_count, int) and reference_count > 0:
        plan.warnings.append(f"{reference_count} referanstan çıkarılan 7Film ritim profili uygulandı.")
    target_frames = frame_rate.frames_from_seconds(target_duration)
    current_frame = 0
    unused = list(candidates)
    consumed_source_frames = {shot.id: 0 for shot in candidates}

    while current_frame < target_frames:
        if not unused:
            unused = [
                shot
                for shot in candidates
                if frame_rate.frames_from_seconds(
                    shot.source_range.rate.seconds_from_frames(
                        _remaining_source_frames(shot, consumed_source_frames[shot.id])
                    ),
                    rounding="nearest",
                )
                > 0
            ]
            if not unused:
                break
        remaining_frames = target_frames - current_frame
        current_time = frame_rate.seconds_from_frames(current_frame)
        progress = current_frame / target_frames
        energy = _energy_at(music, current_time)
        desired = _duration_from_beats(music, current_time, energy, style_profile)
        desired = frame_rate.seconds_from_frames(
            max(1, frame_rate.frames_from_seconds(desired, rounding="nearest"))
        )
        preferred_categories = _preferred_categories(progress)
        preferred_scales = _preferred_scales(progress)
        ranked: list[tuple[float, Shot, dict[str, float]]] = []
        for shot in unused:
            score, components = _score_candidate(
                shot,
                preferred_categories=preferred_categories,
                preferred_scales=preferred_scales,
                energy=energy,
                recent=tuple(plan.items[-4:]),
                desired_duration=desired,
                random_jitter=rng.uniform(-0.015, 0.015),
            )
            ranked.append((score, shot, components))
        ranked.sort(key=lambda candidate: candidate[0], reverse=True)
        selected_score, selected_shot, components = ranked[0]
        remaining_seconds = frame_rate.seconds_from_frames(remaining_frames)
        remaining_source_seconds = selected_shot.source_range.rate.seconds_from_frames(
            _remaining_source_frames(selected_shot, consumed_source_frames[selected_shot.id])
        )
        requested_duration = min(desired, remaining_seconds, remaining_source_seconds)
        source_range = _source_range_for_duration(
            selected_shot,
            requested_duration,
            consumed_frames=consumed_source_frames[selected_shot.id],
        )
        if source_range is None:
            unused.remove(selected_shot)
            continue
        timeline_duration = min(
            remaining_frames,
            frame_rate.frames_from_seconds(source_range.duration_seconds, rounding="nearest"),
        )
        if timeline_duration <= 0:
            unused.remove(selected_shot)
            continue
        timeline_range = TimeRange(current_frame, timeline_duration, frame_rate)
        alternatives = tuple(candidate[1].id for candidate in ranked[1:4])
        component_summary = ", ".join(
            f"{key}={value:.2f}" for key, value in components.items() if value not in (0.0, 1.0)
        )
        reason = (
            f"{selected_shot.category}/{selected_shot.shot_scale}; {energy} enerjiye ve beat aralığına uygun. "
            f"Skor bileşenleri: {component_summary or 'temel kalite ve stil eşleşmesi güçlü'}"
        )
        item = TimelineItem(
            id=str(uuid.uuid4()),
            shot=selected_shot,
            asset=asset_by_id[selected_shot.asset_id],
            source_range=source_range,
            timeline_range=timeline_range,
            score=round(selected_score, 4),
            selection_reason=reason,
            alternatives=alternatives,
        )
        plan.items.append(item)
        current_frame += timeline_duration
        consumed_source_frames[selected_shot.id] += source_range.duration_frames
        unused.remove(selected_shot)

    if current_frame < target_frames:
        available_seconds = frame_rate.seconds_from_frames(current_frame)
        raise InsufficientFootageError(
            f"Kaba kurgu hedef süresine erişemedi: {float(available_seconds):.1f} sn oluşturuldu. "
            "Hedef süreyi azaltın veya daha fazla görüntü ekleyin."
        )
    if plan.duration != target_duration:
        plan.warnings.append("Son plan kare sınırına yuvarlandı; süre hedefe en yakın frame-accurate değerdedir.")
    return plan


def persist_timeline(database: Database, plan: TimelinePlan) -> None:
    database.insert(
        "timeline_versions",
        {
            "id": plan.id,
            "project_id": plan.project_id,
            "name": plan.name,
            "target_duration_seconds": str(plan.target_duration),
            "frame_rate": f"{plan.frame_rate.numerator}/{plan.frame_rate.denominator}",
            "seed": plan.seed,
            "warnings_json": plan.warnings,
            "created_at": now(),
        },
    )
    for position, item in enumerate(plan.items):
        database.insert(
            "timeline_items",
            {
                "id": item.id,
                "timeline_id": plan.id,
                "position": position,
                "shot_id": item.shot.id,
                "asset_id": item.asset.id,
                "source_start_frame": item.source_range.start_frame,
                "source_duration_frames": item.source_range.duration_frames,
                "source_rate": f"{item.source_range.rate.numerator}/{item.source_range.rate.denominator}",
                "timeline_start_frame": item.timeline_range.start_frame,
                "timeline_duration_frames": item.timeline_range.duration_frames,
                "score": item.score,
                "reason": item.selection_reason,
                "alternatives_json": list(item.alternatives),
            },
        )


def _clamped_source_range(start_frame: int, duration_frames: int, rate: FrameRate, asset_duration: Fraction) -> TimeRange:
    """Keep a persisted source range inside the media the NLE will actually see.

    ffprobe and PySceneDetect frame counts run a frame or two long on VFR and long-GOP camera
    files. Resolve rejects an entire AppendToTimeline batch when a single item points past the
    media, so the range is clamped here, at the one place every export and adapter reads from.
    """
    available = rate.frames_from_seconds(asset_duration, rounding="floor")
    if available <= 0:
        return TimeRange(0, max(1, duration_frames), rate)
    start = max(0, min(start_frame, available - 1))
    duration = max(1, min(duration_frames, available - start))
    return TimeRange(start, duration, rate)


def get_timeline(database: Database, timeline_id: str) -> TimelinePlan:
    header = database.fetch_one("SELECT * FROM timeline_versions WHERE id = ?", (timeline_id,))
    if header is None:
        raise KeyError(f"Timeline bulunamadı: {timeline_id}")
    rate = FrameRate.parse(header["frame_rate"])
    music = database.fetch_one(
        "SELECT path, duration_seconds FROM music_tracks WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
        (header["project_id"],),
    )
    music_path = Path(music["path"]) if music else None
    music_duration = Fraction(music["duration_seconds"]) if music else None

    plan = TimelinePlan(
        id=header["id"],
        project_id=header["project_id"],
        name=header["name"],
        frame_rate=rate,
        target_duration=Fraction(header["target_duration_seconds"]),
        warnings=json.loads(header["warnings_json"]),
        seed=int(header["seed"]),
        music_path=music_path,
        music_duration=music_duration,
    )
    rows = database.fetch_all(
        """SELECT timeline_items.*, shots.category, shots.shot_scale, shots.technical_quality,
                  shots.aesthetic_score, shots.motion_score, shots.confidence, shots.duplicate_group,
                  shots.labels_json, media_assets.project_id, media_assets.path, media_assets.file_name,
                  media_assets.duration_seconds, media_assets.frame_rate AS asset_rate,
                  media_assets.width, media_assets.height, media_assets.codec, media_assets.timecode,
                  media_assets.content_hash
           FROM timeline_items
           JOIN shots ON shots.id = timeline_items.shot_id
           JOIN media_assets ON media_assets.id = timeline_items.asset_id
           WHERE timeline_items.timeline_id = ? ORDER BY timeline_items.position""",
        (timeline_id,),
    )
    for row in rows:
        source_rate = FrameRate.parse(row["source_rate"])
        asset = MediaAsset(
            id=row["asset_id"], project_id=row["project_id"], path=Path(row["path"]),
            name=row["file_name"], duration=Fraction(row["duration_seconds"]),
            frame_rate=FrameRate.parse(row["asset_rate"]), width=int(row["width"]), height=int(row["height"]),
            codec=row["codec"], timecode=row["timecode"], content_hash=row["content_hash"],
        )
        source_range = _clamped_source_range(
            int(row["source_start_frame"]), int(row["source_duration_frames"]), source_rate, asset.duration
        )
        shot = Shot(
            id=row["shot_id"], asset_id=row["asset_id"],
            source_range=source_range,
            category=row["category"], shot_scale=row["shot_scale"],
            technical_quality=float(row["technical_quality"]), aesthetic_score=float(row["aesthetic_score"]),
            motion_score=float(row["motion_score"]), confidence=float(row["confidence"]),
            duplicate_group=row["duplicate_group"], labels=tuple(json.loads(row["labels_json"])),
        )
        plan.items.append(TimelineItem(
            id=row["id"], shot=shot, asset=asset, source_range=source_range,
            timeline_range=TimeRange(int(row["timeline_start_frame"]), int(row["timeline_duration_frames"]), rate),
            score=float(row["score"]), selection_reason=row["reason"],
            alternatives=tuple(json.loads(row["alternatives_json"])),
        ))
    return plan
