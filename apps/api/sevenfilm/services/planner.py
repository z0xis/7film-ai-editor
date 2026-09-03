"""Explainable, constraint-aware v0.1 rough-cut planner."""

from __future__ import annotations

import json
import random
import uuid
from bisect import bisect_left
from collections.abc import Iterable, Mapping, Sequence
from fractions import Fraction
from pathlib import Path

from ..db import Database, now
from ..domain import BeatGrid, MediaAsset, Shot, TimelineItem, TimelinePlan
from ..timebase import FrameRate, TimeRange

MIN_TARGET_DURATION = Fraction(120, 1)
# An editor never cuts to a smeared or blown out frame, whatever the semantic model called it:
# CLIP reads a large white blurry area as a bride. These are hard gates, not score components.
# Raw camera footage is ungraded and measures far below a finished, graded reference edit, so
# an absolute quality bar throws away usable material: on real project footage the best shot
# scores under 0.5 and a third of the shoot falls under 0.35. Only genuinely unusable frames
# are rejected outright, and the working bar is set relative to what this shoot looks like.
ABSOLUTE_MIN_QUALITY = 0.15
RELATIVE_MIN_QUALITY = 0.6
MAX_HIGHLIGHT_CLIPPING = 0.25
# How far from this shoot's own look a shot may sit before it stops matching, and how much
# harder being brighter than typical counts: blowing out is the failure mode, which the
# references confirm by sitting well below any blown highlight.
VISUAL_SPREAD = 0.35
OVERBRIGHT_WEIGHT = 1.5
# One detected shot usually covers a long take that still holds several usable segments.
# Taking another segment from a strong clip costs this much, which keeps the edit varied while
# letting a good clip beat a weaker clip's first appearance instead of marching through every
# shot in turn regardless of how it scored.
REUSE_PENALTY = 0.22


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


# analyze_references.py measures each reference edit in four equal quarters, so the planner
# reads its pacing back out of the profile on exactly the same boundaries.
REFERENCE_SECTIONS = ("intro", "build", "core", "finale")
# Fallbacks when the profile carries no shot length spread: a calm passage holds roughly half
# again as long as the median cut, a driving one runs about two thirds of it.
DEFAULT_ENERGY_SCALE = {"low": Fraction(3, 2), "medium": Fraction(1, 1), "high": Fraction(2, 3)}
# Beat-derived cuts are capped at this multiple of the reference length. Past it the grid is
# too sparse to cut to - a rubato or half time passage - and holding a dead shot to stay on it
# would be worse than cutting at the length the references hold.
MAX_BEAT_HOLD_FACTOR = 2
# The shortest cut allowed anywhere except the final frames of the edit. A shot whose source is
# nearly used up used to contribute its one remaining frame as a cut, which shows up as a flash.
# A quarter second still allows a one-beat cut at any tempo up to 240 BPM.
MIN_CUT_SECONDS = Fraction(1, 4)
BEAT_TOLERANCE = Fraction(3, 25)  # 120 ms, the tolerance the reference profile reports.


def _reference_section_duration(
    style_profile: Mapping[str, object] | None, progress: float
) -> Fraction | None:
    """The median shot length the references hold at this point of the edit."""
    if not style_profile:
        return None
    sections = style_profile.get("section_median_shot_duration_seconds")
    if not isinstance(sections, Mapping):
        return None
    name = REFERENCE_SECTIONS[min(3, int(progress * 4))]
    value = sections.get(name)
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    return Fraction(str(value))


def _energy_scale(style_profile: Mapping[str, object] | None, energy: str) -> Fraction:
    """How much the music's energy stretches or compresses the reference shot length."""
    median = style_profile.get("median_shot_duration_seconds") if style_profile else None
    low = style_profile.get("shot_duration_p75_seconds") if style_profile else None
    high = style_profile.get("shot_duration_p25_seconds") if style_profile else None
    if all(isinstance(value, (int, float)) and value > 0 for value in (median, low, high)):
        measured = {
            "low": Fraction(str(low)) / Fraction(str(median)),
            "medium": Fraction(1, 1),
            "high": Fraction(str(high)) / Fraction(str(median)),
        }
        return measured.get(energy, Fraction(1, 1))
    return DEFAULT_ENERGY_SCALE.get(energy, Fraction(1, 1))


