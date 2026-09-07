"""A film finishes; it does not stop.

Measured across the 18 reference films, 1219 shots: their median shot runs 1.00 second and
their last shot 3.17 — three times as long — with the last five already lengthening to 1.62.
Half close on three seconds or more and two hold for over twelve.

Our edits were ending on an ordinary 0.98 second cut of whatever happened to be left, because
the tail was handed over only when an ordinary cut would have left less than a quarter of a
second behind.
"""

import unittest
from fractions import Fraction
from pathlib import Path

from sevenfilm.domain import BeatGrid, MediaAsset, Shot
from sevenfilm.services.planner import CLOSING_SECONDS, build_timeline
from sevenfilm.timebase import FrameRate, TimeRange

RATE = FrameRate(50)


def _plan(target=Fraction(150), poor_last=False):
    assets, shots = [], []
    categories = ("couple", "bride", "groom", "party", "venue", "detail")
    for index in range(200):
        one = MediaAsset(id=f"a{index}", project_id="p", path=Path(f"/m/{index}.mov"),
                         name=f"{index}.mov", duration=Fraction(30), frame_rate=RATE,
                         width=1920, height=1080)
        assets.append(one)
        # One clip is technically strong but its subject is cut by the frame edge: exactly the
        # shot a film must not be left sitting on.
        edge = poor_last and index == 0
        shots.append(Shot(
            id=f"s{index}", asset_id=one.id, source_range=TimeRange(0, 1400, RATE),
            category=categories[index % len(categories)], shot_scale="medium",
            technical_quality=.99 if edge else .8, aesthetic_score=.99 if edge else .8,
            motion_score=.5, confidence=.9, duplicate_group=f"visual:{index:016x}",
            brightness=.36, saturation=.15, highlight_clipping=.01,
            face_ratio=0.05, face_edge=0.9 if edge else 0.0))
    beats = tuple(Fraction(i, 2) for i in range(900))
    music = BeatGrid(bpm=120, beats=beats, duration=Fraction(450),
                     sections=({"energy": "medium", "start": "0", "end": "450"},))
    return build_timeline(project_id="p", assets=assets, shots=shots, music=music,
                          frame_rate=RATE, target_duration=target, seed=1)


class TheFilmHoldsItsLastImageTests(unittest.TestCase):
    def test_the_closing_shot_runs_at_least_a_closing(self):
        plan = _plan()

        self.assertGreaterEqual(plan.items[-1].timeline_range.duration_seconds, CLOSING_SECONDS)

    def test_it_is_the_longest_cut_in_the_film(self):
        plan = _plan()
        longest_before = max(
            item.timeline_range.duration_seconds for item in plan.items[:-1]
        )

        self.assertGreaterEqual(
            plan.items[-1].timeline_range.duration_seconds, longest_before)

    def test_the_edit_still_lands_on_its_target_exactly(self):
        self.assertEqual(_plan().duration, Fraction(150))

    def test_the_film_is_not_left_on_a_shot_nobody_could_hold(self):
        """The strongest shot in the set has its subject against the frame edge."""
        plan = _plan(poor_last=True)

        self.assertNotEqual(plan.items[-1].asset.id, "a0")

    def test_a_short_film_gets_a_short_close_rather_than_one_shot_of_it(self):
        plan = _plan(target=Fraction(120))
        closing = plan.items[-1].timeline_range.duration_seconds

        self.assertLessEqual(closing, Fraction(120) / 10)
        self.assertEqual(plan.duration, Fraction(120))


class TheTailIsOnlyHandedOverWhenAShotCanCarryItTests(unittest.TestCase):
    """Shots are split at five seconds and lose a handle at each end, so nothing supplies more
    than about 4.6. Traced on the shoot: 4.82 seconds left, a 3.90 cut asked for, 3.66
    delivered because the source ran out, and the film ended on the 1.16 that was left.
    """

    def build(self):
        assets, shots = [], []
        categories = ("couple", "bride", "groom", "party", "venue", "detail")
        for index in range(200):
            one = MediaAsset(id=f"a{index}", project_id="p", path=Path(f"/m/{index}.mov"),
                             name=f"{index}.mov", duration=Fraction(6), frame_rate=RATE,
                             width=1920, height=1080)
            assets.append(one)
            # Five second shots, as the splitter caps them: no single one can carry a long tail.
            shots.append(Shot(
                id=f"s{index}", asset_id=one.id, source_range=TimeRange(0, 250, RATE),
                category=categories[index % len(categories)], shot_scale="medium",
                technical_quality=.8, aesthetic_score=.8, motion_score=.5, confidence=.9,
                duplicate_group=f"visual:{index:016x}", brightness=.36, saturation=.15,
                highlight_clipping=.01, face_ratio=0.05, face_edge=0.0))
        beats = tuple(Fraction(i, 2) for i in range(900))
        music = BeatGrid(bpm=120, beats=beats, duration=Fraction(450),
                         sections=({"energy": "medium", "start": "0", "end": "450"},))
        profile = {"held_shots": {"share_by_band": [0.3] * 10, "median_seconds": 4.0}}
        return build_timeline(project_id="p", assets=assets, shots=shots, music=music,
                              frame_rate=RATE, target_duration=Fraction(150), seed=1,
                              style_profile=profile)

    def test_the_film_does_not_end_on_what_was_left_over(self):
        plan = self.build()

        self.assertGreaterEqual(
            plan.items[-1].timeline_range.duration_seconds, CLOSING_SECONDS)
        self.assertEqual(plan.duration, Fraction(150))


if __name__ == "__main__":
    unittest.main()
