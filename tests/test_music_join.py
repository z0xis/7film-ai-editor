import unittest
from fractions import Fraction
from itertools import pairwise
from pathlib import Path

from sevenfilm.domain import BeatGrid
from sevenfilm.services.music import (
    STORY_BOUNDARIES,
    MusicSegment,
    MusicTrack,
    choose_window,
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
        """The two lists are written apart; this is what keeps them from drifting.

        These are the fallback arc's turns. When a profile carries a measured arc the planner
        follows that instead, and tying the song switches to it is separate work.
        """
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


def two_part_grid(*, bpm, seconds, beat_gap, quiet_until):
    """A song that starts calm and opens up, which is what most of them do."""
    gap = Fraction(beat_gap)
    beats = tuple(Fraction(i) * gap for i in range(int(Fraction(seconds) / gap)))
    return BeatGrid(
        bpm=bpm, beats=beats, duration=Fraction(seconds),
        sections=(
            {"energy": "low", "start": Fraction(0), "end": Fraction(quiet_until)},
            {"energy": "high", "start": Fraction(quiet_until), "end": Fraction(seconds)},
        ))


class ChooseWindowTests(unittest.TestCase):
    """A song does not have to be used from its first second to its last."""

    def setUp(self):
        self.grid = two_part_grid(bpm=120, seconds=200, beat_gap="1/2", quiet_until=60)

    def test_the_party_takes_the_part_that_moves(self):
        self.assertEqual(choose_window(self.grid, Fraction(40), "high"), Fraction(60))

    def test_the_opening_takes_the_calm_part(self):
        self.assertEqual(choose_window(self.grid, Fraction(40), "low"), Fraction(0))

    def test_asking_for_nothing_uses_the_song_from_its_start(self):
        self.assertEqual(choose_window(self.grid, Fraction(40), None), Fraction(0))

    def test_a_song_no_longer_than_the_slot_is_used_whole(self):
        self.assertEqual(choose_window(self.grid, Fraction(200), "high"), Fraction(0))
        self.assertEqual(choose_window(self.grid, Fraction(400), "high"), Fraction(0))

    def test_the_window_never_runs_past_the_end_of_the_song(self):
        for length in (Fraction(10), Fraction(90), Fraction(150)):
            start = choose_window(self.grid, length, "high")
            self.assertLessEqual(start + length, self.grid.duration, f"{length} sn")

    def test_the_song_comes_in_on_a_beat(self):
        odd = BeatGrid(
            bpm=120, beats=tuple(Fraction(1, 4) + Fraction(i, 2) for i in range(400)),
            duration=Fraction(200),
            sections=({"energy": "low", "start": Fraction(0), "end": Fraction(61)},
                      {"energy": "high", "start": Fraction(61), "end": Fraction(200)}))

        start = choose_window(odd, Fraction(40), "high")

        self.assertIn(start, odd.beats)
        self.assertLessEqual(start, Fraction(61))

    def test_a_song_with_no_energy_to_choose_between_is_used_from_the_start(self):
        flat = BeatGrid(bpm=120, beats=tuple(Fraction(i, 2) for i in range(400)),
                        duration=Fraction(200),
                        sections=({"energy": "medium", "start": Fraction(0), "end": Fraction(200)},))

        self.assertEqual(choose_window(flat, Fraction(40), "high"), Fraction(0))


class WindowedJoinTests(unittest.TestCase):
    """The chosen window has to reach the segments, the beats and the sections alike."""

    def setUp(self):
        self.slow = MusicTrack(Path("/m/yavas.mp3"),
                               two_part_grid(bpm=80, seconds=240, beat_gap="3/4", quiet_until=150))
        self.fast = MusicTrack(Path("/m/hareketli.mp3"),
                               two_part_grid(bpm=140, seconds=200, beat_gap="1/2", quiet_until=90))

    def joined(self, total=Fraction(120)):
        return join_tracks([self.slow, self.fast], story_switch_points(2, total), total)

    def test_the_party_song_is_taken_from_its_loud_part(self):
        _, segments, _ = self.joined()

        self.assertEqual(segments[1].source_start, Fraction(90))
        self.assertEqual(segments[1].source_end, Fraction(90) + segments[1].duration)

    def test_the_opening_song_still_starts_at_its_own_beginning(self):
        _, segments, _ = self.joined()

        self.assertEqual(segments[0].source_start, Fraction(0))

    def test_the_edit_ends_where_it_was_asked_to(self):
        combined, segments, _ = self.joined()

        self.assertEqual(combined.duration, Fraction(120))
        self.assertEqual(segments[-1].timeline_end, Fraction(120))

    def test_the_beats_of_the_windowed_song_land_on_the_edit_not_on_the_song(self):
        combined, segments, _ = self.joined()
        party = segments[1]
        inside = [beat for beat in combined.beats if beat >= party.timeline_start]

        # The song's 90th second is the party's first frame, so its beat lands there.
        self.assertEqual(inside[0], party.timeline_start)
        self.assertLessEqual(max(inside), Fraction(120))

    def test_no_beat_from_the_unused_part_of_the_song_comes_along(self):
        combined, segments, _ = self.joined()
        party = segments[1]

        self.assertEqual(
            len([b for b in combined.beats if b >= party.timeline_start]),
            len([b for b in self.fast.grid.beats
                 if party.source_start <= b < party.source_end]))

    def test_the_sections_describe_the_window_that_plays(self):
        combined, _, _ = self.joined()

        self.assertEqual(
            [(s["energy"], s["start"], s["end"]) for s in combined.sections],
            [("low", Fraction(0), Fraction(984, 10)),
             ("high", Fraction(984, 10), Fraction(120))])

    def test_using_part_of_a_song_is_reported(self):
        _, _, warnings = self.joined()

        self.assertTrue(any("hareketli.mp3" in w and "90" in w for w in warnings))

    def test_without_a_total_the_last_song_plays_out(self):
        combined, segments, _ = join_tracks(
            [self.slow, self.fast], story_switch_points(2, Fraction(120)))

        self.assertEqual(segments[1].duration, Fraction(200))
        self.assertEqual(combined.duration, Fraction(984, 10) + Fraction(200))


class ArcSwitchPointTests(unittest.TestCase):
    """Where the songs change is read off the measured arc, not off a written list."""

    def arc(self, *bands):
        return {"story_arc": list(bands)}

    def band(self, **shares):
        base = dict.fromkeys(
            ("bride", "groom", "couple", "family", "venue", "detail", "ceremony", "party"), 0.0)
        base.update(shares)
        return base

    def measured(self):
        """The 18 references: party enters the top three at 60% and holds to 80%."""
        return self.arc(
            self.band(couple=.40, venue=.21, bride=.18, groom=.09),
            self.band(bride=.26, couple=.25, groom=.19, venue=.15),
            self.band(couple=.38, groom=.20, bride=.12, venue=.12),
            self.band(couple=.32, venue=.19, groom=.16, family=.12),
            self.band(couple=.28, bride=.21, venue=.18, family=.12),
            self.band(couple=.29, bride=.23, venue=.15, party=.13),
            self.band(couple=.38, party=.25, bride=.13, groom=.09),
            self.band(couple=.38, party=.18, groom=.15, bride=.13),
            self.band(couple=.29, party=.25, groom=.17, bride=.12),
            self.band(couple=.35, bride=.21, family=.15, party=.15),
        )

    def shares(self, count, profile):
        return [point / Fraction(150) for point in
                story_switch_points(count, Fraction(150), profile)]

    def test_two_songs_change_where_the_party_starts(self):
        """The written list said 82%, which left the upbeat song the last fifth of the film."""
        self.assertEqual(self.shares(2, self.measured()), [Fraction(6, 10)])

    def test_more_songs_add_the_boundaries_the_shares_move_most_across(self):
        points = self.shares(4, self.measured())

        self.assertIn(Fraction(6, 10), points)
        self.assertEqual(points, sorted(points))
        self.assertEqual(len(points), 3)

    def test_one_song_never_switches_whatever_the_arc_says(self):
        self.assertEqual(story_switch_points(1, Fraction(150), self.measured()), ())

    def test_an_arc_with_no_party_still_produces_switches(self):
        without = self.arc(self.band(couple=.5, bride=.3), self.band(venue=.6, couple=.2))

        self.assertEqual(len(self.shares(2, without)), 1)

    def test_no_profile_falls_back_to_the_written_list(self):
        self.assertEqual(self.shares(2, None), [Fraction(82, 100)])
        self.assertEqual(self.shares(2, {"median_shot_duration_seconds": 1.0}), [Fraction(82, 100)])

    def test_a_broken_arc_falls_back_too(self):
        for arc in ([], [{}], "nonsense", [{"couple": 1.0}]):
            self.assertEqual(self.shares(2, {"story_arc": arc}), [Fraction(82, 100)],
                             repr(arc))

    def test_more_songs_than_the_arc_has_turns_are_spaced_evenly(self):
        points = self.shares(12, self.measured())

        self.assertEqual(points, [Fraction(index, 12) for index in range(1, 12)])
