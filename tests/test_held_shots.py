"""The edit has to hold a shot sometimes, the way the references do.

Built from cut-length averages alone the edit came out uniformly around a second — median
0.96s, longest cut 2.48s, nothing over three seconds anywhere. Measured across the 18
references: a quarter of their running time sits in shots longer than three seconds, they
reach 19 seconds, and they hold most at the two ends of a film. That difference is what an
entrance or a slow passage is made of.
"""

import unittest
from fractions import Fraction
from pathlib import Path

from sevenfilm.domain import BeatGrid, MediaAsset, Shot
from sevenfilm.services.planner import (
    DEFAULT_HELD_SECONDS,
    HELD_SHOT_SECONDS,
    _held_duration,
    _held_seconds,
    _held_share,
    _hold_frequency,
    _hold_this_cut,
    build_timeline,
)
from sevenfilm.timebase import FrameRate, TimeRange

RATE = FrameRate(25)


def grid(gap="1/2", seconds=300):
    step = Fraction(gap)
    return BeatGrid(bpm=60 / float(step), duration=Fraction(seconds),
                    beats=tuple(Fraction(i) * step for i in range(int(Fraction(seconds) / step))),
                    sections=({"energy": "medium", "start": "0", "end": str(seconds)},))


class HoldFrequencyTests(unittest.TestCase):
    """A share of screen time is not a share of cuts, and reading it as one overshoots."""

    def test_a_quarter_of_the_time_is_far_fewer_than_a_quarter_of_the_cuts(self):
        frequency = _hold_frequency(Fraction(1, 4), Fraction(4), Fraction(1))

        # One cut in thirteen, not one in four.
        self.assertAlmostEqual(float(frequency), 1 / 13, places=2)

    def test_the_frequency_really_does_spend_the_share(self):
        share, held, ordinary = Fraction(1, 4), Fraction(4), Fraction(1)
        frequency = _hold_frequency(share, held, ordinary)

        spent = frequency * held / (frequency * held + (1 - frequency) * ordinary)

        self.assertAlmostEqual(float(spent), float(share), places=6)

    def test_no_share_means_no_holds(self):
        self.assertEqual(_hold_frequency(Fraction(0), Fraction(4), Fraction(1)), 0)

    def test_a_degenerate_length_is_refused_rather_than_dividing_by_zero(self):
        self.assertEqual(_hold_frequency(Fraction(1, 4), Fraction(0), Fraction(1)), 0)
        self.assertEqual(_hold_frequency(Fraction(1, 4), Fraction(4), Fraction(0)), 0)

    def test_the_remainder_is_carried_so_a_run_averages_out(self):
        debt = Fraction(0)
        holds = 0
        for _ in range(130):
            hold, debt = _hold_this_cut(Fraction(1, 13), debt)
            holds += hold

        self.assertEqual(holds, 10)

    def test_the_same_run_decides_the_same_way_every_time(self):
        first = []
        second = []
        for target in (first, second):
            debt = Fraction(0)
            for _ in range(40):
                hold, debt = _hold_this_cut(Fraction(3, 10), debt)
                target.append(hold)

        self.assertEqual(first, second)


class HeldDurationTests(unittest.TestCase):
    def test_a_hold_lands_on_a_beat(self):
        landing = _held_duration(grid(), Fraction(0), Fraction(4), Fraction(60))

        self.assertIn(landing, [beat for beat in grid().beats])
        self.assertGreaterEqual(landing, HELD_SHOT_SECONDS)

    def test_the_landing_closest_to_the_wanted_length_wins(self):
        landing = _held_duration(grid(gap="7/10"), Fraction(0), Fraction(4), Fraction(60))

        # Beats every 0.7s: 3.5 and 4.2 straddle 4.0, and 4.2 is the nearer.
        self.assertEqual(landing, Fraction(42, 10))

    def test_no_beat_in_range_means_no_hold(self):
        sparse = BeatGrid(bpm=6, duration=Fraction(300),
                          beats=tuple(Fraction(i * 10) for i in range(30)),
                          sections=({"energy": "medium", "start": "0", "end": "300"},))

        self.assertIsNone(_held_duration(sparse, Fraction(0), Fraction(4), Fraction(12)))

    def test_a_hold_never_swallows_a_long_remainder(self):
        landing = _held_duration(grid(), Fraction(0), Fraction(20), Fraction(30))

        self.assertLessEqual(landing, Fraction(10))

    def test_but_the_ending_can_still_hold(self):
        """The references spend 56% of their last tenth held; a plain third-of-what-is-left
        rule made the ending the one place a hold could never happen."""
        landing = _held_duration(grid(), Fraction(0), Fraction(4), Fraction(45, 10))

        self.assertIsNotNone(landing)
        self.assertGreaterEqual(landing, HELD_SHOT_SECONDS)

    def test_nothing_is_held_when_there_is_no_room_at_all(self):
        self.assertIsNone(_held_duration(grid(), Fraction(0), Fraction(4), Fraction(2)))


