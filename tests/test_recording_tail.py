"""The last frames of a clip are the operator lowering the camera.

The complaint that produced this: the first cut of an edit ended four frames from the end of
its clip, and those frames are a whip. Measured over 70 clips of this shoot against each
clip's own median frame-to-frame motion, the last frame runs 1.88x, the second-to-last 2.30x
and the third 2.00x, falling to 1.21x by the fifth; 71% of clips spike past twice their median
somewhere in their last eight frames. The head is calm at 0.80-0.94x, so it is left alone.
"""

import unittest
from fractions import Fraction
from pathlib import Path

from sevenfilm.domain import MediaAsset, Shot
from sevenfilm.services.planner import (
    RECORDING_TAIL_SECONDS,
    _without_recording_tail,
)
from sevenfilm.timebase import FrameRate, TimeRange

RATE = FrameRate(50)


def asset(seconds):
    return MediaAsset(id="a", project_id="p", path=Path("/m/a.mov"), name="a.mov",
                      duration=Fraction(seconds), frame_rate=RATE, width=1920, height=1080)


def shot(start, duration):
    return Shot(id="s", asset_id="a", source_range=TimeRange(start, duration, RATE),
                category="couple", shot_scale="medium", technical_quality=.8,
                aesthetic_score=.8, motion_score=.5, confidence=.8,
                duplicate_group="visual:1", brightness=.36, saturation=.15,
                highlight_clipping=.01)


class RecordingTailTests(unittest.TestCase):
    def test_a_shot_running_to_the_end_of_the_clip_is_pulled_back(self):
        # The shot that opened the edit: the last 44 frames of a 408 frame clip.
        trimmed = _without_recording_tail(shot(364, 44), asset(Fraction(408, 50)))
        margin = RATE.frames_from_seconds(RECORDING_TAIL_SECONDS, rounding="ceil")

        self.assertEqual(trimmed.source_range.start_frame, 364)
        self.assertEqual(
            trimmed.source_range.start_frame + trimmed.source_range.duration_frames,
            408 - margin,
        )

    def test_a_shot_in_the_middle_of_the_clip_is_left_alone(self):
        original = shot(100, 100)

        self.assertEqual(_without_recording_tail(original, asset(20)), original)

    def test_nothing_is_taken_off_the_front(self):
        trimmed = _without_recording_tail(shot(0, 1000), asset(20))

        self.assertEqual(trimmed.source_range.start_frame, 0)

    def test_a_shot_that_is_nothing_but_the_tail_is_emptied_for_the_length_filter(self):
        margin = RATE.frames_from_seconds(RECORDING_TAIL_SECONDS, rounding="ceil")
        trimmed = _without_recording_tail(shot(1000 - margin, margin), asset(20))

        self.assertEqual(trimmed.source_range.duration_frames, 0)

    def test_a_shot_longer_than_its_own_clip_is_not_trimmed_against_that_length(self):
        """The two disagree, so there is no knowing where the recording stopped."""
        original = shot(0, 250)

        self.assertEqual(_without_recording_tail(original, asset(4)), original)


class TheEditKeepsOffTheTailTests(unittest.TestCase):
    def test_no_cut_in_a_built_edit_lands_in_the_whip(self):
        from sevenfilm.domain import BeatGrid
        from sevenfilm.services.planner import build_timeline

        assets, shots = [], []
        categories = ("couple", "bride", "groom", "party", "venue", "detail")
        for index in range(200):
            one = MediaAsset(id=f"a{index}", project_id="p", path=Path(f"/m/{index}.mov"),
                             name=f"{index}.mov", duration=Fraction(10), frame_rate=RATE,
                             width=1920, height=1080)
            assets.append(one)
            # Every shot runs to the very last frame of its clip, which is the case the
            # trim exists for.
            shots.append(Shot(
                id=f"s{index}", asset_id=one.id, source_range=TimeRange(300, 200, RATE),
                category=categories[index % len(categories)], shot_scale="medium",
                technical_quality=.8, aesthetic_score=.8, motion_score=.5, confidence=.8,
                duplicate_group=f"visual:{index:016x}", brightness=.36, saturation=.15,
                highlight_clipping=.01))
        beats = tuple(Fraction(i, 2) for i in range(700))
        music = BeatGrid(bpm=120, beats=beats, duration=Fraction(350),
                         sections=({"energy": "medium", "start": "0", "end": "350"},))
        plan = build_timeline(project_id="p", assets=assets, shots=shots, music=music,
                              frame_rate=RATE, target_duration=Fraction(150), seed=1)
        margin = RATE.frames_from_seconds(RECORDING_TAIL_SECONDS, rounding="ceil")
        closest = min(500 - item.source_range.end_frame for item in plan.items)

        self.assertGreaterEqual(closest, margin)


if __name__ == "__main__":
    unittest.main()
