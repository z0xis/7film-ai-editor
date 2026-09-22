"""Authoritative source-time recovery from offline Resolve project metadata."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from fractions import Fraction
from itertools import pairwise
from pathlib import Path
from typing import Any


def rational_seconds(value: str) -> Fraction:
    if not value.endswith("s"):
        raise ValueError("FCPXML time must end in 's'")
    return Fraction(value[:-1])


@dataclass(frozen=True)
class OfflineSourceCoordinate:
    source_name: str
    source_start_seconds: Fraction | None
    source_end_seconds: Fraction | None
    logical_source_frame_in: int | None
    logical_source_frame_out: int | None
    source_fps: Fraction | None
    timeline_fps: Fraction | None
    speed_ratio: Fraction | None
    project_source_frames: int | None
    online_status: str
    coordinate_method: str
    bounds_valid: bool | None
    duration_consistent: bool | None


def from_resolve_item(item: dict[str, Any], timeline_fps: str | float) -> OfflineSourceCoordinate:
    """Recover local source time from Resolve's explicit source-frame API."""
    media = item.get("media", {}).get("properties") or {}
    canonical = item.get("canonical_api") or {}
    source_in = canonical.get("source_start_frame")
    source_out = canonical.get("source_end_frame")
    source_fps_value = media.get("FPS")
    speed = item.get("speed") or {}
    speed_value = speed.get("Percentage")
    frames_value = media.get("Frames")
    online = media.get("Online Status") or "UNKNOWN"
    if not all(isinstance(value, (int, float)) for value in (source_in, source_out,
                                                             source_fps_value, speed_value)):
        return OfflineSourceCoordinate(
            item.get("name", ""), None, None, None, None, None,
            Fraction(str(timeline_fps)), None, None, online, "UNKNOWN", None, None,
        )
    source_fps = Fraction(str(source_fps_value))
    timeline_rate = Fraction(str(timeline_fps))
    speed_ratio = Fraction(str(speed_value)) / 100
    source_in, source_out = int(source_in), int(source_out)
    project_frames = int(frames_value) if str(frames_value).isdigit() else None
    low, high = sorted((source_in, source_out))
    bounds = (0 <= low < high <= project_frames) if project_frames is not None else None
    expected = Fraction(item["timeline"]["duration"]) * source_fps * abs(speed_ratio) / timeline_rate
    consistent = abs(Fraction(abs(source_out - source_in)) - expected) <= 1
    return OfflineSourceCoordinate(
        source_name=item.get("name", ""),
        source_start_seconds=Fraction(source_in, 1) / source_fps,
        source_end_seconds=Fraction(source_out, 1) / source_fps,
        logical_source_frame_in=source_in,
        logical_source_frame_out=source_out,
        source_fps=source_fps, timeline_fps=timeline_rate,
        speed_ratio=speed_ratio, project_source_frames=project_frames,
        online_status=online, coordinate_method="RESOLVE_EXPLICIT_SOURCE_FRAME",
        bounds_valid=bounds, duration_consistent=consistent,
    )


def _walk_otio(node: Any):
    if isinstance(node, dict):
        if node.get("OTIO_SCHEMA", "").startswith("Clip."):
            yield node
        for value in node.values():
            yield from _walk_otio(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_otio(value)


def parse_otio_source_ranges(
    path: Path, *, track_name: str | None = None,
) -> list[OfflineSourceCoordinate]:
    """Parse local source ranges, including constant LinearTimeWarp effects."""
    document = json.loads(path.read_text(encoding="utf-8"))
    timeline_fps = Fraction(str(document["global_start_time"]["rate"]))
    rows = []
    tracks = [track for track in document["tracks"]["children"]
              if track.get("kind") == "Video"
              and (track_name is None or track.get("name") == track_name)]
    for clip in _walk_otio(tracks):
        source_range = clip.get("source_range")
        reference = (clip.get("media_references") or {}).get(
            clip.get("active_media_reference_key", "DEFAULT_MEDIA"), {})
        available = reference.get("available_range")
        if not source_range or not available:
            continue
        source_rate = Fraction(str(available["start_time"]["rate"]))
        absolute_start = Fraction(str(source_range["start_time"]["value"]))
        absolute_rate = Fraction(str(source_range["start_time"]["rate"]))
        available_start = Fraction(str(available["start_time"]["value"]))
        available_rate = Fraction(str(available["start_time"]["rate"]))
        start_seconds = absolute_start / absolute_rate - available_start / available_rate
        duration = (Fraction(str(source_range["duration"]["value"]))
                    / Fraction(str(source_range["duration"]["rate"])))
        scalars = [Fraction(str(effect["time_scalar"])) for effect in clip.get("effects", [])
                   if effect.get("OTIO_SCHEMA", "").startswith("LinearTimeWarp.")]
        speed = scalars[0] if len(scalars) == 1 else Fraction(1)
        consumed = duration * abs(speed)
        if speed < 0:
            playback_in, playback_out = start_seconds + consumed, start_seconds
        else:
            playback_in, playback_out = start_seconds, start_seconds + consumed
        frame_in = round(playback_in * source_rate)
        frame_out = round(playback_out * source_rate)
        total = round(Fraction(str(available["duration"]["value"]))
                      * source_rate / Fraction(str(available["duration"]["rate"])))
        rows.append(OfflineSourceCoordinate(
            clip.get("name", ""), playback_in, playback_out,
            frame_in, frame_out, source_rate, timeline_fps, speed, total, "OFFLINE",
            "OTIO_SOURCE_RANGE", 0 <= min(frame_in, frame_out)
            < max(frame_in, frame_out) <= total, True,
        ))
    return rows


def _interpolate(points: list[tuple[Fraction, Fraction]], time: Fraction) -> Fraction:
    for (time_a, value_a), (time_b, value_b) in pairwise(points):
        if time_a <= time <= time_b:
            return value_a + (value_b - value_a) * (time - time_a) / (time_b - time_a)
    raise ValueError("clip time falls outside FCPXML timeMap")


def parse_fcpxml_source_ranges(path: Path) -> list[dict[str, Any]]:
    """Parse source-time ranges from FCPXML clips, including linear time maps."""
    root = ET.parse(path).getroot()
    assets = {asset.attrib["id"]: asset for asset in root.findall(".//resources/asset")}
    rows = []
    for clip in [*root.findall(".//clip"), *root.findall(".//asset-clip")]:
        video = clip.find("video")
        reference = video.attrib.get("ref") if video is not None else clip.attrib.get("ref")
        if reference not in assets:
            continue
        asset = assets[reference]
        asset_start = rational_seconds(asset.attrib.get("start", "0/1s"))
        clip_start = rational_seconds(clip.attrib["start"])
        clip_end = clip_start + rational_seconds(clip.attrib["duration"])
        time_map = clip.find("timeMap")
        if time_map is None:
            source_start, source_end = clip_start, clip_end
        else:
            points = [(rational_seconds(point.attrib["time"]),
                       rational_seconds(point.attrib["value"]))
                      for point in time_map.findall("timept")]
            source_start = _interpolate(points, clip_start)
            source_end = _interpolate(points, clip_end)
        rows.append({
            "source_name": clip.attrib.get("name", ""),
            "source_start_seconds": source_start - asset_start,
            "source_end_seconds": source_end - asset_start,
            "coordinate_method": "FCPXML_SOURCE_TIME",
        })
    return rows