class HeldProfileTests(unittest.TestCase):
    def profile(self, **held):
        return {"held_shots": held}

    def test_the_share_is_read_band_by_band(self):
        profile = self.profile(share_by_band=[0.38, 0.1, 0.56])

        self.assertEqual(_held_share(profile, 0.0), Fraction(38, 100))
        self.assertEqual(_held_share(profile, 0.5), Fraction(10, 100))
        self.assertEqual(_held_share(profile, 1.0), Fraction(56, 100))

    def test_the_length_is_read_band_by_band_too(self):
        profile = self.profile(median_seconds_by_band=[4.1, 3.4, 5.3], median_seconds=4.0)

        self.assertEqual(_held_seconds(profile, 0.0), Fraction(41, 10))
        self.assertEqual(_held_seconds(profile, 0.9), Fraction(53, 10))

    def test_a_band_with_no_measured_length_falls_back_to_the_overall_median(self):
        profile = self.profile(median_seconds_by_band=[None, None], median_seconds=4.0)

        self.assertEqual(_held_seconds(profile, 0.0), Fraction(4))

    def test_no_profile_at_all_still_holds_something(self):
        self.assertEqual(_held_seconds(None), DEFAULT_HELD_SECONDS)
        self.assertGreater(_held_share(None, 0.5), 0)


class HeldShotsReachThePlanTests(unittest.TestCase):
    def plan(self, profile):
        assets, shots = [], []
        for index in range(160):
            asset = MediaAsset(id=f"a{index}", project_id="p", path=Path(f"/m/{index}.mov"),
                               name=f"{index}.mov", duration=Fraction(30), frame_rate=RATE,
                               width=1920, height=1080)
            assets.append(asset)
            shots.append(Shot(id=f"s{index}", asset_id=asset.id,
                              source_range=TimeRange(0, 750, RATE), category="couple",
                              shot_scale="medium", technical_quality=.85, aesthetic_score=.85,
                              motion_score=.5, confidence=.85,
                              duplicate_group=f"visual:{index:016x}", brightness=.36,
                              saturation=.15, highlight_clipping=.01))
        return build_timeline(project_id="p", assets=assets, shots=shots, music=grid(),
                              frame_rate=RATE, target_duration=Fraction(120),
                              style_profile=profile, seed=1)

    def test_a_measured_profile_produces_held_shots(self):
        plan = self.plan({"held_shots": {"share_by_band": [0.25] * 10, "median_seconds": 4.0}})
        held = [i for i in plan.items if i.timeline_range.duration_seconds > HELD_SHOT_SECONDS]

        self.assertGreater(len(held), 0)

    def test_a_zero_share_produces_none(self):
        plan = self.plan({"held_shots": {"share_by_band": [0.0] * 10, "median_seconds": 4.0}})
        held = [i for i in plan.items if i.timeline_range.duration_seconds > HELD_SHOT_SECONDS]

        self.assertEqual(held, [])

    def test_the_share_of_time_held_is_near_what_was_asked_for(self):
        plan = self.plan({"held_shots": {"share_by_band": [0.25] * 10, "median_seconds": 4.0}})
        total = sum(float(i.timeline_range.duration_seconds) for i in plan.items)
        held = sum(float(i.timeline_range.duration_seconds) for i in plan.items
                   if i.timeline_range.duration_seconds > HELD_SHOT_SECONDS)

        self.assertAlmostEqual(held / total, 0.25, delta=0.10)
