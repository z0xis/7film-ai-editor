"""Run the moment search over a whole clip, beside the one that runs over a single shot.

Nothing here is wired into the plan. The planner's answer is still the planner's answer; this
module works out what the same search would have chosen had it been allowed to look at the
rest of the clip, and reports the two side by side.

Why this exists. Windows are measured a shot at a time and handed to the planner grouped by
shot, so `_best_offset` can only ever see the shot it was given. That was never an editorial
decision — it is what the data layout allows. Measured on the 54 clips this edit and the
editor's both use, the editor's moment falls outside the searched range in 22 of them, and in
19 it sits inside a different detected shot. A search bounded that way has a ceiling of about
59% on this material no matter how good its scoring is.

What deliberately does not change here: the scoring. Every window is scored by the planner's
own `_window_score`, with the planner's constants, aggregated by the planner's own
worst-window rule, and a window keeps the category of the shot it was measured in. The only
variable this module changes is where the search is allowed to look, so its effect can be
measured on its own.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction

from ..domain import Shot
from ..timebase import TimeRange
from .windows import AssetWindow, ShotWindow

# The handle the planner keeps off each end of a shot, expressed the same way: an eighth of
# what is available, never more than a fifth of a second. Kept at the ends of the clip for the
# same reason it is kept at the ends of a shot — the first frames are the operator pressing
# record, not the shot.
HANDLE_SECONDS = Fraction(1, 5)
HANDLE_SHARE = 8


@dataclass(frozen=True)
class SearchRange:
    """Where a moment search was allowed to start, in frames from the start of the media."""

    first_frame: int
    last_frame: int

    def holds(self, frame: int) -> bool:
        return self.first_frame <= frame <= self.last_frame

    @property
    def span_frames(self) -> int:
        return max(0, self.last_frame - self.first_frame)


@dataclass(frozen=True)
class ShadowResult:
    """What each search chose, and whether a given moment was ever in reach of either."""

    frames: int
    legacy_range: SearchRange
    legacy_start: int
    shadow_range: SearchRange | None
    shadow_start: int | None
    shadow_score: float | None
    fallback: bool
    reason: str
    host_shot_id: str | None

    def legacy_time_range(self, rate) -> TimeRange:
        return TimeRange(self.legacy_start, self.frames, rate)

    def shadow_time_range(self, rate) -> TimeRange:
        start = self.legacy_start if self.shadow_start is None else self.shadow_start
        return TimeRange(start, self.frames, rate)


def _handle(duration_frames: int, rate) -> int:
    return min(duration_frames // HANDLE_SHARE, rate.frames_from_seconds(HANDLE_SECONDS))


def legacy_search_range(shot: Shot, frames: int, consumed_frames: int = 0) -> SearchRange:
    """The range `_best_offset` may start in, in asset frames rather than shot offsets.

    Mirrors `_source_range_for_duration`: a handle off each end, and never behind what the
    shot has already given.
    """
    source = shot.source_range
    handle = _handle(source.duration_frames, source.rate)
    floor = handle + consumed_frames
    ceiling = max(floor, source.duration_frames - handle - frames)
    return SearchRange(source.start_frame + floor, source.start_frame + ceiling)


def asset_search_range(
    windows: Sequence[AssetWindow], asset_duration_frames: int, frames: int, rate,
    *, floor_frame: int = 0,
) -> SearchRange | None:
    """The range a search over the whole clip may start in.

    Bounded by the clip rather than by the shot, with the same handle kept off each end, and
    never behind `floor_frame` so a second cut from one clip still comes from later in it.
    Returns None when the clip has no measured window to search.
    """
    if not windows or asset_duration_frames <= 0:
        return None
    handle = _handle(asset_duration_frames, rate)
    first = max(handle, floor_frame)
    last = max(first, asset_duration_frames - handle - frames)
    return SearchRange(first, last)


def _covered(windows: Sequence[AssetWindow], span: SearchRange) -> bool:
    """Whether the search range has any measured window in it at all."""
    return any(span.holds(window.asset_frame) for window in windows)


def shadow_offset(
    windows: Sequence[AssetWindow],
    span: SearchRange,
    frames: int,
    sharpness_bar: float,
    *,
    window_score,
) -> tuple[int, float] | None:
    """The best start inside `span`, scored exactly the way the planner scores a run.

    Candidates are the measured window positions, as they are in `_best_offset`, plus the
    first frame of the range so a span that falls between two windows still has one. A run is
    worth its worst window, and a window is scored under the category of the shot it was
    measured in.
    """
    if not windows:
        return None
    positions = [span.first_frame] + [
        window.asset_frame for window in windows
        if span.first_frame < window.asset_frame <= span.last_frame
    ]
    best: tuple[int, float] | None = None
    for start in positions:
        covered = [
            window for window in windows
            if start <= window.asset_frame < start + frames
        ]
        if not covered:
            # The run sits between measured windows: fall back to the window at or before it,
            # which is what `_best_offset` does when a narrow range holds none of its own.
            earlier = [w for w in windows if w.asset_frame <= start]
            if not earlier:
                continue
            covered = [earlier[-1]]
        value = min(
            window_score(window.as_shot_window(), sharpness_bar, window.category)
            for window in covered
        )
        if best is None or value > best[1]:
            best = (start, value)
    return best


def evaluate(
    shot: Shot,
    frames: int,
    *,
    asset_duration_frames: int,
    windows: Sequence[AssetWindow],
    sharpness_bar: float,
    window_score,
    consumed_frames: int = 0,
    legacy_start: int | None = None,
) -> ShadowResult:
    """Both searches for one cut, with the reason when the wider one could not run.

    Fails closed: any clip without measured windows to search, or without a usable range,
    comes back as a fallback carrying the planner's own answer, never a guess.
    """
    legacy = legacy_search_range(shot, frames, consumed_frames)
    start = legacy.first_frame if legacy_start is None else legacy_start

    if frames <= 0:
        return ShadowResult(frames, legacy, start, None, None, None, True,
                            "no frames requested", None)
    if not windows:
        return ShadowResult(frames, legacy, start, None, None, None, True,
                            "clip has no measured windows", None)

    floor = shot.source_range.start_frame + consumed_frames if consumed_frames else 0
    span = asset_search_range(
        windows, asset_duration_frames, frames, shot.source_range.rate, floor_frame=floor)
    if span is None or span.span_frames < 0:
        return ShadowResult(frames, legacy, start, None, None, None, True,
                            "no usable search range on the clip", None)
    if not _covered(windows, span):
        return ShadowResult(frames, legacy, start, span, None, None, True,
                            "search range has no measured window", None)

    found = shadow_offset(windows, span, frames, sharpness_bar, window_score=window_score)
    if found is None:
        return ShadowResult(frames, legacy, start, span, None, None, True,
                            "nothing scorable in range", None)

    chosen, value = found
    host = next(
        (window.shot_id for window in reversed(windows) if window.asset_frame <= chosen),
        None,
    )
    return ShadowResult(frames, legacy, start, span, chosen, value, False, "ok", host)


def reachable(span: SearchRange | None, frame: int) -> bool:
    """Whether a moment could have been chosen by a search over this range."""
    return bool(span and span.holds(frame))


def as_shot_windows(windows: Sequence[AssetWindow]) -> list[ShotWindow]:
    """The asset view in the shape the existing scorer takes, for callers that want it."""
    return [window.as_shot_window() for window in windows]


# What an eligible window is worth before its framing is charged for.
#
# The production score starts a window at its crispness, so of two windows a search can use,
# the sharper one wins on sharpness alone. Measured against the editor on the 54 clips both
# edits share, that is the single largest thing standing between the moment he chose and the
# moment the score prefers: putting crispness back as the base value of a score that was
# otherwise reading face count cost 18.2 points of agreement, more than any other term.
#
# Here every window that clears the gate starts level, and sharpness only decides whether a
# window may be used at all. The gate itself is untouched — same threshold, same measure.
ELIGIBLE = 1.0


def gated_window_score(window: ShotWindow, sharpness_bar: float, category: str = "") -> float:
    """The planner's window score with sharpness demoted from ranker to gate.

    Line for line the production score except for the base value, so the framing charges stay
    exactly what they are and this cannot quietly drift away from them. A test holds the two
    together: on a window at or above the shoot's median sharpness, where crispness is 1.0 and
    the base values agree, both must return the same number.
    """
    from .planner import (
        BYSTANDER_LIMIT,
        BYSTANDER_PENALTY,
        FRAME_EDGE_PENALTY,
        STILL_CATEGORIES,
        UNUSABLE_SHARPNESS_SHARE,
    )

    crisp = min(1.0, window.sharpness / sharpness_bar) if sharpness_bar > 0 else 1.0
    if crisp < UNUSABLE_SHARPNESS_SHARE:
        return 0.0
    if category in STILL_CATEGORIES:
        return ELIGIBLE
    crowd = min(window.bystanders, BYSTANDER_LIMIT) / BYSTANDER_LIMIT
    return ELIGIBLE - FRAME_EDGE_PENALTY * window.face_edge - BYSTANDER_PENALTY * crowd


def unpenalised_window_score(
    window: ShotWindow, sharpness_bar: float, category: str = "",
) -> float:
    """The gated score with the charge for other people's faces taken off.

    Measured on the 54 clips both edits use, the median number of small background faces in
    the chosen window falls at every step away from the planner: the editor's own moments
    hold 1.88, the planner's 1.00, a clip-wide search 0.45, and a clip-wide search with
    sharpness demoted 0.00. The editor cuts to the busy frame; the score walks away from it,
    and once sharpness stops ranking, this charge is what decides.

    So this path neutralises it — and does nothing else. There is no reward for a crowd here:
    a frame full of people scores exactly what an empty one does. The question being asked is
    only whether "other faces are bad" is wrong, not whether "other faces are good" is right.
    Everything else, the gate and the frame-edge charge included, stays where it is.
    """
    from .planner import FRAME_EDGE_PENALTY, STILL_CATEGORIES, UNUSABLE_SHARPNESS_SHARE

    crisp = min(1.0, window.sharpness / sharpness_bar) if sharpness_bar > 0 else 1.0
    if crisp < UNUSABLE_SHARPNESS_SHARE:
        return 0.0
    if category in STILL_CATEGORIES:
        return ELIGIBLE
    return ELIGIBLE - FRAME_EDGE_PENALTY * window.face_edge