def _preferred_cut_seconds(
    style_profile: Mapping[str, object] | None, progress: float, energy: str
) -> Fraction | None:
    base = _reference_section_duration(style_profile, progress)
    if base is None:
        return None
    return base * _energy_scale(style_profile, energy)


def _section_beats_per_cut(
    style_profile: Mapping[str, object] | None, progress: float, energy: str
) -> int:
    """How many beats a cut lasts here, in beats rather than seconds.

    The references were measured at their own tempo, so their pacing only transfers to another
    song when it is expressed on the beat grid: two beats is two beats at any BPM, while "one
    second" is a fast cut at 80 BPM and a slow one at 160. The seconds the references hold per
    section modulate that beat count around the median.
    """
    base = _beats_per_cut(energy, style_profile)
    section = _reference_section_duration(style_profile, progress)
    median = style_profile.get("median_shot_duration_seconds") if style_profile else None
    if section is None or not isinstance(median, (int, float)) or median <= 0:
        return base
    return max(1, round(base * section / Fraction(str(median))))


def _duration_from_beats(
    grid: BeatGrid,
    start: Fraction,
    energy: str,
    style_profile: Mapping[str, object] | None = None,
    progress: float = 0.0,
) -> Fraction:
    """Hold for a whole number of beats, which is what makes an edit feel cut to the music.

    When the grid is too sparse for that to be musical - the next beats are seconds away - the
    cut takes the length the references hold instead of sitting on a dead shot.
    """
    fallback = {"low": Fraction(14, 5), "medium": Fraction(9, 5), "high": Fraction(9, 10)}.get(
        energy, Fraction(9, 5)
    )
    preferred = _preferred_cut_seconds(style_profile, progress, energy)
    # Cut positions are rounded to whole frames, so the current position often sits a frame or
    # two before the beat it was cut on. Counting that beat as "the next one" asks for a cut a
    # single frame long, which is where the one frame flashes in the timeline came from.
    future = [beat for beat in grid.beats if beat - start >= MIN_CUT_SECONDS]
    beats_per_cut = _section_beats_per_cut(style_profile, progress, energy)
    if len(future) >= beats_per_cut:
        duration = future[beats_per_cut - 1] - start
        limit = (preferred if preferred is not None else fallback) * MAX_BEAT_HOLD_FACTOR
        if duration <= limit:
            return duration
    return preferred if preferred is not None else fallback


def beat_alignment_ratio(
    plan: TimelinePlan, grid: BeatGrid, tolerance: Fraction = BEAT_TOLERANCE
) -> float:
    """The share of cuts landing within tolerance of a beat, as the reference analyzer counts."""
    cuts = [item.timeline_range.start_seconds for item in plan.items[1:]]
    if not cuts or not grid.beats:
        return 0.0
    beats = sorted(grid.beats)
    aligned = 0
    for cut in cuts:
        index = bisect_left(beats, cut)
        neighbours = beats[max(0, index - 1) : min(len(beats), index + 1)]
        if min(abs(cut - beat) for beat in neighbours) <= tolerance:
            aligned += 1
    return aligned / len(cuts)


