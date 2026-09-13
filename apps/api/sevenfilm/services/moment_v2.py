"""Find the stretch of a clip that is ready to cut to, and let the music say where in it.

Nothing here is wired into the plan. The planner still chooses its own source range by its own
score; this module works out what a different arrangement of the same measurements would have
chosen, so the two can be reported side by side.

Why this shape. Three rounds of shadow work asked the same question — which half second of a
clip is the best one — and answered it with picture quality. The answer never came out well,
so the search is split in two, and the two halves live in different coordinate systems:

    ready region   source coordinates    which stretches of the clip are usable
    edit grid      timeline coordinates  where the cut lands and how long it runs

Of the two, only the second half is supported by a measurement that survives checking.

  music    86% of the editor's 167 cuts run a whole number of beats, and the beat count is a
           property of the section, not of the film: 2 beats in the opening, 6 in the quiet
           passage, 1 in the finale, where 50 of 54 cuts are exactly one beat. Correcting the
           tracker's phase by half a beat takes his cuts from 177 ms off the grid to 66 ms.
  quality  Sharpness separates usable from unusable and nothing more, which is the role it
           already has. It is not a locator: 97% of an average clip passes the gate.
  motion   NOT supported. The earlier finding that the editor cuts into the calm part of a
           clip — 79.1% discrimination, dz -1.05 — was measured on samples whose spacing was
           not held constant, and motion is a difference between samples, so it scales with
           that spacing. His own readings sat a median of 2 frames after the previous sample
           and the random controls sat 20 frames after theirs. Re-asked on the stored window
           grid, where every reading is one half-second step, his in-point sits at the 53rd
           motion percentile of his own clip: p 0.56, dz +0.14, calmer on 26 of 53. Chance.
           `tools/motion_audit.py` is that check, and it is the reason this module is a shadow
           and not a proposal.

The ready region is still built and reported, because the arrangement is worth having and
the region is where a better readiness signal would go when there is one. It is not evidence.

Face and content measurements are carried through as a description of what a region holds.
They rank nothing: in P3 they carried coarse information, around 61-72%, and added no
prediction over anything else.

What this module does not do. There is no event branch: the motion rule that would have been
the ordinary case is not established, so neither is the exception to it. An event shot is
flagged as unsupported and reported as such, never silently handled. There is no detector of
any kind, no training, and no weight fitted to the editor's choices.
"""

from __future__ import annotations

import statistics as st
from collections.abc import Sequence
from dataclasses import dataclass, replace
from fractions import Fraction
from itertools import pairwise

from .windows import WINDOW_SECONDS, AssetWindow

# ---------------------------------------------------------------------------------------
# Ready regions — source coordinates
# ---------------------------------------------------------------------------------------

# A window is ready when it clears the quality gate and carries less motion than this clip
# typically does. The clip's own median is the bar for the same reason sharpness is read
# against the shoot's median: the measure is a mean absolute difference between downscaled
# frames and has no absolute meaning — a locked-off detail and a handheld dance floor do not
# share a scale, and a number written here would be a number from one of them.
READY_MOTION_QUANTILE = Fraction(1, 2)

# The first window of a shot has no window before it, so its motion is stored as 0.0. That is
# "not measured", not "still", and it is 1405 of this project's 9374 windows. Reading it as
# stillness would mark the head of every detected shot as the calmest place in the clip —
# exactly the head bias three earlier rounds were spent removing. Unknown is not ready.
MOTION_UNKNOWN = 0.0


