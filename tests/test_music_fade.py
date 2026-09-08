"""The music goes quiet at the end instead of stopping dead.

"BU ÇOK SAÇMA BİTİŞ VE MÜZİK PAT DİYE BİTİYOR FADE OUT FALAN OLSUN YANİ." Measured on the 18
reference films: 11 of them fade the music out, over a median 1.5 seconds.

Written as volume automation on the music clip, which is the part Resolve actually reads —
measured on Studio 21.0.2 by importing the file and exporting the timeline back out, the
keyframes return as written, while `adjust-opacity` and `<transition>` are dropped silently.
"""

import tempfile
import unittest
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

from sevenfilm.domain import MediaAsset, MusicSegment, Shot, TimelineItem, TimelinePlan
from sevenfilm.services.exporter import (
    MUSIC_FADE_SECONDS,
    PICTURE_FADE_SECONDS,
    export_fcpxml,
    plan_as_dict,
)
from sevenfilm.timebase import FrameRate, TimeRange

RATE = FrameRate(50)


def _plan(songs, timeline_frames=500):
    """`duration` comes off the items, so the edit's length is set by the cut in it."""
    asset = MediaAsset(id="a1", project_id="p", path=Path("/m/one.mov"), name="one.mov",
                       duration=Fraction(30), frame_rate=RATE, width=1920, height=1080)
    shot = Shot(id="s1", asset_id="a1", source_range=TimeRange(0, 500, RATE), category="couple",
                shot_scale="medium", technical_quality=.8, aesthetic_score=.8, motion_score=.5,
                confidence=.9, duplicate_group="visual:1", brightness=.36, saturation=.15,
                highlight_clipping=.01)
    plan = TimelinePlan(id="t1", project_id="p", name="7Film", frame_rate=RATE,
                        target_duration=Fraction(timeline_frames, 50))
    plan.items.append(TimelineItem(
        id="i1", shot=shot, asset=asset, source_range=TimeRange(0, timeline_frames, RATE),
        timeline_range=TimeRange(0, timeline_frames, RATE), score=0.5,
        selection_reason="test"))
    plan.music_segments = songs
    plan.music_path = songs[0].path
    plan.music_duration = songs[0].duration
    return plan


def _song(path, start, duration):
    return MusicSegment(path=Path(path), timeline_start=Fraction(start),
                        source_start=Fraction(0), duration=Fraction(duration),
                        source_total=Fraction(200))


def _music_clips(plan):
    with tempfile.TemporaryDirectory() as temporary:
        written = export_fcpxml(plan, Path(temporary) / "e.fcpxml")
        root = ET.parse(written).getroot()
        return [clip for clip in root.iter("asset-clip") if clip.get("audioRole") == "music"]


class TheMusicFadesOutTests(unittest.TestCase):
    def test_the_last_song_goes_down_to_silence(self):
        clip = _music_clips(_plan([_song("/m/song.mp3", 0, 10)]))[0]
        keyframes = [(k.get("time"), k.get("value")) for k in clip.iter("keyframe")]

        self.assertEqual(len(keyframes), 2, keyframes)
        self.assertEqual(keyframes[-1][1], "-96")

    def test_it_takes_the_measured_time_to_get_there(self):
        clip = _music_clips(_plan([_song("/m/song.mp3", 0, 10)]))[0]
        begins, ends = (k.get("time") for k in clip.iter("keyframe"))

        def seconds(value):
            whole, _, part = value.rstrip("s").partition("/")
            return Fraction(int(whole), int(part or 1))

        self.assertEqual(seconds(ends) - seconds(begins), MUSIC_FADE_SECONDS)

    def test_a_song_that_hands_over_to_another_one_does_not_fade(self):
        """Only the song the film ends on. A song running into the next is meant to."""
        plan = _plan([_song("/m/first.mp3", 0, 4), _song("/m/second.mp3", 4, 6)])
        first, second = _music_clips(plan)

        self.assertEqual(list(first.iter("keyframe")), [])
        self.assertEqual(len(list(second.iter("keyframe"))), 2)

    def test_a_song_shorter_than_the_fade_is_left_alone(self):
        """Fading a one second song from its own start is not a fade, it is a quiet song."""
        plan = _plan([_song("/m/song.mp3", 0, 1)], timeline_frames=50)

        self.assertEqual(list(_music_clips(plan)[0].iter("keyframe")), [])


class ThePictureFadeTravelsInThePlanTests(unittest.TestCase):
    """Resolve drops every picture fade FCPXML can express — adjust-opacity and <transition>
    both — and before 21.1 there was no other way to write one. So the number is carried in the
    exported plan and applied by the Resolve adapter through TimelineItem.SetFades.

    Verified by rendering the closing shot on 21.1: brightness runs 0.377 down to 0.000."""

    def test_the_plan_carries_a_closing_fade(self):
        plan = _plan([_song("/m/song.mp3", 0, 10)])
        self.assertEqual(
            plan_as_dict(plan)["closing_fade_seconds"], str(PICTURE_FADE_SECONDS))

    def test_it_is_the_measured_length(self):
        """13 of the 18 references end on black, over a median 2.5 seconds."""
        self.assertEqual(PICTURE_FADE_SECONDS, Fraction(5, 2))

    def test_fcpxml_does_not_try_to_write_it(self):
        """Writing one would be silently dropped, and a fade that looks written but is not is
        worse than none."""
        clips = _music_clips(_plan([_song("/m/song.mp3", 0, 10)]))
        self.assertTrue(clips)
        with tempfile.TemporaryDirectory() as temporary:
            written = export_fcpxml(
                _plan([_song("/m/song.mp3", 0, 10)]), Path(temporary) / "e.fcpxml")
            text = written.read_text()
        self.assertNotIn("adjust-opacity", text)
        self.assertNotIn("<transition", text)


if __name__ == "__main__":
    unittest.main()
