"""The edit must follow the music: its structure, its beats and the reference pacing."""

import unittest
from fractions import Fraction
from itertools import pairwise
from pathlib import Path

import numpy as np
from sevenfilm.domain import BeatGrid, MediaAsset, Shot
from sevenfilm.services.analysis import _energy_sections
from sevenfilm.services.planner import (
    _duration_from_beats,
    _energy_at,
    _preferred_cut_seconds,
    beat_alignment_ratio,
    build_timeline,
)
from sevenfilm.timebase import FrameRate, TimeRange

# The measured signature of the 18 finished 7Film reference edits.
REFERENCE_PROFILE = {
    "reference_count": 18,
    "median_reference_bpm": 123.047,
    "median_shot_duration_seconds": 1.0,
    "shot_duration_p25_seconds": 0.64,
    "shot_duration_p75_seconds": 1.6,
    "section_median_shot_duration_seconds": {
        "intro": 1.17, "build": 1.13, "core": 0.99, "finale": 0.959,
    },
    "beat_alignment_ratio_120ms": 0.6064,
    "beat_alignment_ratio_200ms": 0.8043,
    "beats_per_cut": {"low": 3, "medium": 2, "high": 1},
    "visual_profile": {"mean_brightness": 0.3474, "mean_saturation": 0.2863},
}
SAMPLE_RATE = 22050


def tone(seconds, amplitude):
    time = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    return (amplitude * np.sin(2 * np.pi * 220 * time)).astype(np.float32)


class EnergyStructureTests(unittest.TestCase):
    """The energy curve must describe the song, not four arbitrary quarters of it."""

    def sections(self, samples, duration):
        return _energy_sections(samples, SAMPLE_RATE, Fraction(duration))

    def test_a_short_drop_is_found_where_it_actually_is(self):
        samples = np.concatenate([tone(40, .04), tone(10, .30), tone(10, .04)])

        sections = self.sections(samples, 60)

        high = [s for s in sections if s["energy"] == "high"]
        self.assertTrue(high, sections)
        start = min(float(Fraction(s["start"])) for s in high)
        end = max(float(Fraction(s["end"])) for s in high)
        # The drop runs 40-50s. Quarters used to mark everything from 30s to 60s as high.
        self.assertGreater(start, 35)
        self.assertLess(end, 55)

    def test_an_evenly_calm_track_gets_no_high_energy_section(self):
        sections = self.sections(tone(60, .04), 60)
        self.assertEqual({s["energy"] for s in sections}, {"medium"})

    def test_a_track_that_builds_reports_the_build_in_order(self):
        samples = np.concatenate([tone(20, .03), tone(20, .12), tone(20, .32)])

        energies = [s["energy"] for s in self.sections(samples, 60)]

        order = ["low", "medium", "high"]
        self.assertEqual(energies[0], "low")
        self.assertEqual(energies[-1], "high")
        # The build only ever rises: no section is calmer than the one before it.
        levels = [order.index(energy) for energy in energies]
        self.assertEqual(levels, sorted(levels), energies)

    def test_sections_are_contiguous_and_cover_the_whole_track(self):
        samples = np.concatenate([tone(20, .03), tone(10, .30), tone(30, .05)])

        sections = self.sections(samples, 60)

        self.assertEqual(Fraction(sections[0]["start"]), 0)
        self.assertEqual(Fraction(sections[-1]["end"]), 60)
        for previous, current in pairwise(sections):
            self.assertEqual(Fraction(previous["end"]), Fraction(current["start"]))

    def test_adjacent_windows_of_the_same_level_are_merged(self):
        sections = self.sections(tone(60, .04), 60)
        self.assertEqual(len(sections), 1)

    def test_a_chorus_is_found_even_though_its_average_sits_below_the_threshold(self):
        """The real defect: averaging a long window drags a chorus below "high" energy."""
        chorus = np.concatenate([tone(2, .30), tone(2, .10)] * 5)  # loud, but only half the time
        samples = np.concatenate([tone(40, .04), chorus, tone(40, .04)])

        sections = self.sections(samples, 100)

        self.assertIn("high", [s["energy"] for s in sections])

    def test_a_single_loud_bar_does_not_become_its_own_section(self):
        """One flickering window inside a passage must not change the cut pacing."""
        samples = np.concatenate([tone(28, .05), tone(2, .32), tone(30, .05)])

        sections = self.sections(samples, 60)

        self.assertNotIn("high", [s["energy"] for s in sections])

    def test_window_length_does_not_grow_with_the_track(self):
        """A four minute track must resolve structure as finely as a one minute one."""
        short = np.concatenate([tone(25, .04), tone(10, .30), tone(25, .04)])
        long = np.concatenate([tone(105, .04), tone(10, .30), tone(125, .04)])

        def high_span(sections):
            high = [s for s in sections if s["energy"] == "high"]
            return max(float(Fraction(s["end"])) - float(Fraction(s["start"])) for s in high)

        self.assertLess(high_span(self.sections(short, 60)), 25)
        self.assertLess(high_span(self.sections(long, 240)), 25)

    def test_silence_falls_back_to_one_neutral_section(self):
        sections = self.sections(np.zeros(SAMPLE_RATE * 10, dtype=np.float32), 10)
        self.assertEqual(sections, ({"start": "0", "end": "10", "energy": "medium"},))

    def test_every_second_of_the_track_resolves_to_an_energy(self):
        samples = np.concatenate([tone(20, .03), tone(10, .30), tone(30, .05)])
        grid = BeatGrid(bpm=120, beats=(), duration=Fraction(60),
                        sections=self.sections(samples, 60))

        for second in range(60):
            self.assertIn(_energy_at(grid, Fraction(second)), {"low", "medium", "high"})


