"""A shot is chosen for what it holds, and the cut for where it holds it.

Until these existed a shot was judged on three frames spanning 0.2 seconds from its middle,
its framing on the single frame between them, and the planner cut a segment out by arithmetic
starting a fixed handle after the shot began. Measured on six clips the editor picked out, the
moment objected to was inside the cut and the measurement had never looked at it: a head
against the frame edge at 0.76 and 1.00 where the stored value was 0.00, a whip at 9 sharpness
against the shoot's 45 to 78, a bystander standing in a doorway.
"""

import unittest
from fractions import Fraction

from sevenfilm.services.planner import (
    BYSTANDER_PENALTY,
    WINDOW_QUALITY_WEIGHT,
    _best_offset,
    _score_candidate,
    _source_range_for_duration,
    _window_score,
)
from sevenfilm.services.windows import SHARPNESS_WIDTH, ShotWindow, _sharpness
from sevenfilm.timebase import FrameRate

from tests.test_recording_tail import shot as make_shot

RATE = FrameRate(50)
BAR = 60.0


def window(offset, sharpness=80.0, edge=0.0, bystanders=0):
    return ShotWindow(shot_id="s", offset_frames=offset, sharpness=sharpness, motion=0.0,
                      face_ratio=0.05, face_edge=edge, face_count=1, bystanders=bystanders)


class WindowScoreTests(unittest.TestCase):
    def test_a_crisp_clear_half_second_scores_full(self):
        self.assertEqual(_window_score(window(0), BAR), 1.0)

    def test_a_head_against_the_frame_edge_is_charged_the_whole_way(self):
        """C2075 and C2076 both began on one, at 0.76 and 1.00."""
        self.assertAlmostEqual(_window_score(window(0, edge=1.0), BAR), 0.0)
        self.assertAlmostEqual(_window_score(window(0, edge=0.76), BAR), 0.24)

    def test_a_whip_is_not_usable_at_all_on_the_shoot_own_scale(self):
        """C2155 sat at 9 where this shoot's windows run 45 to 78 — a sixth of the median.

        It used to score 0.15, low but carryable: with no face at the frame edge and nobody
        crossing behind, the rest of the score could lift it back into a cut. Below the
        crispness floor it is simply not picture, and eight cuts an edit were coming from the
        shoot's softest 6% that way.
        """
        self.assertEqual(_window_score(window(0, sharpness=9.0), BAR), 0.0)

    def test_softness_still_grades_above_the_floor(self):
        """The floor is a floor, not a switch: above it crispness is still a share of the
        shoot's own median."""
        self.assertAlmostEqual(_window_score(window(0, sharpness=BAR / 2), BAR), 0.5)

    def test_bystanders_cost_and_the_scale_stops_at_a_crowd(self):
        alone = _window_score(window(0), BAR)
        one = _window_score(window(0, bystanders=1), BAR)
        crowd = _window_score(window(0, bystanders=9), BAR)

        self.assertLess(one, alone)
        self.assertAlmostEqual(alone - crowd, BYSTANDER_PENALTY)

    def test_a_shoot_with_no_measured_sharpness_is_not_judged_on_it(self):
        self.assertEqual(_window_score(window(0, sharpness=1.0), 0.0), 1.0)


class BestOffsetTests(unittest.TestCase):
    def test_it_steps_over_the_bad_opening_the_edit_used_to_land_on(self):
        """The exact shape of C2075: edge at the start, clean half a second in."""
        windows = [window(0, edge=0.76), window(25), window(50), window(75)]

        offset, value = _best_offset(make_shot(0, 100), windows, 50, floor=0, ceiling=50,
                                     sharpness_bar=BAR)

        self.assertEqual(offset, 25)
        self.assertEqual(value, 1.0)

    def test_the_worst_half_second_in_the_run_decides(self):
        windows = [window(0), window(25, edge=1.0), window(50), window(75)]

        _, value = _best_offset(make_shot(0, 100), windows, 50, floor=0, ceiling=0,
                                sharpness_bar=BAR)

        self.assertAlmostEqual(value, 0.0)

    def test_a_shot_bad_all_the_way_reports_it_rather_than_hiding_it(self):
        """C2181 held the frame edge across its whole length; there was nowhere to move to."""
        windows = [window(offset, edge=1.0) for offset in (0, 25, 50, 75)]

        _, value = _best_offset(make_shot(0, 100), windows, 50, floor=0, ceiling=50,
                                sharpness_bar=BAR)

        self.assertLessEqual(value, 0.0)

    def test_it_never_starts_before_what_the_shot_has_already_given(self):
        windows = [window(0), window(25, edge=1.0), window(50, edge=1.0)]

        offset, _ = _best_offset(make_shot(0, 100), windows, 25, floor=25, ceiling=75,
                                 sharpness_bar=BAR)

        self.assertGreaterEqual(offset, 25)

    def test_an_unmeasured_shot_keeps_the_offset_it_always_had(self):
        offset, value = _best_offset(make_shot(0, 100), [], 50, floor=12, ceiling=50,
                                     sharpness_bar=BAR)

        self.assertEqual(offset, 12)
        self.assertEqual(value, 1.0)


