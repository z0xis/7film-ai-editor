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
from sevenfilm.services.planner import (
    CLOSING_SECONDS,
    HELD_SHOT_SECONDS,
    OPENING_SECONDS,
    build_timeline,
)
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

    def test_it_is_longer_than_any_ordinary_cut(self):
        """Not longer than *every* cut: measured on the 18 references, 13 of them close on
        something shorter than their own longest shot, and their held shots run a median 4.0
        seconds against a median close of 3.17. The claim that holds it is that the film
        finishes rather than stops — so it is measured against the ordinary cutting, with the
        deliberate long shots (the opening ramp and the held shots) left out."""
        plan = _plan()
        ordinary = [
            item.timeline_range.duration_seconds
            for item in plan.items[len(OPENING_SECONDS):-1]
            if item.timeline_range.duration_seconds < HELD_SHOT_SECONDS
        ]

        self.assertGreaterEqual(
            plan.items[-1].timeline_range.duration_seconds, max(ordinary))

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


class TheFilmPullsBackToEndTests(unittest.TestCase):
    """Measured across the 18 references: 15 of them close on a `venue` shot — 83% of their
    endings against 23% of their shots — and not one closes on a `couple` or a `detail`. What
    those endings are, looking at them: the couple small in a wide frame walking away, a card
    on a table. The film pulls back.

    Ours was ending on the bride's back in a crowded room. "intro outro kötü".

    The category cannot be required: this shoot's four usable venue shots are all from the
    first minutes of the day, and closing an evening on the morning foyer trades one fault for
    another. The shape is asked for instead — wide, nobody large in frame, late in the day.
    """

    def _plan(self):
        assets, shots = [], []
        # A crowded evening, plus one wide shot at the end of the day and one in the morning.
        plans = [("sabah-genis.mov", "venue", "wide", 0.0, "09:00:00:00"),
                 ("aksam-genis.mov", "couple", "wide", 0.02, "22:00:00:00")]
        for index, (name, category, scale, ratio, clock) in enumerate(plans):
            one = MediaAsset(id=f"w{index}", project_id="p", path=Path(f"/m/{name}"),
                             name=name, duration=Fraction(12), frame_rate=RATE,
                             width=1920, height=1080, timecode=clock)
            assets.append(one)
            shots.append(Shot(
                id=f"ws{index}", asset_id=one.id, source_range=TimeRange(0, 500, RATE),
                category=category, shot_scale=scale, technical_quality=.85,
                aesthetic_score=.85, motion_score=.5, confidence=.9,
                duplicate_group=f"visual:{index:016x}", brightness=.36, saturation=.15,
                highlight_clipping=.01, face_ratio=ratio))
        for index in range(120):
            clock = 9 * 3600 + 600 + index * 380
            one = MediaAsset(
                id=f"c{index}", project_id="p", path=Path(f"/m/c{index}.mov"),
                name=f"c{index}.mov", duration=Fraction(6), frame_rate=RATE,
                width=1920, height=1080,
                timecode=f"{clock // 3600:02}:{clock // 60 % 60:02}:{clock % 60:02}:00")
            assets.append(one)
            shots.append(Shot(
                id=f"cs{index}", asset_id=one.id, source_range=TimeRange(0, 250, RATE),
                category=("couple", "bride", "groom", "party")[index % 4],
                shot_scale="medium", technical_quality=.8, aesthetic_score=.8,
                motion_score=.5, confidence=.9,
                duplicate_group=f"visual:{index + 500:016x}", brightness=.36,
                saturation=.15, highlight_clipping=.01, face_ratio=0.05))
        beats = tuple(Fraction(i, 2) for i in range(900))
        music = BeatGrid(bpm=120, beats=beats, duration=Fraction(450),
                         sections=({"energy": "medium", "start": "0", "end": "450"},))
        return build_timeline(project_id="p", assets=assets, shots=shots, music=music,
                              frame_rate=RATE, target_duration=Fraction(150), seed=1)

    def test_the_film_ends_on_a_wide_frame(self):
        self.assertEqual(self._plan().items[-1].shot.shot_scale, "wide")

    def test_it_does_not_reach_back_to_the_morning_for_one(self):
        """A wide shot with nobody in it fits the shape perfectly and finishes the film in the
        wrong hour: a morning shot of a laid table came out as the ending."""
        self.assertEqual(self._plan().items[-1].asset.name, "aksam-genis.mov")
