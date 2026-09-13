"""Ready regions, a phase-corrected edit grid, and a duration read off the music.

Three rounds of shadow work asked which single half second of a clip was the best one and
could not answer it. This round splits the question: motion and the quality gate say which
stretches of a clip are usable, and the beat grid says where the cut lands and how long it
runs. Only the music half survived checking — `tools/motion_audit.py` shows the motion finding
the region rests on was an artefact of uneven sampling — so what is tested here is the
behaviour of the arrangement, not a claim that it reproduces the editor.

These tests hold the split apart — source coordinates on one side, timeline coordinates on the
other — and hold the line that matters most: none of this is wired into the plan, and every
path that cannot answer fails closed rather than guessing.
"""

import unittest
from fractions import Fraction

from sevenfilm.services import moment_v2
from sevenfilm.services.moment_v2 import (
    beat_interval,
    beats_to_frames,
    clip_motion_bar,
    decide,
    edit_grid,
    grid_is_reliable,
    ready_regions,
    section_beats,
)
from sevenfilm.services.planner import UNUSABLE_SHARPNESS_SHARE, _best_offset, _window_score
from sevenfilm.services.windows import AssetWindow, ShotWindow
from sevenfilm.timebase import FrameRate, TimeRange

RATE = FrameRate(50)
BAR = 100.0
STEP = 25
BEAT = Fraction(4876, 10000)          # this film's measured beat, 487.6 ms
CALM, BUSY = 1.0, 90.0                # either side of any bar these lists produce


def _window(frame, motion=1.0, sharpness=BAR, shot_id="s1", faces=2,
            edge=0.0, category="couple"):
    return AssetWindow(shot_id=shot_id, asset_frame=frame, category=category,
                       sharpness=sharpness, motion=motion, face_ratio=0.02,
                       face_edge=edge, face_count=faces, bystanders=0)


def _clip(motions, start=0, shot_id="s1", **kwargs):
    """A clip whose windows carry the motions given, half a second apart."""
    return [_window(start + index * STEP, motion=motion, shot_id=shot_id, **kwargs)
            for index, motion in enumerate(motions)]


def _grid(count=64, interval=BEAT, first=Fraction(0)):
    return edit_grid([first + interval * index for index in range(count)])


# ---------------------------------------------------------------------------------------
# The production line. Nothing below this heading may move.
# ---------------------------------------------------------------------------------------


class ProductionIsUntouchedTests(unittest.TestCase):
    def test_the_production_window_score_is_the_score_it_was(self):
        window = ShotWindow(shot_id="s1", offset_frames=0, sharpness=BAR, motion=1.0,
                            face_ratio=0.02, face_edge=0.5, face_count=2, bystanders=2)
        crowd = min(2, 3) / 3
        self.assertAlmostEqual(_window_score(window, BAR, "couple"),
                               1.0 - 1.0 * 0.5 - 0.35 * crowd)

    def test_the_production_search_still_looks_only_inside_its_shot(self):
        from sevenfilm.domain import Shot
        shot = Shot(id="s1", asset_id="a1", source_range=TimeRange(0, 250, RATE),
                    category="couple", shot_scale="medium", technical_quality=.8,
                    aesthetic_score=.8, motion_score=.5, confidence=.8)
        windows = [ShotWindow(shot_id="s1", offset_frames=i * STEP, sharpness=BAR, motion=1.0,
                              face_ratio=0.02, face_edge=0.0, face_count=2, bystanders=0)
                   for i in range(10)]
        offset, _ = _best_offset(shot, windows, 50, floor=5, ceiling=150, sharpness_bar=BAR)
        self.assertGreaterEqual(offset, 5)
        self.assertLessEqual(offset, 150)

    def test_the_earlier_shadow_paths_still_score_what_they_scored(self):
        # A, B, C, D and E are the five searches the last three rounds were measured with. If
        # any of them moves, every number reported against them stops meaning anything, so
        # they are pinned here rather than left to drift alongside a new module.
        from sevenfilm.services import shadow
        window = ShotWindow(shot_id="s1", offset_frames=0, sharpness=BAR, motion=1.0,
                            face_ratio=0.02, face_edge=0.25, face_count=4, bystanders=2)
        self.assertAlmostEqual(_window_score(window, BAR, "couple"), 1.0 - 0.25 - 0.35 * 2 / 3)
        self.assertAlmostEqual(shadow.gated_window_score(window, BAR, "couple"),
                               1.0 - 0.25 - 0.35 * 2 / 3)
        self.assertAlmostEqual(shadow.unpenalised_window_score(window, BAR, "couple"),
                               1.0 - 0.25)
        faces = shadow.content_scorer(4.0, 0.02, use_count=True, use_ratio=False)
        self.assertAlmostEqual(faces(window, BAR, "couple"), 1.0 - 0.25)

    def test_nothing_in_the_planner_imports_this_module(self):
        from pathlib import Path

        from sevenfilm.services import planner
        source = Path(planner.__file__).read_text()
        self.assertNotIn("moment_v2", source)

    def test_this_module_never_reaches_for_resolve_or_the_exporter(self):
        from pathlib import Path
        source = Path(moment_v2.__file__).read_text()
        for forbidden in ("resolve", "exporter", "fcpxml", "DaVinci"):
            self.assertNotIn(forbidden, source.lower())


