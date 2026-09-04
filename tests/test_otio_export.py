"""The OTIO the user can download must be readable by OpenTimelineIO itself."""

import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

import opentimelineio as otio
from sevenfilm.domain import MediaAsset, Shot, TimelineItem, TimelinePlan
from sevenfilm.services.exporter import export_otio
from sevenfilm.timebase import FrameRate, TimeRange

RATE = FrameRate(25)
SOURCE_RATE = FrameRate(50)  # The project's own footage is 50 fps on a 25 fps timeline.


def plan_with(items=3, music=True):
    plan = TimelinePlan(id="t", project_id="p", name="AI Rough Cut", frame_rate=RATE,
                        target_duration=Fraction(6))
    for index in range(items):
        asset = MediaAsset(
            id=f"a{index}", project_id="p", path=Path(f"/tmp/A{index:03}.mov"),
            name=f"A{index:03}.mov", duration=Fraction(20), frame_rate=SOURCE_RATE,
            width=1920, height=1080)
        shot = Shot(id=f"s{index}", asset_id=asset.id, source_range=TimeRange(0, 1000, SOURCE_RATE))
        plan.items.append(TimelineItem(
            id=f"i{index}", shot=shot, asset=asset,
            source_range=TimeRange(100 * index, 100, SOURCE_RATE),
            timeline_range=TimeRange(50 * index, 50, RATE), score=.9, selection_reason="reason"))
    if music:
        plan.music_path = Path("/tmp/track.mp3")
        plan.music_duration = Fraction(200)
    return plan


class OtioReadbackTests(unittest.TestCase):
    def written(self, plan):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        destination = Path(folder.name) / "timeline.otio"
        export_otio(plan, destination)
        return otio.adapters.read_from_file(str(destination))

    def test_opentimelineio_can_read_what_we_write(self):
        """It could not: a single media_reference is the pre-0.15 shape and is refused."""
        timeline = self.written(plan_with())

        self.assertEqual(timeline.name, "AI Rough Cut")
        self.assertEqual(len(list(timeline.find_clips())), 4)  # 3 video, 1 music

    def test_the_video_track_holds_every_cut_in_order(self):
        timeline = self.written(plan_with(items=5))

        clips = list(timeline.video_tracks()[0])

        self.assertEqual([clip.name for clip in clips],
                         [f"A{index:03}.mov" for index in range(5)])

    def test_each_clip_keeps_its_source_range_at_the_footage_rate(self):
        clip = self.written(plan_with()).video_tracks()[0][1]

        self.assertEqual(clip.source_range.start_time.rate, 50.0)
        self.assertEqual(clip.source_range.start_time.value, 100)
        self.assertEqual(clip.source_range.duration.value, 100)

    def test_the_media_points_at_the_original_file(self):
        track = self.written(plan_with()).video_tracks()[0]

        self.assertEqual(track[0].media_reference.target_url, Path("/tmp/A000.mov").resolve().as_uri())
        self.assertEqual(track[0].media_reference.available_range.duration.to_seconds(), 20.0)

    def test_the_music_gets_its_own_audio_track(self):
        timeline = self.written(plan_with())

        audio = timeline.audio_tracks()
        self.assertEqual(len(audio), 1)
        self.assertEqual(audio[0].name, "A1 Music")
        self.assertEqual(audio[0][0].name, "track.mp3")

    def test_the_music_is_clamped_to_the_rough_cut(self):
        plan = plan_with(items=3)  # 3 x 50 frames at 25 fps = 6 seconds

        music = self.written(plan).audio_tracks()[0][0]

        self.assertEqual(music.source_range.duration.to_seconds(), 6.0)
        self.assertEqual(music.media_reference.available_range.duration.to_seconds(), 200.0)

    def test_a_plan_without_music_has_no_audio_track(self):
        timeline = self.written(plan_with(music=False))

        self.assertEqual(timeline.audio_tracks(), [])
        self.assertEqual(len(list(timeline.find_clips())), 3)

    def test_the_explanations_survive_into_the_metadata(self):
        clip = self.written(plan_with()).video_tracks()[0][0]

        self.assertEqual(clip.metadata["sevenfilm"]["selection_reason"], "reason")
        self.assertEqual(clip.metadata["sevenfilm"]["score"], .9)

    def test_the_timeline_length_is_the_rough_cut_length(self):
        self.assertEqual(self.written(plan_with(items=4)).duration().to_seconds(), 8.0)


if __name__ == "__main__":
    unittest.main()
