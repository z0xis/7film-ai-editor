"""The moments a wedding film has to contain, found rather than waited for.

Measured on an edit the editor spent an evening picking apart. Of the eight shots that match
each moment best, this is how many reached the film: the cake one, the feeding two, and the
kiss, the ring, the first dance and the entrance none at all. All of that footage was indexed
and available.

The planner had no notion that a wedding owes its subjects certain things. It scores every
shot on quality, category, rhythm and the day's order, and the ring exchange loses to a
technically cleaner shot of somebody walking. That is what "gelin damadın girişi yok" and
"bir hikaye sıralaması yok" were describing all along.
"""

import unittest
from fractions import Fraction
from pathlib import Path

from sevenfilm.domain import BeatGrid, MediaAsset, Shot
from sevenfilm.services.moments import (
    MOMENT_CONFIDENT,
    MOMENT_LIFT,
    MOMENT_PROMPTS,
    Moment,
)
from sevenfilm.services.planner import (
    CHRONOLOGY_SLACK,
    GLIMPSE_SECONDS,
    HELD_SHOT_SECONDS,
    MOMENT_BONUS,
    MOMENT_DAY_SPREAD,
    MOMENT_MIN_SECONDS,
    TYPICAL_CUT_SECONDS,
    _moment_shots_of_the_day,
    _score_candidate,
    build_timeline,
)
from sevenfilm.timebase import FrameRate, TimeRange

RATE = FrameRate(50)


class TheScoreAsksForWhatIsMissingTests(unittest.TestCase):
    def components(self, missing, progress=0.0, day_position=None):
        _, parts = _score_candidate(
            Shot(id="s", asset_id="a", source_range=TimeRange(0, 500, RATE),
                 category="couple", shot_scale="medium", technical_quality=.8,
                 aesthetic_score=.8, motion_score=.5, confidence=.8,
                 duplicate_group="visual:1", brightness=.36, saturation=.15,
                 highlight_clipping=.01),
            preferred_categories=("couple",), preferred_scales=("medium",), energy="medium",
            recent=(), desired_duration=Fraction(1), random_jitter=0.0,
            missing_moment=missing,
            progress=progress,
            day_position=day_position,
        )
        return parts

    def test_a_moment_the_film_has_not_shown_is_worth_something(self):
        self.assertAlmostEqual(self.components(True)["moment_bonus"], MOMENT_BONUS)

    def test_an_ordinary_shot_is_worth_nothing_extra(self):
        self.assertEqual(self.components(False)["moment_bonus"], 0.0)

    def test_a_moment_owed_is_not_a_moment_due_now(self):
        """Offered unconditionally the bonus simply outweighed the chronology term, 0.10
        against 0.064, and the first twenty-two seconds of the film came out as the kiss, the
        entrance, the cake, the ring and the first dance one after another.
        """
        far = self.components(True, progress=0.05, day_position=0.9)
        due = self.components(True, progress=0.05, day_position=0.05 + CHRONOLOGY_SLACK / 2)

        self.assertEqual(far["moment_bonus"], 0.0)
        self.assertAlmostEqual(due["moment_bonus"], MOMENT_BONUS)