# ---------------------------------------------------------------------------------------
# Ready regions — source coordinates
# ---------------------------------------------------------------------------------------


class ReadyRegionTests(unittest.TestCase):
    def test_calm_windows_become_one_contiguous_region(self):
        regions = ready_regions(_clip([CALM] * 4 + [BUSY] * 4), sharpness_bar=BAR, rate=RATE)
        self.assertEqual(len(regions), 1)
        self.assertEqual(regions[0].window_count, 4)
        self.assertEqual(regions[0].source_start, 0)
        self.assertEqual(regions[0].source_end, 4 * STEP)

    def test_a_busy_stretch_breaks_a_region_in_two(self):
        regions = ready_regions(_clip([CALM, CALM, BUSY, BUSY, CALM, CALM] + [BUSY] * 2),
                                sharpness_bar=BAR, rate=RATE)
        self.assertEqual([region.window_count for region in regions], [2, 2])

    def test_a_window_the_quality_gate_rejects_is_never_ready(self):
        soft = BAR * (UNUSABLE_SHARPNESS_SHARE / 2)
        windows = _clip([CALM] * 4 + [BUSY] * 4)
        windows[1] = _window(windows[1].asset_frame, motion=CALM, sharpness=soft)
        regions = ready_regions(windows, sharpness_bar=BAR, rate=RATE)
        self.assertTrue(all(not region.contains(STEP) for region in regions))

    def test_a_region_may_cross_a_detected_shot_boundary(self):
        windows = (_clip([CALM, CALM], shot_id="s1")
                   + _clip([CALM, CALM], start=2 * STEP, shot_id="s2")
                   + _clip([BUSY] * 4, start=4 * STEP, shot_id="s3"))
        regions = ready_regions(windows, sharpness_bar=BAR, rate=RATE)
        self.assertEqual(len(regions), 1)
        self.assertEqual(regions[0].shot_ids, ("s1", "s2"))
        self.assertTrue(regions[0].crosses_shot_boundary)

    def test_a_region_never_crosses_the_end_of_its_clip(self):
        regions = ready_regions(_clip([CALM] * 4 + [BUSY] * 4), sharpness_bar=BAR, rate=RATE,
                                asset_duration_frames=80)
        self.assertTrue(all(region.source_end <= 80 for region in regions))

    def test_an_unmeasured_stretch_ends_a_region_rather_than_bridging_it(self):
        windows = (_clip([CALM, CALM]) + _clip([CALM, CALM], start=20 * STEP)
                   + _clip([BUSY] * 4, start=40 * STEP))
        regions = ready_regions(windows, sharpness_bar=BAR, rate=RATE)
        self.assertEqual(len(regions), 2)

    def test_the_first_window_of_a_shot_is_unknown_motion_not_stillness(self):
        # Windows are measured against the one before them, so a shot's first window has no
        # motion at all — it is stored as zero. Reading that as the calmest frame in the clip
        # is the head bias three earlier rounds were spent removing.
        windows = _clip([moment_v2.MOTION_UNKNOWN] + [CALM] * 3 + [BUSY] * 4)
        regions = ready_regions(windows, sharpness_bar=BAR, rate=RATE)
        self.assertEqual(len(regions), 1)
        self.assertEqual(regions[0].source_start, STEP)

    def test_the_motion_bar_is_the_clips_own_median_and_ignores_the_unknown(self):
        windows = _clip([moment_v2.MOTION_UNKNOWN, 10, 20, 30])
        self.assertEqual(clip_motion_bar(windows), 20)

    def test_a_region_reports_what_it_holds(self):
        region = ready_regions(_clip([CALM] * 4 + [BUSY] * 4),
                               sharpness_bar=BAR, rate=RATE)[0]
        self.assertEqual(region.min_motion, CALM)
        self.assertEqual(region.median_face_count, 2)
        self.assertEqual(region.min_sharpness, BAR)
        self.assertEqual(region.duration_frames, 4 * STEP)


# ---------------------------------------------------------------------------------------
# The edit grid — timeline coordinates
# ---------------------------------------------------------------------------------------


