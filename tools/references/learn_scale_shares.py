"""Read the shot scale mix out of the reference films and write it into the style profile.

The scale preference table in the planner was doing nothing for most of the film: between 15%
and 75% of the running time it lists all four scales, and the score only asks whether a scale
is in the list. So the edit inherited the shoot's own mix rather than the editor's.

Measured across the 18 reference films, 1109 cuts: they are 60.0% wide and 38.6% medium. One
edit of this shoot came out 26.4% wide and 68.8% medium, while the shoot itself holds 34%
wide — the wides were there and were not being reached for.

This is a number to learn, not to write down, so it is read off the films and stored beside
the tempo and story-arc figures the profile already carries. Re-run it whenever the reference
set changes.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))

import cv2  # type: ignore[import-not-found]
from sevenfilm.services.vision import SCALE_PROMPTS, VisionClassifier

ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / "data" / "references" / "media"
PROFILE = ROOT / "data" / "references" / "7film-style-profile.json"
FFMPEG = ROOT / ".runtime" / "mamba-root" / "envs" / "sevenfilm" / "bin" / "ffmpeg"
# Where one shot ends and the next begins, as ffmpeg scores it. Read off this reference set:
# 0.30 finds 1109 cuts across 18 films against the 1219 the profile counted by other means.
SCENE_THRESHOLD = 0.30
# A cut is judged on the frame just after it, which is the framing the editor chose.
MAX_FRAMES = 200


def _cut_frames(film: Path, into: Path) -> list:
    into.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(FFMPEG), "-v", "quiet", "-i", str(film),
            "-vf", f"select='gt(scene,{SCENE_THRESHOLD})',scale=336:-2",
            "-fps_mode", "vfr", "-frames:v", str(MAX_FRAMES),
            str(into / "%04d.png"),
        ],
        check=True,
    )
    frames = [cv2.imread(str(path)) for path in sorted(into.glob("*.png"))]
    return [frame for frame in frames if frame is not None]


def learn(media: Path) -> tuple[dict[str, float], int, int]:
    """The share of each shot scale across every reference film."""
    vision = VisionClassifier()
    scales = list(SCALE_PROMPTS)
    counted: Counter[str] = Counter()
    films = 0
    with tempfile.TemporaryDirectory() as work:
        for film in sorted(media.glob("*.mkv")):
            frames = _cut_frames(film, Path(work) / film.stem)
            if len(frames) < 5:
                print(f"  {film.stem}: atlandı, {len(frames)} kare")
                continue
            features = vision.encode(frames)
            if features is None:
                raise SystemExit("CLIP yüklenemedi; HF_HOME doğru mu?")
            _, scale_probabilities, _ = vision._probabilities(features)
            counted.update(scales[index] for index in scale_probabilities.argmax(axis=1))
            films += 1
            print(f"  {film.stem}: {len(frames)} kesim")
    total = sum(counted.values())
    if not total:
        raise SystemExit("Referans filmlerden kesim çıkmadı.")
    return {name: round(counted[name] / total, 4) for name in scales}, films, total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--media", type=Path, default=MEDIA)
    parser.add_argument("--profile", type=Path, default=PROFILE)
    parser.add_argument(
        "--dry-run", action="store_true", help="Ölç ve yaz, profili değiştirme.")
    args = parser.parse_args()

    shares, films, cuts = learn(args.media)
    print(f"\n{films} film · {cuts} kesim")
    for name, share in sorted(shares.items(), key=lambda pair: -pair[1]):
        print(f"  {name:10} %{share * 100:.1f}")
    if args.dry_run:
        return
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    profile["scale_shares"] = shares
    profile["scale_shares_source"] = {"films": films, "cuts": cuts}
    args.profile.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n{args.profile} güncellendi.")


if __name__ == "__main__":
    main()
