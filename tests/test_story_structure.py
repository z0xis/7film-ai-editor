"""What a band of the film is about, and the framing measures that decide a held shot.

Ranking a band by share alone named the same categories in every one of them, because the
couple is the backbone of all ten. The structure was invisible: the preparation shows up at
1.8% and 4.5% in the references' second band and almost nowhere else, which is the whole
reason it exists, and nine good preparation files reached no edit at all.
"""

import unittest

from sevenfilm.services.planner import (
    CHARACTERISTIC_LIFT,
    MEANINGFUL_CATEGORY_SHARE,
    STORY_CATEGORIES_PER_BAND,
    _band_preferences,
    _preferred_categories,
)
from sevenfilm.services.vision import CATEGORY_PROMPTS, _face_framing


class BandPreferenceTests(unittest.TestCase):
    def bands(self):
        """A film whose couple is everywhere and whose preparation is only in band one."""
        return [
            {"couple": 0.40, "venue": 0.21, "bride": 0.17, "bride_prep": 0.008, "party": 0.06},
            {"couple": 0.26, "bride": 0.25, "venue": 0.15, "bride_prep": 0.018, "party": 0.07},
            {"couple": 0.38, "bride": 0.13, "venue": 0.08, "bride_prep": 0.0, "party": 0.25},
        ]

    def test_the_backbone_of_the_band_is_kept(self):
        for index in range(3):
            self.assertEqual(_band_preferences(self.bands(), index)[0], "couple")

    def test_a_category_the_band_alone_leans_on_is_named(self):
        """bride_prep is 1.8% here against 0.9% across the film — twice its own average."""
        self.assertIn("bride_prep", _band_preferences(self.bands(), 1))

    def test_a_category_present_everywhere_is_not_what_a_band_is_about(self):
        # venue is close to its own average in band 0, so it earns no place by lift.
        self.assertNotIn("venue", _band_preferences(self.bands(), 1))

    def test_the_band_that_holds_the_party_names_it(self):
        self.assertIn("party", _band_preferences(self.bands(), 2))

    def test_no_more_than_the_band_may_put_forward(self):
        for index in range(3):
            self.assertLessEqual(len(_band_preferences(self.bands(), index)),
                                 STORY_CATEGORIES_PER_BAND)

    def test_a_category_barely_in_the_film_cannot_win_on_lift_alone(self):
        """Something seen twice in total shows a huge lift somewhere by chance."""
        bands = [{"couple": 0.9, "ceremony": 0.0}, {"couple": 0.9, "ceremony": 0.001}]

        self.assertNotIn("ceremony", _band_preferences(bands, 1))
        self.assertLess(0.001, MEANINGFUL_CATEGORY_SHARE)

    def test_a_flat_film_still_fills_the_band(self):
        flat = [{name: 0.1 for name in list(CATEGORY_PROMPTS)[:5]} for _ in range(3)]

        chosen = _band_preferences(flat, 1)

        self.assertEqual(len(chosen), STORY_CATEGORIES_PER_BAND)

    def test_the_lift_bar_is_above_one(self):
        """At 1.0 every category above its own mean would qualify, which is half of them."""
        self.assertGreater(CHARACTERISTIC_LIFT, 1.0)

    def test_the_profile_reaches_preferred_categories(self):
        profile = {"story_arc": self.bands()}

        self.assertIn("bride_prep", _preferred_categories(0.5, profile))


class FaceFramingTests(unittest.TestCase):
    """Both come out of the detector that was already running; only the count was kept."""

    def test_a_face_against_the_edge_reads_as_cut(self):
        _, edge = _face_framing([(0, 100, 80, 80)], 1920, 1080)

        self.assertEqual(edge, 1.0)

    def test_a_face_clear_of_the_border_reads_as_whole(self):
        _, edge = _face_framing([(900, 500, 80, 80)], 1920, 1080)

        self.assertEqual(edge, 0.0)

    def test_the_ratio_says_how_much_of_the_frame_the_subject_fills(self):
        small, _ = _face_framing([(900, 500, 40, 40)], 1920, 1080)
        large, _ = _face_framing([(700, 300, 500, 500)], 1920, 1080)

        self.assertLess(small, 0.001)
        self.assertGreater(large, 0.1)

    def test_the_largest_face_is_the_one_that_counts(self):
        ratio, _ = _face_framing([(10, 10, 20, 20), (700, 300, 400, 400)], 1920, 1080)

        self.assertGreater(ratio, 0.07)

    def test_no_face_measures_nothing_rather_than_something_bad(self):
        self.assertEqual(_face_framing([], 1920, 1080), (0.0, 0.0))

    def test_a_frame_with_no_size_is_refused_rather_than_dividing_by_zero(self):
        self.assertEqual(_face_framing([(0, 0, 10, 10)], 0, 0), (0.0, 0.0))
