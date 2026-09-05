"""Dependency-free domain data used in jobs, planner and interchange writers."""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

from .timebase import FrameRate, TimeRange


@dataclass(frozen=True)
class MediaAsset:
    id: str
    project_id: str
    path: Path
    name: str
    duration: Fraction
    frame_rate: FrameRate
    width: int
    height: int
    codec: str | None = None
    timecode: str | None = None
    content_hash: str | None = None


@dataclass(frozen=True)
class Shot:
    id: str
    asset_id: str
    source_range: TimeRange
    category: str = "b_roll"
    shot_scale: str = "medium"
    technical_quality: float = 0.5
    aesthetic_score: float = 0.5
    motion_score: float = 0.5
    confidence: float = 0.3
    duplicate_group: str | None = None
    labels: tuple[str, ...] = ()
    # Measured visual signature, compared against the reference style profile. All three stay
    # at zero for shots analysed before these measurements existed, which reads as "unknown".
    brightness: float = 0.0
    saturation: float = 0.0
    highlight_clipping: float = 0.0
    # How much of the frame the largest face fills, and how close it sits to the edge. Zero for
    # a shot with no face in it, and for one measured before these existed.
    face_ratio: float = 0.0
    face_edge: float = 0.0

    @property
    def has_visual_measurements(self) -> bool:
        return self.brightness > 0.0 or self.saturation > 0.0 or self.highlight_clipping > 0.0


@dataclass(frozen=True)
class BeatGrid:
    bpm: float
    beats: tuple[Fraction, ...]
    duration: Fraction
    sections: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class TimelineItem:
    id: str
    shot: Shot
    asset: MediaAsset
    source_range: TimeRange
    timeline_range: TimeRange
    score: float
    selection_reason: str
    alternatives: tuple[str, ...] = ()


@dataclass(frozen=True)
class MusicSegment:
    """One song's turn: which file, which part of it, and where that part sits on the edit."""

    path: Path
    timeline_start: Fraction
    duration: Fraction
    source_start: Fraction = Fraction(0)
    # The whole song's length, which the exports declare so a host knows how much is there
    # beyond the part being used. None when it was never measured.
    source_total: Fraction | None = None

    @property
    def timeline_end(self) -> Fraction:
        return self.timeline_start + self.duration

    @property
    def source_end(self) -> Fraction:
        return self.source_start + self.duration


@dataclass
class TimelinePlan:
    id: str
    project_id: str
    name: str
    frame_rate: FrameRate
    target_duration: Fraction
    items: list[TimelineItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    seed: int = 0
    # Every song under the edit, in order. music_path and music_duration describe the first
    # of them and stay for the callers that only ever knew about one.
    # When this plan was built. Shown in the app so a panel still holding an earlier edit is
    # visible at a glance rather than being sent to Resolve by mistake.
    created_at: str | None = None
    music_segments: tuple[MusicSegment, ...] = ()
    music_path: Path | None = None
    music_duration: Fraction | None = None

    @property
    def duration_frames(self) -> int:
        return sum(item.timeline_range.duration_frames for item in self.items)

    @property
    def duration(self) -> Fraction:
        return self.frame_rate.seconds_from_frames(self.duration_frames)