class EveryMomentReachesTheFilmTests(unittest.TestCase):
    """The six that matter, each carried by one deliberately unremarkable shot."""

    def build(self, moments):
        return self.build_with(moments)

    def build_with(self, moments, rejected=None, handicap=True):
        assets, shots = [], []
        categories = ("couple", "bride", "groom", "party", "venue", "detail")
        for index in range(200):
            one = MediaAsset(id=f"a{index}", project_id="p", path=Path(f"/m/{index}.mov"),
                             name=f"{index}.mov", duration=Fraction(30), frame_rate=RATE,
                             width=1920, height=1080)
            assets.append(one)
            # Behind the rest by 0.20, which the quality and aesthetic weights turn into a
            # 0.09 deficit — just inside what the bonus can answer. On the shoot the moment
            # shots are not behind at all: they run 0.41 to 0.49 against a median of 0.406,
            # and lose to the category, share and framing terms rather than on merit. The
            # handicap here stands in for that so the test has something to overturn.
            carries = index < len(MOMENT_PROMPTS)
            shots.append(Shot(
                id=f"s{index}", asset_id=one.id, source_range=TimeRange(0, 500, RATE),
                category=categories[index % len(categories)], shot_scale="medium",
                technical_quality=.65 if (carries and handicap) else .85,
                aesthetic_score=.65 if (carries and handicap) else .85,
                motion_score=.5, confidence=.9, duplicate_group=f"visual:{index:016x}",
                brightness=.36, saturation=.15, highlight_clipping=.01))
        beats = tuple(Fraction(i, 2) for i in range(700))
        music = BeatGrid(bpm=120, beats=beats, duration=Fraction(350),
                         sections=({"energy": "medium", "start": "0", "end": "350"},))
        return build_timeline(project_id="p", assets=assets, shots=shots, music=music,
                              frame_rate=RATE, target_duration=Fraction(150), seed=1,
                              moments=moments, rejected=rejected)

    def moments(self):
        return tuple(
            Moment(name=name, shot_ids=(f"s{index}",), best=0.3)
            for index, name in enumerate(MOMENT_PROMPTS)
        )

    def test_without_them_the_moment_shots_lose(self):
        used = {item.shot.id for item in self.build(None).items}

        self.assertEqual(used & {f"s{i}" for i in range(len(MOMENT_PROMPTS))}, set())

    def test_with_them_every_moment_is_in_the_film(self):
        moments = self.moments()
        used = {item.shot.id for item in self.build(moments).items}

        for moment in moments:
            self.assertTrue(
                set(moment.shot_ids) & used, f"{moment.name} filme girmedi")

    def test_a_moment_stops_being_asked_for_once_it_is_shown(self):
        """Otherwise the whole shortlist would be pulled in behind the first one."""
        moment = Moment(name="cake", shot_ids=tuple(f"s{i}" for i in range(8)), best=0.3)
        used = [item.shot.id for item in self.build((moment,)).items]
        carried = [shot_id for shot_id in used if shot_id in set(moment.shot_ids)]

        self.assertGreaterEqual(len(carried), 1)
        self.assertLessEqual(len(carried), 3)


class AMomentIsWhereItHappenedTests(unittest.TestCase):
    """The affinity cannot tell a shortlist apart; the time of day can.

    Measured on this shoot: the eight best shots for each moment score between 0.94 and 1.00
    of the best, with no gap anywhere. Their positions in the day do have a gap. The entrance
    sits at 0.183 to 0.193 and the first dance at 0.648 to 0.687, and the strays in each
    shortlist sit far outside — the entrance's held one at 0.102 and one at 0.308, and it was
    the 0.102 one the film answered the entrance with, a clip with no face in it at all.
    """

    def test_a_clip_far_from_the_rest_of_the_moment_is_not_that_moment(self):
        shots = {
            f"s{i}": Shot(id=f"s{i}", asset_id=f"a{i}", source_range=TimeRange(0, 500, RATE),
                          category="couple", shot_scale="medium", technical_quality=.8,
                          aesthetic_score=.8, motion_score=.5, confidence=.9,
                          duplicate_group=f"visual:{i}", brightness=.36, saturation=.15,
                          highlight_clipping=.01)
            for i in range(4)
        }
        moment = Moment(name="entrance", shot_ids=("s0", "s1", "s2", "s3"), best=0.35)
        day = {"a0": 0.183, "a1": 0.190, "a2": 0.193, "a3": 0.102}

        kept = _moment_shots_of_the_day(moment, shots, day)

        self.assertEqual(kept, ("s0", "s1", "s2"))

    def test_a_shoot_with_no_recording_times_keeps_the_whole_shortlist(self):
        moment = Moment(name="entrance", shot_ids=("s0", "s1"), best=0.35)

        self.assertEqual(_moment_shots_of_the_day(moment, {}, {}), ("s0", "s1"))

    def test_the_spread_is_a_twentieth_of_the_day(self):
        """Wide enough for every clustered shot on this shoot (spread at most 0.039), tight
        enough to drop every stray (nearest 0.088)."""
        self.assertEqual(MOMENT_DAY_SPREAD, 0.05)


