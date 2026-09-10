"""How long the film may stay on one shot scale.

Watching a whole cut as stills, its last third was medium shot after medium shot of a crowded
room. Measured: runs of the same scale reached 17 cuts, every seed had one of 10 or more, and
half the film sat inside runs of four or more.

The footage is the first cause and cannot be fixed in the planner — the evening of this shoot
is 79% medium shots against 26% in the morning — but the edit can spread the variety it does
have instead of clustering it.

Swept over 8 seeds:

    ceza  en uzun seri  ort seri  kötü%   an
    0.00          12.5      2.27      7  4.0
    0.02           6.2      1.99      8  4.0
    0.04           5.4      1.88      7  4.0   <-
    0.08           5.0      1.84      9  4.0
"""

import unittest
from fractions import Fraction
from itertools import groupby
from pathlib import Path

from sevenfilm.domain import BeatGrid, MediaAsset, Shot
from sevenfilm.services.planner import (
    SCALE_RUN_LIMIT,
    SCALE_RUN_PENALTY,
    SCALE_SHARE_WEIGHT,
    _scale_overrun,
    _score_candidate,
    _trailing_scale_run,
    build_timeline,
)
from sevenfilm.timebase import FrameRate, TimeRange

RATE = FrameRate(50)


def _shot(identifier="s", scale="medium"):
    return Shot(id=identifier, asset_id=f"a{identifier}",
                source_range=TimeRange(0, 500, RATE), category="couple", shot_scale=scale,
                technical_quality=.8, aesthetic_score=.8, motion_score=.5, confidence=.8,
                duplicate_group=f"visual:{identifier}", brightness=.36, saturation=.15,
                highlight_clipping=.01)


class TheChargeGrowsWithTheRunTests(unittest.TestCase):
    def _penalty(self, run):
        return _score_candidate(
            _shot(), preferred_categories=("couple",), preferred_scales=("medium",),
            energy="medium", recent=(), desired_duration=Fraction(1), random_jitter=0.0,
            scale_run=run)[1]["scale_run_penalty"]

    def test_a_short_run_costs_nothing(self):
        self.assertEqual(self._penalty(SCALE_RUN_LIMIT - 2), 0.0)

    def test_it_starts_at_the_limit(self):
        self.assertAlmostEqual(self._penalty(SCALE_RUN_LIMIT), SCALE_RUN_PENALTY)

    def test_it_grows_rather_than_switching_on(self):
        """A flat charge is paid once and ignored; this one gets heavier the longer the run."""
        self.assertGreater(self._penalty(SCALE_RUN_LIMIT + 4), self._penalty(SCALE_RUN_LIMIT))

    def test_the_limit_is_a_few_cuts_not_a_dozen(self):
        self.assertLessEqual(SCALE_RUN_LIMIT, 6)


class CountingTheRunTests(unittest.TestCase):
    def test_it_counts_back_from_the_end_of_the_film(self):
        items = []
        for index, scale in enumerate(("wide", "medium", "medium", "medium")):
            shot = _shot(str(index), scale)
            items.append(type("Item", (), {"shot": shot})())
        self.assertEqual(_trailing_scale_run(items, "medium"), 3)
        self.assertEqual(_trailing_scale_run(items, "wide"), 0)

    def test_an_empty_film_has_no_run(self):
        self.assertEqual(_trailing_scale_run([], "medium"), 0)


class TheEditSpreadsWhatVarietyItHasTests(unittest.TestCase):
    def _plan(self):
        """A shoot that is mostly medium, as the evening of a real one is."""
        assets, shots = [], []
        for index in range(150):
            scale = "medium" if index % 5 else ("wide" if index % 10 else "close_up")
            one = MediaAsset(id=f"a{index}", project_id="p", path=Path(f"/m/{index}.mov"),
                             name=f"{index}.mov", duration=Fraction(11), frame_rate=RATE,
                             width=1920, height=1080)
            assets.append(one)
            shots.append(Shot(
                id=f"s{index}", asset_id=one.id, source_range=TimeRange(0, 500, RATE),
                category=("couple", "bride", "groom", "party")[index % 4], shot_scale=scale,
                technical_quality=.8, aesthetic_score=.8, motion_score=.5, confidence=.9,
                duplicate_group=f"visual:{index:016x}", brightness=.36, saturation=.15,
                highlight_clipping=.01))
        beats = tuple(Fraction(i, 2) for i in range(900))
        music = BeatGrid(bpm=120, beats=beats, duration=Fraction(450),
                         sections=({"energy": "medium", "start": "0", "end": "450"},))
        return build_timeline(project_id="p", assets=assets, shots=shots, music=music,
                              frame_rate=RATE, target_duration=Fraction(120), seed=1)

    def test_the_film_does_not_sit_on_one_scale(self):
        runs = [len(list(group))
                for _, group in groupby(i.shot.shot_scale for i in self._plan().items)]
        self.assertLess(max(runs), 12, f"en uzun seri {max(runs)}")


if __name__ == "__main__":
    unittest.main()


class TheEditSpendsTheScalesTheReferencesDoTests(unittest.TestCase):
    """The preference table was doing nothing for most of the film.

    Between 15% and 75% of the running time `_preferred_scales` lists all four scales, and the
    score only asks whether a scale is in the list — so every scale scored the same and the
    edit simply inherited the shoot's own mix. The shoot is not the reference.

    Measured across the 18 reference films, 1109 cuts: 60.0% wide, 38.6% medium. One edit of
    this shoot came out 26.4% wide and 68.8% medium while the shoot itself holds 34% wide, so
    the wides were there and were not being reached for. Read as a share instead — the way the
    categories already are — wide reaches 37.1%.

    The share is learned, not written here: tools/references/learn_scale_shares.py reads it
    off the films and stores it in the profile.
    """

    def _profile(self, wide: float) -> dict:
        return {"scale_shares": {"wide": wide, "medium": 1.0 - wide}}

    def test_a_scale_under_its_share_is_not_charged(self):
        overrun = _scale_overrun(self._profile(0.6), "wide", {"wide": 2}, 10)

        self.assertEqual(overrun, 0.0)

    def test_a_scale_past_its_share_is_charged_by_how_far(self):
        overrun = _scale_overrun(self._profile(0.6), "wide", {"wide": 9}, 10)

        self.assertAlmostEqual(overrun, 0.3)

    def test_a_shoot_with_no_learned_shares_is_left_alone(self):
        """A profile from before this was measured, or none at all, changes nothing."""
        self.assertEqual(_scale_overrun(None, "wide", {"wide": 9}, 10), 0.0)
        self.assertEqual(_scale_overrun({}, "wide", {"wide": 9}, 10), 0.0)

    def test_a_scale_the_references_never_use_is_left_alone(self):
        """Silence in the profile is not a quota of zero: the references hold 0.3% detail and
        a shoot may reasonably hold more."""
        self.assertEqual(
            _scale_overrun(self._profile(0.6), "detail", {"detail": 5}, 10), 0.0)

    def test_the_charge_is_heavy_enough_to_move_the_mix(self):
        """Swept at 0, 1, 2, 3, 5 and 8: wide goes 30.1% to 37.1% at 5 and stops — 8 adds half
        a point. Nothing else moves: quality holds at 0.411, the moments hold, no clip is used
        more than four times, and neighbouring cuts stay as unalike as the references' own."""
        self.assertGreaterEqual(SCALE_SHARE_WEIGHT, 3.0)
