"""The film opens on a long shot and comes down to its own pace.

"klibin intro ve outrosu kötü hatta yok". Measured across the 18 reference films: their first
shot runs a median 2.36 seconds and settles to their median 1.00 by the fifth — 2.36, 1.76,
1.26, 1.08, 0.98. Ours opened at 2.00 and stayed near 2.00 for ten cuts, with a four second
hold landing inside the opening.

Two traps this covers, both found by measuring rather than by reading the code:
  * asking `_duration_from_beats` for more beats used to come back *shorter*, because past its
    limit it falls back to a fixed preferred length;
  * a ramp that asks for 2.50 seconds and picks a 1.10 second shot delivers 1.10.
"""

import unittest
from fractions import Fraction
from pathlib import Path

from sevenfilm.domain import BeatGrid, MediaAsset, Shot
from sevenfilm.services.planner import (
    OPENING_CATEGORIES,
    OPENING_DETAIL_CUTS,
    OPENING_SECONDS,
    _duration_from_beats,
    _opening_beats,
    build_timeline,
)
from sevenfilm.timebase import FrameRate, TimeRange

RATE = FrameRate(50)
PROFILE = {
    "median_shot_duration_seconds": 1.0,
    "median_reference_bpm": 123.047,
    "section_median_shot_duration_seconds": {
        "intro": 1.17, "build": 1.13, "core": 0.99, "finale": 0.959,
    },
}


def _plan(clips=120, long_clips=True):
    """A shoot where the long shots are the good ones, as the opening bar expects."""
    assets, shots = [], []
    categories = ("couple", "bride", "groom", "party", "venue", "detail")
    for index in range(clips):
        seconds = 8 if (long_clips and index % 3 == 0) else 2
        one = MediaAsset(id=f"a{index}", project_id="p", path=Path(f"/m/{index}.mov"),
                         name=f"{index}.mov", duration=Fraction(seconds + 1), frame_rate=RATE,
                         width=1920, height=1080)
        assets.append(one)
        shots.append(Shot(
            id=f"s{index}", asset_id=one.id, source_range=TimeRange(0, seconds * 50, RATE),
            category=categories[index % len(categories)], shot_scale="medium",
            technical_quality=.8, aesthetic_score=.8, motion_score=.5, confidence=.9,
            duplicate_group=f"visual:{index:016x}", brightness=.36, saturation=.15,
            highlight_clipping=.01))
    beats = tuple(Fraction(i * 60, 123) for i in range(900))
    music = BeatGrid(bpm=123, beats=beats, duration=Fraction(450),
                     sections=({"energy": "medium", "start": "0", "end": "450"},))
    return build_timeline(project_id="p", assets=assets, shots=shots, music=music,
                          frame_rate=RATE, target_duration=Fraction(120),
                          style_profile=PROFILE, seed=1)


def _opening_shoot():
    """A shoot whose morning holds one long detail shot, and whose evening holds a better one.

    Without the day limit the evening shot wins on merit — it is the stronger picture — which
    is how an edit came to open on the cake.
    """
    assets, shots = [], []
    plans = [
        ("sabah-detay.mov", "detail", 0.80, "09:00:00:00"),
        ("aksam-detay.mov", "detail", 0.95, "21:00:00:00"),
        ("sabah-cift.mov", "couple", 0.90, "09:02:00:00"),
    ]
    for index, (name, category, quality, recorded) in enumerate(plans):
        one = MediaAsset(id=f"o{index}", project_id="p", path=Path(f"/m/{name}"), name=name,
                         duration=Fraction(11), frame_rate=RATE, width=1920, height=1080,
                         timecode=recorded)
        assets.append(one)
        shots.append(Shot(
            id=f"os{index}", asset_id=one.id, source_range=TimeRange(0, 500, RATE),
            category=category, shot_scale="medium", technical_quality=quality,
            aesthetic_score=quality, motion_score=.5, confidence=.9,
            duplicate_group=f"visual:{index:016x}", brightness=.36, saturation=.15,
            highlight_clipping=.01))
    # and a body of ordinary material spread across the day, so the edit has something to cut
    for index in range(90):
        clock = 9 * 3600 + 300 + index * 900
        one = MediaAsset(
            id=f"b{index}", project_id="p", path=Path(f"/m/b{index}.mov"),
            name=f"b{index}.mov", duration=Fraction(4), frame_rate=RATE, width=1920,
            height=1080,
            timecode=f"{clock // 3600:02}:{clock // 60 % 60:02}:{clock % 60:02}:00")
        assets.append(one)
        shots.append(Shot(
            id=f"bs{index}", asset_id=one.id, source_range=TimeRange(0, 150, RATE),
            category=("couple", "bride", "groom", "party")[index % 4], shot_scale="medium",
            technical_quality=.7, aesthetic_score=.7, motion_score=.5, confidence=.9,
            duplicate_group=f"visual:{index + 900:016x}", brightness=.36, saturation=.15,
            highlight_clipping=.01))
    beats = tuple(Fraction(i * 60, 123) for i in range(900))
    music = BeatGrid(bpm=123, beats=beats, duration=Fraction(450),
                     sections=({"energy": "medium", "start": "0", "end": "450"},))
    return build_timeline(project_id="p", assets=assets, shots=shots, music=music,
                          frame_rate=RATE, target_duration=Fraction(120),
                          style_profile=PROFILE, seed=1)


