"""A wedding film is made of sequences: an entrance, the cake, a table of details.

The planner charged 0.30 for taking the next shot from the same clip and 0.16 for staying on
the same subject, so it changed both at every cut. Measured on a 117 clip edit it had built:
not one of its 116 transitions kept either — an empty table dropped in alone at position 2, 28,
33, 39 and 44. Measured on the 18 references instead: 29% of consecutive shots stay in the same
category, a run averages 1.41 shots and reaches 12, and 49% of their running time is inside a
run of two or more.
"""

import unittest
from fractions import Fraction
from itertools import pairwise
from pathlib import Path

from sevenfilm.domain import BeatGrid, MediaAsset, Shot, TimelineItem
from sevenfilm.services.planner import (
    MINIMUM_CATEGORY_SHARE,
    SEQUENCE_TARGET_RUN,
    _score_candidate,
    _share_overrun,
    _trailing_run,
    build_timeline,
)
from sevenfilm.timebase import FrameRate, TimeRange

RATE = FrameRate(25)


def shot(identifier, category="couple", scale="medium", asset="a", group=None):
    return Shot(id=identifier, asset_id=asset, source_range=TimeRange(0, 500, RATE),
                category=category, shot_scale=scale, technical_quality=.8, aesthetic_score=.8,
                motion_score=.5, confidence=.8, duplicate_group=group or f"visual:{hash(identifier) & 0xFFFFFFFFFFFFFFFF:016x}",
                brightness=.36, saturation=.15, highlight_clipping=.01)


def item(one):
    return TimelineItem(
        id=one.id, shot=one,
        asset=MediaAsset(id=one.asset_id, project_id="p", path=Path("/m/x.mov"), name="x.mov",
                         duration=Fraction(20), frame_rate=RATE, width=1920, height=1080),
        source_range=TimeRange(0, 50, RATE), timeline_range=TimeRange(0, 50, RATE),
        score=.8, selection_reason="r")


class TrailingRunTests(unittest.TestCase):
    def test_it_counts_back_while_the_category_holds(self):
        items = [item(shot("a", "venue")), item(shot("b", "detail")), item(shot("c", "detail"))]

        self.assertEqual(_trailing_run(items, "detail"), 2)
        self.assertEqual(_trailing_run(items, "venue"), 0)

    def test_an_empty_edit_is_sitting_on_nothing(self):
        self.assertEqual(_trailing_run([], "couple"), 0)


class SequenceScoringTests(unittest.TestCase):
    def score(self, candidate, previous=None, run=0, overrun=0.0):
        value, _ = _score_candidate(
            candidate,
            preferred_categories=("couple", "bride", "groom"),
            preferred_scales=("medium", "wide"),
            energy="medium",
            recent=(item(previous),) if previous else (),
            desired_duration=Fraction(1),
            random_jitter=0.0,
            current_run=run,
            share_overrun=overrun,
        )
        return value

    def test_staying_on_a_subject_costs_nothing_inside_a_sequence(self):
        """The cake is several shots of the cake, and the film has to be allowed to stay."""
        previous = shot("p", "couple", "medium")
        staying = self.score(shot("s", "couple", "wide"), previous, run=1)
        leaving = self.score(shot("s", "couple", "wide"), previous=None)

        self.assertAlmostEqual(staying, leaving, places=6)

    def test_past_the_ceiling_staying_costs_more_each_time(self):
        previous = shot("p", "couple", "medium")
        readings = [self.score(shot("s", "couple", "wide"), previous, run=run)
                    for run in range(SEQUENCE_TARGET_RUN, SEQUENCE_TARGET_RUN + 4)]

        self.assertEqual(readings, sorted(readings, reverse=True))
        self.assertLess(readings[-1], readings[0])

    def test_the_same_subject_at_the_same_size_is_still_charged(self):
        previous = shot("p", "couple", "medium")
        same = self.score(shot("s", "couple", "medium"), previous, run=1)
        different = self.score(shot("s", "couple", "wide"), previous, run=1)

        self.assertLess(same, different)

    def test_a_category_past_its_share_scores_lower(self):
        plain = self.score(shot("s", "couple"), overrun=0.0)
        over = self.score(shot("s", "couple"), overrun=0.3)

        self.assertLess(over, plain)


class ShareOverrunTests(unittest.TestCase):
    def profile(self):
        return {"story_arc": [{"couple": 0.40, "venue": 0.21, "bride": 0.18}]}

    def test_a_category_under_its_reference_share_costs_nothing(self):
        used = {"couple": 3}

        self.assertEqual(_share_overrun(self.profile(), 0.0, "couple", used, 10), 0.0)

    def test_a_category_over_its_share_reports_the_excess(self):
        used = {"couple": 6}

        self.assertAlmostEqual(_share_overrun(self.profile(), 0.0, "couple", used, 10), 0.2)

    def test_a_category_the_references_never_show_still_gets_a_floor(self):
        used = {"party": 1}

        self.assertEqual(_share_overrun(self.profile(), 0.0, "party", used, 100), 0.0)
        self.assertGreater(_share_overrun(self.profile(), 0.0, "party", {"party": 20}, 100), 0.0)
        self.assertAlmostEqual(MINIMUM_CATEGORY_SHARE, 0.05)

    def test_no_arc_means_no_cap(self):
        self.assertEqual(_share_overrun(None, 0.0, "couple", {"couple": 9}, 10), 0.0)
        self.assertEqual(_share_overrun({}, 0.0, "couple", {"couple": 9}, 10), 0.0)

    def test_an_empty_edit_has_no_share_yet(self):
        self.assertEqual(_share_overrun(self.profile(), 0.0, "couple", {}, 0), 0.0)


class SequencesReachThePlanTests(unittest.TestCase):
    def plan(self):
        assets, shots = [], []
        categories = ("couple", "bride", "groom", "party", "venue", "detail", "family", "ceremony")
        for index in range(200):
            asset = MediaAsset(id=f"a{index}", project_id="p", path=Path(f"/m/{index}.mov"),
                               name=f"{index}.mov", duration=Fraction(30), frame_rate=RATE,
                               width=1920, height=1080)
            assets.append(asset)
            shots.append(shot(f"s{index}", categories[index % len(categories)],
                              ("medium", "wide", "close_up")[index % 3], asset.id,
                              f"visual:{index:016x}"))
        beats = tuple(Fraction(i, 2) for i in range(700))
        music = BeatGrid(bpm=120, beats=beats, duration=Fraction(350),
                         sections=({"energy": "medium", "start": "0", "end": "350"},))
        return build_timeline(project_id="p", assets=assets, shots=shots, music=music,
                              frame_rate=RATE, target_duration=Fraction(150), seed=1)

    def test_the_edit_stays_on_a_subject_at_least_sometimes(self):
        categories = [i.shot.category for i in self.plan().items]
        stayed = sum(a == b for a, b in pairwise(categories))

        self.assertGreater(stayed, 0)

    def test_no_subject_runs_away_with_the_whole_edit(self):
        categories = [i.shot.category for i in self.plan().items]
        biggest = max(categories.count(name) for name in set(categories))

        self.assertLess(biggest / len(categories), 0.6)
