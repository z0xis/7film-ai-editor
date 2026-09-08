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
from sevenfilm.services.exporter import plan_as_dict, rotation_for, zoom_for
from sevenfilm.timebase import FrameRate, TimeRange

RATE = FrameRate(50)


def _asset(name, width, height, written=0):
    return MediaAsset(id=name, project_id="p", path=Path(f"/m/{name}.mov"), name=f"{name}.mov",
                      duration=Fraction(20), frame_rate=RATE, width=width, height=height,
                      written_rotation=written)


class TurningTheMislabelledClipsBackTests(unittest.TestCase):
    def test_a_clip_is_turned_by_the_opposite_of_what_was_written(self):
        """A first attempt turned every one of them -90. The two written +90 came out right
        and the other fourteen came out upside down: "yine ters hepsini kontrol et"."""
        self.assertEqual(rotation_for(_asset("a", 2160, 3840, written=-90)), 90.0)
        self.assertEqual(rotation_for(_asset("b", 2160, 3840, written=90)), -90.0)

    def test_an_ordinary_clip_is_left_alone(self):
        self.assertEqual(rotation_for(_asset("fine", 3840, 2160, written=0)), 0.0)
        self.assertEqual(zoom_for(_asset("fine", 3840, 2160, written=0)), 1.0)

    def test_a_clip_with_no_angle_written_is_not_guessed_at(self):
        self.assertEqual(rotation_for(_asset("odd", 2160, 3840, written=0)), 0.0)

    def test_a_turned_clip_is_scaled_back_to_full_width(self):
        """Resolve fits it by the height of the frame it thinks it has, so a turned clip sits
        at 1080x607 inside 1920x1080 until it is scaled: "fit olmamış monitöre"."""
        self.assertAlmostEqual(zoom_for(_asset("a", 2160, 3840, written=-90)), 3840 / 2160)

    def test_the_plan_carries_both_for_the_adapter(self):
        """FCPXML cannot express either, so they travel in the plan and Resolve applies them."""
        turned = _asset("turned", 2160, 3840, written=-90)
        straight = _asset("straight", 3840, 2160)
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

        self.assertEqual(items[0]["rotation_degrees"], 90.0)
        self.assertAlmostEqual(items[0]["rotation_zoom"], 3840 / 2160)
        self.assertEqual(items[1]["rotation_degrees"], 0.0)
        self.assertEqual(items[1]["rotation_zoom"], 1.0)


if __name__ == "__main__":
    unittest.main()