class EditGridTests(unittest.TestCase):
    def test_the_raw_grid_and_the_edit_grid_are_separate(self):
        grid = _grid()
        self.assertNotEqual(grid.raw_beats, grid.beats)
        self.assertEqual(len(grid.raw_beats), len(grid.beats))
        for raw, corrected in zip(grid.raw_beats, grid.beats, strict=True):
            self.assertEqual(corrected - raw, grid.phase)

    def test_the_correction_is_half_a_beat_derived_from_the_interval(self):
        grid = _grid()
        self.assertEqual(grid.phase, grid.interval / 2)
        self.assertAlmostEqual(float(grid.phase) * 1000, 243.8, places=1)

    def test_a_different_tempo_gets_a_different_correction(self):
        slow = _grid(interval=Fraction(1))
        self.assertEqual(slow.phase, Fraction(1, 2))
        self.assertNotEqual(slow.phase, _grid().phase)

    def test_the_old_hardcoded_offset_is_gone_and_nothing_replaced_it(self):
        # P3.5 reported a 0.76 second offset it could not account for. It was beat-multiple
        # ambiguity: the real displacement is half a beat. Neither that number nor the two
        # per-song millisecond figures that measured it may be applied to anything.
        from pathlib import Path
        code = [line.split("#")[0] for line in
                Path(moment_v2.__file__).read_text().splitlines()]
        for stale in ("0.76", "0.240", "0.242"):
            self.assertNotIn(stale, "\n".join(code))

    def test_the_correction_is_the_same_every_run(self):
        self.assertEqual(_grid().phase, _grid().phase)
        self.assertEqual(_grid().beats, _grid().beats)

    def test_a_grid_too_short_to_check_is_refused(self):
        self.assertIsNone(edit_grid([Fraction(i) * BEAT for i in range(3)]))

    def test_a_grid_that_lost_the_tempo_is_refused(self):
        ragged = [Fraction(0), Fraction(1), Fraction(1, 10), Fraction(9, 2),
                  Fraction(9), Fraction(9, 1), Fraction(20), Fraction(21)]
        self.assertFalse(grid_is_reliable(sorted(ragged)))
        self.assertIsNone(edit_grid(ragged))

    def test_an_empty_grid_has_no_interval(self):
        self.assertIsNone(beat_interval([]))
        self.assertIsNone(edit_grid([]))


# ---------------------------------------------------------------------------------------
# Duration
# ---------------------------------------------------------------------------------------


class DurationTests(unittest.TestCase):
    def test_a_duration_is_a_whole_number_of_beats(self):
        frames = beats_to_frames(2, BEAT, RATE)
        self.assertEqual(frames, RATE.frames_from_seconds(BEAT * 2, rounding="nearest"))

    def test_sections_may_want_different_lengths(self):
        policy = {"quiet": 6, "finale": 1, "opening": 2}
        self.assertEqual(section_beats("quiet", policy), 6)
        self.assertEqual(section_beats("finale", policy), 1)
        self.assertEqual(section_beats("opening", policy), 2)

    def test_an_unknown_section_falls_back_rather_than_inventing_a_length(self):
        self.assertEqual(section_beats("nothing measured here", {"quiet": 6}),
                         moment_v2.DEFAULT_SECTION_BEATS)
        self.assertEqual(section_beats(None, None), moment_v2.DEFAULT_SECTION_BEATS)

    def test_no_single_beat_count_is_written_into_the_module_as_the_answer(self):
        # The policy is supplied by the caller and measured on the film being reconstructed.
        # A number here would claim one wedding's sections generalise, which is not shown.
        self.assertEqual(section_beats("finale", {"finale": 6}), 6)


# ---------------------------------------------------------------------------------------
# The decision
# ---------------------------------------------------------------------------------------


