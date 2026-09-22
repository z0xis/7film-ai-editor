"""Canonical physical-source coordinates for rich-reference timeline items.

The canonical domain is decoded frames in an asset's native timebase.  Legacy
Resolve ``left``/``right`` offsets are retained as evidence but are never promoted
to canonical coordinates without an authoritative source-frame or source-time API.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from fractions import Fraction
from typing import Any


class CoordinateConfidence(StrEnum):
    AUTHORITATIVE = "AUTHORITATIVE"
    UNKNOWN_COORDINATE = "UNKNOWN_COORDINATE"


def rational_rate(value: str | float | Fraction) -> Fraction:
    """Parse frame rates without losing NTSC-style rational precision."""
    rate = value if isinstance(value, Fraction) else Fraction(str(value))
    if rate <= 0:
        raise ValueError("frame rate must be positive")
    return rate


def seconds_to_frame(seconds: str | float | Fraction, fps: Fraction) -> int:
    """Round an exact source time to the nearest decoded-frame boundary."""
    value = Fraction(str(seconds)) * rational_rate(fps)
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


@dataclass(frozen=True)
class CoordinateEvidence:
    asset_id: str
    source_filename: str
    physical_asset_frames: int | None
    source_fps: str | None
    timeline_fps: str | None
    raw_resolve_left_offset: int | None = None
    raw_resolve_right_offset: int | None = None
    raw_timeline_start: int | None = None
    raw_timeline_end: int | None = None
    retime_mode: str | None = None
    speed_ratio: str | None = None
    api_source_in_frame: int | None = None
    api_source_out_frame: int | None = None
    api_source_in_seconds: str | None = None
    api_source_out_seconds: str | None = None


@dataclass(frozen=True)
class CanonicalCoordinate:
    coordinate_schema_version: str
    asset_id: str
    source_filename: str
    physical_asset_frames: int | None
    source_fps: str | None
    timeline_fps: str | None
    raw_resolve_left_offset: int | None
    raw_resolve_right_offset: int | None
    raw_timeline_start: int | None
    raw_timeline_end: int | None
    retime_mode: str | None
    speed_ratio: str | None
    canonical_source_in: int | None
    canonical_source_out: int | None
    canonical_source_duration: int | None
    coordinate_confidence: CoordinateConfidence
    coordinate_method: str
    bounds_valid: bool | None
    duration_consistent: bool | None
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def expected_source_duration(
    *, timeline_duration_frames: int, timeline_fps: Fraction,
    source_fps: Fraction, speed_ratio: Fraction,
) -> Fraction:
    """Physical frames consumed when speed_ratio is source-time/timeline-time."""
    if timeline_duration_frames <= 0 or speed_ratio <= 0:
        raise ValueError("duration and speed ratio must be positive")
    return Fraction(timeline_duration_frames) * source_fps * speed_ratio / timeline_fps


def duration_is_consistent(
    *, canonical_duration: int, timeline_duration_frames: int,
    timeline_fps: Fraction, source_fps: Fraction, speed_ratio: Fraction,
    tolerance_frames: int = 1,
) -> bool:
    expected = expected_source_duration(
        timeline_duration_frames=timeline_duration_frames,
        timeline_fps=timeline_fps,
        source_fps=source_fps,
        speed_ratio=speed_ratio,
    )
    return abs(Fraction(canonical_duration) - expected) <= tolerance_frames


def canonicalize(evidence: CoordinateEvidence) -> CanonicalCoordinate:
    """Canonicalize only authoritative source-domain API evidence.

    Direct source frames take precedence. Source seconds are accepted only with a
    native source FPS. Raw Resolve offsets are intentionally never converted here.
    """
    source_in = evidence.api_source_in_frame
    source_out = evidence.api_source_out_frame
    method = "resolve_source_frame_api"
    if source_in is None or source_out is None:
        if (evidence.api_source_in_seconds is not None
                and evidence.api_source_out_seconds is not None
                and evidence.source_fps is not None):
            rate = rational_rate(evidence.source_fps)
            source_in = seconds_to_frame(evidence.api_source_in_seconds, rate)
            source_out = seconds_to_frame(evidence.api_source_out_seconds, rate)
            method = "resolve_source_time_api_x_native_fps"
        else:
            return _result(evidence, None, None, CoordinateConfidence.UNKNOWN_COORDINATE,
                           "none", None, None,
                           "authoritative_source_frame_or_time_metadata_missing")

    bounds = (
        evidence.physical_asset_frames is not None
        and 0 <= source_in < source_out <= evidence.physical_asset_frames
    )
    if not bounds:
        return _result(evidence, source_in, source_out,
                       CoordinateConfidence.UNKNOWN_COORDINATE, method, False, None,
                       "canonical_source_range_out_of_physical_bounds")

    consistent = None
    if (evidence.raw_timeline_start is not None and evidence.raw_timeline_end is not None
            and evidence.timeline_fps and evidence.source_fps and evidence.speed_ratio):
        consistent = duration_is_consistent(
            canonical_duration=source_out - source_in,
            timeline_duration_frames=evidence.raw_timeline_end - evidence.raw_timeline_start,
            timeline_fps=rational_rate(evidence.timeline_fps),
            source_fps=rational_rate(evidence.source_fps),
            speed_ratio=rational_rate(evidence.speed_ratio),
        )
        if not consistent:
            return _result(evidence, source_in, source_out,
                           CoordinateConfidence.UNKNOWN_COORDINATE, method, True, False,
                           "retime_duration_inconsistent")
    return _result(evidence, source_in, source_out, CoordinateConfidence.AUTHORITATIVE,
                   method, True, consistent, "authoritative_and_validated")


def _result(
    evidence: CoordinateEvidence, source_in: int | None, source_out: int | None,
    confidence: CoordinateConfidence, method: str, bounds: bool | None,
    consistent: bool | None, reason: str,
) -> CanonicalCoordinate:
    return CanonicalCoordinate(
        coordinate_schema_version="p6.30.1-canonical-source-v1",
        asset_id=evidence.asset_id, source_filename=evidence.source_filename,
        physical_asset_frames=evidence.physical_asset_frames,
        source_fps=evidence.source_fps, timeline_fps=evidence.timeline_fps,
        raw_resolve_left_offset=evidence.raw_resolve_left_offset,
        raw_resolve_right_offset=evidence.raw_resolve_right_offset,
        raw_timeline_start=evidence.raw_timeline_start,
        raw_timeline_end=evidence.raw_timeline_end,
        retime_mode=evidence.retime_mode, speed_ratio=evidence.speed_ratio,
        canonical_source_in=source_in, canonical_source_out=source_out,
        canonical_source_duration=(source_out - source_in
                                   if source_in is not None and source_out is not None else None),
        coordinate_confidence=confidence, coordinate_method=method,
        bounds_valid=bounds, duration_consistent=consistent, reason=reason,
    )


def range_relation(first: CanonicalCoordinate, second: CanonicalCoordinate) -> str:
    """Describe repeated ranges from one asset without treating reuse as a fault."""
    if first.asset_id != second.asset_id:
        return "DIFFERENT_ASSET"
    values = (first.canonical_source_in, first.canonical_source_out,
              second.canonical_source_in, second.canonical_source_out)
    if any(value is None for value in values):
        return "UNKNOWN"
    a0, a1, b0, b1 = values
    if (a0, a1) == (b0, b1):
        return "EXACT_REPEAT"
    if a1 <= b0:
        return "FORWARD_DISTINCT"
    if b1 <= a0:
        return "BACKWARD_DISTINCT"
    return "OVERLAP"