class OpeningRampTests(unittest.TestCase):
    def test_the_ramp_comes_down(self):
        self.assertEqual(list(OPENING_SECONDS), sorted(OPENING_SECONDS, reverse=True))

    def test_the_ramp_is_measured_in_beats_so_it_survives_another_tempo(self):
        """2.36 seconds is five beats of a 123 BPM song and ten of a 246 BPM one."""
        slow = _opening_beats({"median_reference_bpm": 123}, Fraction(59, 25))
        fast = _opening_beats({"median_reference_bpm": 246}, Fraction(59, 25))
        self.assertAlmostEqual(float(fast / slow), 2.0, places=6)

    def test_asking_for_more_beats_never_returns_a_shorter_cut(self):
        """Past its limit `_duration_from_beats` falls back to a fixed length. The opening
        states its own ceiling so eight beats cannot come out shorter than six."""
        beats = tuple(Fraction(i * 60, 123) for i in range(40))
        grid = BeatGrid(bpm=123, beats=beats, duration=Fraction(60),
                        sections=({"energy": "low", "start": "0", "end": "60"},))
        wanted = Fraction(59, 25)
        six, eight = (
            _duration_from_beats(grid, Fraction(0), "low", PROFILE, 0.0, count,
                                 hold_limit=wanted * 2)
            for count in (6, 8)
        )
        self.assertGreater(eight, six)

    def test_the_film_opens_longer_than_it_runs(self):
        plan = _plan()
        opening = plan.items[0].timeline_range.duration_seconds
        rest = sorted(i.timeline_range.duration_seconds for i in plan.items[len(OPENING_SECONDS):])
        median = rest[len(rest) // 2]
        self.assertGreater(opening, median * Fraction(3, 2))

    def test_the_opening_is_not_cut_short_by_a_shot_too_brief_to_carry_it(self):
        """The ramp asked for 2.50 seconds and a 1.10 second shot won it, so the opening came
        out shorter than with no ramp at all."""
        plan = _plan()
        self.assertGreaterEqual(
            plan.items[0].timeline_range.duration_seconds, Fraction(2))

    def test_the_film_opens_at_the_start_of_the_day(self):
        """The edit runs chronologically and one opened on cake and glasses from halfway
        through the shoot: "direkt pasta kadehten başlamış iyi seçim değil"."""
        plan = _opening_shoot()
        self.assertEqual(plan.items[0].asset.name, "sabah-detay.mov")

    def test_it_opens_on_a_detail(self):
        """Measured on the references: detail is 40% of their first five shots against 18% of
        their films, 2.18 times its own weight. Nothing else is lifted."""
        self.assertIn(_opening_shoot().items[0].shot.category, OPENING_CATEGORIES)

    def test_the_detail_steer_stops_short_of_the_whole_ramp(self):
        """The references run 40% detail across their first five shots. Steering only the
        first cut left us at one in five; steering the whole ramp made all five details."""
        opening = [i.shot.category for i in _opening_shoot().items[:len(OPENING_SECONDS)]]
        details = sum(1 for category in opening if category in OPENING_CATEGORIES)
        self.assertEqual(details, OPENING_DETAIL_CUTS, opening)

    def test_no_hold_lands_inside_the_opening(self):
        plan = _plan()
        inside = [i.timeline_range.duration_seconds for i in plan.items[1:len(OPENING_SECONDS)]]
        self.assertTrue(all(seconds < Fraction(3) for seconds in inside), inside)


if __name__ == "__main__":
    unittest.main()