class BeatSnappingTests(unittest.TestCase):
    """Cuts last a whole number of beats, which is what makes an edit feel cut to the music."""

    def setUp(self):
        self.interval = Fraction(60) / Fraction("123.047")  # ~0.4877s at the reference BPM
        self.grid = BeatGrid(
            bpm=123.047, duration=Fraction(180),
            beats=tuple(self.interval * step for step in range(370)),
            sections=({"start": "0", "end": "180", "energy": "medium"},),
        )

    def duration(self, energy, progress=0.5, grid=None, profile=REFERENCE_PROFILE):
        return _duration_from_beats(grid or self.grid, Fraction(0), energy, profile, progress)

    def test_the_cut_lasts_a_whole_number_of_beats(self):
        self.assertEqual(self.duration("medium") % self.interval, 0)

    def test_the_reference_pace_of_two_beats_is_kept(self):
        # median 1.0s over a 0.99s core section keeps the profile's medium pace of two beats.
        self.assertEqual(self.duration("medium"), self.interval * 2)

    def test_a_calm_passage_holds_longer_than_a_driving_one(self):
        self.assertGreater(self.duration("low"), self.duration("medium"))
        self.assertGreater(self.duration("medium"), self.duration("high"))

    def test_a_sparse_grid_takes_the_reference_length_instead_of_a_dead_hold(self):
        sparse = BeatGrid(
            bpm=12, beats=tuple(Fraction(step * 5) for step in range(40)),
            duration=Fraction(180), sections=(),
        )

        # Two beats would be a ten second hold; the references hold 0.99s here.
        self.assertEqual(self.duration("medium", grid=sparse), Fraction("0.99"))

    def test_a_beat_a_frame_away_is_not_treated_as_the_next_beat(self):
        """Rounding leaves the position just before a beat; asking for it gives a one frame cut."""
        just_before = self.interval - Fraction(1, 100)

        duration = _duration_from_beats(
            self.grid, just_before, "high", REFERENCE_PROFILE, progress=0.5
        )

        self.assertGreaterEqual(duration, Fraction(1, 4))

    def test_without_a_reference_profile_the_original_pacing_is_kept(self):
        self.assertEqual(self.duration("medium", profile=None), self.interval * 2)

    def test_the_pace_is_measured_in_beats_so_it_survives_a_tempo_change(self):
        for bpm in (80, 100, 123.047, 160):
            with self.subTest(bpm=bpm):
                interval = Fraction(60) / Fraction(str(bpm))
                grid = BeatGrid(
                    bpm=bpm, duration=Fraction(180),
                    beats=tuple(interval * step for step in range(600)), sections=(),
                )
                self.assertEqual(self.duration("medium", grid=grid), interval * 2)

    def test_pacing_follows_the_reference_section_the_edit_is_in(self):
        intro = _preferred_cut_seconds(REFERENCE_PROFILE, 0.05, "medium")
        finale = _preferred_cut_seconds(REFERENCE_PROFILE, 0.95, "medium")
        self.assertEqual(intro, Fraction("1.17"))
        self.assertEqual(finale, Fraction("0.959"))
        self.assertGreater(intro, finale, "the references tighten towards the end")

    def test_energy_scale_comes_from_the_measured_reference_spread(self):
        core = Fraction("0.99")
        self.assertEqual(
            _preferred_cut_seconds(REFERENCE_PROFILE, 0.5, "low"),
            core * Fraction("1.6") / Fraction("1.0"),
        )
        self.assertEqual(_preferred_cut_seconds(REFERENCE_PROFILE, 0.5, "medium"), core)


