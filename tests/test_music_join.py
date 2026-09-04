import unittest
from fractions import Fraction
from itertools import pairwise
from pathlib import Path

from sevenfilm.domain import BeatGrid
from sevenfilm.services.music import (
    STORY_BOUNDARIES,
    MusicSegment,
    MusicTrack,
    join_tracks,
    story_switch_points,
)
from sevenfilm.services.planner import _preferred_categories


def grid(*, bpm, seconds, beat_gap, energy="medium"):
    gap = Fraction(beat_gap)
    beats = tuple(Fraction(i) * gap for i in range(int(Fraction(seconds) / gap)))
    return BeatGrid(bpm=bpm, beats=beats, duration=Fraction(seconds),
                    sections=({"energy": energy, "start": Fraction(0), "end": Fraction(seconds)},))


class JoinTracksTests(unittest.TestCase):
    """The opening wants a slow track and the party wants a fast one, under one edit."""

    def setUp(self):
        self.slow = MusicTrack(Path("/m/slow.mp3"), grid(bpm=80, seconds=100, beat_gap="3/4", energy="low"))
        self.fast = MusicTrack(Path("/m/fast.mp3"), grid(bpm=140, seconds=80, beat_gap="3/7", energy="high"))

    def join(self, tracks=None, switches=(Fraction(60),)):
        return join_tracks(tracks or [self.slow, self.fast], switches)

    def test_the_second_track_takes_over_at_the_switch(self):
        _, segments, _ = self.join()

        self.assertEqual(
            [(s.path.name, s.timeline_start, s.duration) for s in segments],
            [("slow.mp3", Fraction(0), Fraction(60)), ("fast.mp3", Fraction(60), Fraction(80))])

    def test_the_grid_runs_the_whole_length_of_both(self):
        combined, _, _ = self.join()

        self.assertEqual(combined.duration, Fraction(140))

    def test_the_second_track_keeps_its_own_beats_moved_onto_the_edit(self):
        combined, _, _ = self.join()
        after = [beat for beat in combined.beats if beat >= 60]

        # The fast track's grid restarts from its own first beat at the switch.
        self.assertEqual(after[0], Fraction(60))
        self.assertEqual(after[1] - after[0], Fraction(3, 7))

    def test_the_first_track_keeps_its_own_beats_untouched(self):
        combined, _, _ = self.join()
        before = [beat for beat in combined.beats if beat < 60]

        self.assertEqual(before[1] - before[0], Fraction(3, 4))
        self.assertEqual(before[-1], Fraction(60) - Fraction(3, 4))

    def test_no_beat_is_left_over_from_the_part_of_a_track_that_never_plays(self):
        combined, _, _ = self.join()

        self.assertEqual(len([beat for beat in combined.beats if beat < 60]), 80)

    def test_the_energy_sections_are_clipped_to_what_plays(self):
        combined, _, _ = self.join()

        self.assertEqual(
            [(s["energy"], s["start"], s["end"]) for s in combined.sections],
            [("low", Fraction(0), Fraction(60)), ("high", Fraction(60), Fraction(140))])

    def test_a_track_too_short_for_its_slot_ends_the_slot_early_and_says_so(self):
        short = MusicTrack(Path("/m/short.mp3"), grid(bpm=80, seconds=40, beat_gap="3/4"))

        combined, segments, warnings = self.join([short, self.fast])

        self.assertEqual(segments[0].duration, Fraction(40))
        self.assertEqual(segments[1].timeline_start, Fraction(40))
        self.assertEqual(combined.duration, Fraction(120))
        self.assertIn("short.mp3", warnings[0])

    def test_one_track_still_works(self):
        combined, segments, warnings = self.join([self.slow], ())

        self.assertEqual(len(segments), 1)
        self.assertEqual(combined.duration, Fraction(100))
        self.assertEqual(warnings, [])

    def test_the_reported_tempo_comes_from_the_first_track(self):
        combined, _, _ = self.join()

        self.assertEqual(combined.bpm, 80)

    def test_a_switch_point_past_every_track_is_refused_rather_than_guessed(self):
        with self.assertRaises(ValueError):
            join_tracks([], ())

    def test_a_missing_switch_point_is_refused(self):
        with self.assertRaises(ValueError):
            join_tracks([self.slow, self.fast], ())

    def test_a_switch_at_zero_drops_the_first_track_with_a_warning(self):
        combined, segments, warnings = self.join(switches=(Fraction(0),))

        self.assertEqual([s.path.name for s in segments], ["fast.mp3"])
        self.assertEqual(combined.duration, Fraction(80))
        self.assertTrue(any("slow.mp3" in warning for warning in warnings))

    def test_a_segment_knows_where_it_ends(self):
        segment = MusicSegment(path=Path("/m/a.mp3"), timeline_start=Fraction(10), duration=Fraction(5))

        self.assertEqual(segment.timeline_end, Fraction(15))


