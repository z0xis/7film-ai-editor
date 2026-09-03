"""One long take must yield several independently measurable segments, not one shot."""

import unittest
from fractions import Fraction
from itertools import pairwise

from sevenfilm.services.analysis import MAX_SHOT_SECONDS, _split_long_range
from sevenfilm.timebase import FrameRate, TimeRange


class SplitLongRangeTests(unittest.TestCase):
    def setUp(self):
        self.rate = FrameRate(25)

    def split(self, start, duration):
        return list(_split_long_range(TimeRange(start, duration, self.rate)))

    def test_a_short_scene_is_left_alone(self):
        segments = self.split(10, 75)
        self.assertEqual([(s.start_frame, s.duration_frames) for s in segments], [(10, 75)])

    def test_a_scene_exactly_at_the_limit_is_left_alone(self):
        limit = self.rate.frames_from_seconds(MAX_SHOT_SECONDS, rounding="floor")
        self.assertEqual(len(self.split(0, limit)), 1)

    def test_a_long_take_becomes_several_segments(self):
        segments = self.split(0, 1000)  # 40 seconds at 25 fps
        self.assertEqual(len(segments), 8)
        self.assertTrue(all(s.duration_frames == 125 for s in segments))

    def test_segments_are_contiguous_and_cover_the_scene_exactly(self):
        for duration in (126, 313, 1000, 1001, 7777):
            with self.subTest(duration=duration):
                segments = self.split(40, duration)
                self.assertEqual(segments[0].start_frame, 40)
                self.assertEqual(sum(s.duration_frames for s in segments), duration)
                for previous, current in pairwise(segments):
                    self.assertEqual(previous.end_frame, current.start_frame)
                self.assertEqual(segments[-1].end_frame, 40 + duration)

    def test_no_segment_exceeds_the_limit(self):
        limit = self.rate.frames_from_seconds(MAX_SHOT_SECONDS, rounding="floor")
        for duration in (126, 313, 1000, 1001, 7777):
            with self.subTest(duration=duration):
                self.assertTrue(all(s.duration_frames <= limit for s in self.split(0, duration)))

    def test_segments_stay_usable_in_length(self):
        """A trailing sliver would be dropped by the planner's half second floor."""
        minimum = self.rate.frames_from_seconds(Fraction(1, 2), rounding="ceil")
        for duration in (126, 251, 313, 1001, 7777):
            with self.subTest(duration=duration):
                self.assertTrue(all(s.duration_frames >= minimum for s in self.split(0, duration)))

    def test_splitting_an_already_split_scene_changes_nothing(self):
        once = self.split(0, 1000)
        twice = [part for segment in once for part in _split_long_range(segment)]
        self.assertEqual(
            [(s.start_frame, s.duration_frames) for s in once],
            [(s.start_frame, s.duration_frames) for s in twice],
        )

    def test_a_high_frame_rate_source_splits_on_seconds_not_frames(self):
        rate = FrameRate(60000, 1001)  # 59.94 fps
        segments = list(_split_long_range(TimeRange(0, 3600, rate)))
        self.assertTrue(all(s.duration_seconds <= MAX_SHOT_SECONDS for s in segments))
        self.assertEqual(sum(s.duration_frames for s in segments), 3600)


if __name__ == "__main__":
    unittest.main()
