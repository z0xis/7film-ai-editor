"""A shot with nothing usable left for this cut is not offered for it.

The score already knew about these: the back of a man's head filling the frame scored -0.12
and -0.10 across half its cut. Knowing is not acting, and raising the window weight does not
reach them — past 0.15 the day's order and the returns come apart while the bad share barely
moves.

Charging the shot for the stretch it would use was tried first and measured worse on every
count: bad cuts 20% to 26%, very bad 7% to 14%, the day's order 0.82 to 0.74. A shot that has
already given the edit a cut has a naturally poorer remainder, and it was being punished for
having been used. So this is a gate rather than a price — the shot is not a candidate for this
cut and is free to come back for the next one.
"""

import unittest
from fractions import Fraction

from sevenfilm.services.planner import UNUSABLE_RUN_SCORE, _cut_run_score
from sevenfilm.services.windows import ShotWindow
from sevenfilm.timebase import FrameRate

from tests.test_recording_tail import shot as make_shot

RATE = FrameRate(50)
BAR = 60.0


def window(offset, sharpness=80.0, edge=0.0):
    return ShotWindow(shot_id="s", offset_frames=offset, sharpness=sharpness, motion=0.0,
                      face_ratio=0.05, face_edge=edge, face_count=2, bystanders=0)


class WhatIsLeftOfAShotTests(unittest.TestCase):
    def test_a_clean_stretch_scores_full(self):
        windows = [window(offset) for offset in range(0, 200, 25)]

        self.assertEqual(
            _cut_run_score(make_shot(0, 200), windows, 0, Fraction(1), BAR), 1.0)

    def test_a_shot_that_is_bad_throughout_has_nothing_to_offer(self):
        windows = [window(offset, edge=1.0) for offset in range(0, 200, 25)]

        self.assertLessEqual(
            _cut_run_score(make_shot(0, 200), windows, 0, Fraction(1), BAR),
            UNUSABLE_RUN_SCORE)

    def test_what_the_shot_has_already_given_is_behind_it(self):
        """The good half is used up; only the bad half is left for this cut."""
        windows = [window(offset) for offset in range(0, 100, 25)]
        windows += [window(offset, edge=1.0) for offset in range(100, 200, 25)]
        shot = make_shot(0, 200)

        fresh = _cut_run_score(shot, windows, 0, Fraction(1), BAR)
        after = _cut_run_score(shot, windows, 120, Fraction(1), BAR)

        self.assertGreater(fresh, UNUSABLE_RUN_SCORE)
        self.assertLessEqual(after, UNUSABLE_RUN_SCORE)

    def test_an_unmeasured_shot_is_never_turned_away(self):
        self.assertEqual(
            _cut_run_score(make_shot(0, 200), None, 0, Fraction(1), BAR), 1.0)

    def test_a_shot_with_no_source_left_is_left_to_the_length_filter(self):
        windows = [window(offset) for offset in range(0, 200, 25)]

        self.assertEqual(
            _cut_run_score(make_shot(0, 200), windows, 500, Fraction(1), BAR), 1.0)


class WhereTheGateSitsTests(unittest.TestCase):
    def test_the_gate_sits_where_it_was_swept_to(self):
        """It started at 0.0, where the window charges cancel the crispness. Once the stillness
        and short-cut rules were in it was swept again over 8 seeds, everything else fixed:

            eşik  süre   kesim  kötü%  çokkötü%  durgun%   an
            0.00  150.0    112     13         1        3  6.0
            0.15  150.0    112      7         0        3  6.0
            0.25  150.0    112      7         0        2  6.0
            0.35  150.0    112      6         0        4  6.0
            0.50  150.0    112      0         0        4  5.0   <- bir düğün anı kayboluyor

        The editor expected raising it to cost length — "gereksiz plan eklemek yerine klip
        uzunluğu kısaltılabilir" — and it does not: the film still fills its 150 seconds.
        """
        self.assertEqual(UNUSABLE_RUN_SCORE, 0.25)


if __name__ == "__main__":
    unittest.main()
