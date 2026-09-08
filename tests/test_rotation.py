"""Clips the camera labelled the wrong way up.

Sixteen clips in one shoot are stored 3840x2160 with a rotation of -90 or +90 in their
metadata, so every player — Resolve and our own analysis included — turns them on their side
and reports 2160x3840. The metadata is wrong. Measured by running face detection on both
orientations of each clip, the unrotated frame wins in 14 of the 16, by 14 faces to 1 on one
and 16 to 0 on another: the picture is upright in the file and the camera mislabelled it.

Dropping them was the first fix; the editor asked for the other one — "şu dikeyleri de
döndürsün artık". The angle is measured rather than assumed: rendering +90 came out upside
down, -90 came out level with the venue signage readable.
"""

import unittest
from fractions import Fraction
from pathlib import Path

from sevenfilm.domain import MediaAsset, Shot, TimelineItem, TimelinePlan
from sevenfilm.services.exporter import UPRIGHT_ROTATION, plan_as_dict, rotation_for
from sevenfilm.timebase import FrameRate, TimeRange

RATE = FrameRate(50)


def _asset(name, width, height):
    return MediaAsset(id=name, project_id="p", path=Path(f"/m/{name}.mov"), name=f"{name}.mov",
                      duration=Fraction(20), frame_rate=RATE, width=width, height=height)


class TurningTheMislabelledClipsBackTests(unittest.TestCase):
    def test_a_clip_reported_taller_than_it_is_wide_is_turned(self):
        self.assertEqual(rotation_for(_asset("wrong", 2160, 3840)), UPRIGHT_ROTATION)

    def test_an_ordinary_clip_is_left_alone(self):
        self.assertEqual(rotation_for(_asset("fine", 3840, 2160)), 0.0)

    def test_the_angle_is_the_one_that_rendered_level(self):
        """+90 rendered upside down."""
        self.assertEqual(UPRIGHT_ROTATION, -90.0)

    def test_the_plan_carries_the_angle_for_the_adapter(self):
        """FCPXML cannot express it, so it travels in the plan and Resolve applies it."""
        turned, straight = _asset("turned", 2160, 3840), _asset("straight", 3840, 2160)
        plan = TimelinePlan(id="t", project_id="p", name="7Film", frame_rate=RATE,
                            target_duration=Fraction(4))
        for index, asset in enumerate((turned, straight)):
            shot = Shot(id=f"s{index}", asset_id=asset.id,
                        source_range=TimeRange(0, 100, RATE), category="couple",
                        shot_scale="medium", technical_quality=.8, aesthetic_score=.8,
                        motion_score=.5, confidence=.9, duplicate_group=f"visual:{index}",
                        brightness=.36, saturation=.15, highlight_clipping=.01)
            plan.items.append(TimelineItem(
                id=f"i{index}", shot=shot, asset=asset,
                source_range=TimeRange(0, 100, RATE),
                timeline_range=TimeRange(index * 100, 100, RATE),
                score=0.5, selection_reason="test"))

        items = plan_as_dict(plan)["items"]

        self.assertEqual(items[0]["rotation_degrees"], UPRIGHT_ROTATION)
        self.assertEqual(items[1]["rotation_degrees"], 0.0)


if __name__ == "__main__":
    unittest.main()
