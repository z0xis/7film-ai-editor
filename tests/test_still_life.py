"""One record of a still object per moment.

The shoot rolls a graphic several times and the film needs one of them. Measured on an edit
the editor picked apart, one moment at 08:19 to 08:20 supplied three — the welcome sign twice
and the ceremony card — and they read them as the same shot coming back.

Nothing already in the planner could see it. The two takes of that sign sit 17 bits apart on
the perceptual hash, outside the near-duplicate threshold entirely, so no penalty ever fired;
and CLIP puts them at 0.822 against a random-pair 90th percentile of 0.807 on this footage,
which is not a separation either. What tells them apart is not how they look but what they
are: two records of one still object, seconds apart on the camera's clock.
"""

import unittest
from fractions import Fraction
from pathlib import Path

from sevenfilm.domain import BeatGrid, MediaAsset, Shot
from sevenfilm.services.planner import (
    FACELESS_FACES,
    STILL_LIFE_REPEAT_PENALTY,
    _score_candidate,
    build_timeline,
)
from sevenfilm.services.windows import ShotWindow
from sevenfilm.timebase import FrameRate, TimeRange

RATE = FrameRate(50)


class TheSecondStillLifeIsChargedTests(unittest.TestCase):
    def components(self, repeat):
        _, parts = _score_candidate(
            Shot(id="s", asset_id="a", source_range=TimeRange(0, 500, RATE),
                 category="detail", shot_scale="detail", technical_quality=.8,
                 aesthetic_score=.8, motion_score=.5, confidence=.8,
                 duplicate_group="visual:1", brightness=.36, saturation=.15,
                 highlight_clipping=.01),
            preferred_categories=("detail",), preferred_scales=("detail",), energy="medium",
            recent=(), desired_duration=Fraction(1), random_jitter=0.0,
            still_life_repeat=repeat,
        )
        return parts

    def test_the_first_one_from_a_moment_costs_nothing(self):
        self.assertEqual(self.components(False)["still_life_penalty"], 0.0)

    def test_the_second_gives_up_the_swept_amount(self):
        self.assertAlmostEqual(
            self.components(True)["still_life_penalty"], STILL_LIFE_REPEAT_PENALTY)


class OneStillLifePerMomentTests(unittest.TestCase):
    """Two clips of one sign, rolled seconds apart, against a shoot full of people."""

    def build(self):
        assets, shots, windows = [], [], {}
        categories = ("couple", "bride", "groom", "party", "venue", "detail")
        for index in range(200):
            # The three signs share a minute of the camera's clock; everything else is spread
            # far enough apart to be its own moment.
            second = 8 * 3600 + (20 if index < 3 else 600 + index * 400)
            one = MediaAsset(
                id=f"a{index}", project_id="p", path=Path(f"/m/{index}.mov"),
                name=f"{index}.mov", duration=Fraction(30), frame_rate=RATE, width=1920,
                height=1080,
                timecode=f"{second // 3600:02d}:{second // 60 % 60:02d}:{second % 60:02d}:00")
            assets.append(one)
            shots.append(Shot(
                id=f"s{index}", asset_id=one.id, source_range=TimeRange(0, 500, RATE),
                category="detail" if index < 3 else categories[index % len(categories)],
                shot_scale="medium", technical_quality=.85 if index < 3 else .8,
                aesthetic_score=.85 if index < 3 else .8, motion_score=.5, confidence=.9,
                duplicate_group=f"visual:{index:016x}", brightness=.36, saturation=.15,
                highlight_clipping=.01))
            windows[f"s{index}"] = [
                ShotWindow(shot_id=f"s{index}", offset_frames=offset, sharpness=80.0,
                           motion=1.0, face_ratio=0.0 if index < 3 else 0.05,
                           face_edge=0.0, face_count=0 if index < 3 else 2, bystanders=0)
                for offset in range(0, 500, 25)
            ]
        beats = tuple(Fraction(i, 2) for i in range(700))
        music = BeatGrid(bpm=120, beats=beats, duration=Fraction(350),
                         sections=({"energy": "medium", "start": "0", "end": "350"},))
        return build_timeline(project_id="p", assets=assets, shots=shots, music=music,
                              frame_rate=RATE, target_duration=Fraction(150), seed=1,
                              windows_by_shot=windows)

    def test_the_moment_gives_the_edit_one_of_its_signs_not_three(self):
        used = {item.asset.id for item in self.build().items}
        signs = used & {"a0", "a1", "a2"}

        # Not vacuous: the moment is still in the film, once.
        self.assertEqual(len(signs), 1)

    def test_the_faceless_bar_is_an_average_not_an_absolute(self):
        """A guest crossing the back of one frame does not make a still life a portrait."""
        self.assertGreater(FACELESS_FACES, 0.0)


if __name__ == "__main__":
    unittest.main()
