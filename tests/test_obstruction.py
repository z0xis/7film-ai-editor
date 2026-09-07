"""A body between the camera and what the shot is of.

"alakasız sırt var." "çok kötü kafanın arkası görünüyor sadece." "kötü kadraj." The editor kept
finding these and nothing in the planner could see them: the face detector reads a blurred
shoulder across the lens as no face at all, which is exactly what an empty room reads as.

CLIP can, and the vectors are already stored, so it costs a read. Verified by looking at what
it ranks: the top of this shoot is an arm sweeping across the lens over a table of guests, and
a blurred head filling the right third of the frame; the bottom is the couple facing the
camera with their faces clear. Over 8 seeds the share of these shots reaching the edit went
from 4.2% to 0.0%, with bad cuts, wedding moments and chronology unchanged.
"""

import unittest
from fractions import Fraction
from pathlib import Path

from sevenfilm.domain import BeatGrid, MediaAsset, Shot
from sevenfilm.services.planner import (
    OBSTRUCTION_PENALTY,
    _score_candidate,
    build_timeline,
)
from sevenfilm.timebase import FrameRate, TimeRange

RATE = FrameRate(50)


def _shot(identifier="s", category="couple"):
    return Shot(id=identifier, asset_id=f"a{identifier}",
                source_range=TimeRange(0, 500, RATE), category=category,
                shot_scale="medium", technical_quality=.8, aesthetic_score=.8,
                motion_score=.5, confidence=.8, duplicate_group="visual:1",
                brightness=.36, saturation=.15, highlight_clipping=.01)


def _score(**extra):
    return _score_candidate(
        _shot(), preferred_categories=("couple",), preferred_scales=("medium",),
        energy="medium", recent=(), desired_duration=Fraction(1), random_jitter=0.0, **extra)


class AnObstructedShotIsChargedTests(unittest.TestCase):
    def test_a_clear_shot_costs_nothing(self):
        self.assertEqual(_score()[1]["obstruction_penalty"], 0.0)

    def test_an_obstructed_one_gives_up_the_measured_amount(self):
        self.assertAlmostEqual(
            _score(obstructed=True)[1]["obstruction_penalty"], OBSTRUCTION_PENALTY)

    def test_it_comes_off_the_score(self):
        self.assertLess(_score(obstructed=True)[0], _score()[0])

    def test_a_moment_the_film_owes_is_never_suppressed_for_it(self):
        """If the only record of the ring is over a guest's shoulder, the film still owes it."""
        self.assertEqual(
            _score(obstructed=True, missing_moment=True)[1]["obstruction_penalty"], 0.0)


class TheEditPrefersTheClearShotTests(unittest.TestCase):
    def _plan(self, obstructions):
        assets, shots = [], []
        categories = ("couple", "bride", "groom", "party", "venue", "detail")
        for index in range(120):
            one = MediaAsset(id=f"a{index}", project_id="p", path=Path(f"/m/{index}.mov"),
                             name=f"{index}.mov", duration=Fraction(11), frame_rate=RATE,
                             width=1920, height=1080)
            assets.append(one)
            shots.append(Shot(
                id=f"s{index}", asset_id=one.id, source_range=TimeRange(0, 500, RATE),
                category=categories[index % len(categories)], shot_scale="medium",
                # The obstructed half is the *better* footage, as it is on the real shoot:
                # a blocked shot is not a weak one by any measure already in the planner.
                technical_quality=.85 if index % 2 else .8,
                aesthetic_score=.85 if index % 2 else .8, motion_score=.5, confidence=.9,
                duplicate_group=f"visual:{index:016x}", brightness=.36, saturation=.15,
                highlight_clipping=.01))
        beats = tuple(Fraction(i, 2) for i in range(900))
        music = BeatGrid(bpm=120, beats=beats, duration=Fraction(450),
                         sections=({"energy": "medium", "start": "0", "end": "450"},))
        return build_timeline(project_id="p", assets=assets, shots=shots, music=music,
                              frame_rate=RATE, target_duration=Fraction(120), seed=1,
                              obstructions=obstructions)

    def test_the_blocked_half_of_the_shoot_loses_ground(self):
        blocked = frozenset(f"s{index}" for index in range(1, 120, 2))
        without = sum(1 for i in self._plan(None).items if i.shot.id in blocked)
        with_penalty = sum(1 for i in self._plan(blocked).items if i.shot.id in blocked)

        self.assertGreater(without, 0, "ceza öncesi hiç engelli plan yok, test boş")
        self.assertLess(with_penalty, without)


if __name__ == "__main__":
    unittest.main()
