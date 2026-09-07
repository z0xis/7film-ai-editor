"""Two takes of one setup, cut back to back, read as a repeat rather than a sequence.

The editor pointed at 36 seconds: "iki plan ard arda çok benziyor". C1974 and C1975 — the
camera rolled twice on the couple standing in the same spot, and both takes reached the edit
one after the other at 0.939 similarity.

This is not a rule about similar neighbours, and measuring the references settled that. Across
their 1201 consecutive pairs they are *more* willing than this edit to put alike shots
together: 4.7% of theirs sit above 0.90 against 0.9% of ours, and they reach 0.988. What they
presumably do not do is cut one take against another of the same setup — which is what the
perceptual hash was meant to catch and cannot, since the two takes sit 17 bits apart, outside
the near-duplicate threshold entirely.

What the rule does to a whole edit is measured on the shoot rather than simulated here. Over
three seeds it takes the second-take pairs from 0.7 to none and the most alike neighbours in
the film from 0.919 to 0.899, leaving the six moments and the scene runs untouched. A fixture
that reproduces the interaction has to be built so particularly — the right categories, the
right clocks, the right alternatives — that it ends up testing the fixture; one written here
stopped reproducing the fault at all once its chronology was made even.
"""

import unittest
from fractions import Fraction
from pathlib import Path

import numpy as np
from sevenfilm.domain import MediaAsset, Shot, TimelineItem
from sevenfilm.services.planner import (
    SECOND_TAKE_PENALTY,
    SECOND_TAKE_SIMILARITY,
    _is_second_take,
    _score_candidate,
)
from sevenfilm.timebase import FrameRate, TimeRange

RATE = FrameRate(50)


def shot(identifier, asset):
    return Shot(id=identifier, asset_id=asset, source_range=TimeRange(0, 500, RATE),
                category="couple", shot_scale="medium", technical_quality=.8,
                aesthetic_score=.8, motion_score=.5, confidence=.8,
                duplicate_group=f"visual:{identifier}", brightness=.36, saturation=.15,
                highlight_clipping=.01)


def item(one):
    return TimelineItem(
        id=one.id, shot=one,
        asset=MediaAsset(id=one.asset_id, project_id="p", path=Path("/m/x.mov"), name="x.mov",
                         duration=Fraction(20), frame_rate=RATE, width=1920, height=1080),
        source_range=TimeRange(0, 50, RATE), timeline_range=TimeRange(0, 50, RATE),
        score=.8, selection_reason="r")


def vectors(similarity):
    """Two unit vectors a known cosine apart."""
    first = np.array([1.0, 0.0], dtype=np.float32)
    second = np.array([similarity, (1 - similarity ** 2) ** 0.5], dtype=np.float32)
    return {"a": first, "b": second}


class WhatCountsAsASecondTakeTests(unittest.TestCase):
    def test_a_near_identical_shot_from_another_file_of_the_same_moment(self):
        found = _is_second_take(
            shot("b", "file2"), item(shot("a", "file1")),
            vectors(SECOND_TAKE_SIMILARITY + 0.02), same_scene=True)

        self.assertTrue(found)

    def test_a_shot_continuing_within_one_take_never_is(self):
        """A sequence continues inside a take, however alike the two frames look."""
        found = _is_second_take(
            shot("b", "file1"), item(shot("a", "file1")),
            vectors(0.99), same_scene=True)

        self.assertFalse(found)

    def test_two_files_from_different_moments_are_not_takes_of_each_other(self):
        found = _is_second_take(
            shot("b", "file2"), item(shot("a", "file1")),
            vectors(0.99), same_scene=False)

        self.assertFalse(found)

    def test_shots_that_only_resemble_each_other_are_left_alone(self):
        # The references put pairs at 0.85 and above together freely.
        found = _is_second_take(
            shot("b", "file2"), item(shot("a", "file1")),
            vectors(SECOND_TAKE_SIMILARITY - 0.05), same_scene=True)

        self.assertFalse(found)

    def test_an_unmeasured_shoot_is_not_guessed_at(self):
        self.assertFalse(
            _is_second_take(shot("b", "file2"), item(shot("a", "file1")), {}, same_scene=True))

    def test_the_opening_cut_has_nothing_behind_it(self):
        self.assertFalse(
            _is_second_take(shot("b", "file2"), None, vectors(0.99), same_scene=True))


class TheScoreChargesForItTests(unittest.TestCase):
    def components(self, second_take):
        _, parts = _score_candidate(
            shot("s", "a"),
            preferred_categories=("couple",), preferred_scales=("medium",), energy="medium",
            recent=(), desired_duration=Fraction(1), random_jitter=0.0,
            second_take=second_take,
        )
        return parts

    def test_a_second_take_gives_something_up(self):
        self.assertAlmostEqual(
            self.components(True)["second_take_penalty"], SECOND_TAKE_PENALTY)

    def test_anything_else_gives_up_nothing(self):
        self.assertEqual(self.components(False)["second_take_penalty"], 0.0)


if __name__ == "__main__":
    unittest.main()
