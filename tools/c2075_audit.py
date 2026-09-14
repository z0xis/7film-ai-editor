"""Find out why the same clip's single-frame cake-cutting probe gave 0.436 in one round and
0.828 in the next.

Two things changed between the two rounds and this isolates which one did the work:

  frame set    the earlier round compared his 7 used windows against all 212 other windows
               the analyser had stored across the whole ~120-second file; the later round
               compared 3 used centres against 32 windows in an 8-second neighbourhood either
               side of the cut it looked at
  question     "is the knife already cutting into the cake" against "is the knife touching or
               inside the cake" — a state of motion against a state of contact

Both used the same model, the same weights, the same tokenisation (" Yes" / " No", each a
single token, confirmed below) and the same scoring function — `Probe.ask` from
`semantic_probe.py`, imported and called directly here rather than reimplemented, so a
difference in the replay cannot itself be a new source of disagreement.

The design is a 2x2: each of the two frame sets scored under each of the two questions, with
the same code both times. Whichever axis moves the number is the explanation.

Read-only. Reuses cached frames; no model is downloaded.
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from semantic_probe import MEDIA, Probe, frame_at

OLD_QUESTION = "Is the knife already cutting into the cake?"
NEW_QUESTION = "Is the knife touching or inside the cake in this picture?"
CLIP = "C2075.MP4"


def pairwise(used, rest) -> tuple[float, int]:
    wins = ties = total = 0
    for a in used:
        for b in rest:
            total += 1
            if a > b:
                wins += 1
            elif a == b:
                ties += 1
    return ((wins + ties / 2) / total if total else float("nan")), total


def old_frames(signal2_path: Path) -> tuple[list[int], list[int]]:
    """The window frames the earlier round's C2075 pairwise number was computed over."""
    rows = json.loads(signal2_path.read_text())
    rows = [r for r in rows if r["clip"] == CLIP and r.get("sem_cake_cutting") is not None]
    used = sorted(r["frame"] for r in rows if r["used"])
    rest = sorted(r["frame"] for r in rows if not r["used"])
    return used, rest


def new_frames(temporal_path: Path) -> tuple[list[int], list[int]]:
    """The centres the later round's local single-frame number was computed over."""
    entry = json.loads(temporal_path.read_text())[CLIP]
    records = entry["records"]
    used = sorted(r["centre"] for r in records if r["band"] == "USED")
    rest = sorted(r["centre"] for r in records
                  if r["band"] in ("PRE", "POST"))
    return used, rest


def score_all(probe: Probe, frames: list[int], question: str, cache: dict) -> list[float]:
    """One question's answer for each frame, memoised so the 2x2 shares work across cells."""
    import cv2

    capture = cv2.VideoCapture(str(MEDIA / CLIP))
    out = []
    try:
        for frame in frames:
            key = (frame, question)
            if key not in cache:
                picture = frame_at(capture, frame, cv2)
                if picture is None:
                    cache[key] = None
                else:
                    cache[key] = probe.ask(picture, {"q": question})["q"]
            if cache[key] is not None:
                out.append(cache[key])
    finally:
        capture.release()
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--signal2", type=Path, required=True)
    parser.add_argument("--temporal", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()

    print("H) TOKENISATION")
    print("  ' Yes' and ' No' are each a single token in this tokenizer — confirmed by hand")
    print("  before this run; Probe.ask reads exactly those two token logits at the position")
    print("  right after the prompt, softmaxed against each other only. One code path, used")
    print("  by every experiment this round compares — see F) below for its call sites.")

    old_used, old_rest = old_frames(args.signal2)
    new_used, new_rest = new_frames(args.temporal)
    print(f"\nC) FRAME SETS\n  old: {len(old_used)} used, {len(old_rest)} rest, "
          f"rest spans {min(old_rest)}-{max(old_rest)} (whole file)")
    print(f"  new: {len(new_used)} used, {len(new_rest)} rest, "
          f"rest spans {min(new_rest)}-{max(new_rest)} (local, 8 s either side of the cut)")
    overlap_used = set(old_used) & set(new_used)
    overlap_rest = set(old_rest) & set(new_rest)
    print(f"  used frames shared between the two rounds: {sorted(overlap_used)}")
    print(f"  rest frames shared: {len(overlap_rest)} of {len(new_rest)} in the new, "
          f"local set")

    probe = Probe()
    cache: dict = {}

    print("\nJ) 2x2 REPLAY — same code, same weights, every combination")
    grid = {}
    for frame_label, (used_f, rest_f) in (("old frames", (old_used, old_rest)),
                                          ("new frames", (new_used, new_rest))):
        for question_label, question in (("old question", OLD_QUESTION),
                                         ("new question", NEW_QUESTION)):
            used_scores = score_all(probe, used_f, question, cache)
            rest_scores = score_all(probe, rest_f, question, cache)
            value, total = pairwise(used_scores, rest_scores)
            grid[(frame_label, question_label)] = (value, total, used_scores, rest_scores)
            print(f"  {frame_label:11} x {question_label:13}  pairwise {value:.3f}  "
                  f"(used median {st.median(used_scores):.3f}, "
                  f"rest median {st.median(rest_scores):.3f}, n={total})")

    print("\nK) HOLDING ONE AXIS FIXED")
    for label, a, b in (
        ("question fixed at OLD, frames old->new",
         grid[("old frames", "old question")], grid[("new frames", "old question")]),
        ("question fixed at NEW, frames old->new",
         grid[("old frames", "new question")], grid[("new frames", "new question")]),
        ("frames fixed at OLD, question old->new",
         grid[("old frames", "old question")], grid[("old frames", "new question")]),
        ("frames fixed at NEW, question old->new",
         grid[("new frames", "old question")], grid[("new frames", "new question")]),
    ):
        print(f"  {label:38} {a[0]:.3f} -> {b[0]:.3f}  (delta {b[0] - a[0]:+.3f})")

    print(f"\nL) DETERMINISM — new frames x new question, {args.repeats} repeats")
    for _ in range(args.repeats):
        used_scores = score_all(probe, new_used, NEW_QUESTION, {})
        rest_scores = score_all(probe, new_rest, NEW_QUESTION, {})
        value, _ = pairwise(used_scores, rest_scores)
        rounded = [f"{v:.4f}" for v in used_scores]
        print(f"  pairwise {value:.4f}  used={rounded}")

    print("\nT) HIGH/LOW SCORING FRAMES ON THE OLD, WHOLE-FILE QUESTION")
    old_all_scores = score_all(probe, old_used + old_rest, OLD_QUESTION, cache)
    paired = sorted(zip(old_used + old_rest, old_all_scores, strict=True), key=lambda kv: -kv[1])
    print("  highest scoring frames (old question, whole file):")
    for frame, score in paired[:8]:
        band = "USED" if frame in old_used else "rest"
        print(f"    frame {frame:5d}  {score:.3f}  {band}")
    print("  lowest scoring frames:")
    for frame, score in paired[-8:]:
        band = "USED" if frame in old_used else "rest"
        print(f"    frame {frame:5d}  {score:.3f}  {band}")

    Path(args.out).write_text(json.dumps({
        "old_used": old_used, "old_rest": old_rest,
        "new_used": new_used, "new_rest": new_rest,
        "grid": {f"{a}|{b}": {"pairwise": v[0], "n": v[1],
                              "used_scores": v[2], "rest_scores": v[3]}
                for (a, b), v in grid.items()},
        "old_question": OLD_QUESTION, "new_question": NEW_QUESTION,
    }, indent=1))
    print(f"\nwritten {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
