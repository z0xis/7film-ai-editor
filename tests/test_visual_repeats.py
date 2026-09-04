"""Near-identical shots must not land next to each other, whatever file they came from."""

import hashlib
import unittest
from fractions import Fraction
from pathlib import Path

from sevenfilm.domain import BeatGrid, MediaAsset, Shot, TimelineItem
from sevenfilm.services.planner import (
    DUPLICATE_PENALTY,
    NEAR_DUPLICATE_BITS,
    _perceptual_hash,
    _visual_repeat_penalty,
    build_timeline,
)
from sevenfilm.timebase import FrameRate, TimeRange

RATE = FrameRate(25)


def digest(value: int) -> str:
    return f"visual:{value:016x}"


def spread(index: int) -> str:
    """A hash unlike any other in the set: shifting an index leaves them a few bits apart."""
    return f"visual:{hashlib.sha256(str(index).encode()).hexdigest()[:16]}"


def item(shot):
    return TimelineItem(
        id="i", shot=shot, asset=MediaAsset(
            id=shot.asset_id, project_id="p", path=Path("/m/x.mov"), name="x.mov",
            duration=Fraction(20), frame_rate=RATE, width=1920, height=1080),
        source_range=TimeRange(0, 50, RATE), timeline_range=TimeRange(0, 50, RATE),
        score=.8, selection_reason="r")


def used(*shots):
    """What the edit remembers: the hash of every shot already in it."""
    return [h for h in (_perceptual_hash(one) for one in shots) if h is not None]


def shot(shot_id, group, asset_id="a"):
    return Shot(
        id=shot_id, asset_id=asset_id, source_range=TimeRange(0, 500, RATE),
        category="couple", shot_scale="medium", technical_quality=.8, aesthetic_score=.8,
        motion_score=.5, confidence=.7, duplicate_group=group,
        brightness=.36, saturation=.15, highlight_clipping=.01)


class PerceptualHashTests(unittest.TestCase):
    def test_the_hash_is_read_out_of_the_duplicate_group(self):
        self.assertEqual(_perceptual_hash(shot("s", digest(0xDEADBEEF))), 0xDEADBEEF)

    def test_anything_else_is_no_hash_at_all(self):
        for group in (None, "", "visual:", "visual:zzz", "other:abc", "abcdef"):
            self.assertIsNone(_perceptual_hash(shot("s", group)), repr(group))


class VisualRepeatPenaltyTests(unittest.TestCase):
    def test_the_same_frame_again_costs_the_full_penalty(self):
        already = used(shot("a", digest(0xFF00FF00FF00FF00)))

        penalty = _visual_repeat_penalty(shot("b", digest(0xFF00FF00FF00FF00)), already)

        self.assertAlmostEqual(penalty, DUPLICATE_PENALTY)

    def test_a_single_bit_apart_is_still_caught(self):
        """Exact equality was the old test, and a 64 bit hash never repeats exactly."""
        already = used(shot("a", digest(0xFF00FF00FF00FF00)))

        penalty = _visual_repeat_penalty(shot("b", digest(0xFF00FF00FF00FF01)), already)

        self.assertGreater(penalty, DUPLICATE_PENALTY * 0.8)

    def test_a_different_shot_costs_nothing(self):
        already = used(shot("a", digest(0)))
        far = digest((1 << NEAR_DUPLICATE_BITS) - 1)  # exactly the threshold apart

        self.assertEqual(_visual_repeat_penalty(shot("b", far), already), 0.0)

    def test_the_penalty_fades_with_distance(self):
        already = used(shot("a", digest(0)))
        readings = [
            _visual_repeat_penalty(shot("b", digest((1 << bits) - 1)), already)
            for bits in range(NEAR_DUPLICATE_BITS + 1)
        ]

        self.assertEqual(readings, sorted(readings, reverse=True))
        self.assertEqual(readings[-1], 0.0)

    def test_the_closest_of_everything_already_used_decides(self):
        already = used(shot("a", digest(0xFFFFFFFFFFFFFFFF)), shot("b", digest(0)))

        self.assertAlmostEqual(_visual_repeat_penalty(shot("c", digest(0)), already), DUPLICATE_PENALTY)

    def test_a_repeat_far_back_in_the_edit_still_costs(self):
        """A neon sign came back four times, every repeat just outside a four cut window."""
        already = used(*[shot(f"s{i}", spread(i)) for i in range(40)],
                       shot("sign", digest(0xABCDEF0123456789)),
                       *[shot(f"t{i}", spread(100 + i)) for i in range(30)])

        penalty = _visual_repeat_penalty(shot("again", digest(0xABCDEF0123456789)), already)

        self.assertAlmostEqual(penalty, DUPLICATE_PENALTY)

    def test_shots_with_no_hash_are_not_penalised(self):
        self.assertEqual(_visual_repeat_penalty(shot("b", None), used(shot("a", digest(0)))), 0.0)
        self.assertEqual(_visual_repeat_penalty(shot("b", digest(0)), used(shot("a", None))), 0.0)
        self.assertEqual(_visual_repeat_penalty(shot("b", digest(0)), []), 0.0)


