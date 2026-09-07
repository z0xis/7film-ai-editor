"""The band is at the wedding; it is not what the wedding is about.

The editor watched an edit through and said so: "solist çok fazla görünüyor, hem bu planda hem
genel". Measured on that edit, of the shots in this shoot's top tenth for "a wedding band
performing on stage", a quarter of the film's cuts were among them — two and a half times what
an even hand would give — and the singer alone ran 17%.
"""

import unittest
from fractions import Fraction
from pathlib import Path

from sevenfilm.domain import BeatGrid, MediaAsset, Shot
from sevenfilm.services.moments import DISTRACTION_QUANTILE, Moment
from sevenfilm.services.planner import (
    DISTRACTION_PENALTY,
    _score_candidate,
    build_timeline,
)
from sevenfilm.timebase import FrameRate, TimeRange

RATE = FrameRate(50)


class TheScoreChargesForTheBandTests(unittest.TestCase):
    def components(self, distraction, missing_moment=False):
        _, parts = _score_candidate(
            Shot(id="s", asset_id="a", source_range=TimeRange(0, 500, RATE),
                 category="party", shot_scale="medium", technical_quality=.8,
                 aesthetic_score=.8, motion_score=.5, confidence=.8,
                 duplicate_group="visual:1", brightness=.36, saturation=.15,
                 highlight_clipping=.01),
            preferred_categories=("party",), preferred_scales=("medium",), energy="medium",
            recent=(), desired_duration=Fraction(1), random_jitter=0.0,
            distraction=distraction, missing_moment=missing_moment,
        )
        return parts

    def test_a_shot_of_the_band_gives_something_up(self):
        self.assertAlmostEqual(
            self.components(True)["distraction_penalty"], DISTRACTION_PENALTY)

    def test_an_ordinary_shot_gives_up_nothing(self):
        self.assertEqual(self.components(False)["distraction_penalty"], 0.0)

    def test_a_moment_is_never_suppressed_for_happening_in_front_of_the_band(self):
        """The first dance *is* in front of the band. Without this the six moments the film
        owes came out at 5.7 of six."""
        self.assertEqual(
            self.components(True, missing_moment=True)["distraction_penalty"], 0.0)


class TheBandComesDownToItsShareTests(unittest.TestCase):
    def build(self, distractions):
        assets, shots = [], []
        categories = ("couple", "bride", "groom", "party", "venue", "detail")
        for index in range(200):
            one = MediaAsset(id=f"a{index}", project_id="p", path=Path(f"/m/{index}.mov"),
                             name=f"{index}.mov", duration=Fraction(30), frame_rate=RATE,
                             width=1920, height=1080)
            assets.append(one)
            # The band's corner is the best-lit part of the room, as it was on this shoot.
            band = index % 5 == 0
            shots.append(Shot(
                id=f"s{index}", asset_id=one.id, source_range=TimeRange(0, 500, RATE),
                category=categories[index % len(categories)], shot_scale="medium",
                technical_quality=.9 if band else .8, aesthetic_score=.9 if band else .8,
                motion_score=.5, confidence=.9, duplicate_group=f"visual:{index:016x}",
                brightness=.36, saturation=.15, highlight_clipping=.01))
        beats = tuple(Fraction(i, 2) for i in range(700))
        music = BeatGrid(bpm=120, beats=beats, duration=Fraction(350),
                         sections=({"energy": "medium", "start": "0", "end": "350"},))
        return build_timeline(project_id="p", assets=assets, shots=shots, music=music,
                              frame_rate=RATE, target_duration=Fraction(150), seed=1,
                              distractions=distractions)

    def band(self):
        return frozenset(f"s{index}" for index in range(200) if index % 5 == 0)

    def share(self, plan, band):
        return sum(1 for item in plan.items if item.shot.id in band) / len(plan.items)

    def test_the_band_takes_less_of_the_film_than_it_did(self):
        band = self.band()
        before = self.share(self.build(None), band)
        after = self.share(self.build(band), band)

        self.assertLess(after, before)

    def test_it_is_not_banished_either(self):
        """The band is part of the party; the film is allowed to look at it."""
        band = self.band()

        self.assertGreater(self.share(self.build(band), band), 0.0)

    def test_the_edit_still_fills_its_target(self):
        self.assertEqual(self.build(self.band()).duration, Fraction(150))


class WhereTheLineIsDrawnTests(unittest.TestCase):
    def test_the_share_is_read_off_the_shoot_not_written_here(self):
        """A band fills more of some weddings than others; the question is which of *these*
        shots are the band's."""
        self.assertGreater(DISTRACTION_QUANTILE, 0.5)
        self.assertLess(DISTRACTION_QUANTILE, 1.0)


if __name__ == "__main__":
    unittest.main()