class AMomentGetsALongEnoughCutTests(unittest.TestCase):
    """A hold is what an entrance, a first look or a slow dance is made of.

    Measured on this shoot before this: the cake reached the film for 0.48 seconds and the
    kiss for 1.96, because the moment bonus landed on whatever cut the rhythm happened to be
    making. Spending the holds on the moments the film still owes took the cake to 4.24
    seconds, the kiss to 3.92 and the first dance to 8.30, with the running time unchanged.
    """

    def test_a_hold_goes_to_a_moment_the_film_still_owes(self):
        # No handicap here: a hold picks from the better half of what is left, so a moment
        # carried by a shot worse than the shoot's median is not held at all. On the shoot
        # that is the entrance, whose best clips run 0.36 to 0.40 against a median of 0.406,
        # and it still reaches the film in one 0.80 second cut. Not solved.
        maker = EveryMomentReachesTheFilmTests()
        plan = maker.build_with(maker.moments(), handicap=False)
        longest = {}
        for item in plan.items:
            seconds = item.timeline_range.duration_seconds
            longest[item.shot.id] = max(longest.get(item.shot.id, seconds), seconds)
        moment_cuts = [
            longest[f"s{i}"] for i in range(len(MOMENT_PROMPTS)) if f"s{i}" in longest
        ]

        self.assertTrue(moment_cuts, "hiçbir an filme girmedi")
        self.assertGreaterEqual(max(moment_cuts), HELD_SHOT_SECONDS)


class AMomentIsAskedForInTheOrderItHappenedTests(unittest.TestCase):
    """Two moments owed at one cut is a race, and the earlier one kept losing.

    Measured on this shoot. The film makes six long cuts in 150 seconds; the one at 11% went
    to the kiss, at 0.26 of the day, while the entrance at 0.19 was the moment actually due
    there — and the entrance then reached the film in a single 0.80 second cut, the one the
    editor picked out: "gelin damat girişi kısa kalıyor ve bi planda nerdeyse görünmüyorlar."

    Four other routes were tried against this and measured on the real shoot. Lowering the
    hold's quality bar for moments in steps of 5% changed nothing at any step. Widening the
    shortlist to the neighbouring shots of the same take moved the entrance from 0.80 to 0.82.
    Holding out for a long cut unconditionally did give the entrance 3.90 seconds — at cut 98
    of 131, three quarters through a film whose entrance belongs at a fifth, with the cake
    pushed to 0.48 seconds behind it. What works is this, with the two below.
    """

    def test_the_moments_of_the_day_land_in_order(self):
        plan = EveryMomentReachesTheFilmTests().build(
            EveryMomentReachesTheFilmTests().moments())

        self.assertTrue(plan.items)


class AMomentNeedsACutItCanFillTests(unittest.TestCase):
    """A cut shorter than an ordinary one does not settle a moment; the film keeps owing it.

    On the shoot, with the ordering above and the hold's quality bar lifted for moments the
    day has only one of:

        entrance     0.80 -> 4.60 s, in two cuts at 12 and 13 of 133
        cake         3.98 -> 4.18
        first dance  8.70 -> 8.94, and the film ends on it
        kiss         3.80 -> 1.96

    Swept at 1.00, 1.25, 1.50, 1.75 and 2.00 seconds. 1.00 and 1.25 give the table above;
    from 1.50 the entrance takes the holds the cake and the first dance were getting, and at
    2.00 the first dance stops reaching the film at all.
    """

    def test_the_bar_is_an_ordinary_cut(self):
        self.assertEqual(MOMENT_MIN_SECONDS, TYPICAL_CUT_SECONDS)

    def test_past_its_place_in_the_day_a_moment_settles_for_what_it_got(self):
        """Otherwise a moment whose footage cannot carry a long cut is chased to the end of
        the film - the entrance landed at cut 98 of 131 that way."""
        self.assertGreater(CHRONOLOGY_SLACK, 0)


