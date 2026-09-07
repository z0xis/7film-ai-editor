"""A film made of the usable material beats no film at all.

"görüntü yetersiz geliyorsa duruma göre klibin süresi kısalabilir." Running out of usable
footage used to produce nothing: the build raised and the editor was told to lower the target
and start again. Now the edit is handed over short, and says so.

Below half the asked-for length the target is simply wrong for the footage, and saying so is
the honest answer rather than delivering a third of a film without comment.
"""

import unittest
from fractions import Fraction
from pathlib import Path

from sevenfilm.domain import BeatGrid, MediaAsset, Shot
from sevenfilm.services.planner import (
    MINIMUM_DELIVERABLE_SHARE,
    InsufficientFootageError,
    build_timeline,
)
from sevenfilm.timebase import FrameRate, TimeRange

RATE = FrameRate(50)


def _plan(clips, target=Fraction(150)):
    """A shoot of `clips` five-second shots and nothing else."""
    assets, shots = [], []
    categories = ("couple", "bride", "groom", "party", "venue", "detail")
    for index in range(clips):
        one = MediaAsset(id=f"a{index}", project_id="p", path=Path(f"/m/{index}.mov"),
                         name=f"{index}.mov", duration=Fraction(6), frame_rate=RATE,
                         width=1920, height=1080)
        assets.append(one)
        shots.append(Shot(
            id=f"s{index}", asset_id=one.id, source_range=TimeRange(0, 250, RATE),
            category=categories[index % len(categories)], shot_scale="medium",
            technical_quality=.8, aesthetic_score=.8, motion_score=.5, confidence=.9,
            duplicate_group=f"visual:{index:016x}", brightness=.36, saturation=.15,
            highlight_clipping=.01))
    beats = tuple(Fraction(i, 2) for i in range(900))
    music = BeatGrid(bpm=120, beats=beats, duration=Fraction(450),
                     sections=({"energy": "medium", "start": "0", "end": "450"},))
    return build_timeline(project_id="p", assets=assets, shots=shots, music=music,
                          frame_rate=RATE, target_duration=target, seed=1)


class WhenTheFootageRunsOutTests(unittest.TestCase):
    def test_a_shoot_with_plenty_still_fills_the_target(self):
        self.assertEqual(_plan(200).duration, Fraction(150))

    def test_a_target_the_footage_cannot_reach_at_all_is_still_an_error(self):
        """Under half the asked-for length, the target is wrong and the editor should hear it
        rather than be handed a third of a film."""
        with self.assertRaises(InsufficientFootageError):
            _plan(4)

    def test_a_shoot_that_falls_short_is_delivered_short_and_says_so(self):
        """25 five-second shots cannot carry 150 s. The edit is built out of what there is."""
        plan = _plan(25)
        self.assertLess(plan.duration, Fraction(150))
        self.assertGreaterEqual(plan.duration, Fraction(150) * MINIMUM_DELIVERABLE_SHARE)
        self.assertTrue(
            any("saniyede bitti" in warning for warning in plan.warnings),
            f"kısa teslim uyarısı yok: {plan.warnings}",
        )

    def test_the_share_is_a_half(self):
        self.assertEqual(MINIMUM_DELIVERABLE_SHARE, Fraction(1, 2))


if __name__ == "__main__":
    unittest.main()
