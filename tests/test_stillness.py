"""People who are not doing anything, and glances too short to read.

"öylece duruyorlar shota hazırlık kısmı daha." "yine duruyorlar gelin terini siliyor." And
earlier: "yine shota hazırlık var damat saçını düzeltiyor." Measured on the edit the editor
picked apart, one of those shots sits in the stillest 2% of the whole shoot and another in the
stillest 7%; 18% of the film's cuts came from the shoot's stillest quarter.

Charged only where people are the subject. A ring or a table setting is supposed to be still.

The short-cut rule is the other half of the same complaint — "kısa kalmış plan". The length was
not the fault: the references cut under half a second 16% of the time against our 10%. What
they do not do is give that half second to a wide shot of a hotel lobby, which is where 7 of
our 24 shortest cuts went, none of them a close-up.

Over 8 seeds: still shots of people 18% -> 5%, wide shots in short cuts 7.0 -> 1.0 a film.
"""

import unittest
from fractions import Fraction
from pathlib import Path

from sevenfilm.domain import BeatGrid, MediaAsset, Shot
from sevenfilm.services.planner import (
    STILL_CATEGORIES,
    STILLNESS_PENALTY,
    _score_candidate,
    build_timeline,
)
from sevenfilm.timebase import FrameRate, TimeRange

RATE = FrameRate(50)


def _score(category="couple", motion=0.05, **extra):
    return _score_candidate(
        Shot(id="s", asset_id="a", source_range=TimeRange(0, 500, RATE), category=category,
             shot_scale="medium", technical_quality=.8, aesthetic_score=.8,
             motion_score=motion, confidence=.8, duplicate_group="visual:1", brightness=.36,
             saturation=.15, highlight_clipping=.01),
        preferred_categories=("couple",), preferred_scales=("medium",), energy="medium",
        recent=(), desired_duration=Fraction(1), random_jitter=0.0, **extra)


class StillPeopleAreChargedTests(unittest.TestCase):
    def test_a_still_shot_of_people_gives_up_the_measured_amount(self):
        self.assertAlmostEqual(
            _score(motion=0.05, stillness_bar=0.18)[1]["stillness_penalty"], STILLNESS_PENALTY)

    def test_a_moving_shot_costs_nothing(self):
        self.assertEqual(_score(motion=0.9, stillness_bar=0.18)[1]["stillness_penalty"], 0.0)

    def test_a_still_life_is_supposed_to_be_still(self):
        for category in STILL_CATEGORIES:
            self.assertEqual(
                _score(category=category, motion=0.01, stillness_bar=0.18)[1][
                    "stillness_penalty"], 0.0, category)

    def test_a_moment_the_film_owes_is_never_suppressed_for_it(self):
        self.assertEqual(
            _score(motion=0.01, stillness_bar=0.18, missing_moment=True)[1][
                "stillness_penalty"], 0.0)

    def test_without_a_bar_nothing_is_charged(self):
        """A shoot that measured no motion at all does not get a film of penalties."""
        self.assertEqual(_score(motion=0.0)[1]["stillness_penalty"], 0.0)


class TheEditLeavesTheStillestFootageAloneTests(unittest.TestCase):
    """The still half of this shoot is also its better-looking half, as on the real one: a
    couple posing for the camera is sharp, well lit and doing nothing."""

    def _plan(self):
        assets, shots = [], []
        for index in range(150):
            still = index % 2 == 0
            one = MediaAsset(id=f"a{index}", project_id="p", path=Path(f"/m/{index}.mov"),
                             name=f"{index}.mov", duration=Fraction(11), frame_rate=RATE,
                             width=1920, height=1080)
            assets.append(one)
            shots.append(Shot(
                id=f"s{index}", asset_id=one.id, source_range=TimeRange(0, 500, RATE),
                category=("couple", "bride", "groom", "party")[index % 4],
                shot_scale="medium",
                technical_quality=.85 if still else .8,
                aesthetic_score=.85 if still else .8,
                # Spread rather than two values: the bar is a quantile of the shoot, and a
                # shoot whose motion sits on one number has no quarter below it.
                motion_score=(.02 + index / 3000) if still else (.4 + index / 1000),
                confidence=.9,
                duplicate_group=f"visual:{index:016x}", brightness=.36, saturation=.15,
                highlight_clipping=.01))
        beats = tuple(Fraction(i, 2) for i in range(900))
        music = BeatGrid(bpm=120, beats=beats, duration=Fraction(450),
                         sections=({"energy": "medium", "start": "0", "end": "450"},))
        return build_timeline(project_id="p", assets=assets, shots=shots, music=music,
                              frame_rate=RATE, target_duration=Fraction(120), seed=1)

    def test_the_still_half_of_the_shoot_loses_ground(self):
        """Measured against its share of the pool rather than an absolute, so the fixture's
        own mix cannot make the test pass or fail on its own. Half this shoot is still; the
        edit should be less still than that."""
        items = self._plan().items
        in_edit = sum(1 for i in items if i.shot.motion_score < 0.1) / len(items)

        self.assertLess(in_edit, 0.5 * 0.85, f"kurguda %{100 * in_edit:.0f} durgun")


class AShortCutIsNotGivenToAWideShotTests(unittest.TestCase):
    def _plan(self):
        """Wides are the better footage here, so only the rule can keep them out of a glance."""
        assets, shots = [], []
        for index in range(150):
            wide = index % 2 == 0
            one = MediaAsset(id=f"a{index}", project_id="p", path=Path(f"/m/{index}.mov"),
                             name=f"{index}.mov", duration=Fraction(11), frame_rate=RATE,
                             width=1920, height=1080)
            assets.append(one)
            shots.append(Shot(
                id=f"s{index}", asset_id=one.id, source_range=TimeRange(0, 500, RATE),
                category=("couple", "bride", "groom", "party")[index % 4],
                shot_scale="wide" if wide else "medium",
                technical_quality=.85 if wide else .8, aesthetic_score=.85 if wide else .8,
                motion_score=.5, confidence=.9, duplicate_group=f"visual:{index:016x}",
                brightness=.36, saturation=.15, highlight_clipping=.01))
        # A fast grid, so plenty of cuts land under the short-cut length.
        beats = tuple(Fraction(i, 4) for i in range(2000))
        music = BeatGrid(bpm=240, beats=beats, duration=Fraction(500),
                         sections=({"energy": "high", "start": "0", "end": "500"},))
        return build_timeline(project_id="p", assets=assets, shots=shots, music=music,
                              frame_rate=RATE, target_duration=Fraction(120), seed=1)

    def test_the_shortest_cuts_are_not_wide(self):
        # The threshold is written out rather than read from the constant, so switching the
        # rule off leaves the test still looking at the same cuts.
        plan = self._plan()
        short = [i for i in plan.items
                 if i.timeline_range.duration_seconds < Fraction(16, 25)]

        self.assertTrue(short, "hiç kısa kesim yok, test bir şey ölçmüyor")
        wides = [i.shot.id for i in short if i.shot.shot_scale == "wide"]
        self.assertEqual(wides, [], f"{len(wides)} kısa kesim geniş planda")

    def test_wides_still_reach_the_film(self):
        """Narrowed for the glance, not banned from the edit."""
        plan = self._plan()
        self.assertTrue(any(i.shot.shot_scale == "wide" for i in plan.items))


if __name__ == "__main__":
    unittest.main()
