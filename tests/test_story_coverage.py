"""What the footage cannot supply must be said, not quietly filled in with something else."""

import unittest
from fractions import Fraction
from pathlib import Path

from sevenfilm.domain import BeatGrid, MediaAsset, Shot, TimelineItem, TimelinePlan
from sevenfilm.services.planner import (
    _preferred_categories,
    _story_arc_ratio,
    _story_coverage_warning,
    build_timeline,
)
from sevenfilm.timebase import FrameRate, TimeRange

RATE = FrameRate(25)


def shot(index, category):
    return Shot(
        id=f"s{index}", asset_id=f"a{index}", source_range=TimeRange(0, 500, RATE),
        category=category, shot_scale="medium", technical_quality=.8, aesthetic_score=.8,
        motion_score=.5, confidence=.7, brightness=.36, saturation=.15, highlight_clipping=.01)


def plan_of(*categories):
    plan = TimelinePlan(id="t", project_id="p", name="AI", frame_rate=RATE,
                        target_duration=Fraction(len(categories)))
    for index, category in enumerate(categories):
        asset = MediaAsset(id=f"a{index}", project_id="p", path=Path(f"/m/A{index}.mov"),
                           name=f"A{index}.mov", duration=Fraction(20), frame_rate=RATE,
                           width=1920, height=1080)
        plan.items.append(TimelineItem(
            id=f"i{index}", shot=shot(index, category), asset=asset,
            source_range=TimeRange(0, 25, RATE),
            timeline_range=TimeRange(25 * index, 25, RATE), score=.9, selection_reason="r"))
    return plan


class StoryCoverageWarningTests(unittest.TestCase):
    def test_a_shoot_missing_a_whole_part_of_the_story_is_named(self):
        # 98 couple shots and one venue: the opening cannot be built from this.
        candidates = [shot(index, "couple") for index in range(98)] + [shot(98, "venue")]

        warning = _story_coverage_warning(candidates)

        self.assertIn("venue", warning)
        self.assertIn("%1", warning)

    def test_the_thinnest_is_named_first(self):
        candidates = ([shot(i, "couple") for i in range(200)]
                      + [shot(200, "ceremony")]
                      + [shot(201, "venue"), shot(202, "venue"), shot(203, "venue")])

        warning = _story_coverage_warning(candidates)

        self.assertLess(warning.index("ceremony"), warning.index("venue"))

    def test_a_well_covered_shoot_says_nothing(self):
        categories = ("venue", "detail", "bride", "groom", "family", "ceremony", "couple", "party")
        candidates = [shot(index, categories[index % 8]) for index in range(80)]

        self.assertIsNone(_story_coverage_warning(candidates))

    def test_no_footage_at_all_says_nothing(self):
        self.assertIsNone(_story_coverage_warning([]))

    def test_a_category_the_story_never_asks_for_is_not_reported(self):
        """b_roll is preferred nowhere, so its being thin is not worth telling anyone."""
        categories = ("venue", "detail", "bride", "groom", "family", "ceremony", "couple", "party")
        candidates = [shot(index, categories[index % 8]) for index in range(80)]
        candidates.append(shot(80, "b_roll"))

        warning = _story_coverage_warning(candidates)

        self.assertIsNone(warning, "only story categories should ever be named")


class StoryArcRatioTests(unittest.TestCase):
    def test_an_edit_that_follows_the_arc_reads_as_whole(self):
        wanted = [_preferred_categories(index / 8)[0] for index in range(8)]

        self.assertEqual(_story_arc_ratio(plan_of(*wanted)), 1.0)

    def test_an_edit_that_ignores_it_reads_as_nothing(self):
        # b_roll is preferred nowhere.
        self.assertEqual(_story_arc_ratio(plan_of(*(["b_roll"] * 8))), 0.0)

    def test_a_half_and_half_edit_reads_as_half(self):
        wanted = [_preferred_categories(index / 8)[0] for index in range(8)]
        mixed = [category if index % 2 == 0 else "b_roll" for index, category in enumerate(wanted)]

        self.assertAlmostEqual(_story_arc_ratio(plan_of(*mixed)), 0.5)

    def test_an_empty_plan_is_zero_rather_than_a_crash(self):
        plan = TimelinePlan(id="t", project_id="p", name="AI", frame_rate=RATE,
                            target_duration=Fraction(1))
        self.assertEqual(_story_arc_ratio(plan), 0.0)


class PlanReportsCoverageTests(unittest.TestCase):
    def test_both_findings_reach_the_plan(self):
        interval = Fraction(60) / Fraction(120)
        music = BeatGrid(bpm=120, duration=Fraction(200),
                         beats=tuple(interval * step for step in range(401)),
                         sections=({"start": "0", "end": "200", "energy": "medium"},))
        assets, shots = [], []
        for index in range(120):
            assets.append(MediaAsset(id=f"a{index}", project_id="p", path=Path(f"/m/A{index}.mov"),
                                     name=f"A{index}.mov", duration=Fraction(20), frame_rate=RATE,
                                     width=1920, height=1080))
            # Nothing but couples and brides: no venue, no ceremony, no party.
            shots.append(shot(index, "couple" if index % 2 else "bride"))

        plan = build_timeline(project_id="p", assets=assets, shots=shots, music=music,
                              frame_rate=RATE, target_duration=Fraction(120), seed=5)

        self.assertTrue(any("neredeyse yok" in warning for warning in plan.warnings), plan.warnings)
        self.assertTrue(any("tercih edilen" in warning for warning in plan.warnings), plan.warnings)


if __name__ == "__main__":
    unittest.main()
