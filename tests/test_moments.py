"""The moments a wedding film has to contain, found rather than waited for.

Measured on an edit the editor spent an evening picking apart. Of the eight shots that match
each moment best, this is how many reached the film: the cake one, the feeding two, and the
kiss, the ring, the first dance and the entrance none at all. All of that footage was indexed
and available.

The planner had no notion that a wedding owes its subjects certain things. It scores every
shot on quality, category, rhythm and the day's order, and the ring exchange loses to a
technically cleaner shot of somebody walking. That is what "gelin damadın girişi yok" and
"bir hikaye sıralaması yok" were describing all along.
"""

import unittest
from fractions import Fraction
from pathlib import Path

from sevenfilm.domain import BeatGrid, MediaAsset, Shot
from sevenfilm.services.moments import MOMENT_LIFT, MOMENT_PROMPTS, Moment
from sevenfilm.services.planner import MOMENT_BONUS, _score_candidate, build_timeline
from sevenfilm.timebase import FrameRate, TimeRange

RATE = FrameRate(50)


class TheScoreAsksForWhatIsMissingTests(unittest.TestCase):
    def components(self, missing):
        _, parts = _score_candidate(
            Shot(id="s", asset_id="a", source_range=TimeRange(0, 500, RATE),
                 category="couple", shot_scale="medium", technical_quality=.8,
                 aesthetic_score=.8, motion_score=.5, confidence=.8,
                 duplicate_group="visual:1", brightness=.36, saturation=.15,
                 highlight_clipping=.01),
            preferred_categories=("couple",), preferred_scales=("medium",), energy="medium",
            recent=(), desired_duration=Fraction(1), random_jitter=0.0,
            missing_moment=missing,
        )
        return parts

    def test_a_moment_the_film_has_not_shown_is_worth_something(self):
        self.assertAlmostEqual(self.components(True)["moment_bonus"], MOMENT_BONUS)

    def test_an_ordinary_shot_is_worth_nothing_extra(self):
        self.assertEqual(self.components(False)["moment_bonus"], 0.0)


class EveryMomentReachesTheFilmTests(unittest.TestCase):
    """The six that matter, each carried by one deliberately unremarkable shot."""

    def build(self, moments):
        assets, shots = [], []
        categories = ("couple", "bride", "groom", "party", "venue", "detail")
        for index in range(200):
            one = MediaAsset(id=f"a{index}", project_id="p", path=Path(f"/m/{index}.mov"),
                             name=f"{index}.mov", duration=Fraction(30), frame_rate=RATE,
                             width=1920, height=1080)
            assets.append(one)
            # Behind the rest by 0.20, which the quality and aesthetic weights turn into a
            # 0.09 deficit — just inside what the bonus can answer. On the shoot the moment
            # shots are not behind at all: they run 0.41 to 0.49 against a median of 0.406,
            # and lose to the category, share and framing terms rather than on merit. The
            # handicap here stands in for that so the test has something to overturn.
            carries = index < len(MOMENT_PROMPTS)
            shots.append(Shot(
                id=f"s{index}", asset_id=one.id, source_range=TimeRange(0, 500, RATE),
                category=categories[index % len(categories)], shot_scale="medium",
                technical_quality=.65 if carries else .85,
                aesthetic_score=.65 if carries else .85,
                motion_score=.5, confidence=.9, duplicate_group=f"visual:{index:016x}",
                brightness=.36, saturation=.15, highlight_clipping=.01))
        beats = tuple(Fraction(i, 2) for i in range(700))
        music = BeatGrid(bpm=120, beats=beats, duration=Fraction(350),
                         sections=({"energy": "medium", "start": "0", "end": "350"},))
        return build_timeline(project_id="p", assets=assets, shots=shots, music=music,
                              frame_rate=RATE, target_duration=Fraction(150), seed=1,
                              moments=moments)

    def moments(self):
        return tuple(
            Moment(name=name, shot_ids=(f"s{index}",), best=0.3)
            for index, name in enumerate(MOMENT_PROMPTS)
        )

    def test_without_them_the_moment_shots_lose(self):
        used = {item.shot.id for item in self.build(None).items}

        self.assertEqual(used & {f"s{i}" for i in range(len(MOMENT_PROMPTS))}, set())

    def test_with_them_every_moment_is_in_the_film(self):
        moments = self.moments()
        used = {item.shot.id for item in self.build(moments).items}

        for moment in moments:
            self.assertTrue(
                set(moment.shot_ids) & used, f"{moment.name} filme girmedi")

    def test_a_moment_stops_being_asked_for_once_it_is_shown(self):
        """Otherwise the whole shortlist would be pulled in behind the first one."""
        moment = Moment(name="cake", shot_ids=tuple(f"s{i}" for i in range(8)), best=0.3)
        used = [item.shot.id for item in self.build((moment,)).items]
        carried = [shot_id for shot_id in used if shot_id in set(moment.shot_ids)]

        self.assertGreaterEqual(len(carried), 1)
        self.assertLessEqual(len(carried), 3)


class WhatTheFootageDoesNotHoldTests(unittest.TestCase):
    def test_the_lift_is_a_bar_a_missing_moment_cannot_clear(self):
        """A wedding with no cake should not be given one."""
        self.assertGreater(MOMENT_LIFT, 1.0)


if __name__ == "__main__":
    unittest.main()
