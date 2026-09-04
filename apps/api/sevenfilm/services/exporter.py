"""OpenTimelineIO JSON and Final Cut Pro XML exporters for Resolve import."""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path
from xml.etree import ElementTree as ET

from ..domain import MediaAsset, TimelinePlan


def _rational_time(value: Fraction) -> str:
    if value.denominator == 1:
        return f"{value.numerator}s"
    return f"{value.numerator}/{value.denominator}s"


def _otio_time(value: Fraction, rate: Fraction) -> dict[str, object]:
    return {
        "OTIO_SCHEMA": "RationalTime.1",
        "value": float(value * rate),
        "rate": float(rate),
    }


def _otio_range(start: Fraction, duration: Fraction, rate: Fraction) -> dict[str, object]:
    return {
        "OTIO_SCHEMA": "TimeRange.1",
        "start_time": _otio_time(start, rate),
        "duration": _otio_time(duration, rate),
    }


def _timecode_frames(timecode: str, rate: Fraction) -> int | None:
    """The frame a timecode names, honouring drop-frame notation.

    Drop-frame skips two frame numbers at the top of every minute except every tenth, so
    counting it as if it were continuous runs half a second fast per hour of timecode - thirty
    seconds at the time of day these cameras record. Written into an FCPXML that puts every
    clip's start outside its own media, which is the thing Resolve refuses.
    """
    drop = ";" in timecode or "," in timecode
    parts = timecode.replace(";", ":").replace(",", ":").split(":")
    if len(parts) != 4 or not all(part.isdigit() for part in parts):
        return None
    hours, minutes, seconds, frames = (int(part) for part in parts)
    nominal = round(rate)
    if nominal <= 0:
        return None
    total = (hours * 3600 + minutes * 60 + seconds) * nominal + frames
    # Only the 1000/1001 rates carry drop-frame; a semicolon at 25 fps means nothing.
    if drop and rate.denominator != 1:
        per_minute = nominal // 15
        elapsed_minutes = hours * 60 + minutes
        total -= per_minute * (elapsed_minutes - elapsed_minutes // 10)
    return total


def _asset_start(asset: MediaAsset) -> Fraction:
    """Where the media begins on its own clock, as Resolve reads it off the file.

    Resolve refuses an FCPXML whose asset claims to start at zero when the file carries a
    recorded start timecode - measured against Resolve Studio 21.0.2, the same file imports
    with the timecode and is rejected without it. Sony XAVC records it as time of day, so
    "0s" is out by more than eight hours on this footage.
    """
    if not asset.timecode:
        return Fraction(0, 1)
    rate = asset.frame_rate.value
    frames = _timecode_frames(asset.timecode, rate)
    return Fraction(0, 1) if frames is None else Fraction(frames) / rate


def plan_as_dict(plan: TimelinePlan) -> dict[str, object]:
    return {
        "id": plan.id,
        "name": plan.name,
        "project_id": plan.project_id,
        "frame_rate": f"{plan.frame_rate.numerator}/{plan.frame_rate.denominator}",
        "target_duration_seconds": str(plan.target_duration),
        "actual_duration_seconds": str(plan.duration),
        "warnings": plan.warnings,
        "music_path": str(plan.music_path) if plan.music_path else None,
        "music_duration_seconds": str(plan.music_duration) if plan.music_duration else None,
        "items": [
            {
                "id": item.id,
                "asset_id": item.asset.id,
                "clip_name": item.asset.name,
                "source_path": str(item.asset.path),
                # Resolve stretches a clip whose range overruns the media rather than refusing
                # it, so the adapter needs the source's own frame count to clamp against.
                "asset_duration_frames": item.source_range.rate.frames_from_seconds(
                    item.asset.duration, rounding="floor"
                ),
                "source_in": item.source_range.as_rational_dict(),
                "timeline_in": item.timeline_range.as_rational_dict(),
                "score": item.score,
                "category": item.shot.category,
                "shot_scale": item.shot.shot_scale,
                "selection_reason": item.selection_reason,
                "alternatives": list(item.alternatives),
            }
            for item in plan.items
        ],
    }


def export_plan_json(plan: TimelinePlan, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(plan_as_dict(plan), ensure_ascii=False, indent=2), encoding="utf-8")
    return destination


def _otio_music_track(plan: TimelinePlan, timeline_rate: Fraction) -> list[dict[str, object]]:
    """A1 with the chosen music, matching what the FCPXML and the Resolve adapter both build."""
    if not plan.music_path:
        return []
    source = plan.music_duration or plan.duration
    duration = min(plan.duration, source)
    return [
        {
            "OTIO_SCHEMA": "Track.1",
            "name": "A1 Music",
            "kind": "Audio",
            "children": [
                {
                    "OTIO_SCHEMA": "Clip.2",
                    "name": plan.music_path.name,
                    "metadata": {"sevenfilm": {"role": "music"}},
                    "source_range": _otio_range(Fraction(0, 1), duration, timeline_rate),
                    "media_references": {
                        "DEFAULT_MEDIA": {
                            "OTIO_SCHEMA": "ExternalReference.1",
                            "target_url": plan.music_path.resolve().as_uri(),
                            "available_range": _otio_range(Fraction(0, 1), source, timeline_rate),
                            "metadata": {},
                            "name": plan.music_path.name,
                        }
                    },
                    "active_media_reference_key": "DEFAULT_MEDIA",
                    "effects": [],
                    "markers": [],
                    "enabled": True,
                }
            ],
            "effects": [],
            "markers": [],
            "enabled": True,
            "metadata": {},
        }
    ]


def export_otio(plan: TimelinePlan, destination: Path) -> Path:
    """Emit canonical OTIO JSON without requiring OTIO at export time."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    timeline_rate = plan.frame_rate.value
    children = []
    for item in plan.items:
        source_rate = item.source_range.rate.value
        children.append(
            {
                "OTIO_SCHEMA": "Clip.2",
                "name": item.asset.name,
                "metadata": {
                    "sevenfilm": {
                        "score": item.score,
                        "category": item.shot.category,
                        "selection_reason": item.selection_reason,
                        "alternatives": list(item.alternatives),
                    }
                },
                "source_range": _otio_range(
                    item.source_range.start_seconds, item.source_range.duration_seconds, source_rate
                ),
                # Clip.2 keeps its media under media_references, keyed by the active one.
                # A single media_reference is the pre-0.15 shape, which OTIO refuses to read.
                "media_references": {
                    "DEFAULT_MEDIA": {
                        "OTIO_SCHEMA": "ExternalReference.1",
                        "target_url": item.asset.path.resolve().as_uri(),
                        "available_range": _otio_range(
                            Fraction(0, 1), item.asset.duration, source_rate
                        ),
                        "metadata": {},
                        "name": item.asset.name,
                    }
                },
                "active_media_reference_key": "DEFAULT_MEDIA",
                "effects": [],
                "markers": [],
                "enabled": True,
            }
        )
    payload = {
        "OTIO_SCHEMA": "Timeline.1",
        "name": plan.name,
        "global_start_time": _otio_time(Fraction(0, 1), timeline_rate),
        "metadata": {"sevenfilm": {"timeline_id": plan.id, "warnings": plan.warnings}},
        "tracks": {
            "OTIO_SCHEMA": "Stack.1",
            "name": "tracks",
            "children": [
                {
                    "OTIO_SCHEMA": "Track.1",
                    "name": "V1 Main edit",
                    "kind": "Video",
                    "children": children,
                    "effects": [],
                    "markers": [],
                    "enabled": True,
                    "metadata": {},
                },
                *_otio_music_track(plan, timeline_rate),
            ],
            "effects": [],
            "markers": [],
            "enabled": True,
            "metadata": {},
        },
    }
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return destination


def export_fcpxml(plan: TimelinePlan, destination: Path) -> Path:
    """Write FCPXML 1.10; import it to Resolve and relink to unchanged original paths."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    root = ET.Element("fcpxml", version="1.10")
    resources = ET.SubElement(root, "resources")
    frame_duration = _rational_time(Fraction(1, 1) / plan.frame_rate.value)
    format_element = ET.SubElement(
        resources,
        "format",
        id="r1",
        name="FFVideoFormat",
        frameDuration=frame_duration,
        width=str(max((item.asset.width for item in plan.items), default=1920)),
        height=str(max((item.asset.height for item in plan.items), default=1080)),
    )
    del format_element  # Keep the generated resource visible while avoiding an unused-variable warning.
    assets: dict[str, str] = {}
    for index, item in enumerate(plan.items, start=1):
        if item.asset.id in assets:
            continue
        ref = f"a{index}"
        assets[item.asset.id] = ref
        asset_element = ET.SubElement(
            resources,
            "asset",
            id=ref,
            name=item.asset.name,
            start=_rational_time(_asset_start(item.asset)),
            duration=_rational_time(item.asset.duration),
            hasVideo="1",
            # The rough cut is picture only: the camera audio of the source clips must not
            # land on an audio track, the user's music owns A1.
            hasAudio="0",
            audioSources="0",
            format="r1",
        )
        ET.SubElement(
            asset_element,
            "media-rep",
            kind="original-media",
            src=item.asset.path.resolve().as_uri(),
        )
    if plan.music_path:
        music_ref = "m1"
        music_source_duration = plan.music_duration or plan.duration
        music_timeline_duration = min(plan.duration, music_source_duration)
        music_asset = ET.SubElement(
            resources,
            "asset",
            id=music_ref,
            name=plan.music_path.name,
            start="0s",
            duration=_rational_time(music_source_duration),
            hasAudio="1",
        )
        ET.SubElement(
            music_asset,
            "media-rep",
            kind="original-media",
            src=plan.music_path.resolve().as_uri(),
        )

    library = ET.SubElement(root, "library")
    event = ET.SubElement(library, "event", name="7Film AI Editor")
    project = ET.SubElement(event, "project", name=plan.name)
    sequence = ET.SubElement(
        project,
        "sequence",
        format="r1",
        duration=_rational_time(plan.duration),
        tcStart="0s",
        tcFormat="NDF",
    )
    spine = ET.SubElement(sequence, "spine")
    for i, item in enumerate(plan.items):
        clip = ET.SubElement(
            spine,
            "asset-clip",
            name=item.asset.name,
            ref=assets[item.asset.id],
            offset=_rational_time(item.timeline_range.start_seconds),
            # The clip's start is on the media's clock too, not counted from zero.
            start=_rational_time(_asset_start(item.asset) + item.source_range.start_seconds),
            duration=_rational_time(item.timeline_range.duration_seconds),
        )
        if i == 0 and plan.music_path:
            ET.SubElement(
                clip,
                "asset-clip",
                name=plan.music_path.stem,
                ref="m1",
                offset="0s",
                start="0s",
                duration=_rational_time(music_timeline_duration),
                lane="-1",
                audioRole="music",
            )
        ET.SubElement(
            clip,
            "marker",
            start="0s",
            duration="0s",
            value=f"7Film score={item.score:.3f}; {item.selection_reason}",
        )
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(destination, encoding="utf-8", xml_declaration=True)
    return destination


def export_all(plan: TimelinePlan, exports_root: Path) -> dict[str, Path]:
    folder = exports_root / plan.id
    return {
        "plan": export_plan_json(plan, folder / "timeline-plan.json"),
        "otio": export_otio(plan, folder / "timeline.otio"),
        "fcpxml": export_fcpxml(plan, folder / "timeline.fcpxml"),
    }