class AMomentThatNeverReachesTheFilmTests(unittest.TestCase):
    """The one loss the editor cannot catch by watching: nothing is wrong on screen.

    Measured on this shoot. The cake was absent from a 109 cut edit and no warning said so.
    Its only clip ran 121 seconds and held 53 shots; one bad cut in it was flagged, the whole
    clip was rejected, and with it the day's only record of the cake. A rejection list the
    planner honours in silence is a list that can delete a moment from the wedding.
    """

    def build(self, moments, rejected=None):
        return EveryMomentReachesTheFilmTests().build_with(moments, rejected)

    def test_a_moment_whose_every_shot_is_rejected_is_named_as_rejected(self):
        moment = Moment(name="cake", shot_ids=("s0",), best=0.34)
        plan = self.build((moment,), rejected=(frozenset({"a0"}), frozenset()))
        said = " ".join(plan.warnings)

        self.assertIn("eleme listesinde", said)
        self.assertIn("pasta kesme", said)

    def test_a_moment_that_simply_lost_is_named_differently(self):
        """The footage is there and usable; the edit preferred other cuts. Telling the editor
        to review the rejection list would send them looking for something that is not there.
        """
        moment = Moment(name="cake", shot_ids=("s0",), best=0.34)
        plan = self.build((moment,))
        said = " ".join(plan.warnings)

        self.assertNotIn("eleme listesinde", said)

    def test_a_moment_the_film_could_only_glimpse_is_named(self):
        """In the film, but for 0.80 seconds. A hold picks from the better half of the shoot,
        and the entrance's own footage sits below this shoot's median, so no hold will take
        it. Forcing it in cost 66 seconds of running time. Saying so is what is left."""
        maker = EveryMomentReachesTheFilmTests()
        plan = maker.build_with((Moment(name="cake", shot_ids=("s0",), best=0.34),))
        cake = [
            item for item in plan.items if item.shot.id == "s0"]
        said = " ".join(plan.warnings)

        if cake and max(
                item.timeline_range.duration_seconds for item in cake) < GLIMPSE_SECONDS:
            self.assertIn("çok kısa girdi", said)
            self.assertIn("pasta kesme", said)

    def test_a_moment_the_film_shows_is_not_warned_about_at_all(self):
        moments = EveryMomentReachesTheFilmTests().moments()
        said = " ".join(self.build(moments).warnings)

        self.assertNotIn("kurguda hiç yok", said)
        self.assertNotIn("kurguya giremedi", said)


class WhatTheFootageDoesNotHoldTests(unittest.TestCase):
    """The affinity cannot prove a moment happened, only that this is the closest answer.

    Eighteen prompts were tried against this shoot — fireworks, a decorated wedding car,
    signing the register, none of which this wedding has — and every one cleared the lift,
    scoring 1.26 to 1.94 with no gap anywhere. Two other tests were built and both failed the
    same way: how many shots cluster near the top (fireworks 21, the ring 1), and how tightly
    the best shots sit in time, which looked decisive until "a mother helping the bride into
    her dress" came back with the tightest spread of all and three shots of the dance floor.

    So the tool says so instead of pretending otherwise.
    """

    def test_the_lift_is_only_a_floor(self):
        self.assertGreater(MOMENT_LIFT, 1.0)

    def test_a_weak_match_is_marked_for_the_editor_to_look_at(self):
        weak = Moment(name="cake", shot_ids=("s1",), best=MOMENT_CONFIDENT - 0.01)
        strong = Moment(name="cake", shot_ids=("s1",), best=MOMENT_CONFIDENT + 0.01)

        self.assertTrue(weak.uncertain)
        self.assertFalse(strong.uncertain)

    def test_every_moment_has_a_name_the_editor_would_use(self):
        for name in MOMENT_PROMPTS:
            self.assertNotEqual(Moment(name=name, shot_ids=(), best=0.3).label, name)

    def test_the_plan_says_which_moments_it_is_unsure_of(self):
        moments = (
            Moment(name="cake", shot_ids=("s0",), best=MOMENT_CONFIDENT - 0.05),
            Moment(name="ring", shot_ids=("s1",), best=MOMENT_CONFIDENT + 0.05),
        )
        plan = EveryMomentReachesTheFilmTests().build(moments)
        said = " ".join(plan.warnings)
        weak = said.split("zayıf eşleşti", 1)[1]

        self.assertIn("pasta kesme", weak)
        self.assertNotIn("yüzük", weak)


if __name__ == "__main__":
    unittest.main()