@dataclass(frozen=True)
class ReadyRegion:
    """A contiguous stretch of a clip whose windows are all usable and all calm.

    Source coordinates throughout: `source_start` and `source_end` are frames from the start of
    the media file, `source_end` exclusive. A region may run across a boundary the scene
    detector drew — that boundary is a property of the detector, not of the material — but it
    never runs past the end of the clip it was read from.
    """

    source_start: int
    source_end: int
    window_count: int
    median_motion: float
    min_motion: float
    max_motion: float
    median_sharpness: float
    min_sharpness: float
    median_face_count: float
    median_face_ratio: float
    median_face_edge: float
    shot_ids: tuple[str, ...]

    @property
    def duration_frames(self) -> int:
        return max(0, self.source_end - self.source_start)

    @property
    def crosses_shot_boundary(self) -> bool:
        return len(self.shot_ids) > 1

    def holds(self, start: int, frames: int) -> bool:
        """Whether a cut of `frames` starting here sits entirely inside this region."""
        return self.source_start <= start and start + frames <= self.source_end

    def contains(self, frame: int) -> bool:
        return self.source_start <= frame < self.source_end


def clip_motion_bar(windows: Sequence[AssetWindow]) -> float | None:
    """The clip's own median motion, read off the windows whose motion was measured."""
    known = sorted(w.motion for w in windows if w.motion != MOTION_UNKNOWN)
    if not known:
        return None
    index = int(len(known) * READY_MOTION_QUANTILE)
    return known[min(index, len(known) - 1)]


def window_is_usable(window: AssetWindow, sharpness_bar: float) -> bool:
    """The production quality gate, unchanged, applied to a window on its own.

    Same threshold and same measure as `_window_score`; nothing here softens it, and a window
    that production would call unusable is unusable here too.
    """
    from .planner import UNUSABLE_SHARPNESS_SHARE

    if sharpness_bar <= 0:
        return True
    return window.sharpness / sharpness_bar >= UNUSABLE_SHARPNESS_SHARE


def _summarise(windows: Sequence[AssetWindow], step_frames: int) -> ReadyRegion:
    motions = [w.motion for w in windows]
    seen: list[str] = []
    for window in windows:
        if window.shot_id not in seen:
            seen.append(window.shot_id)
    return ReadyRegion(
        source_start=windows[0].asset_frame,
        source_end=windows[-1].asset_frame + step_frames,
        window_count=len(windows),
        median_motion=round(st.median(motions), 4),
        min_motion=round(min(motions), 4),
        max_motion=round(max(motions), 4),
        median_sharpness=round(st.median([w.sharpness for w in windows]), 2),
        min_sharpness=round(min(w.sharpness for w in windows), 2),
        median_face_count=st.median([w.face_count for w in windows]),
        median_face_ratio=round(st.median([w.face_ratio for w in windows]), 5),
        median_face_edge=round(st.median([w.face_edge for w in windows]), 3),
        shot_ids=tuple(seen),
    )


def ready_regions(
    windows: Sequence[AssetWindow],
    *,
    sharpness_bar: float,
    rate,
    motion_bar: float | None = None,
    asset_duration_frames: int | None = None,
) -> list[ReadyRegion]:
    """Every stretch of this clip that is usable picture and calmer than the clip's median.

    Runs of ready windows become regions; a gap wider than one window's own length ends a
    region, because two ready windows with an unmeasured stretch between them are not one
    stretch that was checked. The ready mask is never handed out as a mask: what a caller gets
    is the list of regions, each of which knows how long it is and what it holds.
    """
    step = max(1, rate.frames_from_seconds(WINDOW_SECONDS, rounding="nearest"))
    if not windows:
        return []
    bar = clip_motion_bar(windows) if motion_bar is None else motion_bar
    if bar is None:
        return []

    runs: list[list[AssetWindow]] = []
    current: list[AssetWindow] = []
    for window in sorted(windows, key=lambda w: w.asset_frame):
        ready = (
            window.motion != MOTION_UNKNOWN
            and window.motion < bar
            and window_is_usable(window, sharpness_bar)
        )
        if not ready:
            if current:
                runs.append(current)
            current = []
            continue
        if current and window.asset_frame - current[-1].asset_frame > step:
            runs.append(current)
            current = []
        current.append(window)
    if current:
        runs.append(current)

    regions = [_summarise(run, step) for run in runs]
    if asset_duration_frames is not None:
        regions = [
            region if region.source_end <= asset_duration_frames
            else replace(region, source_end=asset_duration_frames)
            for region in regions
        ]
        regions = [region for region in regions if region.duration_frames > 0]
    return regions


