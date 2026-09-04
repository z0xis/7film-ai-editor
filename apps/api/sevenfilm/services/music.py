"""Play more than one track under a single edit.

A wedding film is not one piece of music. The opening — inserts, details, the ceremony —
wants something slow, and the party wants something that moves. The planner, however, reads
one beat grid and one set of energy sections, and everything downstream of it (pacing, beat
snapping, the rhythm report) is written against that single timeline of beats.

So rather than teach every one of those to handle a list, the tracks are joined here into one
grid laid out on the edit's clock, plus the segments saying which file plays where. The
planner keeps working on a single grid; the exporters and the Resolve adapter lay down the
segments.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from sevenfilm.domain import BeatGrid


# Where the story arc turns, most telling first. These are the points at which
# planner._preferred_categories changes its answer, and test_music_join keeps the two in step.
# The order is what a wedding film is built out of: the party is the one break every edit has,
# then the ceremony, then the portraits, and so on down to the smaller hinges.
STORY_BOUNDARIES: tuple[Fraction, ...] = (
    Fraction(82, 100),   # the party starts
    Fraction(42, 100),   # the ceremony block starts
    Fraction(62, 100),   # the couple and portraits
    Fraction(28, 100),   # preparation gives way to the family
    Fraction(95, 100),   # the closing
    Fraction(10, 100),   # the venue intro ends
)


def story_switch_points(track_count: int, target_duration: Fraction) -> tuple[Fraction, ...]:
    """When each track after the first takes over, read off the story arc.

    The editor chooses how many tracks to use; where they change is a consequence of the film,
    not another setting. Two tracks change at the party, which is the one break every wedding
    edit has. A third takes the ceremony as well, a fourth the portraits, and so on down the
    arc. Past the hinges the arc actually has, the remaining tracks are spaced evenly — there
    is nothing left to read, and saying so honestly beats inventing a structural meaning.
    """
    if track_count < 1:
        raise ValueError("En az bir müzik parçası gerekiyor.")
    switches = track_count - 1
    if switches == 0:
        return ()
    if switches <= len(STORY_BOUNDARIES):
        chosen = sorted(STORY_BOUNDARIES[:switches])
    else:
        chosen = [Fraction(index, track_count) for index in range(1, track_count)]
    return tuple(point * target_duration for point in chosen)


@dataclass(frozen=True)
class MusicSegment:
    """One track's turn: which file, where it starts on the timeline, and how long it plays."""

    path: Path
    timeline_start: Fraction
    duration: Fraction
    source_start: Fraction = Fraction(0)

    @property
    def timeline_end(self) -> Fraction:
        return self.timeline_start + self.duration


@dataclass(frozen=True)
class MusicTrack:
    """A file and the grid measured from it."""

    path: Path
    grid: BeatGrid


def _shift(values: Sequence[Fraction], offset: Fraction, limit: Fraction) -> list[Fraction]:
    return [offset + value for value in values if 0 <= value < limit]


def _shift_sections(
    sections: Sequence[dict[str, Any]], offset: Fraction, limit: Fraction
) -> list[dict[str, Any]]:
    """Clip each section to the part of the track that is actually used, then move it."""
    moved: list[dict[str, Any]] = []
    for section in sections:
        start = max(Fraction(0), Fraction(str(section["start"])))
        end = min(limit, Fraction(str(section["end"])))
        if end <= start:
            continue
        moved.append({**section, "start": offset + start, "end": offset + end})
    return moved


def join_tracks(tracks: Sequence[MusicTrack], switch_points: Sequence[Fraction]) -> tuple[
    BeatGrid, tuple[MusicSegment, ...], list[str]
]:
    """Lay the tracks end to end on the edit's clock.

    `switch_points` says when each track after the first takes over, so two tracks need one
    point. A track shorter than the slot it was given ends the slot early rather than leaving
    silence under the picture, and says so: the switch is a musical decision and moving it
    quietly would be the wrong kind of help.
    """
    if not tracks:
        raise ValueError("En az bir müzik parçası gerekiyor.")
    if len(switch_points) != len(tracks) - 1:
        raise ValueError("Her ek parça için bir geçiş noktası gerekiyor.")

    warnings: list[str] = []
    segments: list[MusicSegment] = []
    beats: list[Fraction] = []
    sections: list[dict[str, Any]] = []
    cursor = Fraction(0)

    for index, track in enumerate(tracks):
        requested = (
            switch_points[index] - cursor
            if index < len(tracks) - 1
            else track.grid.duration
        )
        playable = min(max(Fraction(0), requested), track.grid.duration)
        if index < len(tracks) - 1 and playable < requested:
            short_by = requested - playable
            warnings.append(
                f"{track.path.name} kendisine ayrılan yerden {float(short_by):.0f} saniye kısa; "
                f"sonraki parça {float(cursor + playable):.0f}. saniyede başlıyor."
            )
        if playable <= 0:
            warnings.append(f"{track.path.name} için yer kalmadı, kurguya alınmadı.")
            continue
        segments.append(MusicSegment(path=track.path, timeline_start=cursor, duration=playable))
        beats.extend(_shift(track.grid.beats, cursor, playable))
        sections.extend(_shift_sections(track.grid.sections, cursor, playable))
        cursor += playable

    if not segments:
        raise ValueError("Hiçbir müzik parçası kurguya sığmadı.")
    grid = BeatGrid(
        # The first track sets the reported tempo; nothing in planning reads it, and a single
        # number cannot describe two songs honestly.
        bpm=tracks[0].grid.bpm,
        beats=tuple(beats),
        duration=cursor,
        sections=tuple(sections),
    )
    return grid, tuple(segments), warnings
