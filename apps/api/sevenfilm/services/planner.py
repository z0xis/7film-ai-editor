"""Explainable, constraint-aware v0.1 rough-cut planner."""

from __future__ import annotations

import json
import random
import uuid
from bisect import bisect_left
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from typing import Any

from ..db import Database, now
from ..domain import BeatGrid, MediaAsset, MusicSegment, Shot, TimelineItem, TimelinePlan
from ..timebase import FrameRate, TimeRange
from .moments import Moment
from .windows import ShotWindow

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
# One camera file usually holds one long take, and the shot detector cuts it into dozens of
# segments that each look like a fresh candidate. Nothing counted the file, so a 121 second
# take of the cake being cut supplied sixteen of one edit's 137 clips.
#
# Measured on this shoot at 120 seconds, sweeping the value: 0 leaves one file used 5 times,
# 0.03 caps it at 2 across 105 files, 0.06 and above allow each file exactly once. Mean shot
# quality moves from 0.424 to 0.420 over that whole range, so the variety is nearly free.
# 0.03 was chosen there as the one that still lets a genuinely strong clip come back, which is
# what taking a second segment is for. That sweep predates sequences: once the run the edit is
# inside stopped being charged, 0.03 let a cake supply seven of 123 cuts and 28 cuts in all
# were returns. Re-swept with that in place, 0.06 halves the returns to 10 and caps any one
# file at 3, while scene runs hold at 40 and the day's order at 0.84; 0.10 buys three fewer
# returns and costs the chronology.
ASSET_REUSE_PENALTY = 0.06
# Perceptual hashes are compared by Hamming distance, not equality: two frames of the same
# moment differ in a few bits, and the odds of a 64 bit hash matching exactly are nil, which is
# why the duplicate penalty had never once fired. This footage holds 56 pairs within 5 bits and
# 409 within 10, across different files - the kind the same-asset penalty cannot see.
NEAR_DUPLICATE_BITS = 10
DUPLICATE_PENALTY = 0.65


class InsufficientFootageError(ValueError):
    pass


def _energy_at(grid: BeatGrid, second: Fraction) -> str:
    for section in grid.sections:
        if Fraction(str(section["start"])) <= second < Fraction(str(section["end"])):
            return str(section["energy"])
    return "medium"


# What the edit shows and when, used only when the profile carries no measured arc. It was
# written by hand, and against the references it is wrong in places: it gives the middle of the
# film to `ceremony`, which those films spend between 0% and 5% of every band on, and puts
# `detail` at the start, where they have almost none.
FALLBACK_STORY_ARC = (
    (0.10, ("venue", "bride_prep", "detail")),
    (0.28, ("bride_prep", "groom_prep", "bride")),
    (0.42, ("family", "ceremony", "venue")),
    (0.62, ("ceremony", "couple", "family")),
    (0.82, ("couple", "bride", "groom")),
    (0.95, ("party", "family", "couple")),
    (1.01, ("couple", "venue", "detail")),
)
# How many categories a band puts forward. _score_candidate ranks the first three and treats
# everything else alike, so a longer list would change nothing.
STORY_CATEGORIES_PER_BAND = 3
# A category has to hold at least this much of the film overall before its concentration in one
# band means anything: a category seen twice in total will show a huge lift somewhere by chance.
MEANINGFUL_CATEGORY_SHARE = 0.005
# How far above its own average a category has to sit in a band to count as what that band is
# about, rather than something present everywhere.
CHARACTERISTIC_LIFT = 1.2


def _band_preferences(bands: Sequence[Mapping[str, object]], index: int) -> tuple[str, ...]:
    """What this part of the film is about: its backbone, and what it alone leans on.

    Ranking a band purely by share names the same categories everywhere, because the couple is
    the backbone of every band — measured on the references, `couple` is first in all ten. That
    hid the structure completely: the preparation shows up at 1.8% and 4.5% in the second band
    and almost nowhere else, which is the whole reason it exists, and a top-three-by-share rule
    could never see it. Nine good preparation files were indexed, scored above this shoot's
    median, and reached no edit at all.

    So the band keeps its largest category and adds what it favours relative to the rest of the
    film. Across the references that reads as: venue and ceremony to open, the two preparations
    next, details, the ceremony again, the party, and family to close.
    """
    band = bands[index]
    names = sorted({name for other in bands for name in other})
    means = {
        name: sum(float(other.get(name, 0.0)) for other in bands) / len(bands)
        for name in names
    }
    ranked_by_share = sorted(band.items(), key=lambda item: (-float(item[1]), item[0]))
    chosen = [name for name, share in ranked_by_share[:1] if float(share) > 0]
    lifts = sorted(
        (
            (float(band.get(name, 0.0)) / means[name], name)
            for name in names
            if means[name] >= MEANINGFUL_CATEGORY_SHARE and name not in chosen
        ),
        reverse=True,
    )
    for lift, name in lifts:
        if lift < CHARACTERISTIC_LIFT or len(chosen) >= STORY_CATEGORIES_PER_BAND:
            break
        chosen.append(name)
    # Fill out of what the band actually holds, and stop rather than name something the film
    # barely contains: two categories that mean something beat three where one is noise.
    for name, share in ranked_by_share:
        if len(chosen) >= STORY_CATEGORIES_PER_BAND:
            break
        if name not in chosen and float(share) >= MEANINGFUL_CATEGORY_SHARE:
            chosen.append(name)
    return tuple(chosen)


def _preferred_categories(
    progress: float, style_profile: Mapping[str, object] | None = None
) -> tuple[str, ...]:
    """What this point of the edit should be showing.

    Read off the reference films when the profile carries their story arc: each band holds the
    share of frames each category took there, so the categories come out in the order those
    films actually favour at this point. Twelve sampled frames were checked by eye before this
    was trusted — the categories carry across the grade, though the shot scale does not.
    """
    arc = style_profile.get("story_arc") if style_profile else None
    if isinstance(arc, Sequence) and arc:
        bands = [band for band in arc if isinstance(band, Mapping) and band]
        if len(bands) == len(arc):
            chosen = _band_preferences(bands, _band_index(style_profile, progress))
            if chosen:
                return chosen
    for limit, categories in FALLBACK_STORY_ARC:
        if progress < limit:
            return categories
    return FALLBACK_STORY_ARC[-1][1]


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
# A story section whose categories make up less than this much of the footage cannot be built
# from it, however the planner scores. Saying so beats quietly filling the section with
# whatever else was to hand, and the editor is the one who knows whether the coverage is
# really missing or the labels are wrong.
THIN_CATEGORY_SHARE = 0.02
STORY_PROGRESS_POINTS = (0.05, 0.2, 0.35, 0.55, 0.75, 0.9, 0.98)
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


REFERENCE_SECONDS_BY_ENERGY = {
    "low": "shot_duration_p75_seconds",
    "medium": "median_shot_duration_seconds",
    "high": "shot_duration_p25_seconds",
}
# How far the running beat debt may drift before it is simply given up on, so one unusual
# passage cannot go on paying itself back for the rest of the edit.
MAX_BEAT_DEBT = Fraction(2)


def _reference_beats(style_profile: Mapping[str, object] | None, energy: str) -> Fraction | None:
    """The reference pace for this energy, in beats, without rounding it to a whole one.

    The profile also states beats_per_cut, but it rounds: the references' fastest quarter runs
    1.31 beats and is stored as 1, a fifth short. Reading the seconds back against the
    references' own tempo keeps the figure the planner should be aiming at.
    """
    if not style_profile:
        return None
    bpm = style_profile.get("median_reference_bpm")
    seconds = style_profile.get(REFERENCE_SECONDS_BY_ENERGY.get(energy, ""))
    if not isinstance(bpm, (int, float)) or not isinstance(seconds, (int, float)):
        return None
    if bpm <= 0 or seconds <= 0:
        return None
    return Fraction(str(seconds)) * Fraction(str(bpm)) / 60


def _target_beats_per_cut(
    style_profile: Mapping[str, object] | None, progress: float, energy: str
) -> Fraction:
    """How many beats a cut should last here, kept fractional.

    The references were measured at their own tempo, so their pacing only transfers to another
    song when it is expressed on the beat grid: two beats is two beats at any BPM, while "one
    second" is a fast cut at 80 BPM and a slow one at 160. The seconds the references hold per
    section modulate that beat count around the median.
    """
    base = _reference_beats(style_profile, energy)
    if base is None:
        base = Fraction(_beats_per_cut(energy, style_profile))
    section = _reference_section_duration(style_profile, progress)
    median = style_profile.get("median_shot_duration_seconds") if style_profile else None
    if section is None or not isinstance(median, (int, float)) or median <= 0:
        return base
    return base * section / Fraction(str(median))


# How long the film's opening shots run.
#
# Measured on the 18 references, 1219 shots: their first shot runs a median 2.36 seconds and
# the length comes down a step at a time — 2.36, 1.76, 1.26, 1.08 — reaching their own median
# of 1.00 by the fifth. The film arrives, is looked at, and only then starts cutting.
#
# Ours opened at 2.00 and never came down: 2.00, 1.96, 1.10, 0.80, 3.96, 1.96 — no settling,
# and a four second hold landing inside the opening. "klibin intro ve outrosu kötü hatta yok".
#
# Held as seconds rather than beats because that is how they were measured, and turned into a
# multiple of what the pacing already asked for, so it survives another song's tempo and the
# profile's own intro section instead of overriding them.
OPENING_SECONDS = (
    Fraction(59, 25), Fraction(44, 25), Fraction(63, 50), Fraction(27, 25), Fraction(49, 50),
)
# What the film opens on.
#
# Measured across the 18 references, 1219 shots: detail shots make up 40% of their first five
# against 18% of their films, 2.18 times their own weight. Nothing else is lifted — venue 0.91,
# bride 0.86 — and the two categories the opening avoids are the ones ours was opening on:
# couple 0.56 and family 0.49.
OPENING_CATEGORIES = frozenset({"detail"})
# And it opens at the start of the day. The edit runs chronologically, so a detail shot is not
# enough on its own: the first cut of one edit was a cake and glasses at 0.50 of the way
# through the shoot — "direkt pasta kadehten başlamış iyi seçim değil". The chronology penalty
# alone is too soft to keep the opening out of the evening, being 0.2 of a score that a strong
# shot clears easily.
OPENING_DAY_LIMIT = 0.25
# How many of the opening cuts are steered to a detail. The references run two in
# five; one gave us one in five, five gave us five.
OPENING_DETAIL_CUTS = 2
# The rest of the ramp may range further into the day than the first cut, but not
# into the evening.
OPENING_RAMP_DAY_LIMIT = 0.35
# One beat at the references' own median tempo, for a profile that carries no BPM.
REFERENCE_BEAT_SECONDS = Fraction(60, 123)
# How far past the asked-for opening a beat may land and still be taken. Without slack the
# ramp only ever lands on beats at or under its target and the opening comes out short.
OPENING_SLACK = Fraction(3, 2)


def _opening_beats(
    style_profile: Mapping[str, object] | None, wanted: Fraction
) -> Fraction:
    """The opening length in beats, so it carries to a song at another tempo.

    The references were measured in seconds at their own median tempo. Two beats is two beats
    at any BPM; "2.36 seconds" is five beats of a slow song and eight of a fast one.
    """
    bpm = style_profile.get("median_reference_bpm") if style_profile else None
    if not isinstance(bpm, (int, float)) or bpm <= 0:
        return wanted / REFERENCE_BEAT_SECONDS
    return wanted * Fraction(str(bpm)) / 60


def _worthy_shots(shots: Sequence[Shot], hold_bar: float) -> list[Shot]:
    """The shots that can carry a long cut: better than half this shoot, subject readable,
    and not cut by the frame edge."""
    return [
        shot for shot in shots
        if shot.technical_quality >= hold_bar
        and shot.face_edge < 0.5
        and (shot.face_ratio == 0.0 or shot.face_ratio >= READABLE_FACE_RATIO)
    ]