class MusicDrivenPlanTests(unittest.TestCase):
    """End to end: a finished plan measured the way a reference edit is measured."""

    def setUp(self):
        self.rate = FrameRate(25)
        interval = Fraction(60) / Fraction("123.047")
        self.grid = BeatGrid(
            bpm=123.047, duration=Fraction(200),
            beats=tuple(interval * step for step in range(int(Fraction(200) / interval) + 1)),
            sections=(
                {"start": "0", "end": "40", "energy": "low"},
                {"start": "40", "end": "120", "energy": "medium"},
                {"start": "120", "end": "150", "energy": "high"},
                {"start": "150", "end": "200", "energy": "medium"},
            ),
        )
        categories = ("venue", "detail", "bride", "groom", "couple", "family", "ceremony", "party")
        scales = ("wide", "medium", "close_up", "detail")
        self.assets, self.shots = [], []
        for index in range(300):
            asset = MediaAsset(
                id=f"a{index}", project_id="p", path=Path(f"/m/A{index:03}.mov"),
                name=f"A{index:03}.mov", duration=Fraction(20), frame_rate=self.rate,
                width=1920, height=1080,
            )
            self.assets.append(asset)
            self.shots.append(Shot(
                id=f"s{index}", asset_id=asset.id, source_range=TimeRange(0, 125, self.rate),
                category=categories[index % 8], shot_scale=scales[index % 4],
                technical_quality=.8, aesthetic_score=.8, motion_score=.2 + (index % 4) * .2,
                confidence=.7, brightness=.35, saturation=.29, highlight_clipping=.01,
            ))

    def plan(self, **overrides):
        arguments = {
            "project_id": "p", "assets": self.assets, "shots": self.shots, "music": self.grid,
            "frame_rate": self.rate, "target_duration": Fraction(150),
            "style_profile": REFERENCE_PROFILE, "seed": 7,
        }
        arguments.update(overrides)
        return build_timeline(**arguments)

    def test_the_plan_beats_the_reference_alignment_it_was_learned_from(self):
        plan = self.plan()

        aligned = beat_alignment_ratio(plan, self.grid)

        self.assertGreaterEqual(aligned, REFERENCE_PROFILE["beat_alignment_ratio_120ms"])
        self.assertGreater(aligned, 0.9, "beat snapping should align nearly every cut")

    def test_the_plan_reports_its_own_alignment_next_to_the_reference_figure(self):
        warnings = self.plan().warnings
        self.assertTrue(
            any("beat'e 120 ms içinde hizalandı" in warning for warning in warnings), warnings
        )
        self.assertTrue(any("referans kurgular" in warning for warning in warnings), warnings)

    def test_cuts_run_faster_in_the_high_energy_section_than_the_calm_opening(self):
        plan = self.plan()

        def median_duration(low, high):
            durations = sorted(
                item.timeline_range.duration_seconds for item in plan.items
                if low <= item.timeline_range.start_seconds < high
            )
            return durations[len(durations) // 2]

        calm = median_duration(Fraction(0), Fraction(40))
        driving = median_duration(Fraction(120), Fraction(150))
        self.assertGreater(calm, driving, "a calm opening must hold longer than the drop")

    def test_shot_lengths_stay_inside_the_reference_quartiles(self):
        plan = self.plan()

        durations = sorted(float(item.timeline_range.duration_seconds) for item in plan.items)
        p25 = durations[len(durations) // 4]
        p75 = durations[3 * len(durations) // 4]
        self.assertGreaterEqual(p25, REFERENCE_PROFILE["shot_duration_p25_seconds"] * 0.7)
        self.assertLessEqual(p75, REFERENCE_PROFILE["shot_duration_p75_seconds"] * 1.3)

    def test_no_cut_is_shorter_than_a_single_beat(self):
        plan = self.plan()
        beat = Fraction(60) / Fraction("123.047")
        shortest = min(item.timeline_range.duration_seconds for item in plan.items[:-1])
        self.assertGreaterEqual(shortest, beat * Fraction(9, 10))

    def test_a_slower_song_produces_a_slower_edit(self):
        slow_interval = Fraction(60) / Fraction(80)
        slow = BeatGrid(
            bpm=80, duration=Fraction(200),
            beats=tuple(slow_interval * step for step in range(int(Fraction(200) / slow_interval) + 1)),
            sections=({"start": "0", "end": "200", "energy": "medium"},),
        )
        fast_interval = Fraction(60) / Fraction(160)
        fast = BeatGrid(
            bpm=160, duration=Fraction(200),
            beats=tuple(fast_interval * step for step in range(int(Fraction(200) / fast_interval) + 1)),
            sections=({"start": "0", "end": "200", "energy": "medium"},),
        )

        self.assertLess(len(self.plan(music=slow).items), len(self.plan(music=fast).items))

    def test_the_edit_still_lands_on_the_target_duration(self):
        self.assertEqual(self.plan().duration, Fraction(150))

    def test_no_cut_is_a_single_frame_flash(self):
        """Shots running out of source used to contribute their last frame as a cut."""
        plan = self.plan()

        shortest = min(item.timeline_range.duration_seconds for item in plan.items)

        self.assertGreaterEqual(shortest, Fraction(1, 4))

    def test_a_cut_never_starts_a_frame_before_the_beat_it_was_cut_on(self):
        plan = self.plan()
        beat = Fraction(60) / Fraction("123.047")

        for item in plan.items[:-1]:
            self.assertGreaterEqual(item.timeline_range.duration_seconds, beat * Fraction(3, 4))


if __name__ == "__main__":
    unittest.main()
