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
    SAME_CLIP_REPEAT_SIMILARITY,
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

    def test_a_sequence_continuing_within_one_take_is_not(self):
        """A sequence continues inside a take, and two cuts from one file look alike anyway —
        same room, same people, same light. So the same file is held to a higher bar rather
        than exempted: measured on one edit, a pair reading 0.754 is the next moment."""
        found = _is_second_take(
            shot("b", "file1"), item(shot("a", "file1")),
            vectors(0.75), same_scene=True)

        self.assertFalse(found)

    def test_but_a_near_identical_pair_from_one_file_still_is(self):
        """Exempting the same file entirely put two cuts of the bouquet back to back, four
        seconds apart in the source and 0.957 alike, with nothing charged for it."""
        found = _is_second_take(
            shot("b", "file1"), item(shot("a", "file1")),
            vectors(0.96), same_scene=True)

        self.assertTrue(found)

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


class TwoCutsFromOneFileAreHeldToAHigherBarTests(unittest.TestCase):
    """A sequence continues within a take, so two cuts from one file are usually its next
    moment — and they look alike simply because they are the same room and the same people.
    Exempting them entirely let an edit put two cuts of the bouquet back to back, four seconds
    apart in the source and 0.957 alike, with nothing charged for it. The next same-file pair
    in that edit measured 0.754 and reads as a sequence, which is the gap the two thresholds
    sit in.
    """

    def test_the_same_file_bar_is_higher_than_the_other(self):
        self.assertGreater(SAME_CLIP_REPEAT_SIMILARITY, SECOND_TAKE_SIMILARITY)

    def test_a_near_identical_pair_from_one_file_is_caught(self):
        previous, shot = _pair(same_asset=True)
        embeddings = _embeddings(shot, previous, similarity=0.96)

        self.assertTrue(
            _is_second_take(shot, previous, embeddings, same_scene=True))

    def test_a_sequence_from_one_file_is_left_alone(self):
        previous, shot = _pair(same_asset=True)
        embeddings = _embeddings(shot, previous, similarity=0.75)

        self.assertFalse(
            _is_second_take(shot, previous, embeddings, same_scene=True))

    def test_a_second_take_from_another_file_still_uses_the_lower_bar(self):
        previous, shot = _pair(same_asset=False)
        embeddings = _embeddings(shot, previous, similarity=0.92)

        self.assertTrue(
            _is_second_take(shot, previous, embeddings, same_scene=True))


def _pair(*, same_asset):
    import numpy as np  # noqa: F401
    previous_shot = Shot(id="p", asset_id="a1", source_range=TimeRange(0, 100, RATE),
                         category="bride", shot_scale="medium", technical_quality=.8,
                         aesthetic_score=.8, motion_score=.5, confidence=.9,
                         duplicate_group="visual:1", brightness=.36, saturation=.15,
                         highlight_clipping=.01)
    asset = MediaAsset(id="a1", project_id="p", path=Path("/m/a1.mov"), name="a1.mov",
                       duration=Fraction(20), frame_rate=RATE, width=1920, height=1080)
    previous = TimelineItem(id="i", shot=previous_shot, asset=asset,
                            source_range=TimeRange(0, 100, RATE),
                            timeline_range=TimeRange(0, 100, RATE), score=.5,
                            selection_reason="")
    shot = Shot(id="s", asset_id="a1" if same_asset else "a2",
                source_range=TimeRange(200, 100, RATE), category="bride",
                shot_scale="medium", technical_quality=.8, aesthetic_score=.8,
                motion_score=.5, confidence=.9, duplicate_group="visual:2", brightness=.36,
                saturation=.15, highlight_clipping=.01)
    return previous, shot


def _embeddings(shot, previous, *, similarity):
    import numpy as np
    here = np.array([1.0, 0.0], dtype=np.float32)
    angle = float(np.arccos(similarity))
    there = np.array([np.cos(angle), np.sin(angle)], dtype=np.float32)
    return {shot.id: here, previous.shot.id: there}