class PlanAvoidsVisualRepeatsTests(unittest.TestCase):
    """The case the same-asset penalty cannot see: near-identical takes in different files."""

    def setUp(self):
        interval = Fraction(60) / Fraction(120)
        self.music = BeatGrid(
            bpm=120, duration=Fraction(200),
            beats=tuple(interval * step for step in range(401)),
            sections=({"start": "0", "end": "200", "energy": "medium"},))

    def test_near_identical_takes_from_different_files_are_kept_apart(self):
        # More shots than the edit needs cuts, as on the real project: 1405 for 141.
        assets, shots = [], []
        for index in range(200):
            assets.append(MediaAsset(
                id=f"a{index}", project_id="p", path=Path(f"/m/A{index}.mov"), name=f"A{index}.mov",
                duration=Fraction(20), frame_rate=RATE, width=1920, height=1080))
            # Every third shot is another take of the same moment, in its own file. Two takes
            # never hash identically, which is why exact equality caught none of them.
            group = (digest(0xABCDEF0123456789 ^ (1 << (index % 5)))
                     if index % 3 == 0 else spread(index))
            shots.append(shot(f"s{index}", group, asset_id=f"a{index}"))

        plan = build_timeline(project_id="p", assets=assets, shots=shots, music=self.music,
                              frame_rate=RATE, target_duration=Fraction(120), seed=5)

        hashes = [_perceptual_hash(entry.shot) for entry in plan.items]
        adjacent = [
            (hashes[i] ^ hashes[i + 1]).bit_count()
            for i in range(len(hashes) - 1)
            if hashes[i] is not None and hashes[i + 1] is not None
        ]
        self.assertTrue(adjacent)
        # No two takes hash the same, so nothing here is caught by comparing hashes for equality.
        self.assertNotIn(0, adjacent)
        self.assertGreaterEqual(min(adjacent), NEAR_DUPLICATE_BITS, "a repeat landed next to itself")

    def test_with_nothing_else_left_the_edit_is_still_finished(self):
        """Scarce material: the penalty ranks repeats last, it does not refuse to use them."""
        assets = [MediaAsset(id=f"a{i}", project_id="p", path=Path(f"/m/A{i}.mov"), name=f"A{i}.mov",
                             duration=Fraction(20), frame_rate=RATE, width=1920, height=1080)
                  for i in range(60)]
        shots = [
            shot(f"s{i}", digest(0xABCDEF0123456789 ^ (1 << (i % 5))) if i % 3 == 0 else spread(i),
                 asset_id=f"a{i}")
            for i in range(60)
        ]

        plan = build_timeline(project_id="p", assets=assets, shots=shots, music=self.music,
                              frame_rate=RATE, target_duration=Fraction(120), seed=5)

        self.assertEqual(plan.duration, Fraction(120))

    def test_the_plan_still_reaches_its_target(self):
        assets = [MediaAsset(id=f"a{i}", project_id="p", path=Path(f"/m/A{i}.mov"), name=f"A{i}.mov",
                             duration=Fraction(20), frame_rate=RATE, width=1920, height=1080)
                  for i in range(60)]
        shots = [shot(f"s{i}", digest(0xABCDEF0123456789), asset_id=f"a{i}") for i in range(60)]

        # Every shot looks the same: the penalty must not be able to stall the edit.
        plan = build_timeline(project_id="p", assets=assets, shots=shots, music=self.music,
                              frame_rate=RATE, target_duration=Fraction(120), seed=5)

        self.assertEqual(plan.duration, Fraction(120))


if __name__ == "__main__":
    unittest.main()


class AssetReuseTests(unittest.TestCase):
    """One long take must not supply a sixth of the edit just because it detected many shots."""

    def build(self, target=Fraction(120)):
        assets, shots = [], []
        # One 400 second file cut into 120 shots, and 120 ordinary files with one shot each.
        long_asset = MediaAsset(id="long", project_id="p", path=Path("/m/long.mov"),
                                name="long.mov", duration=Fraction(400), frame_rate=RATE,
                                width=1920, height=1080)
        assets.append(long_asset)
        for index in range(120):
            shots.append(Shot(
                id=f"long-{index}", asset_id="long",
                source_range=TimeRange(index * 80, 80, RATE), category="couple",
                shot_scale="medium", technical_quality=.9, aesthetic_score=.9, motion_score=.5,
                confidence=.9, duplicate_group=spread(index), brightness=.36, saturation=.15,
                highlight_clipping=.01))
        for index in range(120):
            asset = MediaAsset(id=f"a{index}", project_id="p", path=Path(f"/m/{index}.mov"),
                               name=f"{index}.mov", duration=Fraction(20), frame_rate=RATE,
                               width=1920, height=1080)
            assets.append(asset)
            shots.append(Shot(
                id=f"s{index}", asset_id=asset.id, source_range=TimeRange(0, 400, RATE),
                category="couple", shot_scale="medium", technical_quality=.85,
                aesthetic_score=.85, motion_score=.5, confidence=.85,
                duplicate_group=spread(1000 + index), brightness=.36, saturation=.15,
                highlight_clipping=.01))
        beats = tuple(Fraction(i, 2) for i in range(600))
        music = BeatGrid(bpm=120, beats=beats, duration=Fraction(300),
                         sections=({"energy": "medium", "start": "0", "end": "300"},))
        return build_timeline(project_id="p", assets=assets, shots=shots, music=music,
                              frame_rate=RATE, target_duration=target, seed=1)

    def test_the_long_take_does_not_dominate_the_edit(self):
        plan = self.build()
        from_long = sum(1 for item in plan.items if item.asset.id == "long")

        # It is the highest scoring footage in the set, so it should appear — but not run away
        # with the edit the way an uncounted file did with sixteen of 137 clips.
        self.assertLessEqual(from_long, len(plan.items) // 4)

    def test_the_edit_still_reaches_its_target(self):
        plan = self.build()

        self.assertGreaterEqual(float(plan.duration), 119.9)

    def test_most_of_the_edit_comes_from_different_files(self):
        plan = self.build()
        files = {item.asset.id for item in plan.items}

        self.assertGreaterEqual(len(files), len(plan.items) * 3 // 4)
