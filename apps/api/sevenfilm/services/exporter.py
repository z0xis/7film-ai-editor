"""OpenTimelineIO JSON and Final Cut Pro XML exporters for Resolve import."""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path
from xml.etree import ElementTree as ET

from ..domain import MediaAsset, MusicSegment, TimelineItem, TimelinePlan


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
        "created_at": plan.created_at,
        "music_path": str(plan.music_path) if plan.music_path else None,
        "music_duration_seconds": str(plan.music_duration) if plan.music_duration else None,
        # Every song under the edit. music_path above stays for the single-song readers; the
        # Resolve adapter lays these down one per song, each from the part that was chosen.
        "music_segments": [
            {
                "path": str(segment.path),
                "timeline_start_seconds": str(segment.timeline_start),
                "duration_seconds": str(segment.duration),
                "source_start_seconds": str(segment.source_start),
                "source_total_seconds": (
                    str(segment.source_total) if segment.source_total is not None else None
                ),
            }
            for segment in _plan_segments(plan)
        ],
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


def _plan_segments(plan: TimelinePlan) -> list[MusicSegment]:
    """The songs under this edit, as segments, however the plan was put together.

    A plan built before an edit could hold more than one song carries only music_path and
    music_duration, and those still have to export.
    """
    if plan.music_segments:
        return list(plan.music_segments)
    if not plan.music_path:
        return []
    source = plan.music_duration or plan.duration
    return [MusicSegment(
        path=plan.music_path,
        timeline_start=Fraction(0),
        duration=min(plan.duration, source),
        source_total=source,
    )]