def _beats_for_cut(target: Fraction, debt: Fraction) -> tuple[int, Fraction]:
    """Pick a whole number of beats, carrying the fraction over to the next cut.

    A cut has to land on a beat, so a 1.31 beat target can only ever be one beat or two. Paying
    the remainder forward makes the run of cuts average out to the reference pace instead of
    every one of them being rounded the same way, a fifth short.
    """
    wanted = target + debt
    beats = max(1, int(wanted + Fraction(1, 2)))
    carried = wanted - beats
    return beats, max(-MAX_BEAT_DEBT, min(MAX_BEAT_DEBT, carried))


# A held shot is one the edit simply stays on, past the point where it would normally cut. The
# references spend a quarter of their running time on these and reach nineteen seconds; an edit
# built from cut-length averages alone had none at all, its longest cut 2.48 seconds. They are
# what an entrance, a first look or a slow dance is made of.
HELD_SHOT_SECONDS = Fraction(3)
# Without a measured profile: hold about a sixth of the time, for four seconds, which is the
# references' own median held shot.
DEFAULT_HELD_SHARE = Fraction(1, 6)
DEFAULT_HELD_SECONDS = Fraction(4)
# A held shot still has to end on a beat, and it may not eat more than this much of what is
# left, or one hold in the last stretch swallows the ending.
MAX_HELD_SHARE_OF_REMAINDER = Fraction(1, 3)


def _held_share(style_profile: Mapping[str, object] | None, progress: float) -> Fraction:
    """How much of this part of the edit the references spend on a held shot."""
    held = style_profile.get("held_shots") if style_profile else None
    if not isinstance(held, Mapping):
        return DEFAULT_HELD_SHARE
    shares = held.get("share_by_band")
    if not isinstance(shares, Sequence) or not shares:
        return DEFAULT_HELD_SHARE
    value = shares[min(len(shares) - 1, int(progress * len(shares)))]
    if not isinstance(value, (int, float)) or value <= 0:
        return Fraction(0)
    return Fraction(str(round(float(value), 4)))


def _held_seconds(style_profile: Mapping[str, object] | None, progress: float = 0.0) -> Fraction:
    """How long a hold runs here. The references hold longest at the two ends of a film."""
    held = style_profile.get("held_shots") if style_profile else None
    if not isinstance(held, Mapping):
        return DEFAULT_HELD_SECONDS
    by_band = held.get("median_seconds_by_band")
    if isinstance(by_band, Sequence) and by_band:
        value = by_band[min(len(by_band) - 1, int(progress * len(by_band)))]
        if isinstance(value, (int, float)) and value > 0:
            return Fraction(str(value))
    value = held.get("median_seconds")
    if isinstance(value, (int, float)) and value > 0:
        return Fraction(str(value))
    return DEFAULT_HELD_SECONDS


def _hold_frequency(share: Fraction, held: Fraction, ordinary: Fraction) -> Fraction:
    """Turn a share of the running time into a share of the cuts.

    The references' figure is a proportion of screen time, and a held shot buys far more of
    that than an ordinary cut does. Holding one cut in six, when a hold is four seconds and a
    cut is one, spends 44% of the time held, not 17% — measured, the first attempt came out at
    38% against the references' 25%. Solving f·H = s·(f·H + (1-f)·o) for f gives the frequency
    that actually lands on the share.
    """
    if share <= 0 or held <= 0 or ordinary <= 0:
        return Fraction(0)
    if share >= 1:
        return Fraction(1)
    denominator = held * (1 - share) + share * ordinary
    if denominator <= 0:
        return Fraction(0)
    return min(Fraction(1), share * ordinary / denominator)


def _hold_this_cut(frequency: Fraction, debt: Fraction) -> tuple[bool, Fraction]:
    """Decide by paying the frequency forward, the way the beat count carries its fraction.

    It has to come out right over a run rather than by chance on any one cut, and it has to
    fall in the same places every time the plan is rebuilt.
    """
    wanted = frequency + debt
    if wanted >= 1:
        return True, wanted - 1
    return False, wanted


def _closing_ramp_seconds(
    remaining: Fraction, closing: Fraction
) -> Fraction | None:
    """How long this cut should run if the film is already coming in to land.

    Worked out from what is left rather than from a count of cuts, because how many cuts
    remain is not known until they are made. Everything past the ramp returns None and the
    ordinary pacing decides.
    """
    left = remaining - closing
    if left <= 0:
        return None
    # Counted from the closing shot backwards: the nearer the end, the longer the cut. Summed
    # the other way round the ramp ran in reverse — the film sped up into the ending.
    spent = Fraction(0)
    for length in CLOSING_RAMP:
        spent += length
        if left <= spent:
            return length
    return None


def _held_duration(
    grid: BeatGrid, start: Fraction, wanted: Fraction, remaining: Fraction
) -> Fraction | None:
    """The beat landing closest to the held length, so a long shot still sits on the music.

    It has to be a beat. A four second hold that ends between two beats leaves every cut after
    it off the grid, and the next one comes out at whatever fraction of a beat is left — a
    0.36 second flash in the middle of the edit. When no beat lands in range, there is no hold
    here; the share is carried to a cut where one does.
    """
    # A hold may not swallow a long remainder. Close to the end it may take all of what is
    # left, because there it *is* the ending: the references spend 56% of their last tenth
    # held, and a plain third-of-what-is-left rule made the ending the one place a hold could
    # never happen.
    ending = remaining <= HELD_SHOT_SECONDS * 2
    ceiling = remaining if ending else remaining * MAX_HELD_SHARE_OF_REMAINDER
    if ceiling < HELD_SHOT_SECONDS:
        return None
    target = min(wanted, ceiling)
    landings = [
        beat - start for beat in grid.beats if HELD_SHOT_SECONDS <= beat - start <= ceiling
    ]
    if not landings:
        return None
    return min(landings, key=lambda landing: (abs(landing - target), landing))