# ---------------------------------------------------------------------------------------
# The edit grid — timeline coordinates
# ---------------------------------------------------------------------------------------

# What the beat tracker's grid is out by, as a share of one beat.
#
# Measured, not chosen. The editor's cuts came out *further* from the tracker's beats than
# random cuts would be, which only happens if the grid is systematically displaced. Searching
# the displacement inside one beat gives 240.0 ms on the first song and 242.0 ms on the second,
# against a half beat of 243.8 ms — the same answer twice, on two different songs, from a
# tracker that had no reason to agree with itself. A half-beat ambiguity is a known property of
# beat tracking: the grid is right about the tempo and out by one subdivision about the phase.
#
# It is derived from the interval rather than stored as a number of milliseconds on purpose.
# 240 ms is a fact about one wedding's two songs; half a beat is the thing that was measured.
GRID_PHASE_SHARE = Fraction(1, 2)

# What a grid has to look like before its phase is worth correcting. A correction applied to a
# grid that is not really periodic would move every cut by an arbitrary amount, so a grid that
# cannot be checked is refused rather than trusted.
MIN_GRID_BEATS = 8
# How far the beat intervals may scatter around their median before the grid is called
# unreliable, as a share of the median. A tracker that has lost the tempo produces intervals
# that are half and double the true one; this catches that without being tight enough to reject
# an ordinary live recording.
MAX_GRID_JITTER = Fraction(1, 5)


@dataclass(frozen=True)
class EditBeatGrid:
    """The tracker's beats, and the beats an edit is actually cut on.

    The two are kept apart deliberately. `raw_beats` is what the music analysis reported and is
    never edited in place; `beats` is the same grid moved by `phase`, and it is the only one a
    cut is ever placed against. A report that shows one without the other cannot be checked.
    """

    raw_beats: tuple[Fraction, ...]
    interval: Fraction
    phase: Fraction

    @property
    def beats(self) -> tuple[Fraction, ...]:
        return tuple(beat + self.phase for beat in self.raw_beats)

    def nearest(self, second: Fraction) -> Fraction | None:
        beats = self.beats
        return min(beats, key=lambda beat: (abs(beat - second), beat)) if beats else None

    def next_after(self, second: Fraction) -> Fraction | None:
        later = [beat for beat in self.beats if beat >= second]
        return later[0] if later else None


