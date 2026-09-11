"""The song's own passages, and the edit behaviour they ask for.

Measured on one wedding the editor cut by hand, against the track it was cut to. Music energy
and shot length correlate at -0.40, energy and slow motion at -0.62, energy and the movement
in the selected shot at +0.46 once the time of day is held constant. Across the song's own
passages the median cut runs 1.52 s where the track is quiet and 0.50 s at its peak, and the
slowed cuts sit at a mean energy of 0.126 against 0.294 for the rest.

Three coarse labels cannot express that: a song spends most of its length in the middle one,
and the quiet opening and the breakdown both read as "low" while their cuts run 1.52 and 2.40
seconds. So each section also carries the level it reached and the direction it moved, both
measured off the track rather than written here.
"""

import unittest
from fractions import Fraction

from sevenfilm.domain import BeatGrid
from sevenfilm.services.planner import (
    PACING_LEVEL_SPAN,
    SLOW_MOTION_LEVEL,
    SLOW_MOTION_MIN_RATIO,
    _motion_target,
    _pacing_scale,
    _section_at,
    _section_level,
)

TARGETS = {"low": 0.30, "medium": 0.55, "high": 0.78}


def grid(*sections):
    return BeatGrid(bpm=120.0, beats=(), duration=Fraction(200), sections=sections)


class TheSongsOwnPassagesTests(unittest.TestCase):
    def test_a_second_lands_in_its_passage(self):
        music = grid(
            {"start": "0", "end": "60", "energy": "low", "level": 0.12},
            {"start": "60", "end": "120", "energy": "high", "level": 0.91},
        )

        self.assertEqual(_section_at(music, Fraction(30))["energy"], "low")
        self.assertEqual(_section_at(music, Fraction(90))["energy"], "high")

    def test_a_second_past_the_end_belongs_to_no_passage(self):
        music = grid({"start": "0", "end": "60", "energy": "low", "level": 0.12})

        self.assertIsNone(_section_at(music, Fraction(90)))

    def test_a_track_analysed_before_levels_keeps_todays_pace(self):
        """Deriving a level from the coarse label would charge the same energy twice: the
        label is already what the reference profile's beats-per-cut table reads."""
        self.assertIsNone(_section_level({"energy": "low"}))
        self.assertEqual(_pacing_scale({"energy": "low"}), Fraction(1))

    def test_a_level_outside_the_range_is_not_trusted(self):
        self.assertIsNone(_section_level({"level": 1.4}))
        self.assertIsNone(_section_level({"level": -0.2}))


class ThePaceFollowsTheTrackTests(unittest.TestCase):
    def test_a_quiet_passage_stretches_the_cut(self):
        self.assertGreater(_pacing_scale({"level": 0.05}), 1)

    def test_a_driving_passage_shortens_it(self):
        self.assertLess(_pacing_scale({"level": 0.95}), 1)

    def test_a_mid_passage_keeps_exactly_the_pace_it_has_today(self):
        """Only the extremes are stretched, so a song that sits in its middle changes nothing
        about the edit the profile already produces."""
        self.assertEqual(_pacing_scale({"level": 0.5}), Fraction(1))

    def test_the_spread_is_about_three_to_one(self):
        """The reference edit runs 1.52 s where the track is quiet against 0.50 at its peak."""
        quiet = _pacing_scale({"level": 0.0})
        driving = _pacing_scale({"level": 1.0})

        self.assertAlmostEqual(float(quiet / driving), 5 / 3, places=2)
        self.assertEqual(PACING_LEVEL_SPAN, 0.5)

    def test_an_unreadable_song_is_left_alone(self):
        self.assertEqual(_pacing_scale(None), Fraction(1))


class TheMovementTargetFollowsTheTrackTests(unittest.TestCase):
    def test_a_quiet_passage_asks_for_stiller_pictures(self):
        self.assertLess(_motion_target(TARGETS, "low", 0.0), TARGETS["medium"])

    def test_a_driving_passage_asks_for_movement(self):
        self.assertGreater(_motion_target(TARGETS, "high", 1.0), TARGETS["medium"])

    def test_it_reads_continuously_between_the_three(self):
        """A song spends most of its length between the labels, and the editor's preference is
        finer than three steps: energy and selected movement correlate at +0.46."""
        quarter = _motion_target(TARGETS, "low", 0.25)

        self.assertGreater(quarter, TARGETS["low"])
        self.assertLess(quarter, TARGETS["medium"])

    def test_without_a_level_the_three_steps_stand(self):
        self.assertEqual(_motion_target(TARGETS, "high", None), TARGETS["high"])


class SlowingFollowsTheQuietPassagesTests(unittest.TestCase):
    """The rule used to be "a held shot in a low-energy section", and holds are rare enough
    that production edits came out with almost none: 6 of 113 cuts, energy correlating with
    slowing at -0.19. Read off the song's own level instead, the same shoot reaches 22 of 114
    at -0.51, against the editor's 41 of 167 at -0.62 — and the energy the slowed cuts sit at
    matches almost exactly, 0.119 against 0.125.
    """

    def test_the_boundary_stays_in_the_lower_third(self):
        """Read as a share of the track's own floor-to-peak range, not as a loudness: a third
        of that range is what separates the passages the editor slows from the ones they do
        not. Above half the range it would start slowing the middle of the song."""
        self.assertGreater(SLOW_MOTION_LEVEL, 0.0)
        self.assertLess(SLOW_MOTION_LEVEL, 0.5)

    def test_a_short_cut_is_never_slowed(self):
        """Half speed on a fifth of a second is a stutter, not a gesture. The editor's slowed
        cuts run a median of 1.72 s against 0.50 for the rest."""
        self.assertGreater(SLOW_MOTION_MIN_RATIO, 1)


if __name__ == "__main__":
    unittest.main()