def _duration_from_beats(
    grid: BeatGrid,
    start: Fraction,
    energy: str,
    style_profile: Mapping[str, object] | None = None,
    progress: float = 0.0,
    beats_per_cut: int | None = None,
    hold_limit: Fraction | None = None,
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
    if beats_per_cut is None:
        beats_per_cut = _beats_for_cut(
            _target_beats_per_cut(style_profile, progress, energy), Fraction(0)
        )[0]
    if len(future) >= beats_per_cut:
        duration = future[beats_per_cut - 1] - start
        # The limit keeps a cut from sitting on a dead shot when the grid is sparse. A caller
        # that already knows how long this cut should run says so, or asking for more beats
        # past the limit collapses back to `preferred` and comes out *shorter* — which is what
        # the opening ramp did on its first attempt: eight beats gave 1.87 seconds where six
        # gave 3.06.
        limit = hold_limit if hold_limit is not None else (
            (preferred if preferred is not None else fallback) * MAX_BEAT_HOLD_FACTOR
        )
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


def _perceptual_hash(shot: Shot) -> int | None:
    group = shot.duplicate_group or ""
    prefix, _, digits = group.partition(":")
    if prefix != "visual" or not digits:
        return None
    try:
        return int(digits, 16)
    except ValueError:
        return None


def _visual_repeat_penalty(shot: Shot, used: Sequence[int], same_scene: bool = False) -> float:
    """How much this shot looks like one already in the edit, whatever file it came from.

    Falls to nothing at NEAR_DUPLICATE_BITS, so only a shot that genuinely repeats one already
    used is held back; a different angle on the same scene is several times further away.

    This weighs the whole edit, not the last few cuts. Against a four cut window a neon sign
    reading "Daima Aşk ile" came back four times in one 137 clip edit, at positions 37, 41, 48
    and 55 — every repeat just outside the window. A viewer remembers a shot for longer than
    four cuts, so the edit has to as well.
    """
    current = _perceptual_hash(shot)
    if current is None or not used:
        return 0.0
    # Another segment of the clip that just played is the one exception: that is a sequence,
    # and the same moment coming back forty cuts later is the repetition this guards against.
    # Measured on the references, 7% of their consecutive pairs sit above 0.85 semantic
    # similarity against 2% of random pairs — that 7% is the sequences, and charging for them
    # left this edit with 3%. A near-identical frame from a *different* file is still charged:
    # that is a second take cut against the first, which is a jump rather than a sequence.
    history = used[:-1] if same_scene and used else used
    if not history:
        return 0.0
    closest = min((current ^ other).bit_count() for other in history)
    if closest >= NEAR_DUPLICATE_BITS:
        return 0.0
    return DUPLICATE_PENALTY * (1.0 - closest / NEAR_DUPLICATE_BITS)


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


# A wedding film is made of sequences: an entrance, the cake, a table of details. The planner
# used to charge 0.30 for taking the next shot from the same clip and 0.16 for staying on the
# same subject, so it changed both at every single cut — measured on a 117 clip edit, not one
# of its 116 transitions kept either. Measured on the 18 references instead: 29% of consecutive
# shots stay in the same category, a run averages 1.41 shots and reaches 12, and 49% of their
# running time sits inside a run of two or more.
# Staying on a subject is simply allowed up to this many shots, and costs from there on. A
# bonus for staying was tried and rejected by measurement: it locked every sequence to exactly
# the target length, where the references hold a distribution — most runs are one or two shots
# and a few go much further. What actually decides the run length here is the share cap below,
# so this is a ceiling rather than a target: swept from 2 to 6, the figures barely move.
SEQUENCE_TARGET_RUN = 5
SEQUENCE_OVERRUN = 0.05
# What a category already past its measured share of this part of the film costs, per unit of
# share it is over by. A category the references never show at all is still allowed this much
# before it starts costing, so a shoot whose labels disagree with theirs is not locked out.
SHARE_OVERRUN_WEIGHT = 0.9
# How much of that cap still applies while a sequence is running. Swept against the
# references' own figures: 1.00 (no relief) holds consecutive same category at 21% against
# their 29%, 0.85 lands on 31% with a mean run of 1.45 against their 1.41, and 0.60 overshoots
# to 42%. The category spread barely moves across the whole range, so the sequences are close
# to free.
SEQUENCE_SHARE_RELIEF = 0.85
# What staying in the scene is worth while a sequence is running. Swept: 0 lands on the
# references' own figures (8% of consecutive pairs very similar against their 7%, 30% same
# category against their 29%) and the editor still reported no sequence in the film; 0.10
# reaches 69% same category, which is monotony. 0.02 doubles the scene-to-scene continuity —
# 40 adjacent pairs from one scene against 22 — at 41% same category. Deliberately above the
# measured reference, because the reference figure is a floor: the scene detector used to take
# it cannot see a cut *within* a scene, which is exactly what a sequence is made of.
TAKE_CONTINUITY_BONUS = 0.02
MINIMUM_CATEGORY_SHARE = 0.05
# Same subject at the same size back to back reads as a jump rather than as a second look.
JUMP_CUT_PENALTY = 0.18
# A face against the frame edge is a head the frame cuts. Charged in full at the border and
# fading to nothing a twentieth of the frame in, which is where the measurement itself stops.
CUT_HEAD_PENALTY = 0.25
# A face smaller than this fills so little of the frame that the shot is about the room, not
# the people in it — a couple across a hotel atrium measures well under it.
READABLE_FACE_RATIO = 0.004


def _trailing_run(items: Sequence[TimelineItem], category: str) -> int:
    """How many shots of this category the edit is already sitting on, counting back."""
    run = 0
    for item in reversed(items):
        if item.shot.category != category:
            break
        run += 1
    return run


def _is_second_take(
    shot: Shot,
    previous: TimelineItem | None,
    embeddings: Mapping[str, Any],
    *,
    same_scene: bool,
) -> bool:
    """Whether this shot is another take of the one just played rather than its next moment.

    A sequence continues *within* a take, so a shot from the same file is never a second take
    of itself however alike the two look. What this catches is the camera rolling twice on one
    setup and both takes reaching the edit back to back.
    """
    if previous is None or not same_scene or not embeddings:
        return False
    if shot.asset_id == previous.shot.asset_id:
        return False
    here = embeddings.get(shot.id)
    there = embeddings.get(previous.shot.id)
    if here is None or there is None:
        return False
    return float(here @ there) >= SECOND_TAKE_SIMILARITY


def _trailing_asset_run(items: Sequence[TimelineItem], asset_id: str) -> int:
    """How many shots the edit has just taken from this clip without leaving it."""
    run = 0
    for item in reversed(items):
        if item.shot.asset_id != asset_id:
            break
        run += 1
    return run


def _band_index(style_profile: Mapping[str, object] | None, progress: float) -> int:
    """Which band of the measured arc this point of the edit falls in."""
    arc = style_profile.get("story_arc") if style_profile else None
    if not isinstance(arc, Sequence) or not arc:
        return 0
    return min(len(arc) - 1, int(progress * len(arc)))


def _band_shares(style_profile: Mapping[str, object] | None, progress: float) -> Mapping[str, float] | None:
    """The share each category takes at this point of a reference film."""
    arc = style_profile.get("story_arc") if style_profile else None
    if not isinstance(arc, Sequence) or not arc:
        return None
    band = arc[_band_index(style_profile, progress)]
    return band if isinstance(band, Mapping) and band else None


def _share_overrun(
    style_profile: Mapping[str, object] | None,
    progress: float,
    category: str,
    used: Mapping[str, int],
    total: int,
) -> float:
    """How far past its reference share this category already is, in this band of the edit.

    Allowing sequences let the strongest category run away with the film: couple went from 45
    of 116 clips to 67 the moment staying on a subject stopped being charged for. The arc was
    measured as shares — couple 40% of the opening band, venue 21%, bride 18% — and only its
    ranking was being used. Reading the share back keeps a sequence from becoming the film.

    The count is kept over the whole edit, not per band. Per band was tried and measured worse:
    a band's first clips give the share a denominator of one or two, so the second shot of any
    category reads as far past its quota and no sequence can form at all — consecutive same
    category fell from 21% to 3%. Over the whole edit the denominator is large enough for the
    share to mean something.
    """
    shares = _band_shares(style_profile, progress)
    if not shares or total < 1:
        return 0.0
    target = float(shares.get(category, 0.0))
    if target <= 0:
        target = MINIMUM_CATEGORY_SHARE
    return max(0.0, used.get(category, 0) / total - target)


# Two clips recorded within this much of each other are the same moment of the day. The camera
# writes time of day, and the shoot reads straight off it: the bride's makeup is 08:23 to 08:25
# across three files, the groom's preparation 08:26 to 08:29 across four, the cake 08:56, the
# dance 09:09. Without this a sequence could only ever be several shots of one file, so the
# makeup arrived as single clips scattered through the film.
SCENE_WINDOW_SECONDS = 180
# And a scene may not run longer than this, however continuously the camera rolled.
SCENE_SPAN_SECONDS = 300


def _scene_of_asset(assets: Sequence[MediaAsset]) -> dict[str, int]:
    """Group the shoot into scenes by when each clip was recorded.

    A clip with no timecode is its own scene: guessing that it belongs beside its neighbours
    would join two moments that may be hours apart.
    """
    timed: list[tuple[int, str]] = []
    scene_by_asset: dict[str, int] = {}
    next_scene = 0
    for asset in assets:
        seconds = _timecode_seconds(asset)
        if seconds is None:
            scene_by_asset[asset.id] = next_scene
            next_scene += 1
        else:
            timed.append((seconds, asset.id))
    previous = None
    started = None
    for seconds, asset_id in sorted(timed):
        # A gap ends a scene, and so does length. Grouping on the gap alone chained the whole
        # shoot into one scene — a wedding is filmed continuously, so almost every clip starts
        # within three minutes of the one before it, and single-linkage joins them all.
        gap = previous is None or seconds - previous > SCENE_WINDOW_SECONDS
        overlong = started is not None and seconds - started > SCENE_SPAN_SECONDS
        if gap or overlong:
            next_scene += 1
            started = seconds
        scene_by_asset[asset_id] = next_scene
        previous = seconds
    return scene_by_asset


# How far the edit may sit from the moment it is drawing on before the distance is charged.
# The references intercut freely, so a film is not the day played back in order; but a table
# laid before anyone arrived has no business at eighty-four per cent of the running time.
# Swept: at 0.30 six or seven morning shots still closed the film, at 0.15 none did.
# Raised after watching a whole cut as stills rather than reading its correlation. The number
# said 0.79 and looked acceptable; the film went evening, morning, evening — fourteen jumps of
# more than a third of the shooting day in 112 cuts, one of them from 0.79 to 0.06, and 54 cuts
# sitting outside the slack. A correlation hides that, because a few shots in the wrong hour
# barely move it.
#
# Swept over 8 seeds, everything else fixed:
#
#   ağırlık  tolerans  sıçrama  korelasyon  kötü%   an
#      0.2      0.15      10.5       0.816      8  4.0
#      0.4      0.10       0.2       0.929      8  4.0
#      0.6      0.08       0.0       0.950      7  4.0   <-
#      0.8      0.06       0.0       0.959      8  4.0
#      1.2      0.05       0.0       0.970      8  4.0
#
# 0.6 is where the jumps stop. Tighter buys correlation and nothing the film can use, while
# taking away the freedom to choose between shots taken in the same minutes.
CHRONOLOGY_SLACK = 0.08
# What that distance costs per unit beyond the slack. This is the lightest weight that reaches
# zero misplaced shots over five seeds; heavier settings only tie the edit closer to the clock,
# and a film is not the day played back in order.
CHRONOLOGY_WEIGHT = 0.6


def _day_position(assets: Sequence[MediaAsset]) -> dict[str, float]:
    """Where in the shooting day each clip sits, from 0 at the first frame rolled to 1 at the
    last. A clip with no timecode is left out rather than guessed at, and carries no pressure.

    The day is cut at its largest silence rather than at midnight, so a reception that runs
    past twelve stays one continuous evening instead of splitting into two ends of a clock.
    """
    timed = sorted(
        (seconds, asset.id)
        for asset in assets
        if (seconds := _timecode_seconds(asset)) is not None
    )
    if len(timed) < 2:
        return {asset_id: 0.5 for _, asset_id in timed}
    day = 24 * 3600
    gaps = [(timed[i + 1][0] - timed[i][0], i) for i in range(len(timed) - 1)]
    gaps.append((timed[0][0] + day - timed[-1][0], len(timed) - 1))
    _, last = max(gaps)
    origin = timed[(last + 1) % len(timed)][0]
    shifted = {
        asset_id: (seconds - origin) % day for seconds, asset_id in timed
    }
    span = max(shifted.values())
    if span <= 0:
        return {asset_id: 0.5 for asset_id in shifted}
    return {asset_id: offset / span for asset_id, offset in shifted.items()}


def _timecode_seconds(asset: MediaAsset) -> int | None:
    """Time of day in whole seconds, ignoring the frame field."""
    raw = (asset.timecode or "").strip()
    parts = raw.replace(";", ":").split(":")
    if len(parts) < 3:
        return None
    try:
        hours, minutes, seconds = (int(parts[index]) for index in range(3))
    except ValueError:
        return None
    return hours * 3600 + minutes * 60 + seconds


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


# The operator lowers the camera as they stop recording, so a clip's last frames are a whip.
# Measured over 70 clips of this shoot, against each clip's own median frame-to-frame motion:
# the last frame runs 1.88x, the second-to-last 2.30x and the third 2.00x, falling to 1.21x by
# the fifth and to the baseline by the twenty-fifth. 71% of clips spike past twice their own
# median in their last eight frames, 56% past three times. The head is calm by comparison, at
# 0.80-0.94x, so nothing is taken off the front.
#
# The handle below could not cover this: it is a share of the shot's length, so the 44 frame
# shot that opened an edit got five frames of handle and its cut ended four frames from the
# whip. This is a property of the recording stopping, so the margin is a fixed length.
RECORDING_TAIL_SECONDS = Fraction(1, 4)


def _without_recording_tail(shot: Shot, asset: MediaAsset) -> Shot:
    """Pull a shot back from the end of its clip, where the camera is being lowered."""
    rate = shot.source_range.rate
    total = rate.frames_from_seconds(asset.duration, rounding="floor")
    end = shot.source_range.start_frame + shot.source_range.duration_frames
    if end > total:
        # The shot runs past the clip's recorded length, so the two disagree and there is no
        # knowing where the recording actually stopped. Trimming against a length that is
        # wrong would cut real footage away.
        return shot
    margin = rate.frames_from_seconds(RECORDING_TAIL_SECONDS, rounding="ceil")
    overrun = end - (total - margin)
    if overrun <= 0:
        return shot
    # A shot that is nothing but the whip empties, and the caller drops it on the length filter.
    duration = max(0, shot.source_range.duration_frames - overrun)
    return replace(
        shot,
        source_range=TimeRange(shot.source_range.start_frame, duration, rate),
    )


def _available_duration(shot: Shot) -> Fraction:
    handle = min(shot.source_range.duration_frames // 8, shot.source_range.rate.frames_from_seconds(Fraction(1, 5)))
    usable = max(0, shot.source_range.duration_frames - handle * 2)
    return shot.source_range.rate.seconds_from_frames(usable)


def _remaining_source_frames(shot: Shot, consumed_frames: int) -> int:
    rate = shot.source_range.rate
    handle = min(shot.source_range.duration_frames // 8, rate.frames_from_seconds(Fraction(1, 5)))
    return max(0, shot.source_range.duration_frames - handle * 2 - consumed_frames)


def source_rate_seconds(shot: Shot, consumed_frames: int) -> Fraction:
    """How much of this shot is still there to cut from, in seconds."""
    return shot.source_range.rate.seconds_from_frames(
        _remaining_source_frames(shot, consumed_frames)
    )


# What a half second of picture has to be free of. Both are measured, not guessed: the edit
# the editor picked apart had a head against the frame edge at 0.76 and 1.00 where the stored
# whole-shot value was 0.00, and a whip at 9 sharpness against the shoot's 45 to 78.
FRAME_EDGE_PENALTY = 1.0
# Someone else's face, small and behind the subject. Three is a crowd and the scale stops.
BYSTANDER_PENALTY = 0.35
BYSTANDER_LIMIT = 3
# A shot whose best stretch scores below this has no moment worth cutting to. C2181 sat at
# frame-edge 1.00 across its whole length with six to nine faces in it; moving the in-point
# would only have found another bad moment.
UNUSABLE_WINDOW_SCORE = 0.0
# What a shot with no good moment in it gives up against one that has.
#
# Swept twice: first against windows measured off the proxies, then again against the same
# shoot measured at full resolution, where the detector finds far more faces and the scores
# come out harder. The value held both times.
#
#   weight   bad cuts   scene runs   day's order   returns to a clip
#     none        43%         29.3          0.83                 8.3
#     0.15        19%         27.0          0.81                 8.7
#     0.30        18%         22.0          0.79                12.7
#     0.50        15%         22.7          0.70                16.0
#
# Past 0.15 the bad cuts barely move while the day's order and the return count — the two
# things the editor complained about by name — come apart. Sequence runs still cost something
# here, 29 to 27, because a sequence's later shots are often the worse-framed ones; a sequence
# built out of shots with a head against the frame edge is not one worth keeping.
WINDOW_QUALITY_WEIGHT = 0.15
# The length a shot is judged over: what the edit takes is a stretch, not an instant. This is
# about the median cut of an edit at this shoot's pace.
TYPICAL_CUT_SECONDS = Fraction(1)
# Half speed, where the film pauses to look and the music is not driving.
#
# The editor asked for it in the quiet passages: "başta müzik daha slow, daha uzun akorlar
# var, orda slow olabilir". Measured on the chosen song, the opening runs 2.2 to 4.6 onsets a
# second against 4.4 to 6.2 after the drop, at a third of the energy, and the analyser's own
# section pass draws the same two quiet stretches, 0 to 63 seconds and 107 to 139.
#
# Only a held shot is slowed. A held shot is already the film stopping to look at something,
# and doubling that look is the gesture the request was about; slowing the cutting rhythm
# instead would just make the edit sluggish.
SLOW_MOTION_SPEED = Fraction(1, 2)
SLOW_MOTION_ENERGY = "low"
# The categories that are a thing or a place rather than somebody. Nothing here is slowed.
STILL_CATEGORIES = frozenset({"detail", "venue"})
# A shot with nobody in it: a sign, a laid table, a bouquet. Averaged over the shot's windows,
# because a guest crossing the back of one frame does not make a still life into a portrait.
FACELESS_FACES = 0.5
# What the second still life from one moment gives up.
#
# The shoot rolls a graphic several times and the film needs one of them. Measured on this
# edit, one moment at 08:19-08:20 supplied three - the welcome sign twice and the ceremony
# card - and the editor read them as the same shot coming back. The perceptual hash could not
# see it: the two takes of that sign sit 17 bits apart, outside the near-duplicate threshold
# entirely, and CLIP puts them at 0.822 against a random-pair 90th percentile of 0.807. What
# separates them is not how they look but what they are: two records of one still object.
#
# Swept over three seeds: 0.10 is the lightest that leaves no moment giving the edit a second
# still life, and it costs nothing measurable — the detail and venue share stays at 4% and the
# edit keeps its clip count.
STILL_LIFE_REPEAT_PENALTY = 0.1
# What a shot is worth for being the best record of a moment the film has not shown yet.
#
# Measured on an edit the editor spent an evening picking apart: of the eight shots matching
# each wedding moment best, the kiss, the ring, the first dance and the entrance each had
# *none* in the film, and the cake one. All of it was indexed and available; the ring exchange
# simply loses to a technically cleaner shot of somebody walking.
#
# Swept over eight seeds: at zero the film carries 3.5 of the shoot's six moments, at 0.10 all
# six, and going further buys nothing. It costs a tenth of the scene runs, 31.8 to 28.6, and
# nothing else — the bad-cut share, the day's order and the mean technical quality are
# unmoved. A wedding film that does not show the ring is not paying for its sequences.
MOMENT_BONUS = 0.1
# What a shot gives up for being about the band rather than about the wedding.
#
# The band plays at every wedding and belongs in the background of the party. Measured on an
# edit the editor watched through: a quarter of its cuts came from this shoot's top tenth for
# "a wedding band performing on stage" — two and a half times an even hand — and the singer
# alone ran 17%. "solist çok fazla görünüyor, hem bu planda hem genel."
#
# Swept over three seeds: 0.05 brings the band's share of the cuts to exactly 10%, which is
# the share an even hand would give it, and it stops there — the band is part of the party and
# is not being banished. 0.20 takes it to nothing and costs the day's order, 0.84 to 0.78.
# Scene runs come *up*, 26.7 to 29.7, because the band's stage was pulling the edit back to
# the same corner of the room from every part of the evening.
DISTRACTION_PENALTY = 0.05
# A shot of people who are not doing anything.
#
# "öylece duruyorlar shota hazırlık kısmı daha", "yine duruyorlar gelin terini siliyor", and
# earlier "yine shota hazırlık var damat saçını düzeltiyor". Measured on the edit they picked
# apart: one of those shots sits in the stillest 2% of the whole shoot and another in the
# stillest 7%, and 17% of the film's cuts came from the shoot's stillest quarter.
#
# Charged only where people are the subject. A ring or a table setting is *supposed* to be
# still, and the categories that say so are the same ones slow motion already excludes.
STILLNESS_QUANTILE = 0.25
STILLNESS_PENALTY = 0.08
# A cut too short to read a wide shot in.
#
# The references cut this short more often than we do — 16% of their shots run under half a
# second against our 10% — so the length is not the fault. What they do not do is give that
# half second to a wide shot of a hotel lobby: "kısa kalmış plan". Of our 24 cuts under 0.64
# seconds, 17 were medium and 7 wide, and not one was a close-up.
SHORT_CUT_SECONDS = Fraction(16, 25)
# What a laid table costs anywhere in the film.
#
# Kept out of the opening since the welcome-sign work, and left free everywhere else — so four
# of them turned up in the body of one edit: cutlery and glasses at 7, the same table again at
# 17, a centrepiece at 24, a fourth at 33. The editor has objected to this image more than any
# other, in four separate rounds: "alakasız yerde çiçek", "gereksiz yerde çiçek", "bi detay
# planı böyle olmaz", "şu anasını siktiğimin çiçeği duruyor".
#
# Charged rather than banned. One shot of the room before anyone sits down is a detail a
# wedding film can use; four of them spread through the party is the tool not noticing.
TABLE_SETTING_PENALTY = 0.12
# What a body between the camera and the subject costs.
#
# "alakasız sırt var", "çok kötü kafanın arkası görünüyor sadece". These are not weak shots by
# any measure the planner already had: the face detector reads a blurred shoulder across the
# lens as no face at all, which is what an empty room reads as too. Set alongside the band's
# charge rather than above it — an obstructed shot is still a shot of the wedding, and this is
# a preference for the clear one, not a ban.
OBSTRUCTION_PENALTY = 0.05
# How alike two shots have to look, coming from different files of one moment, before the
# second reads as another take of the first rather than as the next shot of a sequence.
#
# The editor pointed at 36 seconds: "iki plan ard arda çok benziyor". C1974 and C1975, two
# takes of the couple standing in the same spot, cut back to back at 0.939 similarity.
#
# The references do not forbid similar neighbours — measured across their 1201 consecutive
# pairs they are *more* willing than this edit: 4.7% of theirs sit above 0.90 against 0.9% of
# ours, and they reach 0.988. So this is not a rule about similarity. It is a rule about a
# second take: same moment, different file, near-identical framing. Measured on this edit
# exactly one pair qualifies — the one complained about — and no pair from a single file
# continuing into itself comes near it, so a sequence is never touched.
SECOND_TAKE_SIMILARITY = 0.90
# Swept over three seeds: 0.05 takes the second-take pairs to none and the most alike pair in
# the film from 0.919 to 0.899, while the six moments and the scene runs are untouched.
SECOND_TAKE_PENALTY = 0.05
# A stretch this bad is not cut to at all, whatever else the shot has going for it.
#
# The score already knows about these — the back of a man's head filling the frame scored
# -0.12 and -0.10 across half its cut — but knowing is not the same as acting, and raising the
# window weight does not reach them: past 0.15 the day's order and the returns come apart
# while the bad share barely moves. Charging the shot for the stretch it would use was tried
# and measured worse on every count, because a shot that has already given the edit a cut has
# a naturally poorer remainder and was being punished for having been used.
#
# So this is a gate rather than a price: a shot with nothing usable left for this cut is not a
# candidate for it, and is free to come back for the next one.
#
# Swept over six seeds. Zero is where the framing and crowd charges exactly cancel a shot's
# crispness — a stretch below it is one the film should not be sitting on — and it is also
# where the numbers land best:
#
#   gate    bad cuts   very bad   scene runs   day's order
#   none         19%         7%         24.5          0.83
#   0.0          10%         0%         27.3          0.83
#   0.2           6%         1%         27.0          0.84  (and a moment starts to go)
#   0.3           7%         0%         30.5          0.82
#
# Scene runs *rise* — a shot turned away for one cut and taken for the next is how a run gets
# built out of the good part of a clip.
#
# The first version of this table read 16% and 5% at zero. Half the gate was being swallowed
# by a blind spot in _best_offset, which a test written for this found: window offsets are
# half a second apart, so a narrow range falling between two of them left nothing to score and
# the shot came back optimistically clean.
# Raised from 0.0 once the stillness and short-cut rules were in. Swept over 8 seeds with
# everything else fixed:
#
#   eşik  süre   kesim  kötü%  çokkötü%  durgun%   an
#   0.00  150.0    112     13         1        3  6.0
#   0.15  150.0    112      7         0        3  6.0
#   0.25  150.0    112      7         0        2  6.0
#   0.35  150.0    112      6         0        4  6.0
#   0.50  150.0    112      0         0        4  5.0   <- loses a wedding moment
#
# The editor expected this to cost length — "gereksiz plan eklemek yerine klip uzunluğu
# kısaltılabilir" — and it does not: the film still fills 150 seconds, it just stops reaching
# for the stretches it was reaching for. The short-delivery path stays for a shoot that cannot.
UNUSABLE_RUN_SCORE = 0.25
# How much of the asked-for length the edit has to reach before a short film is delivered
# instead of an error.
#
# "görüntü yetersiz geliyorsa duruma göre klibin süresi kısalabilir." Until now running out of
# usable footage produced no edit at all: the whole build raised, and the editor was told to
# lower the target and start again. A shorter film made of the good material is worth more
# than that. Below half the target the target is simply wrong for the footage and saying so is
# the honest answer.
MINIMUM_DELIVERABLE_SHARE = Fraction(1, 2)
# How the film slows down before it stops.
#
# Measured across the 18 references, from the last shot backwards: 3.17, 1.76, 1.56, 1.48,
# 1.22, 1.04 — their median shot is 1.00, so the last six cuts lengthen steadily into the
# ending. Ours ran 0.96, 0.98, 0.98, 0.98, 0.96 and then 3.86: flat, and then a wall.
# "çıkış da iyi değil tak diye çıkıyor daha yumuşak bitsin azalarak".
#
# Held as the cuts before the closing shot, longest first, and applied by how much film is
# left rather than by counting cuts — the number of cuts left is not known in advance.
# Lengthened past the reference median once the editor had watched the ramp working and still
# wanted more: "ve çıkış daha uzun halde yumuşak şekilde kapanmalı". The references' own last
# shots run from 0.2 to 12.6 seconds around a median of 3.17, so a longer landing is inside
# what they do, not outside it — this takes the approach to roughly nine seconds of settling
# rather than seven.
CLOSING_RAMP = (
    Fraction(12, 5), Fraction(2), Fraction(42, 25), Fraction(37, 25), Fraction(32, 25),
    Fraction(26, 25),
)
# What the film ends on.
#
# Measured across the 18 references: 15 of them close on a `venue` shot — 83% of their endings
# against 23% of their shots — and not one closes on a `couple` or a `detail`. Looking at what
# those endings actually are: the couple small in a wide frame, walking away through a garden;
# a card on a table. The film pulls back.
#
# Ours was closing on the bride's back in the middle of a crowded room, which is the shot the
# editor has objected to all along, and they said so again: "intro outro kötü".
#
# The category cannot be required here. This shoot holds 23 venue shots and the four that could
# carry an ending are all from the first minutes of the day — closing an evening on the morning
# foyer would break the chronology to fix the framing. So the *shape* is asked for instead,
# which is what the references are really doing: a wide frame with nobody large in it.
#
# Honestly: on this shoot the shape is as far as it goes. Every candidate late in the day is
# somebody in a crowded room, because the film was shot inside a reception and never pulls
# back the way the references do. The rule stops the ending being a close-up of a back in the
# middle of the floor; it cannot supply a shot that was not filmed.
CLOSING_SCALE = "wide"
# Above this the subject is close enough that the frame is a portrait, not a departure.
CLOSING_FACE_RATIO = 0.03
# A floor on the face size was tried here and made it worse: it moved the ending onto `family`
# shots in four seeds of eight without improving any of them. The shot this shoot is missing
# cannot be found by tightening a filter — see the note on CLOSING_SCALE.
# And the ending comes from the end of the day. Asking only for the shape put a morning shot
# of a laid table at the end of an evening: a wide frame with nobody in it fits the shape
# perfectly and finishes the film in the wrong hour.
CLOSING_DAY_FLOOR = 0.6
# How long the film holds its last image.
#
# Measured across the 18 reference films, 1219 shots: their median shot runs 1.00 second and
# their *last* shot 3.17, three times as long, with the last five already lengthening to 1.62.
# Half of them close on a shot of three seconds or more and two hold for over twelve. Our edits
# were ending on an ordinary 0.98 second cut — the film stopped rather than finished.
CLOSING_SECONDS = Fraction(4)
# How much the edit cares that a shot moves the way the music does. The rest of the score is
# fixed alongside it, so raising this takes from the technical bar rather than floating free.
#
# Left where it was. With the targets read off the shoot instead of written by hand, raising
# this to 0.25 buys the driving passages three points of still shots — 27% to 24% — and pays
# for it in technical quality, 0.427 to 0.416. The target was the fault, not the weight.
MUSIC_FIT_WEIGHT = 0.15
TECHNICAL_WEIGHT = 0.25
# What "moving with the music" means, read off the shoot rather than written here.
#
# The targets used to be 0.30, 0.55 and 0.78. Measured on this footage, the median shot moves
# 0.283, 9% reach 0.5 and 1% reach 0.78 — nineteen shots out of 1405. A driving passage was
# therefore asking for something the shoot barely contains, and no weight can conjure it:
# pushing the term from 0.15 to 0.25 moved the still-shot share in the loud passages only from
# 33% to 29% and cost technical quality to do it.
#
# So a passage asks for a quartile of this shoot's own movement instead. On footage that is
# livelier or calmer than this the same three words keep meaning the same three things.
MOTION_QUANTILES = {"low": 0.25, "medium": 0.5, "high": 0.75}
FALLBACK_MOTION_TARGETS = {"low": 0.3, "medium": 0.55, "high": 0.78}


def _motion_targets(shots: Sequence[Shot]) -> dict[str, float]:
    """The movement a low, medium and driving passage should look for, on this shoot's scale."""
    values = sorted(shot.motion_score for shot in shots)
    if not values:
        return dict(FALLBACK_MOTION_TARGETS)
    return {
        energy: values[min(len(values) - 1, int(quantile * len(values)))]
        for energy, quantile in MOTION_QUANTILES.items()
    }


def _window_score(
    window: ShotWindow, sharpness_bar: float, category: str = ""
) -> float:
    """How good this half second is as picture, on the shoot's own scale.

    Laplacian variance has no absolute meaning — it moves with resolution, grade and content —
    so crispness is read against this shoot's median rather than a number written here.

    The face terms are dropped on a shot of a thing or a place. On the three table shots in
    one edit the detector reported 12, 23 and 53 faces and put one against the frame edge in
    all three; there is not a person in any of them. It reads bowls, chairs and flowers as
    faces, and at 0.048 of the frame — large enough that the readable-face floor cannot catch
    them. Their scores came out as noise: the editor's favourite of the three scored -0.35 and
    the one they objected to scored 0.88.
    """
    crisp = min(1.0, window.sharpness / sharpness_bar) if sharpness_bar > 0 else 1.0
    if category in STILL_CATEGORIES:
        return crisp
    crowd = min(window.bystanders, BYSTANDER_LIMIT) / BYSTANDER_LIMIT
    return crisp - FRAME_EDGE_PENALTY * window.face_edge - BYSTANDER_PENALTY * crowd


def _run_score(
    windows: Sequence[ShotWindow], first: int, last: int, sharpness_bar: float,
    category: str = "",
) -> float:
    """The worst half second decides. A cut is only as good as the frame that spoils it."""
    covered = windows[first : last + 1]
    if not covered:
        return 0.0
    return min(_window_score(window, sharpness_bar, category) for window in covered)


def _cut_run_score(
    shot: Shot,
    windows: Sequence[ShotWindow] | None,
    consumed_frames: int,
    wanted: Fraction,
    sharpness_bar: float,
) -> float:
    """The best a cut of this length could be, taken from where this shot has got to."""
    if not windows:
        return 1.0
    rate = shot.source_range.rate
    handle = min(shot.source_range.duration_frames // 8, rate.frames_from_seconds(Fraction(1, 5)))
    frames = min(
        _remaining_source_frames(shot, consumed_frames),
        rate.frames_from_seconds(wanted, rounding="nearest"),
    )
    if frames <= 0:
        return 1.0
    floor = handle + consumed_frames
    _, value = _best_offset(
        shot, windows, frames,
        floor=floor,
        ceiling=max(floor, shot.source_range.duration_frames - handle - frames),
        sharpness_bar=sharpness_bar,
    )
    return value


def _best_offset(
    shot: Shot,
    windows: Sequence[ShotWindow],
    frames: int,
    *,
    floor: int,
    ceiling: int,
    sharpness_bar: float,
) -> tuple[int, float]:
    """Where in the shot to start, and how good the result is.

    Only forward of what the shot has already given, so the segments a shot supplies stay in
    order and never overlap — a second cut from a clip is a later moment, not the same one.
    """
    if not windows:
        return floor, 1.0
    best_offset, best_value = floor, None
    # The floor is always one of the candidates. Window offsets are half a second apart, so a
    # narrow range between two of them used to leave nothing to score and the shot came back
    # optimistically clean — which is how a stretch with nothing usable in it could still be
    # offered to a cut.
    offsets = [floor] + [
        window.offset_frames for window in windows
        if floor < window.offset_frames <= ceiling
    ]
    for offset in offsets:
        # The window this run starts inside, which for the floor is the one at or before it.
        first = max(
            (index for index, other in enumerate(windows) if other.offset_frames <= offset),
            default=0,
        )
        last = first
        while (
            last + 1 < len(windows)
            and windows[last + 1].offset_frames < offset + frames
        ):
            last += 1
        value = _run_score(windows, first, last, sharpness_bar, shot.category)
        if best_value is None or value > best_value:
            best_offset, best_value = offset, value
    if best_value is None:
        return floor, 1.0
    return best_offset, best_value


def _source_range_for_duration(
    shot: Shot,
    wanted: Fraction,
    *,
    consumed_frames: int = 0,
    allow_short: bool = False,
    windows: Sequence[ShotWindow] | None = None,
    sharpness_bar: float = 0.0,
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
    # Where the cut used to begin, unconditionally: a fixed handle after the shot started, or
    # after whatever the shot had already given. That is the moment the scene detector cut on,
    # which is where the framing is still settling, and it is where every shot the editor
    # objected to went wrong.
    floor = handle + consumed_frames
    offset, _ = _best_offset(
        shot, windows or (), frames,
        floor=floor,
        ceiling=max(floor, shot.source_range.duration_frames - handle - frames),
        sharpness_bar=sharpness_bar,
    )
    return TimeRange(shot.source_range.start_frame + offset, frames, rate)


def _score_candidate(
    shot: Shot,
    *,
    preferred_categories: tuple[str, ...],
    preferred_scales: tuple[str, ...],
    energy: str,
    recent: tuple[TimelineItem, ...],
    current_run: int = 0,
    share_overrun: float = 0.0,
    scene: int | None = None,
    previous_scene: int | None = None,
    progress: float = 0.0,
    day_position: float | None = None,
    window_quality: float = 1.0,
    still_life_repeat: bool = False,
    missing_moment: bool = False,
    distraction: bool = False,
    obstructed: bool = False,
    laid_table: bool = False,
    stillness_bar: float | None = None,
    second_take: bool = False,
    motion_targets: Mapping[str, float] | None = None,
    desired_duration: Fraction,
    random_jitter: float,
    style_profile: Mapping[str, object] | None = None,
    reuse_count: int = 0,
    asset_reuse_count: int = 0,
    used_hashes: Sequence[int] = (),
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
    targets = motion_targets or FALLBACK_MOTION_TARGETS
    target_motion = targets.get(energy, targets.get("medium", 0.55))
    music_fit = max(0.0, 1.0 - abs(shot.motion_score - target_motion))
    sequence_continuity = 1.0
    previous = recent[-1] if recent else None
    same_scene = previous is not None and previous_scene is not None and previous_scene == scene
    duplicate_penalty = _visual_repeat_penalty(shot, used_hashes, same_scene)
    jump_cut_penalty = 0.0
    in_sequence = False
    if previous is not None:
        continues = previous.shot.category == shot.category
        in_sequence = continues and current_run < SEQUENCE_TARGET_RUN
        if continues and current_run >= SEQUENCE_TARGET_RUN:
            # Past the length the references hold a subject for, leaving is worth more. Below
            # it nothing is charged at all: an entrance, the cake, a table of details are each
            # several shots of one thing, and the film has to be allowed to stay on them.
            jump_cut_penalty = SEQUENCE_OVERRUN * (current_run - SEQUENCE_TARGET_RUN + 1)
            sequence_continuity = 0.8
        if continues and previous.shot.shot_scale == shot.shot_scale:
            # Same subject at the same size back to back is the cut worth avoiding: it reads
            # as a jump rather than as a second look. A near-duplicate frame is caught by the
            # perceptual hash above, which is a measurement rather than a guess.
            jump_cut_penalty += JUMP_CUT_PENALTY
    # The share cap is about the whole film; a sequence is a local structure. Charging it in
    # full mid-sequence is what held consecutive same category down.
    share_weight = SHARE_OVERRUN_WEIGHT * (SEQUENCE_SHARE_RELIEF if in_sequence else 1.0)
    framing_penalty = CUT_HEAD_PENALTY * shot.face_edge
    # The film is allowed to move around the day, but not to lose it: measured on the last
    # edit, order and time of day correlated at 0.11, sixty-two of a hundred and seventeen
    # cuts went backwards, and a table of flowers shot at 08:21 landed at 125 seconds of 150.
    # A shot measured to have no usable moment anywhere along it. Moving the in-point cannot
    # save it: C2181 held a face against the frame edge across its whole length.
    window_penalty = WINDOW_QUALITY_WEIGHT * max(0.0, 1.0 - window_quality)
    still_life_penalty = STILL_LIFE_REPEAT_PENALTY if still_life_repeat else 0.0
    # The best record of something the film owes its subjects and has not shown yet — offered
    # only where the film has reached that part of the day. Unconditional, the bonus simply
    # outweighed the chronology term, 0.10 against 0.064, and the first twenty-two seconds
    # came out as the kiss, the entrance, the cake, the ring and the first dance one after
    # another. A moment owed is not a moment due now.
    chronology_penalty = 0.0
    if day_position is not None:
        distance = abs(day_position - progress)
        chronology_penalty = CHRONOLOGY_WEIGHT * max(0.0, distance - CHRONOLOGY_SLACK)
    moment_bonus = MOMENT_BONUS if (missing_moment and chronology_penalty == 0.0) else 0.0
    # A moment the film owes is never suppressed for happening in front of the band: the first
    # dance is *in* front of the band. Without this the six moments came out at 5.7 of six.
    distraction_penalty = (
        DISTRACTION_PENALTY if (distraction and not missing_moment) else 0.0
    )
    # A moment is never suppressed for this either: if the only record of the ring is over a
    # guest's shoulder, the film still owes the ring.
    obstruction_penalty = (
        OBSTRUCTION_PENALTY if (obstructed and not missing_moment) else 0.0
    )
    # People who are not doing anything. Only where people are the subject: a ring is
    # supposed to be still, and a moment the film owes is never suppressed for it either.
    stillness_penalty = (
        STILLNESS_PENALTY
        if (
            stillness_bar is not None
            and shot.motion_score < stillness_bar
            and shot.category not in STILL_CATEGORIES
            and not missing_moment
        )
        else 0.0
    )
    table_penalty = TABLE_SETTING_PENALTY if (laid_table and not missing_moment) else 0.0
    second_take_penalty = SECOND_TAKE_PENALTY if second_take else 0.0
    # Taking the next shot from the clip just used is a sequence, not a repetition, so it is
    # pulled towards: removing the charge alone changed nothing, the edit still took every one
    # of its 113 cuts from a different file, everything else in the score preferring a fresh
    # one. The run the edit is inside is already excluded from asset_reuse_count by the caller,
    # so what remains is every earlier visit — and coming back to a clip still costs all of
    # them. Exempting the whole history instead let one cake take seven cuts across 55 seconds,
    # three of them back to back after a 27 second absence, each free because the return had
    # made itself a sequence.
    staying = same_scene and in_sequence
    take_bonus = TAKE_CONTINUITY_BONUS if staying else 0.0
    reuse_penalty = (
        REUSE_PENALTY * reuse_count
        + ASSET_REUSE_PENALTY * asset_reuse_count
        + share_weight * share_overrun
    )
    available = _available_duration(shot)
    duration_fit = max(0.0, 1.0 - float(abs(available - desired_duration) / max(desired_duration, Fraction(1, 2))))
    music_fit = music_fit * 0.7 + duration_fit * 0.3
    score = (
        TECHNICAL_WEIGHT * shot.technical_quality
        + 0.20 * shot.aesthetic_score
        + 0.20 * story_relevance
        + MUSIC_FIT_WEIGHT * music_fit
        + 0.10 * style_fit
        + 0.10 * sequence_continuity
        - duplicate_penalty
        - jump_cut_penalty
        - framing_penalty
        - chronology_penalty
        - window_penalty
        - still_life_penalty
        + moment_bonus
        - distraction_penalty
        - second_take_penalty
        + take_bonus
        - reuse_penalty
        - obstruction_penalty
        - table_penalty
        - stillness_penalty
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
        "framing_penalty": framing_penalty,
        "chronology_penalty": chronology_penalty,
        "window_penalty": window_penalty,
        "still_life_penalty": still_life_penalty,
        "moment_bonus": moment_bonus,
        "distraction_penalty": distraction_penalty,
        "obstruction_penalty": obstruction_penalty,
        "table_penalty": table_penalty,
        "stillness_penalty": stillness_penalty,
        "second_take_penalty": second_take_penalty,
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
    windows_by_shot: Mapping[str, Sequence[ShotWindow]] | None = None,
    rejected: tuple[frozenset[str], frozenset[str]] | None = None,
    moments: Sequence[Moment] | None = None,
    distractions: frozenset[str] | None = None,
    obstructions: frozenset[str] | None = None,
    opening_signs: frozenset[str] | None = None,
    table_settings: frozenset[str] | None = None,
    embeddings: Mapping[str, Any] | None = None,
) -> TimelinePlan:
    """Plan a varied edit and retain each score's human-readable rationale."""
    windows_by_shot = windows_by_shot or {}
    if target_duration < MIN_TARGET_DURATION:
        raise ValueError("Hedef süre v0.1 için en az 120 saniye olmalıdır.")
    if music.duration < target_duration:
        raise ValueError("Seçilen müzik hedef süreden kısa; müzik edit noktası seçin veya hedefi azaltın.")
    asset_by_id = {asset.id: asset for asset in assets}
    # What the editor has said not to use. Taken out before anything is scored: a rejected
    # clip is not a weak candidate, it is not a candidate.
    rejected_assets, rejected_shots = rejected or (frozenset(), frozenset())
    shots = [
        shot for shot in shots
        if shot.asset_id not in rejected_assets and shot.id not in rejected_shots
    ]
    long_enough = [
        trimmed for shot in shots
        if shot.asset_id in asset_by_id
        for trimmed in (_without_recording_tail(shot, asset_by_id[shot.asset_id]),)
        if _available_duration(trimmed) >= Fraction(1, 2)
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
    # Short of the target is not the same as too short to be worth cutting. The edit is built
    # out of what there is and handed over with its length said out loud; only under half the
    # asked-for length is the target wrong enough to stop for.
    if total_candidate_duration < target_duration * MINIMUM_DELIVERABLE_SHARE:
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
    beat_debt = Fraction(0)
    hold_debt = Fraction(0)
    # The bar a shot has to clear to be held: this shoot's own median, so it travels to
    # footage that is better or worse than this without a number being retuned.
    scene_by_asset = _scene_of_asset(list(asset_by_id.values()))
    day_by_asset = _day_position(list(asset_by_id.values()))
    # Laplacian variance has no absolute meaning, so crispness is judged against this shoot's
    # own median. A shoot with no measured windows leaves this at zero and nothing changes.
    measured = [
        window for shot in candidates for window in windows_by_shot.get(shot.id, ())
    ]
    sharpness_values = sorted(window.sharpness for window in measured)
    sharpness_bar = (
        sharpness_values[len(sharpness_values) // 2] if sharpness_values else 0.0
    )
    # Scored over a run rather than a single window: what the edit gets is a stretch of the
    # shot, and taking the best half second on its own let C2181 through — one tolerable
    # window while every run that could actually be cut held a face against the frame edge.
    # A shot with nobody in it, and the moments that have already given the edit one.
    faceless = {
        shot.id
        for shot in candidates
        if (measured := windows_by_shot.get(shot.id))
        and sum(window.face_count for window in measured) / len(measured) < FACELESS_FACES
    }
    still_life_scenes: set[int] = set()
    quality_by_shot = {}
    for shot in candidates:
        measured_windows = windows_by_shot.get(shot.id)
        if not measured_windows:
            continue
        rate = shot.source_range.rate
        typical = rate.frames_from_seconds(TYPICAL_CUT_SECONDS, rounding="nearest")
        _, quality_by_shot[shot.id] = _best_offset(
            shot, measured_windows, typical,
            floor=0, ceiling=shot.source_range.duration_frames,
            sharpness_bar=sharpness_bar,
        )
    qualities = sorted(shot.technical_quality for shot in candidates)
    hold_bar = qualities[len(qualities) // 2] if qualities else 0.0
    # The references hold their last image for three times their own median shot. Long enough
    # to close on, but never so long that it eats the film: a short target gets a short close.
    closing_seconds = min(CLOSING_SECONDS, target_duration / 20)
    motion_targets = _motion_targets(candidates)
    # Read off this shoot rather than written here: how still a wedding's footage is varies.
    shoot_motion = sorted(shot.motion_score for shot in candidates)
    stillness_bar = (
        shoot_motion[int(len(shoot_motion) * STILLNESS_QUANTILE)] if shoot_motion else None
    )
    # A wedding film owes its subjects certain things. Each is carried by whichever of its
    # shots the edit can still use, and stops being owed as soon as one of them is in.
    distractions = distractions or frozenset()
    obstructions = obstructions or frozenset()
    opening_signs = opening_signs or frozenset()
    table_settings = table_settings or frozenset()
    embeddings = embeddings or {}
    moments = tuple(moments or ())
    moment_of_shot: dict[str, set[str]] = {}
    for moment in moments:
        for shot_id in moment.shot_ids:
            moment_of_shot.setdefault(shot_id, set()).add(moment.name)
    unshown = {moment.name for moment in moments}
    wanted_moment_shots = {
        shot_id for shot_id, names in moment_of_shot.items() if names & unshown
    }
    # The middle of what this shoot's shots are worth as picture, for the gates that need a
    # bar rather than a number written here.
    measured_quality = sorted(quality_by_shot.values())
    window_quality_bar = (
        measured_quality[len(measured_quality) // 2] if measured_quality else 0.0
    )
    current_frame = 0
    consumed_source_frames = {shot.id: 0 for shot in candidates}
    usage_count = {shot.id: 0 for shot in candidates}
    asset_usage: dict[str, int] = {shot.asset_id: 0 for shot in candidates}
    category_uses: dict[str, int] = {}
    # Every shot already in the edit, so a repeat is caught however long ago it played.
    used_hashes: list[int] = []
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
        # The opening runs long and comes down to the film's own pace over its first few cuts.
        opening = (
            OPENING_SECONDS[len(plan.items)] if len(plan.items) < len(OPENING_SECONDS) else None
        )
        pace = (
            _opening_beats(style_profile, opening) if opening is not None
            else _target_beats_per_cut(style_profile, progress, energy)
        )
        # The debt is carried through the ramp as everywhere else, and that is what keeps the
        # opening's shape: paying it forward cut by cut held the measured distance to the
        # references at 0.46 seconds, against 0.72 when each opening cut was rounded alone.
        beats_per_cut, beat_debt = _beats_for_cut(pace, beat_debt)
        desired = _duration_from_beats(
            music, current_time, energy, style_profile, progress, beats_per_cut,
            hold_limit=opening * OPENING_SLACK if opening is not None else None,
        )
        # Coming in to land: the last few cuts lengthen towards the closing shot instead of
        # holding the film's pace and then jumping.
        landing = _closing_ramp_seconds(
            frame_rate.seconds_from_frames(remaining_frames), closing_seconds
        )
        landing_now = landing is not None and opening is None
        if landing_now:
            desired = landing
        held_seconds = _held_seconds(style_profile, progress)
        frequency = _hold_frequency(
            _held_share(style_profile, progress), held_seconds, desired
        )
        hold, hold_debt = _hold_this_cut(frequency, hold_debt)
        if landing_now and hold:
            # The ramp is already lengthening; a four second hold dropped into it breaks the
            # settling exactly the way one did in the opening. The share is carried forward.
            hold, hold_debt = False, hold_debt + frequency
        if opening is not None:
            # The ramp is already the long shot here. A four second hold dropped into the
            # fifth cut broke the settling and read as the edit stalling, not opening.
            if hold:
                hold, hold_debt = False, hold_debt + frequency
            first_sign = [
                shot for shot in available_shots if shot.id in opening_signs
            ] if not plan.items else []
            if first_sign and windows_by_shot:
                # The steadiest of them. The first sign chosen on picture score alone was a
                # mirror with the camera shaking against it and the camera operator reflected
                # in the glass: "bunun daha iyisi yok mu titriyor kameraman görünüyor".
                #
                # Nothing new is measured for this. The half-second windows already carry a
                # motion figure per shot, and on the sign clips it tracks a frame-difference
                # measure of shake closely enough to order them: 17.4 against 0.68 for the
                # shaky mirror, 11.8 against 0.37 for the steady one. On a sign the subject
                # does not move, so what motion reads there is the camera.
                def unsteadiness(shot: Shot) -> float:
                    measured = windows_by_shot.get(shot.id) or ()
                    return (
                        sum(window.motion for window in measured) / len(measured)
                        if measured else float("inf")
                    )

                first_sign = [min(first_sign, key=unsteadiness)]
            if first_sign:
                # If the shoot filmed a welcome sign, the film opens on it and nothing else
                # gets a say. Placed before the other narrowings rather than after: as the
                # last of them it kept losing, because a quality bar and a minimum length had
                # already emptied the sign out of the pool by the time it ran.
                available_shots = first_sign
            elif desired > TYPICAL_CUT_SECONDS:
                # An opening cut is on screen longer than the film's own median, so it is held
                # to the same bar as a held shot — and it has to be long enough to fill the
                # ramp. Without that second condition the pacing asked for 2.50 seconds, a
                # 1.10 second shot won it, and the opening came out shorter than before the
                # ramp existed. Where nothing clears both the edit opens on the best it has
                # rather than refusing to start.
                worth_opening = [
                    shot for shot in _worthy_shots(available_shots, hold_bar)
                    if source_rate_seconds(shot, consumed_source_frames[shot.id]) >= desired
                ]
                if worth_opening:
                    available_shots = worth_opening
            # The opening belongs to the start of the day, and the references open on detail.
            # Both are narrowed to whatever is left rather than required, so a shoot with no
            # morning detail still opens on something.
            # Only the very first cut. Held across the whole ramp, the category steer made
            # all five opening shots details where the references run 40%, and the day limit
            # pinned the pool to the earliest minutes of the shoot hard enough to override
            # the still-life rule and put two records of one sign into the opening.
            # Steering a cut to a detail can hand the film a still life, and the ordinary
            # repeat penalty is too small to stop a second record of the same object arriving
            # in the very next cut — a shoot that rolled its welcome sign twice put both into
            # the opening. Inside the ramp the scene is refused outright rather than charged.
            narrowers = [
                lambda shot: scene_by_asset.get(shot.asset_id) not in still_life_scenes
            ]
            # A laid table is not what a film opens on, whatever it scores.
            narrowers.append(lambda shot: shot.id not in table_settings)
            if len(plan.items) < OPENING_DETAIL_CUTS:
                # The references run 40% detail across their first five shots, two in five.
                # Steering only the first cut left us at one in five, and steering the whole
                # ramp made all five details.
                narrowers.append(lambda shot: shot.category in OPENING_CATEGORIES)
            # The whole opening belongs to the start of the day, not just its first cut. With
            # the limit on the first cut alone the third shot of the film came from halfway
            # through the shoot — the cake-and-glasses clip again — because the chronology
            # penalty is 0.2 of a score a strong shot clears.
            narrowers.append(
                lambda shot: day_by_asset.get(shot.asset_id, 0.0) <= OPENING_RAMP_DAY_LIMIT
            )
            if not plan.items:
                narrowers.append(
                    lambda shot: day_by_asset.get(shot.asset_id, 0.0) <= OPENING_DAY_LIMIT
                )

            for narrower in (() if first_sign else narrowers):
                narrowed = [shot for shot in available_shots if narrower(shot)]
                if narrowed:
                    available_shots = narrowed
        if hold:
            held = _held_duration(
                music, current_time, held_seconds,
                frame_rate.seconds_from_frames(remaining_frames),
            )
            if held is not None:
                # A shot held for four seconds has to bear four seconds of looking. The longest
                # cut of one 116 clip edit was a couple across a hotel atrium behind a hanging
                # lamp, at 0.334 technical quality against the shoot's 0.399 median — held
                # longer than anything else in the film. So a hold picks from the better half
                # of what is left, and where that leaves nothing it simply does not hold.
                # A held shot has to bear four seconds of looking: better than half this
                # shoot's footage, its subject readable rather than a figure across a room,
                # and not cut by the frame edge.
                worthy = _worthy_shots(available_shots, hold_bar)
                if energy == SLOW_MOTION_ENERGY:
                    # This hold will be played at half speed, so it is on screen twice as long
                    # as it was shot. Measured on an edit that shipped: the six slowed shots
                    # had a median worst window of 0.44 against 0.77 for the film as a whole —
                    # two of them held a face against the frame edge, doubled. Nothing gets
                    # stretched unless it is better than the film's own middle.
                    #
                    # And only what the film is about gets stretched. Slowing is a way of
                    # looking at someone for longer; a vase of flowers at half speed is only a
                    # longer shot of a vase. The editor found one, four seconds of a table
                    # centrepiece: "gereksiz yerde çiçek".
                    #
                    # Judged on the category rather than on faces. The detector reads both
                    # ways round here: it found 2.2 faces a frame in that table setting, in
                    # the place mats and the flowers, while the couple spinning across an
                    # atrium — a shot worth slowing — carries a largest face of 0.001 of the
                    # frame. The classifier calls the first `detail` and the second `groom`,
                    # which is the distinction that was wanted.
                    steady = [
                        shot for shot in worthy
                        if quality_by_shot.get(shot.id, 1.0) >= window_quality_bar
                        and shot.category not in STILL_CATEGORIES
                    ]
                    if steady:
                        worthy = steady
                    else:
                        worthy = []
                if worthy:
                    available_shots = worthy
                    desired = held
                else:
                    hold = False
                    hold_debt += frequency
            else:
                # No room left to hold: give the frequency back so it is spent at a cut where
                # a beat does land, rather than lost.
                #
                # And this is not a hold any more. Leaving the flag standing meant the cut was
                # still treated as one further down — it was slowed to half speed while its
                # candidate pool was never narrowed, so the shot played at 0.50x had passed
                # none of the tests a slowed shot has to pass. That is how a table centrepiece
                # came to run in slow motion: "gereksiz yerde çiçek".
                hold = False
                hold_debt += frequency
        desired = frame_rate.seconds_from_frames(
            max(1, frame_rate.frames_from_seconds(desired, rounding="nearest"))
        )
        # A shot with nothing usable left for a cut of this length is not a candidate for it.
        # It stays in the pool for the next cut, where a different length may reach a better
        # stretch of it, and the whole pool is never emptied by this.
        if UNUSABLE_RUN_SCORE is not None and windows_by_shot:
            usable = [
                shot for shot in available_shots
                if _cut_run_score(
                    shot, windows_by_shot.get(shot.id), consumed_source_frames[shot.id],
                    desired, sharpness_bar) > UNUSABLE_RUN_SCORE
            ]
            if usable:
                available_shots = usable
            elif current_frame >= frame_rate.frames_from_seconds(
                target_duration * MINIMUM_DELIVERABLE_SHARE
            ):
                # Nothing left worth cutting to, and enough film to hand over. Stopping here
                # is better than filling the rest with the stretches this gate exists to keep
                # out.
                break
        if opening is not None and desired < TYPICAL_CUT_SECONDS:
            # A wide shot inside the opening reads as nothing at all. One edit gave its fourth
            # cut — 0.98 seconds — to a wide of a hotel lobby, and the editor found the opening
            # no better than before: "açılış planı da iyi değil hala".
            readable = [shot for shot in available_shots if shot.shot_scale != "wide"]
            if readable:
                available_shots = readable
        if desired < SHORT_CUT_SECONDS:
            # A cut this short is a glance, and a wide shot of a hotel lobby cannot be read in
            # one. The references cut this short more often than we do; what they do not do is
            # spend it on a wide. Narrowed to whatever is left, so the cut still happens.
            readable = [shot for shot in available_shots if shot.shot_scale != "wide"]
            if readable:
                available_shots = readable
        preferred_categories = _preferred_categories(progress, style_profile)
        preferred_scales = _preferred_scales(progress)
        ranked: list[tuple[float, Shot, dict[str, float]]] = []
        for shot in available_shots:
            score, components = _score_candidate(
                shot,
                preferred_categories=preferred_categories,
                preferred_scales=preferred_scales,
                energy=energy,
                recent=tuple(plan.items[-4:]),
                current_run=_trailing_run(plan.items, shot.category),
                share_overrun=_share_overrun(
                    style_profile, progress, shot.category, category_uses, len(plan.items)),
                scene=scene_by_asset.get(shot.asset_id),
                previous_scene=(
                    scene_by_asset.get(plan.items[-1].shot.asset_id) if plan.items else None),
                progress=progress,
                day_position=day_by_asset.get(shot.asset_id),
                window_quality=quality_by_shot.get(shot.id, 1.0),
                motion_targets=motion_targets,
                still_life_repeat=(
                    shot.id in faceless
                    and scene_by_asset.get(shot.asset_id) in still_life_scenes),
                missing_moment=shot.id in wanted_moment_shots,
                distraction=shot.id in distractions,
                obstructed=shot.id in obstructions,
                laid_table=shot.id in table_settings,
                stillness_bar=stillness_bar,
                second_take=_is_second_take(
                    shot, plan.items[-1] if plan.items else None,
                    embeddings, same_scene=(
                        scene_by_asset.get(shot.asset_id) is not None
                        and plan.items
                        and scene_by_asset.get(shot.asset_id)
                        == scene_by_asset.get(plan.items[-1].shot.asset_id))),
                desired_duration=desired,
                random_jitter=rng.uniform(-0.015, 0.015),
                style_profile=style_profile,
                reuse_count=usage_count[shot.id],
                # The run the edit is inside is free, up to the length a sequence runs to.
                # Without that ceiling a clip the edit never leaves is never charged at all,
                # and one long take took every cut of a test edit.
                asset_reuse_count=(
                    asset_usage[shot.asset_id]
                    - min(_trailing_asset_run(plan.items, shot.asset_id),
                          SEQUENCE_TARGET_RUN)),
                used_hashes=used_hashes,
                visual_baseline=visual_baseline,
            )
            ranked.append((score, shot, components))
        ranked.sort(key=lambda candidate: candidate[0], reverse=True)
        selected_score, selected_shot, components = ranked[0]
        remaining_seconds = frame_rate.seconds_from_frames(remaining_frames)
        # A second of timeline costs `speed` seconds of source, so half speed buys twice the
        # screen time out of the same footage.
        speed = SLOW_MOTION_SPEED if (hold and energy == SLOW_MOTION_ENERGY) else Fraction(1)
        # Take the whole tail now rather than leaving a stub for the next cut to pick up. Only
        # a shot with enough source left can do that, so in the tail the others stand down:
        # picking one that runs out mid-cut is what leaves the four frame shot at the end.
        # Reserve the closing shot rather than letting it be whatever happened to be left. The
        # trigger used to be a quarter of a second, so the film ended on an ordinary cut; now
        # an ordinary cut that would leave less than a closing behind hands the rest over.
        # The last shot therefore runs between one closing and one closing plus a cut, which
        # is where the references sit.
        closing_frames = frame_rate.frames_from_seconds(closing_seconds, rounding="nearest")
        # The tail is only handed over when a single shot can carry all of it. Shots are split
        # at five seconds and lose a handle at each end, so nothing supplies more than about
        # 4.6; asking for 4.92 left the closing shot 1.26 seconds short and that leftover
        # became the real last shot of the film. Where the tail is still too long the edit
        # takes one more ordinary cut and asks again a beat later.
        # Measured against everything still holding source, not the pool this cut was drawn
        # from: a held cut narrows that pool to the better half, and reading the supply off it
        # said the tail was uncarriable when it was not.
        longest_supply = max(
            (
                shot.source_range.rate.seconds_from_frames(
                    _remaining_source_frames(shot, consumed_source_frames[shot.id]))
                for shot in candidates
                if shot.id not in exhausted
            ),
            default=Fraction(0),
        )
        crowding_the_close = (
            remaining_frames - frame_rate.frames_from_seconds(desired) < closing_frames
        )
        if crowding_the_close and remaining_seconds > longest_supply:
            # The tail is longer than any one shot can carry, so it cannot be handed over yet;
            # and taking the cut as asked would eat all but a stub of it. Traced on this shoot:
            # 4.82 seconds left against a 4.60 supply, a 3.90 cut asked for, 3.66 delivered,
            # and the film ended on the 1.16 that was left. So this cut stands back to the
            # nearest beat that leaves a whole closing behind.
            room = remaining_seconds - closing_seconds
            landings = [
                beat - current_time for beat in music.beats
                if MIN_CUT_SECONDS <= beat - current_time <= room
            ]
            if landings:
                desired = max(landings)
                crowding_the_close = False
        finishing = (
            crowding_the_close and remaining_seconds <= longest_supply
        ) or remaining_frames - frame_rate.frames_from_seconds(desired) < minimum_cut_frames
        if finishing:
            desired = remaining_seconds
            # The closing runs at speed. Half speed was decided for a *held* shot, out of the
            # narrowed pool the hold had picked — better than this film's own middle, and not
            # a still life. The closing then reaches outside that pool, and carrying the
            # halved speed across meant a shot that had been kept out of slow motion on
            # purpose came back playing at half speed: one seed ended on a table centrepiece
            # at 0.50x, which is the "gereksiz yerde çiçek" the slowing rule exists to stop.
            speed = Fraction(1)
            # Every shot that still has source, not the pool this cut happened to be drawn
            # from. A closing that lands on a held shot was choosing out of the hold's own
            # narrowed pool, and where nothing in it could carry the whole tail the cut came up
            # short and the leftover became the real last shot — 1.16 seconds on one seed,
            # against the 3.17 the references hold.
            long_enough_to_finish = [
                shot for shot in candidates
                if shot.id not in exhausted
                and _remaining_source_frames(shot, consumed_source_frames[shot.id])
                >= shot.source_range.rate.frames_from_seconds(
                    remaining_seconds * speed, rounding="ceil")
            ]
            # A film is not left on a shot nobody could hold: the closing image bears several
            # seconds of looking, so it clears the same bar a held shot does.
            worthy_to_close = [
                shot for shot in long_enough_to_finish
                if shot.technical_quality >= hold_bar
                and shot.face_edge < 0.5
                and (shot.face_ratio == 0.0 or shot.face_ratio >= READABLE_FACE_RATIO)
            ]
            long_enough_to_finish = worthy_to_close or long_enough_to_finish
            # And the film pulls back to end. Narrowed to whatever is left rather than
            # required: a shoot with no wide shot late in the day still gets an ending.
            pulling_back = [
                shot for shot in long_enough_to_finish
                if shot.shot_scale == CLOSING_SCALE
                and shot.face_ratio <= CLOSING_FACE_RATIO
                and day_by_asset.get(shot.asset_id, 1.0) >= CLOSING_DAY_FLOOR
                and shot.id not in table_settings
            ]
            if pulling_back:
                long_enough_to_finish = pulling_back
            if long_enough_to_finish and selected_shot not in long_enough_to_finish:
                allowed = {shot.id for shot in long_enough_to_finish}
                closing = [entry for entry in ranked if entry[1].id in allowed]
                if closing:
                    selected_score, selected_shot, components = closing[0]
                else:
                    # None of them was ranked, because this cut was drawn from a narrowed pool.
                    # Take the best of what can carry the tail on the quality this film is
                    # already being cut on, rather than ending on a stub.
                    selected_shot = max(
                        long_enough_to_finish,
                        key=lambda shot: (shot.technical_quality, shot.aesthetic_score),
                    )
                    selected_score, components = 0.0, {}
        remaining_source_seconds = selected_shot.source_range.rate.seconds_from_frames(
            _remaining_source_frames(selected_shot, consumed_source_frames[selected_shot.id])
        )
        requested_duration = min(desired, remaining_seconds, remaining_source_seconds / speed)
        # At half speed the timeline stays the authority on length. Deriving it back from the
        # source instead put a held shot 0.04 seconds off the beat: the source rate cannot
        # always halve a beat-aligned length into whole frames, and doubling that remainder
        # showed. So the source is asked for enough to cover the request, rounding up, and the
        # cut is then laid down at the length the beat asked for.
        wanted_frames = frame_rate.frames_from_seconds(requested_duration, rounding="nearest")
        source_rate = selected_shot.source_range.rate
        source_wanted = source_rate.seconds_from_frames(
            source_rate.frames_from_seconds(requested_duration * speed, rounding="ceil")
        )
        source_range = _source_range_for_duration(
            selected_shot,
            source_wanted,
            consumed_frames=consumed_source_frames[selected_shot.id],
            allow_short=remaining_frames <= minimum_cut_frames,
            windows=windows_by_shot.get(selected_shot.id),
            sharpness_bar=sharpness_bar,
        )
        if source_range is None:
            exhausted.add(selected_shot.id)
            continue
        delivered_frames = frame_rate.frames_from_seconds(
            source_range.duration_seconds / speed, rounding="nearest")
        if speed != 1 and delivered_frames >= wanted_frames:
            delivered_frames = wanted_frames
        timeline_duration = min(remaining_frames, delivered_frames)
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
        # Charge the shot everything up to where this segment ended, not just its length:
        # skipping forward over a bad stretch means those frames are behind the edit now, and
        # the next segment from this clip has to start after them or the two would overlap.
        consumed_source_frames[selected_shot.id] = (
            source_range.start_frame - selected_shot.source_range.start_frame
            + source_range.duration_frames
        )
        usage_count[selected_shot.id] += 1
        asset_usage[selected_shot.asset_id] = asset_usage.get(selected_shot.asset_id, 0) + 1
        category_uses[selected_shot.category] = category_uses.get(selected_shot.category, 0) + 1
        if selected_shot.id in faceless:
            still_life_scenes.add(scene_by_asset.get(selected_shot.asset_id))
        shown = moment_of_shot.get(selected_shot.id)
        if shown and shown & unshown:
            unshown -= shown
            wanted_moment_shots = {
                shot_id for shot_id, names in moment_of_shot.items() if names & unshown
            }
        selected_hash = _perceptual_hash(selected_shot)
        if selected_hash is not None:
            used_hashes.append(selected_hash)

    shown = {name for moment in moments for name in ((moment.name,)) if name not in unshown}
    doubtful = [moment for moment in moments if moment.uncertain and moment.name in shown]
    if doubtful:
        # Better said than quietly wrong: the affinity cannot prove the moment happened, only
        # that this is the shoot's closest answer to it. Eighteen prompts were tried against
        # this footage and every one found something, fireworks and a wedding car included.
        plan.warnings.append(
            "Şu anlar zayıf eşleşti, göz atın: "
            + ", ".join(f"{moment.label} ({moment.best:.2f})" for moment in doubtful)
            + ". Çekimde gerçekten olmayabilir."
        )
    if current_frame < target_frames:
        available_seconds = frame_rate.seconds_from_frames(current_frame)
        if available_seconds < target_duration * MINIMUM_DELIVERABLE_SHARE:
            raise InsufficientFootageError(
                f"Kaba kurgu hedef süresine erişemedi: {float(available_seconds):.1f} sn "
                "oluşturuldu. Hedef süreyi azaltın veya daha fazla görüntü ekleyin."
            )
        # Short, and said so. A film made of the material that is actually usable beats no
        # film at all, which is what an error left the editor with.
        plan.warnings.append(
            f"Kurgu {float(available_seconds):.1f} saniyede bitti; hedef "
            f"{float(target_duration):.1f} saniyeydi. Kalan görüntüde bu kesim için "
            "kullanılabilir bir yer kalmadı."
        )
    if plan.duration != target_duration:
        plan.warnings.append("Son plan kare sınırına yuvarlandı; süre hedefe en yakın frame-accurate değerdedir.")
    _append_rhythm_report(plan, music, style_profile)
    coverage = _story_coverage_warning(candidates, style_profile)
    if coverage:
        plan.warnings.append(coverage)
    plan.warnings.append(
        f"Kesimlerin %{_story_arc_ratio(plan, style_profile) * 100:.0f}'ı bulunduğu bölüm için "
        "tercih edilen kategoriden."
    )
    return plan


def _story_coverage_warning(
    candidates: Sequence[Shot], style_profile: Mapping[str, object] | None = None
) -> str | None:
    """Name the parts of the wedding story this footage has almost nothing for."""
    if not candidates:
        return None
    counts = Counter(shot.category for shot in candidates)
    wanted: set[str] = set()
    for progress in STORY_PROGRESS_POINTS:
        wanted.update(_preferred_categories(progress, style_profile))
    thin = sorted(
        (category for category in wanted
         if counts.get(category, 0) / len(candidates) < THIN_CATEGORY_SHARE),
        key=lambda category: counts.get(category, 0),
    )
    if not thin:
        return None
    described = ", ".join(
        f"{category} (%{100 * counts.get(category, 0) / len(candidates):.0f})" for category in thin
    )
    return (
        f"Hikâye akışının şu bölümleri için görüntü neredeyse yok: {described}. "
        "O bölümler eldeki diğer kategorilerden dolduruldu."
    )


def _story_arc_ratio(
    plan: TimelinePlan, style_profile: Mapping[str, object] | None = None
) -> float:
    """How much of the edit sits in a category preferred where it lands."""
    total = plan.duration_frames
    if not total or not plan.items:
        return 0.0
    matched = sum(
        item.timeline_range.duration_frames
        for item in plan.items
        if item.shot.category in _preferred_categories(
            item.timeline_range.start_frame / total, style_profile)
    )
    return matched / total


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


def _segment_as_dict(segment: MusicSegment) -> dict[str, str]:
    """Exact rationals, as strings: a segment start read back as a float would drift."""
    return {
        "path": str(segment.path),
        "timeline_start": str(segment.timeline_start),
        "duration": str(segment.duration),
        "source_start": str(segment.source_start),
        "source_total": str(segment.source_total) if segment.source_total is not None else "",
    }


def _segment_from_dict(payload: Mapping[str, object]) -> MusicSegment:
    return MusicSegment(
        path=Path(str(payload["path"])),
        timeline_start=Fraction(str(payload["timeline_start"])),
        duration=Fraction(str(payload["duration"])),
        source_start=Fraction(str(payload.get("source_start", 0))),
        source_total=Fraction(str(payload["source_total"])) if payload.get("source_total") else None,
    )


def persist_timeline(database: Database, plan: TimelinePlan) -> None:
    plan.created_at = plan.created_at or now()
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
            "music_segments_json": [_segment_as_dict(segment) for segment in plan.music_segments],
            "created_at": plan.created_at,
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
                "category": item.shot.category,
                "shot_scale": item.shot.shot_scale,
            },
        )


def _clamped_source_range(start_frame: int, duration_frames: int, rate: FrameRate, asset_duration: Fraction) -> TimeRange:
    """Keep a persisted source range inside the media the NLE will actually see.

    ffprobe and PySceneDetect frame counts run a frame or two long on VFR and long-GOP camera
    files. Resolve does not refuse a range that overruns the media, it stretches the clip to
    fill it - a range ending 200 frames past a 252 frame file lays down a 442 frame clip - so
    the range is clamped here, at the one place every export and adapter reads from.
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
    segments = tuple(
        _segment_from_dict(item) for item in json.loads(header["music_segments_json"] or "[]")
    )
    if not segments:
        # Timelines saved before the edit could hold more than one song. The newest music row
        # is the only record those have.
        music = database.fetch_one(
            "SELECT path, duration_seconds FROM music_tracks WHERE project_id = ?"
            " ORDER BY created_at DESC LIMIT 1",
            (header["project_id"],),
        )
        if music:
            segments = (MusicSegment(
                path=Path(music["path"]),
                timeline_start=Fraction(0),
                duration=Fraction(music["duration_seconds"]),
            ),)

    plan = TimelinePlan(
        id=header["id"],
        project_id=header["project_id"],
        name=header["name"],
        frame_rate=rate,
        target_duration=Fraction(header["target_duration_seconds"]),
        warnings=json.loads(header["warnings_json"]),
        seed=int(header["seed"]),
        created_at=header["created_at"],
        music_segments=segments,
        music_path=segments[0].path if segments else None,
        music_duration=segments[0].duration if segments else None,
    )
    rows = database.fetch_all(
        """SELECT timeline_items.*, shots.technical_quality, shots.aesthetic_score,
                  shots.motion_score, shots.confidence, shots.duplicate_group, shots.labels_json,
                  shots.brightness, shots.saturation, shots.highlight_clipping,
                  shots.face_ratio, shots.face_edge,
                  media_assets.project_id, media_assets.path, media_assets.file_name,
                  media_assets.duration_seconds, media_assets.frame_rate AS asset_rate,
                  media_assets.width, media_assets.height, media_assets.codec, media_assets.timecode,
                  media_assets.content_hash
           FROM timeline_items
           LEFT JOIN shots ON shots.id = timeline_items.shot_id
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
            # The shot row is gone once the footage is re-analysed; the item's own copy of what
            # the clip is keeps the saved rough cut whole, and the scores fall back to neutral.
            category=row["category"] or "b_roll", shot_scale=row["shot_scale"] or "medium",
            technical_quality=float(row["technical_quality"] or 0.5),
            aesthetic_score=float(row["aesthetic_score"] or 0.5),
            motion_score=float(row["motion_score"] or 0.5),
            confidence=float(row["confidence"] or 0.0),
            duplicate_group=row["duplicate_group"],
            labels=tuple(json.loads(row["labels_json"] or "[]")),
            brightness=float(row["brightness"] or 0.0), saturation=float(row["saturation"] or 0.0),
            highlight_clipping=float(row["highlight_clipping"] or 0.0),
            face_ratio=float(row["face_ratio"] or 0.0),
            face_edge=float(row["face_edge"] or 0.0),
        )
        plan.items.append(TimelineItem(
            id=row["id"], shot=shot, asset=asset, source_range=source_range,
            timeline_range=TimeRange(int(row["timeline_start_frame"]), int(row["timeline_duration_frames"]), rate),
            score=float(row["score"]), selection_reason=row["reason"],
            alternatives=tuple(json.loads(row["alternatives_json"])),
        ))
    return plan