def beat_interval(raw_beats: Sequence[Fraction]) -> Fraction | None:
    """The median gap between beats, or None when there are not enough to have one."""
    if len(raw_beats) < 2:
        return None
    gaps = sorted(b - a for a, b in pairwise(raw_beats))
    gaps = [gap for gap in gaps if gap > 0]
    if not gaps:
        return None
    return gaps[len(gaps) // 2]


def grid_is_reliable(raw_beats: Sequence[Fraction]) -> bool:
    """Whether this grid is periodic enough that moving its phase means anything."""
    if len(raw_beats) < MIN_GRID_BEATS:
        return False
    interval = beat_interval(raw_beats)
    if interval is None or interval <= 0:
        return False
    gaps = [b - a for a, b in pairwise(raw_beats)]
    off = sum(1 for gap in gaps if abs(gap - interval) > interval * MAX_GRID_JITTER)
    return off * 2 <= len(gaps)


def edit_grid(raw_beats: Sequence[Fraction]) -> EditBeatGrid | None:
    """The grid an edit is cut on, or None when the music analysis cannot supply one.

    Fails closed. A caller that gets None has no music grid and must fall back to whatever it
    did before there was one; it must not guess a tempo.
    """
    ordered = tuple(sorted(raw_beats))
    if not grid_is_reliable(ordered):
        return None
    interval = beat_interval(ordered)
    if interval is None:
        return None
    return EditBeatGrid(raw_beats=ordered, interval=interval,
                        phase=interval * GRID_PHASE_SHARE)


# ---------------------------------------------------------------------------------------
# Duration — beats, by section
# ---------------------------------------------------------------------------------------

# What a cut runs when nothing is known about the section it sits in. One beat is this film's
# commonest cut, not a rule about weddings: it is the finale's length, where 50 of 54 cuts are
# exactly one beat, and the quiet passage six sections earlier runs six.
DEFAULT_SECTION_BEATS = 1


def section_beats(
    section_key: str | None, policy: dict[str, int] | None,
    *, default: int = DEFAULT_SECTION_BEATS,
) -> int:
    """How many beats a cut in this section runs.

    The policy is a table the caller supplies, measured on the film being reconstructed. It is
    a parameter rather than a constant because the numbers this wedding produced — 2, 6, 1 —
    are facts about this wedding's song and this editor's reading of it. One number for every
    section would contradict what was measured; one number written into this file would claim
    the measurement generalises, and it has not been shown to.
    """
    if policy and section_key is not None and section_key in policy:
        return max(1, int(policy[section_key]))
    return max(1, default)


def beats_to_frames(beats: int, interval: Fraction, rate) -> int:
    """A whole number of beats as a whole number of frames."""
    return max(1, rate.frames_from_seconds(interval * beats, rounding="nearest"))


# ---------------------------------------------------------------------------------------
# The decision
# ---------------------------------------------------------------------------------------

# Where inside a chosen region the cut starts.
#
# Nothing measured ranks the positions inside a ready region — that was the finding, not a gap
# in the work: the editor's neighbourhood is ready for a median of 94% of its length, so there
# is no within-region winner to learn. What is left is a choice about margins, and the middle
# is the position furthest from both edges of the stretch that was checked. The earliest
# position was tried in three earlier rounds and is the head bias that collapsed them.
SNAP_STRATEGY = "centred in the chosen ready region"

OUT_SAFE = "OUT_SAFE"
OUT_NEAR_BREAKDOWN = "OUT_NEAR_BREAKDOWN"
OUT_OUTSIDE_READY_REGION = "OUT_OUTSIDE_READY_REGION"

# An event shot is a source this pipeline has not been shown to handle. It is never inferred:
# no measurement here separates one from an ordinary shot, and the one candidate rule — the
# local motion peak — held on two of the four events in the set, which is a coin toss.
EVENT_UNKNOWN = "EVENT_UNKNOWN"


@dataclass(frozen=True)
class ShadowSourceMomentDecision:
    """One cut, as this arrangement would have made it, with everything it was told.

    Source and timeline are named apart all the way through: `source_start` is a frame in the
    media file, `timeline_second` is a position in the edit. The mapping between them is the
    whole point of the module and is never left implicit.
    """

    source_start: int | None
    frames: int
    region: ReadyRegion | None
    region_rank: int | None
    region_count: int
    timeline_second: Fraction | None
    raw_beat: Fraction | None
    corrected_beat: Fraction | None
    phase: Fraction | None
    beats: int | None
    beats_requested: int | None
    out_status: str | None
    fallback: bool
    reason: str
    event: str


def _eligible(regions: Sequence[ReadyRegion], frames: int, floor_frame: int) -> list[ReadyRegion]:
    return [
        region for region in regions
        if max(region.source_start, floor_frame) + frames <= region.source_end
    ]


def rank_regions(regions: Sequence[ReadyRegion]) -> list[ReadyRegion]:
    """The order regions are tried in: longest first, then calmest, then earliest.

    Length first because length is the measured thing — a long ready stretch is the material
    saying at length that it is usable, and every alternative ordering would need a weight
    nothing here has earned. The rest is there only so the order is total and the result is the
    same every run.
    """
    return sorted(
        regions,
        key=lambda region: (-region.duration_frames, region.median_motion, region.source_start),
    )


def centred_start(region: ReadyRegion, frames: int, floor_frame: int) -> int:
    """Where in a region a cut of this length starts, under SNAP_STRATEGY."""
    lowest = max(region.source_start, floor_frame)
    highest = region.source_end - frames
    return max(lowest, min(lowest + (highest - lowest) // 2, highest))


def validate_out(
    region: ReadyRegion, windows: Sequence[AssetWindow], source_out: int, motion_bar: float,
) -> str:
    """What happens at the end of the cut, in the three states worth telling apart.

    The editor's out-points are not his in-points read backwards — motion rises after them,
    which is the picture running out rather than the cut being placed. This does not optimise
    an out-point; it says which of three things is true about the one the duration produced.
    """
    if source_out > region.source_end:
        return OUT_OUTSIDE_READY_REGION
    after = [w for w in windows if w.asset_frame >= source_out]
    if after and after[0].motion != MOTION_UNKNOWN and after[0].motion > motion_bar:
        return OUT_NEAR_BREAKDOWN
    return OUT_SAFE


def decide(
    windows: Sequence[AssetWindow],
    *,
    sharpness_bar: float,
    rate,
    asset_duration_frames: int,
    grid: EditBeatGrid | None,
    timeline_second: Fraction | None,
    section_key: str | None = None,
    section_policy: dict[str, int] | None = None,
    floor_frame: int = 0,
    fallback_frames: int | None = None,
    allow_shorter_beats: bool = True,
) -> ShadowSourceMomentDecision:
    """One cut: which stretch, where in it, when on the timeline, and for how long.

    Fails closed at every step. No windows, no grid, no region long enough — each of those
    comes back as a fallback carrying its reason, and a caller that sees `fallback` is expected
    to use whatever it would have used before this module existed. Nothing here ever returns a
    guessed tempo, a guessed region, or a start outside the clip.
    """
    def give_up(reason: str, frames: int = 0) -> ShadowSourceMomentDecision:
        return ShadowSourceMomentDecision(
            source_start=None, frames=frames, region=None, region_rank=None,
            region_count=len(regions), timeline_second=timeline_second, raw_beat=None,
            corrected_beat=None, phase=None, beats=None, beats_requested=None,
            out_status=None, fallback=True, reason=reason, event=EVENT_UNKNOWN)

    regions: list[ReadyRegion] = []
    if not windows:
        return give_up("clip has no measured windows")

    motion_bar = clip_motion_bar(windows)
    if motion_bar is None:
        return give_up("clip has no measured motion")
    regions = ready_regions(
        windows, sharpness_bar=sharpness_bar, rate=rate, motion_bar=motion_bar,
        asset_duration_frames=asset_duration_frames)
    if not regions:
        return give_up("no ready region on the clip")

    if grid is None or timeline_second is None:
        frames = fallback_frames or 0
        return give_up("no reliable beat grid", frames)

    wanted = section_beats(section_key, section_policy)
    frames = beats_to_frames(wanted, grid.interval, rate)
    raw = min(grid.raw_beats, key=lambda beat: (abs(beat - timeline_second), beat))
    corrected = grid.nearest(timeline_second)
    ordered = rank_regions(regions)

    # The fallback order, in full: a start inside the chosen region, then another region of the
    # same clip — both of which `_eligible` and the ranking already cover — and only then a
    # shorter whole number of beats. The duration is never trimmed to an arbitrary frame count:
    # it stays on the grid or the decision fails.
    candidates = range(wanted, 0, -1) if allow_shorter_beats else (wanted,)
    for beats in candidates:
        frames = beats_to_frames(beats, grid.interval, rate)
        eligible = _eligible(ordered, frames, floor_frame)
        if not eligible:
            continue
        region = eligible[0]
        start = centred_start(region, frames, floor_frame)
        if start + frames > asset_duration_frames:
            continue
        break
    else:
        return give_up("no ready region holds a cut of a supported length", frames)

    return ShadowSourceMomentDecision(
        source_start=start, frames=frames, region=region,
        region_rank=ordered.index(region), region_count=len(regions),
        timeline_second=timeline_second, raw_beat=raw, corrected_beat=corrected,
        phase=grid.phase, beats=beats, beats_requested=wanted,
        out_status=validate_out(region, windows, start + frames, motion_bar),
        fallback=False, reason="ok", event=EVENT_UNKNOWN)