class SourceRangeTests(unittest.TestCase):
    def test_the_cut_moves_to_the_good_part_of_the_shot(self):
        windows = [window(0, edge=1.0), window(25, edge=1.0), window(50), window(75)]

        chosen = _source_range_for_duration(
            make_shot(1000, 200), Fraction(1), windows=windows, sharpness_bar=BAR)

        self.assertIsNotNone(chosen)
        self.assertGreaterEqual(chosen.start_frame, 1050)

    def test_without_windows_it_cuts_where_it_always_did(self):
        plain = _source_range_for_duration(make_shot(1000, 200), Fraction(1))

        self.assertIsNotNone(plain)
        # The handle is min(an eighth of the shot, a fifth of a second) — ten frames here.
        self.assertEqual(plain.start_frame, 1010)


class UnusableShotsLoseTests(unittest.TestCase):
    """A shot with no cuttable stretch has to give way, not be cut to a different bad moment."""

    def test_the_weight_is_the_one_that_was_swept(self):
        # 40% of cuts held a bad half second; 0.15 brings that to 15% and 0.30 to 13%.
        self.assertAlmostEqual(WINDOW_QUALITY_WEIGHT, 0.15)

    def test_a_shot_with_no_usable_run_is_charged_and_a_clean_one_is_not(self):
        common = {
            "preferred_categories": ("couple",),
            "preferred_scales": ("medium",),
            "energy": "medium",
            "recent": (),
            "desired_duration": Fraction(1),
            "random_jitter": 0.0,
        }
        clean, clean_parts = _score_candidate(make_shot(0, 100), window_quality=1.0, **common)
        bad, bad_parts = _score_candidate(make_shot(0, 100), window_quality=0.0, **common)

        self.assertEqual(clean_parts["window_penalty"], 0.0)
        self.assertAlmostEqual(bad_parts["window_penalty"], WINDOW_QUALITY_WEIGHT)
        self.assertLess(bad, clean)

    def test_an_unmeasured_shot_is_not_charged(self):
        _, parts = _score_candidate(
            make_shot(0, 100),
            preferred_categories=("couple",), preferred_scales=("medium",), energy="medium",
            recent=(), desired_duration=Fraction(1), random_jitter=0.0,
        )

        self.assertEqual(parts["window_penalty"], 0.0)


if __name__ == "__main__":
    unittest.main()


class SharpnessIsNotNoiseTests(unittest.TestCase):
    """At 4K the Laplacian variance measures the sensor, not the focus.

    Measured on 60 cuts of one edit: the same frames ranked at full resolution and at 640
    pixels agree at a Spearman of only 0.52, and the disagreements are the ones the editor
    picked out by eye. The film's opening — a neon sign, sharp and clean — sat in the bottom
    1% at full resolution, while two cuts of the bride the editor called blurred sat at the
    45th percentile. Read at 640 the sign is the sharpest frame in the film and the blurred
    cuts are the softest.

    It also answers a finding that had none: across eleven features the clips the editor
    rejected measured better than the clips kept, sharpness 25.2 against 23.0. That number
    was reading noise.
    """

    def setUp(self):
        try:
            import cv2  # type: ignore[import-not-found]
        except ImportError:  # pragma: no cover - opencv is a runtime dependency
            self.skipTest("opencv yok")
        import numpy as np

        self.cv2 = cv2
        rng = np.random.default_rng(7)
        size = (2160, 3840)
        # One scene, photographed twice. The sharp frame is clean; the soft one is the same
        # picture out of focus and carrying the sensor noise a wide-open lens brings with it.
        # That pairing is what the shoot holds and what the measure has to tell apart.
        scene = rng.integers(0, 256, (size[0] // 24, size[1] // 24), dtype="uint8")
        scene = cv2.resize(scene, (size[1], size[0]), interpolation=cv2.INTER_LINEAR)
        self.sharp = scene
        blurred = cv2.GaussianBlur(scene, (0, 0), 9)
        self.soft = np.clip(
            blurred.astype("float64") + rng.normal(0, 14, size), 0, 255).astype("uint8")

    def test_at_full_resolution_the_noisy_soft_frame_wins(self):
        """Which is the fault: it is the blurred frame that measures sharper."""
        def full(frame):
            return float(self.cv2.Laplacian(frame, self.cv2.CV_64F).var())

        self.assertGreater(full(self.soft), full(self.sharp))

    def test_read_at_a_fixed_width_the_sharp_frame_wins(self):
        self.assertGreater(
            _sharpness(self.cv2, self.sharp), _sharpness(self.cv2, self.soft))

    def test_a_frame_already_small_enough_is_not_touched(self):
        import numpy as np

        small = np.zeros((360, 480), dtype="uint8")
        small[:, ::8] = 255
        plain = float(self.cv2.Laplacian(small, self.cv2.CV_64F).var())

        self.assertAlmostEqual(_sharpness(self.cv2, small), plain)

    def test_the_width_is_well_below_a_4k_frame(self):
        self.assertLess(SHARPNESS_WIDTH, 1920)