def _quality_gates(
    style_profile: Mapping[str, object] | None, shots: Sequence[Shot]
) -> tuple[float, float]:
    """The quality bar for this shoot, and the highlight clipping ceiling.

    The bar is a fraction of what this footage actually achieves, never below the absolute
    floor for frames no editor could use. A style profile may override either.
    """
    configured = style_profile.get("minimum_technical_quality") if style_profile else None
    maximum = style_profile.get("maximum_highlight_clipping") if style_profile else None
    ceiling = float(maximum) if isinstance(maximum, (int, float)) else MAX_HIGHLIGHT_CLIPPING
    if isinstance(configured, (int, float)):
        return float(configured), ceiling
    qualities = sorted(shot.technical_quality for shot in shots)
    if not qualities:
        return ABSOLUTE_MIN_QUALITY, ceiling
    typical = qualities[len(qualities) // 2]
    return max(ABSOLUTE_MIN_QUALITY, typical * RELATIVE_MIN_QUALITY), ceiling


def _visual_baseline(shots: Sequence[Shot]) -> tuple[float, float] | None:
    """What this shoot typically looks like, against which an outlier frame stands out."""
    measured = [shot for shot in shots if shot.has_visual_measurements]
    if not measured:
        return None
    brightness = sorted(shot.brightness for shot in measured)
    saturation = sorted(shot.saturation for shot in measured)
    return brightness[len(brightness) // 2], saturation[len(saturation) // 2]


def _is_usable(shot: Shot, minimum_quality: float, maximum_clipping: float) -> bool:
    """Reject unusable footage outright instead of letting a good score outvote it."""
    if shot.technical_quality < minimum_quality:
        return False
    return not (shot.has_visual_measurements and shot.highlight_clipping > maximum_clipping)


def _reference_brightness(style_profile: Mapping[str, object] | None) -> float | None:
    profile = style_profile.get("visual_profile") if style_profile else None
    reference = profile.get("mean_brightness") if isinstance(profile, Mapping) else None
    return float(reference) if isinstance(reference, (int, float)) else None


def _reference_visual_fit(
    shot: Shot,
    baseline: tuple[float, float] | None,
    style_profile: Mapping[str, object] | None,
) -> float:
    """How well a shot's look matches what this edit should be made of.

    Brightness carries across from a graded reference edit to raw footage - measured on the
    project's own material it sits at 0.37 against the references' 0.35 - so it is compared
    with the references directly, which keeps the judgement steady even on a shoot where half
    the frames are blown out. Saturation does not carry across, because grading is most of it,
    so it is compared with this shoot's own median instead. Being brighter than the target
    counts harder: that is the blown out, out of focus frame a semantic model calls a bride.
    """
    if baseline is None or not shot.has_visual_measurements:
        return 1.0
    baseline_brightness, baseline_saturation = baseline
    target_brightness = _reference_brightness(style_profile)
    if target_brightness is None:
        target_brightness = baseline_brightness
    brightness_distance = abs(shot.brightness - target_brightness) / VISUAL_SPREAD
    if shot.brightness > target_brightness:
        brightness_distance *= OVERBRIGHT_WEIGHT
    saturation_distance = abs(shot.saturation - baseline_saturation) / VISUAL_SPREAD
    return max(
        0.0,
        1.0 - (0.6 * min(1.0, brightness_distance) + 0.4 * min(1.0, saturation_distance)),
    )


def _reference_duration_bounds(
    style_profile: Mapping[str, object] | None,
) -> tuple[Fraction, Fraction] | None:
    """The p25/p75 shot lengths measured across the reference edits, when available."""
    if not style_profile:
        return None
    low = style_profile.get("shot_duration_p25_seconds")
    high = style_profile.get("shot_duration_p75_seconds")
    if not isinstance(low, (int, float)) or not isinstance(high, (int, float)):
        return None
    if low <= 0 or high < low:
        return None
    return Fraction(str(low)), Fraction(str(high))


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
    allow_short: bool = False,
) -> TimeRange | None:
    """Take the wanted length from a shot, or nothing if what is left is too short to cut to.

    allow_short is set only for the last cut of the edit, where a few frames are all that is
    needed to reach the target; anywhere else a stub would land in the timeline as a flash.
    """
    rate = shot.source_range.rate
    handle = min(shot.source_range.duration_frames // 8, rate.frames_from_seconds(Fraction(1, 5)))
    usable = _remaining_source_frames(shot, consumed_frames)
    requested_frames = rate.frames_from_seconds(wanted, rounding="nearest")
    frames = min(usable, requested_frames)
    minimum = rate.frames_from_seconds(MIN_CUT_SECONDS, rounding="ceil")
    if allow_short:
        minimum = min(minimum, requested_frames)
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
    style_profile: Mapping[str, object] | None = None,
    reuse_count: int = 0,
    visual_baseline: tuple[float, float] | None = None,
) -> tuple[float, dict[str, float]]:
    category_rank = preferred_categories.index(shot.category) if shot.category in preferred_categories else -1
    raw_story_relevance = (1.0, 0.85, 0.7)[category_rank] if 0 <= category_rank < 3 else 0.35
    semantic_trust = max(0.4, min(1.0, shot.confidence * 2.0))
    story_relevance = 0.35 + (raw_story_relevance - 0.35) * semantic_trust
    # style_fit is "does this look like a 7Film shot": the preferred scale for this point in
    # the story, and the brightness and saturation measured across the reference edits.
    scale_fit = 1.0 if shot.shot_scale in preferred_scales else 0.4
    visual_fit = _reference_visual_fit(shot, visual_baseline, style_profile)
    style_fit = 0.5 * scale_fit + 0.5 * visual_fit
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
    reuse_penalty = REUSE_PENALTY * reuse_count
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
        - reuse_penalty
        + random_jitter
    )
    return score, {
        "technical_quality": shot.technical_quality,
        "aesthetic_score": shot.aesthetic_score,
        "story_relevance": story_relevance,
        "music_fit": music_fit,
        "style_fit": style_fit,
        "reference_visual_fit": visual_fit,
        "sequence_continuity": sequence_continuity,
        "duplicate_penalty": duplicate_penalty,
        "jump_cut_penalty": jump_cut_penalty,
        "reuse_penalty": reuse_penalty,
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
    long_enough = [
        shot for shot in shots
        if shot.asset_id in asset_by_id and _available_duration(shot) >= Fraction(1, 2)
    ]
    if not long_enough:
        raise InsufficientFootageError("Kullanılabilir shot adayı bulunamadı.")
    minimum_quality, maximum_clipping = _quality_gates(style_profile, long_enough)
    good = [shot for shot in long_enough if _is_usable(shot, minimum_quality, maximum_clipping)]
    good_duration = sum((_available_duration(shot) for shot in good), Fraction(0, 1))
    rejected_count = len(long_enough) - len(good)
    # Prefer usable footage. Only fall back to the rejected shots when there is genuinely not
    # enough good material for the target, and then say so rather than quietly filling time.
    if good_duration >= target_duration:
        candidates = good
        if rejected_count:
            plan_warning = (
                f"{rejected_count} plan teknik kalite eşiğinin altında kaldığı için "
                "(bulanık, patlamış beyaz veya düz kare) kurguya alınmadı."
            )
        else:
            plan_warning = None
    else:
        candidates = long_enough
        plan_warning = (
            f"Kalite eşiğini geçen görüntü hedef süreyi doldurmuyor "
            f"({float(good_duration):.1f} sn / {float(target_duration):.1f} sn); "
            f"{rejected_count} düşük kaliteli plan da kullanıldı. Hedefi kısaltmayı düşünün."
        ) if rejected_count else None
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
    if plan_warning:
        plan.warnings.append(plan_warning)
    reference_count = style_profile and style_profile.get("reference_count")
    if isinstance(reference_count, int) and reference_count > 0:
        plan.warnings.append(f"{reference_count} referanstan çıkarılan 7Film ritim profili uygulandı.")
    target_frames = frame_rate.frames_from_seconds(target_duration)
    minimum_cut_frames = frame_rate.frames_from_seconds(MIN_CUT_SECONDS, rounding="ceil")
    visual_baseline = _visual_baseline(candidates)
    current_frame = 0
    consumed_source_frames = {shot.id: 0 for shot in candidates}
    usage_count = {shot.id: 0 for shot in candidates}
    exhausted: set[str] = set()

    while current_frame < target_frames:
        # Every shot that still has unused source stays in the running, ranked on merit. A shot
        # already in the edit carries a reuse penalty rather than being locked out, so a second
        # segment of a strong clip can win over a weaker clip that has not been used yet.
        available_shots = [shot for shot in candidates if shot.id not in exhausted]
        if not available_shots:
            break
        remaining_frames = target_frames - current_frame
        current_time = frame_rate.seconds_from_frames(current_frame)
        progress = current_frame / target_frames
        energy = _energy_at(music, current_time)
        desired = _duration_from_beats(music, current_time, energy, style_profile, progress)
        desired = frame_rate.seconds_from_frames(
            max(1, frame_rate.frames_from_seconds(desired, rounding="nearest"))
        )
        preferred_categories = _preferred_categories(progress)
        preferred_scales = _preferred_scales(progress)
        ranked: list[tuple[float, Shot, dict[str, float]]] = []
        for shot in available_shots:
            score, components = _score_candidate(
                shot,
                preferred_categories=preferred_categories,
                preferred_scales=preferred_scales,
                energy=energy,
                recent=tuple(plan.items[-4:]),
                desired_duration=desired,
                random_jitter=rng.uniform(-0.015, 0.015),
                style_profile=style_profile,
                reuse_count=usage_count[shot.id],
                visual_baseline=visual_baseline,
            )
            ranked.append((score, shot, components))
        ranked.sort(key=lambda candidate: candidate[0], reverse=True)
        selected_score, selected_shot, components = ranked[0]
        remaining_seconds = frame_rate.seconds_from_frames(remaining_frames)
        if remaining_frames - frame_rate.frames_from_seconds(desired) < minimum_cut_frames:
            # Take the whole tail now rather than leaving a stub for the next cut to pick up.
            desired = remaining_seconds
        remaining_source_seconds = selected_shot.source_range.rate.seconds_from_frames(
            _remaining_source_frames(selected_shot, consumed_source_frames[selected_shot.id])
        )
        requested_duration = min(desired, remaining_seconds, remaining_source_seconds)
        source_range = _source_range_for_duration(
            selected_shot,
            requested_duration,
            consumed_frames=consumed_source_frames[selected_shot.id],
            allow_short=remaining_frames <= minimum_cut_frames,
        )
        if source_range is None:
            exhausted.add(selected_shot.id)
            continue
        timeline_duration = min(
            remaining_frames,
            frame_rate.frames_from_seconds(source_range.duration_seconds, rounding="nearest"),
        )
        if timeline_duration <= 0:
            exhausted.add(selected_shot.id)
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
        usage_count[selected_shot.id] += 1

    if current_frame < target_frames:
        available_seconds = frame_rate.seconds_from_frames(current_frame)
        raise InsufficientFootageError(
            f"Kaba kurgu hedef süresine erişemedi: {float(available_seconds):.1f} sn oluşturuldu. "
            "Hedef süreyi azaltın veya daha fazla görüntü ekleyin."
        )
    if plan.duration != target_duration:
        plan.warnings.append("Son plan kare sınırına yuvarlandı; süre hedefe en yakın frame-accurate değerdedir.")
    _append_rhythm_report(plan, music, style_profile)
    return plan


def _append_rhythm_report(
    plan: TimelinePlan, music: BeatGrid, style_profile: Mapping[str, object] | None
) -> None:
    """Record how the finished plan sits against the music, next to the reference's own figure."""
    if len(plan.items) < 2:
        return
    aligned = beat_alignment_ratio(plan, music)
    reference = style_profile.get("beat_alignment_ratio_120ms") if style_profile else None
    message = f"Kesimlerin %{aligned * 100:.0f}'ı beat'e 120 ms içinde hizalandı"
    if isinstance(reference, (int, float)):
        message += f" (referans kurgular: %{float(reference) * 100:.0f})"
    plan.warnings.append(message + ".")


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
                  shots.labels_json, shots.brightness, shots.saturation, shots.highlight_clipping,
                  media_assets.project_id, media_assets.path, media_assets.file_name,
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
            brightness=float(row["brightness"] or 0.0), saturation=float(row["saturation"] or 0.0),
            highlight_clipping=float(row["highlight_clipping"] or 0.0),
        )
        plan.items.append(TimelineItem(
            id=row["id"], shot=shot, asset=asset, source_range=source_range,
            timeline_range=TimeRange(int(row["timeline_start_frame"]), int(row["timeline_duration_frames"]), rate),
            score=float(row["score"]), selection_reason=row["reason"],
            alternatives=tuple(json.loads(row["alternatives_json"])),
        ))
    return plan
