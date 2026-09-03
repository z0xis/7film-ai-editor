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

    @property
    def duration_frames(self) -> int:
        return sum(item.timeline_range.duration_frames for item in self.items)

    @property
    def duration(self) -> Fraction:
        return self.frame_rate.seconds_from_frames(self.duration_frames)

