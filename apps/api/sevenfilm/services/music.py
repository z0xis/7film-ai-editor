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

from sevenfilm.domain import BeatGrid, MusicSegment

# Re-exported: the segment is part of a plan, so it lives in domain, but it is this module
# that produces one and callers naturally reach for it here.
__all__ = ["MusicSegment", "MusicTrack", "choose_window", "join_tracks", "story_switch_points"]

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


# What each slot of the edit wants from its track. The opening is inserts, details and the
# ceremony, so it wants the calm part; the party wants the part that moves. A slot in between
# wants neither in particular.
SLOT_ENERGY = {"first": "low", "last": "high", "middle": "medium"}


def _slot_energy(index: int, count: int) -> str | None:
    """A single track is used from its own beginning, so it is asked for nothing."""
    if count < 2:
        return None
    if index == 0:
        return SLOT_ENERGY["first"]
    if index == count - 1:
        return SLOT_ENERGY["last"]
    return SLOT_ENERGY["middle"]


def _energy_seconds(grid: BeatGrid, start: Fraction, end: Fraction, energy: str) -> Fraction:
    total = Fraction(0)
    for section in grid.sections:
        if str(section.get("energy")) != energy:
            continue
        overlap_start = max(start, Fraction(str(section["start"])))
        overlap_end = min(end, Fraction(str(section["end"])))
        if overlap_end > overlap_start:
            total += overlap_end - overlap_start
    return total


def choose_window(grid: BeatGrid, length: Fraction, energy: str | None = None) -> Fraction:
    """Where in the track to start, so the part that plays is the part the edit wants.

    A track does not have to be used from its first second to its last. The party slot wants
    the part of its track that moves, and taking the opening bars of a song that builds for a
    minute would put the quietest thing in the file under the loudest part of the film.

    Candidate starts are the track's own section boundaries, which is where a listener hears
    the music change, plus the beginning. The best is the one holding the most of the wanted
    energy; ties go to the earliest, so a track with nothing to choose between is used from
    the start as before. The start is then pulled back to the nearest beat, so the track comes
    in on the beat rather than a fraction after it.
    """
    latest = grid.duration - length
    if latest <= 0:
        return Fraction(0)
    starts = {Fraction(0)}
    for section in grid.sections:
        start = Fraction(str(section["start"]))
        if 0 < start <= latest:
            starts.add(start)
    if energy is None:
        return Fraction(0)
    best = min(
        starts,
        key=lambda start: (-_energy_seconds(grid, start, start + length, energy), start),
    )
    earlier_beats = [beat for beat in grid.beats if beat <= best]
    return max(earlier_beats) if earlier_beats else best


@dataclass(frozen=True)
class MusicTrack:
    """A file and the grid measured from it."""

    path: Path
    grid: BeatGrid


def _shift(
    values: Sequence[Fraction], window_start: Fraction, window_end: Fraction, offset: Fraction
) -> list[Fraction]:
    """Take the beats inside the used window and put them where they land on the edit."""
    return [offset + value - window_start for value in values if window_start <= value < window_end]


def _shift_sections(
    sections: Sequence[dict[str, Any]],
    window_start: Fraction,
    window_end: Fraction,
    offset: Fraction,
) -> list[dict[str, Any]]:
    """Clip each section to the part of the track that is actually used, then move it."""
    moved: list[dict[str, Any]] = []
    for section in sections:
        start = max(window_start, Fraction(str(section["start"])))
        end = min(window_end, Fraction(str(section["end"])))
        if end <= start:
            continue
        moved.append({
            **section,
            "start": offset + start - window_start,
            "end": offset + end - window_start,
        })
    return moved


def join_tracks(
    tracks: Sequence[MusicTrack],
    switch_points: Sequence[Fraction],
    total_duration: Fraction | None = None,
) -> tuple[BeatGrid, tuple[MusicSegment, ...], list[str]]:
    """Lay the songs end to end on the edit's clock, each playing the part the edit wants.

    `switch_points` says when each song after the first takes over, so two songs need one
    point. `total_duration` closes the last slot; without it the last song plays to its end.

    A song longer than its slot is not truncated at its first second: the slot takes the part
    of it that suits — the moving part under the party, the calm part under the opening. A song
    shorter than its slot ends the slot early rather than leaving silence under the picture,
    and says so, because the switch is a musical decision and moving it quietly would be the
    wrong kind of help.
    """
    if not tracks:
        raise ValueError("En az bir şarkı gerekiyor.")
    if len(switch_points) != len(tracks) - 1:
        raise ValueError("Her ek şarkı için bir geçiş noktası gerekiyor.")

    warnings: list[str] = []
    segments: list[MusicSegment] = []
    beats: list[Fraction] = []
    sections: list[dict[str, Any]] = []
    cursor = Fraction(0)
    last = len(tracks) - 1

    for index, track in enumerate(tracks):
        if index < last:
            requested = switch_points[index] - cursor
        elif total_duration is not None:
            requested = total_duration - cursor
        else:
            requested = track.grid.duration
        playable = min(max(Fraction(0), requested), track.grid.duration)
        if index < last and playable < requested:
            short_by = requested - playable
            warnings.append(
                f"{track.path.name} kendisine ayrılan yerden {float(short_by):.0f} saniye kısa; "
                f"sonraki şarkı {float(cursor + playable):.0f}. saniyede başlıyor."
            )
        if playable <= 0:
            warnings.append(f"{track.path.name} için yer kalmadı, kurguya alınmadı.")
            continue
        window_start = choose_window(track.grid, playable, _slot_energy(index, len(tracks)))
        window_end = window_start + playable
        if window_start > 0:
            warnings.append(
                f"{track.path.name} şarkısının {float(window_start):.0f}. saniyesinden itibaren "
                f"{float(playable):.0f} saniyesi kullanıldı."
            )
        segments.append(MusicSegment(
            path=track.path, timeline_start=cursor, duration=playable,
            source_start=window_start, source_total=track.grid.duration))
        beats.extend(_shift(track.grid.beats, window_start, window_end, cursor))
        sections.extend(_shift_sections(track.grid.sections, window_start, window_end, cursor))
        cursor += playable

    if not segments:
        raise ValueError("Hiçbir şarkı kurguya sığmadı.")
    grid = BeatGrid(
        # The first song sets the reported tempo; nothing in planning reads it, and a single
        # number cannot describe two songs honestly.
        bpm=tracks[0].grid.bpm,
        beats=tuple(beats),
        duration=cursor,
        sections=tuple(sections),
    )
    return grid, tuple(segments), warnings


def plan_music(
    tracks: Sequence[MusicTrack], target_duration: Fraction
) -> tuple[BeatGrid, tuple[MusicSegment, ...], list[str]]:
    """Everything the planner needs from however many songs the editor chose.

    One song behaves exactly as it did before there could be more than one: no switch points,
    nothing to prefer, so it plays from its own beginning.
    """
    switches = story_switch_points(len(tracks), target_duration)
    return join_tracks(tracks, switches, target_duration)
