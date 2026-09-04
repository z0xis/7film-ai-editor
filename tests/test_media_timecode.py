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


class CoverImageTests(unittest.TestCase):
    """An embedded cover image is a video stream to ffprobe, and often the first one."""

    def payload(self, streams):
        return {"streams": streams, "format": {"duration": "10.1", "filename": "/m/x.mp4"}}

    def cover(self):
        return {"codec_type": "video", "codec_name": "mjpeg", "width": 320, "height": 320,
                "avg_frame_rate": "0/0", "duration": "0.04",
                "disposition": {"attached_pic": 1}, "tags": {}}

    def picture(self):
        return {"codec_type": "video", "codec_name": "h264", "width": 3840, "height": 2160,
                "avg_frame_rate": "50/1", "duration": "10.1",
                "disposition": {"attached_pic": 0}, "tags": {"timecode": "08:19:21:02"}}

    def test_the_real_picture_track_is_read_not_the_thumbnail(self):
        """Reading the cover gave a 320x320 clip lasting one frame, so no shot was ever found."""
        details = metadata_from_probe(Path("/m/x.mp4"), self.payload([self.cover(), self.picture()]))

        self.assertEqual((details["width"], details["height"]), (3840, 2160))
        self.assertEqual(float(details["duration"]), 10.1)
        self.assertEqual(details["codec"], "h264")

    def test_the_frame_rate_comes_from_the_picture_track(self):
        details = metadata_from_probe(Path("/m/x.mp4"), self.payload([self.cover(), self.picture()]))

        self.assertEqual(
            (details["frame_rate"].numerator, details["frame_rate"].denominator), (50, 1))

    def test_a_file_without_a_cover_is_unaffected(self):
        details = metadata_from_probe(Path("/m/x.mp4"), self.payload([self.picture()]))

        self.assertEqual(details["width"], 3840)

    def test_a_stream_with_no_disposition_at_all_is_taken_as_picture(self):
        stream = self.picture()
        stream.pop("disposition")

        self.assertEqual(metadata_from_probe(Path("/m/x.mp4"), self.payload([stream]))["width"], 3840)

    def test_nothing_but_a_cover_image_is_no_video_at_all(self):
        """Which the indexer then skips, rather than treating a thumbnail as footage."""
        with self.assertRaises(ValueError):
            metadata_from_probe(Path("/m/x.mp4"), self.payload([self.cover()]))


class DisplayRotationTests(unittest.TestCase):
    """A vertical phone clip codes a landscape frame and attaches the angle beside it."""

    def payload(self, *, rotation=None, tag=None, width=1920, height=1080):
        stream = {"codec_type": "video", "codec_name": "h264", "width": width, "height": height,
                  "avg_frame_rate": "25/1", "duration": "4.0", "tags": {}}
        if rotation is not None:
            stream["side_data_list"] = [
                {"side_data_type": "Display Matrix", "rotation": rotation}]
        if tag is not None:
            stream["tags"]["rotate"] = tag
        return {"streams": [stream], "format": {"duration": "4.0", "filename": "/m/x.mp4"}}

    def shape(self, payload):
        details = metadata_from_probe(Path("/m/x.mp4"), payload)
        return details["width"], details["height"]

    def test_a_quarter_turn_is_stored_as_the_shape_it_is_watched_in(self):
        """ffmpeg writes an upright 1080x1920 proxy; the database said 1920x1080."""
        self.assertEqual(self.shape(self.payload(rotation=90)), (1080, 1920))

    def test_the_other_quarter_turn_too(self):
        self.assertEqual(self.shape(self.payload(rotation=-90)), (1080, 1920))

    def test_an_upside_down_clip_keeps_its_shape(self):
        self.assertEqual(self.shape(self.payload(rotation=180)), (1920, 1080))

    def test_an_unrotated_clip_is_untouched(self):
        self.assertEqual(self.shape(self.payload()), (1920, 1080))

    def test_the_older_rotate_tag_is_honoured_when_there_is_no_display_matrix(self):
        self.assertEqual(self.shape(self.payload(tag="270")), (1080, 1920))

    def test_an_unreadable_angle_is_treated_as_none(self):
        self.assertEqual(self.shape(self.payload(rotation="sideways")), (1920, 1080))
