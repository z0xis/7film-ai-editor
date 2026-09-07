"""What a driving passage should look for, read off the shoot rather than written here.

The targets used to be 0.30, 0.55 and 0.78. Measured on this shoot, the median shot moves
0.283, 9% of shots reach 0.5 and 1% reach 0.78 — nineteen out of 1405. A loud passage was
asking for something the footage barely contains, and no weight can conjure it: pushing the
term from 0.15 to 0.25 moved the still-shot share in those passages only from 33% to 29% and
cost technical quality to do it.

Read as quartiles of this shoot instead, the targets come out 0.179, 0.283 and 0.376, and the
mean distance between a cut's movement and what its passage asked for falls from 0.214 to
0.079.
"""

import unittest
from fractions import Fraction

from sevenfilm.services.planner import (
    FALLBACK_MOTION_TARGETS,
    MOTION_QUANTILES,
    _motion_targets,
    _score_candidate,
)
from sevenfilm.timebase import FrameRate, TimeRange

from tests.test_recording_tail import shot as make_shot

RATE = FrameRate(50)


def moving(identifier, motion):
    return make_shot(0, 100).__class__(
        id=identifier, asset_id="a", source_range=TimeRange(0, 500, RATE), category="couple",
        shot_scale="medium", technical_quality=.8, aesthetic_score=.8, motion_score=motion,
        confidence=.8, duplicate_group=f"visual:{identifier}", brightness=.36, saturation=.15,
        highlight_clipping=.01)


class TargetsComeOffTheShootTests(unittest.TestCase):
    def test_a_calm_shoot_asks_for_calm_and_a_lively_one_for_movement(self):
        calm = _motion_targets([moving(f"s{i}", i / 1000) for i in range(100)])
        lively = _motion_targets([moving(f"s{i}", 0.5 + i / 1000) for i in range(100)])

        self.assertLess(calm["high"], lively["low"])

    def test_they_come_out_in_order(self):
        targets = _motion_targets([moving(f"s{i}", i / 100) for i in range(100)])

        self.assertLess(targets["low"], targets["medium"])
        self.assertLess(targets["medium"], targets["high"])

    def test_a_driving_passage_asks_for_the_top_quartile(self):
        targets = _motion_targets([moving(f"s{i}", i / 100) for i in range(100)])

        self.assertAlmostEqual(targets["high"], MOTION_QUANTILES["high"], places=1)

    def test_a_shoot_with_nothing_in_it_falls_back_rather_than_dividing_by_zero(self):
        self.assertEqual(_motion_targets([]), FALLBACK_MOTION_TARGETS)


class TheScoreUsesThemTests(unittest.TestCase):
    def fit(self, motion, energy, targets):
        _, parts = _score_candidate(
            moving("s", motion),
            preferred_categories=("couple",), preferred_scales=("medium",), energy=energy,
            recent=(), desired_duration=Fraction(1), random_jitter=0.0,
            motion_targets=targets,
        )
        return parts["music_fit"]

    def test_a_still_shot_fits_a_calm_shoot_driving_passage(self):
        """0.376 is what "driving" means here, not 0.78."""
        targets = {"low": 0.179, "medium": 0.283, "high": 0.376}

        self.assertGreater(self.fit(0.38, "high", targets), self.fit(0.78, "high", targets))

    def test_without_targets_it_uses_the_written_fallback(self):
        self.assertGreater(self.fit(0.78, "high", None), self.fit(0.30, "high", None))


if __name__ == "__main__":
    unittest.main()