def _otio_music_track(plan: TimelinePlan, timeline_rate: Fraction) -> list[dict[str, object]]:
    """A1 with the chosen songs, matching what the FCPXML and the Resolve adapter both build."""
    segments = [
        segment for segment in _plan_segments(plan) if segment.timeline_start < plan.duration
    ]
    if not segments:
        return []
    children: list[dict[str, object]] = []
    cursor = Fraction(0)
    for segment in segments:
        if segment.timeline_start > cursor:
            children.append({
                "OTIO_SCHEMA": "Gap.1",
                "name": "",
                "source_range": _otio_range(
                    Fraction(0, 1), segment.timeline_start - cursor, timeline_rate),
                "effects": [],
                "markers": [],
                "enabled": True,
                "metadata": {},
            })
            cursor = segment.timeline_start
        duration = min(segment.duration, plan.duration - cursor)
        if duration <= 0:
            continue
        children.append({
            "OTIO_SCHEMA": "Clip.2",
            "name": segment.path.name,
            "metadata": {"sevenfilm": {"role": "music"}},
            # The part of the song that plays, not the song from its start.
            "source_range": _otio_range(segment.source_start, duration, timeline_rate),
            "media_references": {
                "DEFAULT_MEDIA": {
                    "OTIO_SCHEMA": "ExternalReference.1",
                    "target_url": segment.path.resolve().as_uri(),
                    "available_range": _otio_range(
                        Fraction(0, 1), segment.source_total or segment.source_end, timeline_rate),
                    "metadata": {},
                    "name": segment.path.name,
                }
            },
            "active_media_reference_key": "DEFAULT_MEDIA",
            "effects": [],
            "markers": [],
            "enabled": True,
        })
        cursor += duration
    return [
        {
            "OTIO_SCHEMA": "Track.1",
            "name": "A1 Music",
            "kind": "Audio",
            "children": children,
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


def _sequence_resolution(plan: TimelinePlan) -> tuple[int, int]:
    """The shape most of the edit is actually in, not the widest width beside the tallest height.

    Taking each dimension's maximum independently invents a frame no source has: a shoot mixing
    1920x1080 with a 1080x1920 phone clip produced a square 1920x1920 timeline. An editor picks
    the format the bulk of the footage is in, so weigh each shape by the time it holds.
    """
    frames_by_shape: dict[tuple[int, int], int] = {}
    for item in plan.items:
        shape = (item.asset.width, item.asset.height)
        if shape[0] < 1 or shape[1] < 1:
            continue
        frames_by_shape[shape] = frames_by_shape.get(shape, 0) + item.timeline_range.duration_frames
    if not frames_by_shape:
        return 1920, 1080
    # Ties go to the first shape on the timeline, which keeps the export stable.
    order = {shape: index for index, shape in enumerate(frames_by_shape)}
    return max(frames_by_shape, key=lambda shape: (frames_by_shape[shape], -order[shape]))


def _anchors_here(segment: MusicSegment, item, plan: TimelinePlan) -> bool:
    """Each song hangs off the picture clip that is on screen when it comes in.

    Verified by import: eight clips, two songs, every one where the plan put it.

    FCPXML has no free-floating clip: an anchored item belongs to one clip of the spine. A
    second song entering forty seconds in has to hang off whatever is playing there, and the
    first song hangs off the first clip whether or not the edit starts at zero.
    """
    start = item.timeline_range.start_seconds
    end = start + item.timeline_range.duration_seconds
    if segment.timeline_start < start:
        return item.timeline_range.start_frame == 0
    return start <= segment.timeline_start < end


def _write_time_map(clip: ET.Element, item: TimelineItem) -> None:
    """Retime a clip that plays less source than it occupies of the timeline.

    Both the times and the values are absolute on the media clock, counted from the clip's own
    start. Measured against Resolve 21.0.2: written this way a clip laid down over two seconds
    of timeline out of one second of source comes back at exactly 0.50x, while the same map
    written relative to the clip (0s to the duration) came back at 0.01x — silently wrong, and
    without an error anywhere.
    """
    played = item.source_range.duration_seconds
    occupied = item.timeline_range.duration_seconds
    if played == occupied or occupied <= 0:
        return
    start = _asset_start(item.asset) + item.source_range.start_seconds
    time_map = ET.SubElement(clip, "timeMap")
    ET.SubElement(time_map, "timept", time=_rational_time(start),
                  value=_rational_time(start), interp="linear")
    ET.SubElement(time_map, "timept", time=_rational_time(start + occupied),
                  value=_rational_time(start + played), interp="linear")


# How long the music takes to go quiet at the end of the film.
#
# Measured on the 18 reference films: 11 of them fade their music out rather than stopping it,
# over a median 1.5 seconds (quartiles 0.9-2.6). Ours ended the song mid-bar at full volume:
# "MÜZİK PAT DİYE BİTİYOR FADE OUT FALAN OLSUN YANİ".
#
# Written as volume automation on the music clip. Verified against Resolve Studio 21.0.2 by
# importing the file and having Resolve export the timeline back: the keyframes come back as
# written. `adjust-opacity` and `<transition>` do not — Resolve drops both silently — so the
# picture is not faded here.
MUSIC_FADE_SECONDS = Fraction(3, 2)
# Silence, in the dB the format speaks.
SILENT_DB = "-96"


def _fade_out(clip: ET.Element, playing: Fraction, over: Fraction) -> None:
    """Take the music down to silence over the last `over` seconds of `playing`."""
    if playing <= over:
        return
    volume = ET.SubElement(clip, "adjust-volume")
    parameter = ET.SubElement(volume, "param", name="amount")
    animation = ET.SubElement(parameter, "keyframeAnimation")
    ET.SubElement(animation, "keyframe", time=_rational_time(playing - over), value="0")
    ET.SubElement(animation, "keyframe", time=_rational_time(playing), value=SILENT_DB)


def export_fcpxml(plan: TimelinePlan, destination: Path) -> Path:
    """Write FCPXML 1.10; import it to Resolve and relink to unchanged original paths."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    root = ET.Element("fcpxml", version="1.10")
    resources = ET.SubElement(root, "resources")
    # The sequence has one format; each source has its own. A shoot mixing 25 and 50 fps was
    # declaring every clip at the timeline's rate, which tells Resolve to read a start timecode
    # at a rate the file does not have. Resolve's own export writes a format per combination.
    sequence_format = "r0"
    sequence_width, sequence_height = _sequence_resolution(plan)
    ET.SubElement(
        resources,
        "format",
        id=sequence_format,
        name="FFVideoFormat",
        frameDuration=_rational_time(Fraction(1, 1) / plan.frame_rate.value),
        width=str(sequence_width),
        height=str(sequence_height),
    )
    asset_formats: dict[tuple[str, int, int], str] = {}
    for item in plan.items:
        rate = item.asset.frame_rate.value
        key = (f"{rate.numerator}/{rate.denominator}", item.asset.width, item.asset.height)
        if key in asset_formats:
            continue
        reference = f"f{len(asset_formats) + 1}"
        asset_formats[key] = reference
        ET.SubElement(
            resources,
            "format",
            id=reference,
            name=f"FFVideoFormat{item.asset.width}x{item.asset.height}p{float(rate):g}",
            frameDuration=_rational_time(Fraction(1, 1) / rate),
            width=str(item.asset.width),
            height=str(item.asset.height),
        )

    def format_of(asset: MediaAsset) -> str:
        rate = asset.frame_rate.value
        return asset_formats[(f"{rate.numerator}/{rate.denominator}", asset.width, asset.height)]

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
            format=format_of(item.asset),
        )
        ET.SubElement(
            asset_element,
            "media-rep",
            kind="original-media",
            src=item.asset.path.resolve().as_uri(),
        )
    # A retimed clip needs an asset of its own, starting where the cut starts.
    #
    # Measured against Resolve 21.0.2: an asset-clip carrying a timeMap has its `start` — its
    # in point — ignored, and plays from the beginning of the media whatever the map says.
    # Four ways of writing the map were tried and all four did it; the two that Resolve
    # retimed at all both landed on the media start. So the slow motion was silently playing
    # the opening of a clip instead of the moment chosen 76 seconds in. Declaring a separate
    # asset whose own start *is* the in point makes "the beginning of the media" the right
    # place, and the cut comes back at 32246.12 seconds and 0.50x, which is what was asked for.
    retimed_refs: dict[str, str] = {}
    for index, item in enumerate(plan.items, start=1):
        if item.source_range.duration_seconds == item.timeline_range.duration_seconds:
            continue
        reference = f"s{index}"
        retimed_refs[item.id] = reference
        opening = _asset_start(item.asset) + item.source_range.start_seconds
        retimed = ET.SubElement(
            resources,
            "asset",
            id=reference,
            name=item.asset.name,
            start=_rational_time(opening),
            duration=_rational_time(
                max(Fraction(0), item.asset.duration - item.source_range.start_seconds)),
            hasVideo="1",
            hasAudio="0",
            audioSources="0",
            format=format_of(item.asset),
        )
        ET.SubElement(
            retimed,
            "media-rep",
            kind="original-media",
            src=item.asset.path.resolve().as_uri(),
        )
    music_segments = [
        segment for segment in _plan_segments(plan) if segment.timeline_start < plan.duration
    ]
    music_refs: dict[str, str] = {}
    for segment in music_segments:
        key = str(segment.path)
        if key in music_refs:
            continue
        reference = f"m{len(music_refs) + 1}"
        music_refs[key] = reference
        music_asset = ET.SubElement(
            resources,
            "asset",
            id=reference,
            name=segment.path.name,
            start="0s",
            duration=_rational_time(segment.source_total or segment.source_end),
            hasAudio="1",
        )
        ET.SubElement(
            music_asset,
            "media-rep",
            kind="original-media",
            src=segment.path.resolve().as_uri(),
        )

    library = ET.SubElement(root, "library")
    event = ET.SubElement(library, "event", name="7Film AI Editor")
    project = ET.SubElement(event, "project", name=plan.name)
    sequence = ET.SubElement(
        project,
        "sequence",
        format=sequence_format,
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
            ref=retimed_refs.get(item.id, assets[item.asset.id]),
            offset=_rational_time(item.timeline_range.start_seconds),
            # The clip's start is on the media's clock too, not counted from zero.
            start=_rational_time(_asset_start(item.asset) + item.source_range.start_seconds),
            duration=_rational_time(item.timeline_range.duration_seconds),
            format=format_of(item.asset),
        )
        _write_time_map(clip, item)
        for segment in music_segments:
            if not _anchors_here(segment, item, plan):
                continue
            # An anchored item's offset is measured in the parent clip's own timeline, whose
            # origin is that clip's `start` — the media clock, not zero. The music therefore
            # begins at the parent's start plus however far into that clip the song comes in.
            #
            # Measured in Resolve Studio 21.0.2, importing this file: two songs meant for
            # 0-30s and 30-40s land exactly there, the second one entering at its own 40th
            # second. Written the old way, at offset="0s", they landed at 23.8-53.8s and
            # 0-10s — swapped, and running 13.8s past the end of a 40 second edit. With a
            # single song at the edit's start the old form did work, because Resolve clamps
            # a negative offset to zero; that is why it was never noticed.
            parent_start = _asset_start(item.asset) + item.source_range.start_seconds
            into_clip = segment.timeline_start - item.timeline_range.start_seconds
            playing = min(segment.duration, plan.duration - segment.timeline_start)
            music_clip = ET.SubElement(
                clip,
                "asset-clip",
                name=segment.path.stem,
                ref=music_refs[str(segment.path)],
                offset=_rational_time(parent_start + max(Fraction(0), into_clip)),
                start=_rational_time(segment.source_start),
                duration=_rational_time(playing),
                lane="-1",
                audioRole="music",
            )
            # Only the song the film ends on fades. A song that hands over to another one in
            # the middle of the edit is meant to run into it, not die away.
            if segment.timeline_start + playing >= plan.duration:
                _fade_out(music_clip, playing, MUSIC_FADE_SECONDS)
        # Resolve's FCPXML importer drops markers on the floor: measured on 21.0.2, none of
        # eight clip markers arrived, and neither did the same points written on the sequence.
        # Setting start to the parent's own start made no difference either, so this is not the
        # anchored-time question above. They are written for hosts that do read them; the
        # Resolve plugin path places its markers through the API, where they do land.
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
