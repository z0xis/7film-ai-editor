import unittest
from fractions import Fraction

from sevenfilm.timebase import FrameRate, TimeRange


class FrameAccurateTimeTests(unittest.TestCase):
    def test_ntsc_duration_has_no_float_drift(self):
        rate = FrameRate(30000, 1001)
        one_hour = rate.seconds_from_frames(107892)
        self.assertEqual(one_hour, Fraction(8999991, 2500))
        self.assertEqual(rate.frames_from_seconds(one_hour), 107892)

    def test_range_is_half_open_and_serializable(self):
        range_ = TimeRange(100, 25, FrameRate(25))
        self.assertEqual(range_.end_frame, 125)
        self.assertEqual(range_.start_seconds, Fraction(4))
        self.assertEqual(range_.duration_seconds, Fraction(1))
        self.assertEqual(range_.as_rational_dict()["rate"], "25/1")
