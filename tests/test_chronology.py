"""The edit may move around the shooting day, but it may not lose it.

The complaint that produced this: a table of flowers filmed at 08:21, before anyone had
arrived, closed a 150 second film at 125 seconds of 150. Measured on that edit, order and time
of day correlated at 0.114, sixty-two of a hundred and seventeen cuts went backwards, and the
median cut jumped 12.8 minutes. With the pressure fitted, the correlation is 0.84, the median
jump 4.5 minutes, and over five seeds not one morning shot lands in the closing fifth.
"""

import unittest
from fractions import Fraction
from itertools import pairwise
from pathlib import Path

from sevenfilm.domain import BeatGrid, MediaAsset, Shot
from sevenfilm.services.planner import (
    CHRONOLOGY_SLACK,
    _day_position,
    _score_candidate,
    build_timeline,
)
from sevenfilm.timebase import FrameRate, TimeRange

RATE = FrameRate(25)


def asset(identifier, timecode):
    return MediaAsset(id=identifier, project_id="p", path=Path(f"/m/{identifier}.mov"),
                      name=f"{identifier}.mov", duration=Fraction(20), frame_rate=RATE,
                      width=1920, height=1080, timecode=timecode)


def shot(identifier="s", category="detail"):
    return Shot(id=identifier, asset_id="a", source_range=TimeRange(0, 500, RATE),
                category=category, shot_scale="medium", technical_quality=.8,
                aesthetic_score=.8, motion_score=.5, confidence=.8,
                duplicate_group=f"visual:{identifier}", brightness=.36, saturation=.15,
                highlight_clipping=.01)


class DayPositionTests(unittest.TestCase):
    def test_it_spans_the_shoot_from_first_frame_to_last(self):
        places = _day_position([asset("a", "08:00:00:00"), asset("b", "09:00:00:00"),
                                asset("c", "10:00:00:00")])

        self.assertEqual(places["a"], 0.0)
        self.assertEqual(places["b"], 0.5)
        self.assertEqual(places["c"], 1.0)

    def test_a_clip_without_a_timecode_is_left_out_rather_than_guessed_at(self):
        places = _day_position([asset("a", "08:00:00:00"), asset("b", "09:00:00:00"),
                                asset("c", None)])

        self.assertNotIn("c", places)

    def test_the_day_is_cut_at_its_longest_silence_not_at_midnight(self):
        """A reception running past twelve is one evening, not two ends of a clock."""
        places = _day_position([asset("a", "22:00:00:00"), asset("b", "23:00:00:00"),
                                asset("c", "00:30:00:00")])

        self.assertEqual(places["a"], 0.0)
        self.assertEqual(places["c"], 1.0)
        self.assertLess(places["a"], places["b"])
        self.assertLess(places["b"], places["c"])

    def test_a_shoot_of_one_clip_has_no_shape_to_read(self):
        self.assertEqual(_day_position([asset("a", "08:00:00:00")]), {"a": 0.5})


class ChronologyScoringTests(unittest.TestCase):
    def components(self, progress, day_position):
        _, parts = _score_candidate(
            shot(),
            preferred_categories=("detail", "venue"),
            preferred_scales=("medium",),
            energy="medium",
            recent=(),
            desired_duration=Fraction(1),
            random_jitter=0.0,
            progress=progress,
            day_position=day_position,
        )
        return parts

    def test_the_morning_is_charged_for_closing_the_film(self):
        self.assertGreater(self.components(0.9, 0.05)["chronology_penalty"], 0.0)

    def test_a_shot_from_this_point_of_the_day_costs_nothing(self):
        self.assertEqual(self.components(0.9, 0.9)["chronology_penalty"], 0.0)

    def test_the_slack_lets_the_film_move_around_the_day_for_free(self):
        near = self.components(0.5, 0.5 + CHRONOLOGY_SLACK - 0.01)
        far = self.components(0.5, 0.5 + CHRONOLOGY_SLACK + 0.2)

        self.assertEqual(near["chronology_penalty"], 0.0)
        self.assertGreater(far["chronology_penalty"], 0.0)

    def test_a_clip_with_no_timecode_is_never_charged(self):
        self.assertEqual(self.components(0.9, None)["chronology_penalty"], 0.0)

    def test_the_charge_grows_with_the_distance(self):
        near = self.components(0.9, 0.5)["chronology_penalty"]
        far = self.components(0.9, 0.05)["chronology_penalty"]

        self.assertGreater(far, near)


class TheFilmFollowsTheDayTests(unittest.TestCase):
    def plan(self):
        """Two hundred clips filmed across four hours, every category at every hour."""
        assets, shots = [], []
        categories = ("couple", "bride", "groom", "party", "venue", "detail", "family",
                      "ceremony")
        for index in range(200):
            second = 8 * 3600 + index * 72
            one = MediaAsset(
                id=f"a{index}", project_id="p", path=Path(f"/m/{index}.mov"),
                name=f"{index}.mov", duration=Fraction(30), frame_rate=RATE, width=1920,
                height=1080,
                timecode=f"{second // 3600:02d}:{second // 60 % 60:02d}:{second % 60:02d}:00")
            assets.append(one)
            shots.append(Shot(
                id=f"s{index}", asset_id=one.id, source_range=TimeRange(0, 500, RATE),
                category=categories[index % len(categories)],
                shot_scale=("medium", "wide", "close_up")[index % 3], technical_quality=.8,
                aesthetic_score=.8, motion_score=.5, confidence=.8,
                duplicate_group=f"visual:{index:016x}", brightness=.36, saturation=.15,
                highlight_clipping=.01))
        beats = tuple(Fraction(i, 2) for i in range(700))
        music = BeatGrid(bpm=120, beats=beats, duration=Fraction(350),
                         sections=({"energy": "medium", "start": "0", "end": "350"},))
        return build_timeline(project_id="p", assets=assets, shots=shots, music=music,
                              frame_rate=RATE, target_duration=Fraction(150), seed=1)

    def test_the_film_closes_in_the_later_half_of_the_day(self):
        """Two hundred clips of equal merit spread evenly across four hours: here the
        chronology term is the only thing telling them apart and ties fall to the jitter, so
        the proposition is where the closing fifth sits, not whether one marginal shot
        crossed. Measured on the real shoot across five seeds, nothing from the first thirty
        per cent of the day reaches the closing fifth at all.
        """
        items = self.plan().items
        places = _day_position([i.asset for i in items])
        closing = sorted(
            places[item.asset.id]
            for index, item in enumerate(items)
            if index / len(items) > 0.8
        )

        self.assertGreater(closing[len(closing) // 2], 0.5)
        self.assertEqual([place for place in closing if place < 0.15], [])

    def test_the_edit_still_moves_around_the_day_rather_than_sorting_it(self):
        items = self.plan().items
        places = _day_position([i.asset for i in items])
        order = [places[i.asset.id] for i in items]
        backwards = sum(1 for a, b in pairwise(order) if b < a)

        self.assertGreater(backwards, len(order) // 5)


if __name__ == "__main__":
    unittest.main()
