"""The recorded start timecode is not always on the video stream."""

import unittest
from pathlib import Path

from sevenfilm.services.media import _start_timecode, metadata_from_probe


def payload(streams, format_tags=None):
    return {"streams": streams, "format": {"duration": "10.0", "tags": format_tags or {}}}


def video(tags=None, **extra):
    return {"codec_type": "video", "avg_frame_rate": "25/1", "width": 1920, "height": 1080,
            "codec_name": "h264", "duration": "10.0", "tags": tags or {}, **extra}


class StartTimecodeTests(unittest.TestCase):
    def test_a_sony_metadata_track_carries_it(self):
        """XAVC writes the timecode to an rtmd track; reading the video stream found nothing."""
        streams = [
            video(),
            {"codec_type": "audio", "tags": {"language": "und"}},
            {"codec_type": "data", "codec_tag_string": "rtmd",
             "tags": {"handler_name": "Timed Metadata Media Handler", "timecode": "08:19:21:02"}},
        ]

        self.assertEqual(_start_timecode(payload(streams)), "08:19:21:02")

    def test_a_timecode_on_the_video_stream_still_works(self):
        self.assertEqual(_start_timecode(payload([video({"timecode": "01:00:00:00"})])),
                         "01:00:00:00")

    def test_the_container_tags_are_the_last_place_looked(self):
        self.assertEqual(
            _start_timecode(payload([video()], {"timecode": "10:00:00:00"})), "10:00:00:00")

    def test_the_first_stream_that_has_one_wins(self):
        streams = [
            {"codec_type": "data", "tags": {"timecode": "02:00:00:00"}},
            {"codec_type": "data", "tags": {"timecode": "03:00:00:00"}},
        ]
        self.assertEqual(_start_timecode(payload(streams)), "02:00:00:00")

    def test_footage_without_a_timecode_reports_none(self):
        self.assertIsNone(_start_timecode(payload([video(), {"codec_type": "audio"}])))
        self.assertIsNone(_start_timecode(payload([])))

    def test_an_empty_timecode_is_no_timecode(self):
        self.assertIsNone(_start_timecode(payload([video({"timecode": ""})])))

    def test_streams_without_tags_are_stepped_over(self):
        streams = [{"codec_type": "data"}, {"codec_type": "data", "tags": None},
                   {"codec_type": "data", "tags": {"timecode": "04:00:00:00"}}]
        self.assertEqual(_start_timecode(payload(streams)), "04:00:00:00")

    def test_the_probe_result_carries_it_through(self):
        streams = [video(), {"codec_type": "data", "tags": {"timecode": "08:19:21:02"}}]

        details = metadata_from_probe(Path("/m/A001.mov"), payload(streams))

        self.assertEqual(details["timecode"], "08:19:21:02")
        self.assertEqual(details["frame_rate"].numerator, 25)


if __name__ == "__main__":
    unittest.main()