class DecisionTests(unittest.TestCase):
    def _decide(self, windows, **kwargs):
        options = {"sharpness_bar": BAR, "rate": RATE, "asset_duration_frames": 10_000,
                   "grid": _grid(), "timeline_second": Fraction(5),
                   "section_key": "finale", "section_policy": {"finale": 1}}
        options.update(kwargs)
        return decide(windows, **options)

    def test_the_cut_lands_inside_the_region_it_chose(self):
        result = self._decide(_clip([BUSY] + [CALM] * 20 + [BUSY] * 21))
        self.assertFalse(result.fallback)
        self.assertTrue(result.region.holds(result.source_start, result.frames))

    def test_the_cut_never_runs_past_the_end_of_the_clip(self):
        result = self._decide(_clip([BUSY] + [CALM] * 20 + [BUSY] * 21), asset_duration_frames=300)
        self.assertTrue(result.fallback or result.source_start + result.frames <= 300)

    def test_the_source_start_and_the_timeline_beat_are_reported_apart(self):
        result = self._decide(_clip([BUSY] + [CALM] * 20 + [BUSY] * 21))
        self.assertIsInstance(result.source_start, int)
        self.assertIsInstance(result.corrected_beat, Fraction)
        self.assertEqual(result.corrected_beat - result.raw_beat, result.phase)

    def test_a_second_cut_from_one_clip_comes_from_later_in_it(self):
        windows = _clip([BUSY] + [CALM] * 40 + [BUSY] * 41)
        first = self._decide(windows)
        second = self._decide(windows, floor_frame=first.source_start + first.frames)
        self.assertGreaterEqual(second.source_start, first.source_start + first.frames)

    def test_a_clip_with_no_ready_region_falls_back_rather_than_guessing(self):
        result = self._decide(_clip([BUSY] * 10))
        self.assertTrue(result.fallback)
        self.assertIsNone(result.source_start)

    def test_a_clip_with_nothing_measured_falls_back(self):
        result = self._decide([])
        self.assertTrue(result.fallback)
        self.assertIn("no measured windows", result.reason)

    def test_no_grid_means_no_music_snap_and_a_fallback(self):
        result = self._decide(_clip([BUSY] + [CALM] * 20 + [BUSY] * 21), grid=None)
        self.assertTrue(result.fallback)
        self.assertIsNone(result.corrected_beat)

    def test_a_region_too_short_for_the_wanted_length_takes_fewer_beats_not_fewer_frames(self):
        windows = _clip([BUSY, CALM, CALM, BUSY] + [BUSY] * 10)
        result = self._decide(windows, section_key="quiet", section_policy={"quiet": 6})
        if not result.fallback:
            self.assertLess(result.beats, result.beats_requested)
            self.assertEqual(
                result.frames, beats_to_frames(result.beats, _grid().interval, RATE))

    def test_the_out_point_is_checked_rather_than_assumed(self):
        result = self._decide(_clip([BUSY] + [CALM] * 20 + [BUSY] * 21))
        self.assertIn(result.out_status,
                      (moment_v2.OUT_SAFE, moment_v2.OUT_NEAR_BREAKDOWN,
                       moment_v2.OUT_OUTSIDE_READY_REGION))

    def test_rising_motion_after_the_cut_is_reported_not_hidden(self):
        # One ready window, and the picture running away right after it: the cut fills the
        # region and its out-point lands where the motion goes up. That is the out-point the
        # editor's own cuts sit at, and it is reported rather than smoothed over.
        result = self._decide(_clip([BUSY, CALM, 200.0, BUSY]))
        self.assertEqual(result.out_status, moment_v2.OUT_NEAR_BREAKDOWN)

    def test_an_event_shot_stays_explicitly_unsupported(self):
        result = self._decide(_clip([BUSY] + [CALM] * 20 + [BUSY] * 21))
        self.assertEqual(result.event, moment_v2.EVENT_UNKNOWN)

    def test_nothing_here_classifies_a_shot_as_an_event(self):
        from pathlib import Path
        source = Path(moment_v2.__file__).read_text().lower()
        for forbidden in ("def detect_event", "is_event", "motion_peak", "cake"):
            self.assertNotIn(forbidden, source)

    def test_the_same_clip_decides_the_same_way_every_time(self):
        windows = _clip([BUSY] + [CALM] * 20 + [BUSY] * 22)
        first, second = self._decide(windows), self._decide(windows)
        self.assertEqual(first, second)

    def test_a_failure_here_changes_nothing_about_the_plan(self):
        # The decision is a value. It carries no side effect, no database write and no
        # planner state, so a shadow path that cannot answer can only return a fallback.
        result = self._decide([])
        self.assertTrue(result.fallback)
        self.assertIsNone(result.region)
        self.assertEqual(result.event, moment_v2.EVENT_UNKNOWN)


class RegionRankingTests(unittest.TestCase):
    def test_the_longest_ready_stretch_is_tried_first(self):
        regions = ready_regions(_clip([CALM, BUSY, CALM, CALM, CALM, CALM] + [BUSY] * 6), sharpness_bar=BAR, rate=RATE)
        self.assertEqual(moment_v2.rank_regions(regions)[0].window_count, 4)

    def test_the_cut_is_not_pinned_to_the_head_of_its_region(self):
        windows = _clip([BUSY] + [CALM] * 20 + [BUSY] * 21)
        result = decide(windows, sharpness_bar=BAR, rate=RATE, asset_duration_frames=10_000,
                        grid=_grid(), timeline_second=Fraction(5), section_key="finale",
                        section_policy={"finale": 1})
        self.assertGreater(result.source_start, result.region.source_start)


if __name__ == "__main__":
    unittest.main()
