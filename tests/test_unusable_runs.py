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
    def test_zero_is_where_the_charges_cancel_the_crispness(self):
        """A stretch below it is one the film should not be sitting on. Swept over six seeds:
        bad cuts 19% to 16%, very bad 7% to 5%, and scene runs *up* from 24.5 to 30.3, because
        a shot turned away for one cut and taken for the next is how a run gets built out of
        the good part of a clip."""
        self.assertEqual(UNUSABLE_RUN_SCORE, 0.0)


if __name__ == "__main__":
    unittest.main()
