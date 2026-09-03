"""OpenTimelineIO JSON and Final Cut Pro XML exporters for Resolve import."""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path
from xml.etree import ElementTree as ET

from ..domain import TimelinePlan


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


def plan_as_dict(plan: TimelinePlan) -> dict[str, object]:
    return {
        "id": plan.id,
        "name": plan.name,
        "project_id": plan.project_id,
        "frame_rate": f"{plan.frame_rate.numerator}/{plan.frame_rate.denominator}",
        "target_duration_seconds": str(plan.target_duration),
        "actual_duration_seconds": str(plan.duration),
        "warnings": plan.warnings,
        "items": [
            {
                "id": item.id,
                "asset_id": item.asset.id,
                "clip_name": item.asset.name,
                "source_path": str(item.asset.path),
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
                "media_reference": {
                    "OTIO_SCHEMA": "ExternalReference.1",
                    "target_url": item.asset.path.resolve().as_uri(),
                    "available_range": _otio_range(Fraction(0, 1), item.asset.duration, source_rate),
                    "available_image_bounds": None,
                    "metadata": {},
                    "name": item.asset.name,
                },
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
                }
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
            start="0s",
            duration=_rational_time(item.asset.duration),
            hasVideo="1",
            format="r1",
        )
        ET.SubElement(
            asset_element,
            "media-rep",
            kind="original-media",
            src=item.asset.path.resolve().as_uri(),
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
    for item in plan.items:
        clip = ET.SubElement(
            spine,
            "asset-clip",
            name=item.asset.name,
            ref=assets[item.asset.id],
            offset=_rational_time(item.timeline_range.start_seconds),
            start=_rational_time(item.source_range.start_seconds),
            duration=_rational_time(item.timeline_range.duration_seconds),
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