class StorySwitchPointTests(unittest.TestCase):
    """How many tracks is the editor's call; where they change follows from the film."""

    def points(self, count, target=Fraction(120)):
        return [point / target for point in story_switch_points(count, target)]

    def test_one_track_never_switches(self):
        self.assertEqual(story_switch_points(1, Fraction(120)), ())

    def test_two_tracks_change_at_the_party(self):
        self.assertEqual(self.points(2), [Fraction(82, 100)])

    def test_a_third_track_takes_the_ceremony_as_well(self):
        self.assertEqual(self.points(3), [Fraction(42, 100), Fraction(82, 100)])

    def test_the_points_come_out_in_order(self):
        for count in range(2, 9):
            points = self.points(count)
            self.assertEqual(points, sorted(points), f"{count} parça")

    def test_the_points_are_seconds_on_the_edit(self):
        self.assertEqual(story_switch_points(2, Fraction(200)), (Fraction(164),))

    def test_more_tracks_than_the_arc_has_hinges_are_spaced_evenly(self):
        points = self.points(8)

        self.assertEqual(points, [Fraction(index, 8) for index in range(1, 8)])

    def test_a_switch_point_always_falls_inside_the_edit(self):
        for count in range(2, 9):
            for point in self.points(count):
                self.assertGreater(point, 0, f"{count} parça")
                self.assertLess(point, 1, f"{count} parça")

    def test_no_tracks_is_refused(self):
        with self.assertRaises(ValueError):
            story_switch_points(0, Fraction(120))

    def test_the_boundaries_are_where_the_planner_actually_turns(self):
        """The two lists are written apart; this is what keeps them from drifting."""
        turns, previous = [], _preferred_categories(0.0)
        for step in range(1, 10001):
            progress = step / 10000
            current = _preferred_categories(progress)
            if current != previous:
                turns.append(round(progress, 4))
                previous = current

        self.assertEqual(sorted(float(point) for point in STORY_BOUNDARIES), turns)


class ChosenCountTests(unittest.TestCase):
    """Whatever the count, the tracks are laid end to end over the whole edit."""

    def tracks(self, count):
        return [
            MusicTrack(Path(f"/m/{index}.mp3"), grid(bpm=90 + index, seconds=200, beat_gap="1/2"))
            for index in range(count)
        ]

    def test_every_count_covers_the_edit_without_a_gap(self):
        for count in range(1, 7):
            target = Fraction(120)
            tracks = self.tracks(count)
            combined, segments, _ = join_tracks(tracks, story_switch_points(count, target))

            self.assertEqual(len(segments), count, f"{count} parça")
            self.assertEqual(segments[0].timeline_start, Fraction(0), f"{count} parça")
            for earlier, later in pairwise(segments):
                self.assertEqual(earlier.timeline_end, later.timeline_start, f"{count} parça")
            self.assertGreaterEqual(combined.duration, target, f"{count} parça")

    def test_each_track_contributes_its_own_beats(self):
        count = 3
        tracks = self.tracks(count)
        combined, segments, _ = join_tracks(tracks, story_switch_points(count, Fraction(120)))

        for segment in segments:
            inside = [b for b in combined.beats if segment.timeline_start <= b < segment.timeline_end]
            self.assertGreater(len(inside), 0)
            self.assertEqual(inside[0], segment.timeline_start)
