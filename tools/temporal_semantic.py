"""Show the model a moment as five ordered frames, and ask where in the action the middle one is.

The frozen failure this exists for: on the cake clip the model knows it is looking at a couple
cutting a cake, and asked about one frame at a time whether the knife is already in the cake, it
answers the preparation more confidently than the moment the editor used. What it lacks may not
be understanding but time — a single frame cannot say whether the knife is on its way down or on
its way back.

So each candidate moment becomes a short ordered strip, the same for every candidate:

    FRAME 1  t - 500 ms   earliest
    FRAME 2  t - 240 ms
    FRAME 3  t            centre
    FRAME 4  t + 240 ms
    FRAME 5  t + 500 ms   latest

At 50 frames a second a quarter second is 12.5 frames, which does not exist; 12 frames is the
nearest spacing that lands on real frames symmetrically, so the inner pair sits at 240 ms. The
spacing was fixed before anything was run and is the same for every clip and every condition.

Every question asks about the centre frame and what is happening, never which frame is better and
never anything about editing. The answer is the probability of "Yes" against "No" in the model's
next token, as in `semantic_probe.py`.

The same strip is also shown in ways that should break a model that really uses order, and should
not matter to one that only sees a bag of pictures:

    forward     the true order
    reversed    latest first, labelled as if it were earliest
    shuffled    a fixed random order, labelled 1 to 5
    static      the centre frame five times
    no_centre   frames 1, 2, 4, 5 only
    single      the centre frame alone, the existing single-frame baseline

The model is never shown the words pre, used, post, manual or AI, and is given no measurement.

Read-only. No model is downloaded and nothing reaches a plan, a timeline or Resolve.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from semantic_probe import MEDIA, Probe, frame_at

OFFSETS = (-25, -12, 0, 12, 25)
STEP = 25
SEED = 20260914
CAKE_CLIP = "C2075.MP4"

# Frozen after the free-text look at two strips of the cake clip and nothing else. The generic
# questions are asked of every clip; the knife questions only of the cake, because asking a
# kiss whether a knife is in a cake measures nothing.
GENERIC = {
    "t_underway": "At FRAME 3, the centre frame, is the main action already happening?",
    "t_changes": "Does what the people are doing change between FRAME 1 and FRAME 5?",
    "t_begins": "Does a new action begin between FRAME 2 and FRAME 4?",
}
CAKE = {
    "t_knife_in": "At FRAME 3, the centre frame, is the knife touching or inside the cake?",
    "t_not_started": "At FRAME 3, the centre frame, has the cutting not started yet?",
}
SINGLE = {
    "t_underway": "Is the main action already happening in this picture?",
    "t_knife_in": "Is the knife touching or inside the cake in this picture?",
    "t_not_started": "Has the cutting not started yet in this picture?",
}
LABELS = ("FRAME 1 (earliest)", "FRAME 2", "FRAME 3 (centre)", "FRAME 4", "FRAME 5 (latest)")


class Sequencer(Probe):
    def ask_strip(self, frames, labels, question: str) -> float:
        """P(Yes) for one question about an ordered, labelled strip of frames."""
        content = []
        for label, _ in zip(labels, frames, strict=True):
            content.append({"type": "text", "text": f"{label}:"})
            content.append({"type": "image"})
        content.append({"type": "text", "text": question + " Answer Yes or No."})
        prompt = self.processor.apply_chat_template(
            [{"role": "user", "content": content}], add_generation_prompt=True)
        encoded = self.processor(
            text=prompt, images=list(frames), return_tensors="pt").to(self.device)
        with self.torch.inference_mode():
            logits = self.model(**encoded).logits[0, -1].float()
        pair = self.torch.tensor([logits[self.yes], logits[self.no]])
        return round(float(self.torch.softmax(pair, 0)[0]), 4)

    def describe_strip(self, frames, labels, words: int = 60) -> str:
        content = []
        for label, _ in zip(labels, frames, strict=True):
            content.append({"type": "text", "text": f"{label}:"})
            content.append({"type": "image"})
        content.append({"type": "text", "text":
                        "These frames are in time order. Describe what happens from the "
                        "first frame to the last, in one or two sentences."})
        prompt = self.processor.apply_chat_template(
            [{"role": "user", "content": content}], add_generation_prompt=True)
        encoded = self.processor(
            text=prompt, images=list(frames), return_tensors="pt").to(self.device)
        with self.torch.inference_mode():
            generated = self.model.generate(**encoded, max_new_tokens=words, do_sample=False)
        return self.processor.batch_decode(
            generated[:, encoded["input_ids"].shape[1]:], skip_special_tokens=True)[0].strip()


def cut_list(path: Path) -> dict[str, list[tuple[int, int]]]:
    out: dict[str, list[tuple[int, int]]] = {}
    for part in path.read_text().strip().split(";"):
        fields = part.split("|")
        if len(fields) < 5 or not fields[0].upper().endswith(".MP4"):
            continue
        clip, start, end, doubled, source = fields[:5]
        source, start, end = int(source), int(start), int(end)
        slowed = source > 0 and abs(int(doubled) - 2 * source) <= 8
        out.setdefault(clip, []).append((source, max(1, (end - start) // (2 if slowed else 1))))
    return out


def centres_for(clip: str, cut: tuple[int, int], cake: bool) -> list[int]:
    """Candidate centres: the cut and the stretch either side, every half second.

    The cake gets eight seconds either side, because that is where the preparation and the
    aftermath of the one event this round is about actually are. Every other clip gets two.
    """
    start, frames = cut
    margin = 400 if cake else 50
    first = max(25, start - margin)
    return list(range(first, start + frames + margin + 1, STEP))


def band_of(centre: int, cut: tuple[int, int]) -> str:
    start, frames = cut
    if centre < start:
        return "PRE"
    if centre < start + frames:
        return "USED"
    return "POST"


def main() -> int:
    import cv2

    parser = argparse.ArgumentParser()
    parser.add_argument("--cuts", type=Path, required=True)
    parser.add_argument("--classes", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--describe-only", action="store_true")
    parser.add_argument("--model", default="HuggingFaceTB/SmolVLM-Instruct")
    parser.add_argument("--clips", nargs="*")
    args = parser.parse_args()

    cuts = cut_list(args.cuts)
    classes = json.loads(args.classes.read_text())
    annotations = {k: v for k, v in json.loads(args.annotations.read_text()).items()
                   if not k.startswith("_")}
    events = [c for c, kind in classes.items() if kind == "ACTION_EVENT"]
    controls = ["C1986.MP4", "C2146.MP4", "C1899.MP4",
                *[c for c in sorted(annotations)
                  if annotations[c]["primary"] == "NO_OBVIOUS_REASON"][:3]]
    wanted = args.clips or [*events, *[c for c in controls if c not in events]]

    probe = Sequencer(model_name=args.model)
    rng = random.Random(SEED)
    results: dict[str, dict] = {}
    started = time.time()
    asked = 0

    for clip in wanted:
        if clip not in cuts:
            continue
        cut = cuts[clip][0]
        cake = clip == CAKE_CLIP
        is_event = classes.get(clip) == "ACTION_EVENT"
        capture = cv2.VideoCapture(str(MEDIA / clip))
        if not capture.isOpened():
            continue
        records = []
        try:
            centres = centres_for(clip, cut, cake)
            if args.describe_only:
                centres = [cut[0] - 300, cut[0] + cut[1] // 2] if cake else [cut[0] + cut[1] // 2]
            for centre in centres:
                frames = [frame_at(capture, centre + offset, cv2) for offset in OFFSETS]
                if any(f is None for f in frames):
                    continue
                record = {"centre": centre, "band": band_of(centre, cut)}
                if args.describe_only:
                    record["forward"] = probe.describe_strip(frames, LABELS)
                    record["reversed"] = probe.describe_strip(frames[::-1], LABELS)
                    records.append(record)
                    continue
                questions = {**GENERIC, **(CAKE if cake else {})}
                order = list(range(5))
                rng.shuffle(order)
                conditions = {
                    "forward": (frames, LABELS),
                    "static": ([frames[2]] * 5, LABELS),
                }
                if cake or is_event:
                    conditions["reversed"] = (frames[::-1], LABELS)
                    conditions["shuffled"] = ([frames[i] for i in order], LABELS)
                    conditions["no_centre"] = (
                        [frames[0], frames[1], frames[3], frames[4]],
                        (LABELS[0], LABELS[1], LABELS[3], LABELS[4]))
                for name, (strip, labels) in conditions.items():
                    record[name] = {}
                    for key, question in questions.items():
                        if name == "no_centre":
                            question = question.replace(
                                "At FRAME 3, the centre frame,", "Halfway between FRAME 2 and FRAME 4,")
                        record[name][key] = probe.ask_strip(strip, labels, question)
                        asked += 1
                record["single"] = {
                    key: probe.ask(frames[2], {key: SINGLE[key]})[key]
                    for key in questions if key in SINGLE
                }
                asked += len(record["single"])
                records.append(record)
        finally:
            capture.release()
        results[clip] = {"class": classes.get(clip, "CONTINUOUS_ACTION"),
                         "label": annotations.get(clip, {}).get("primary"),
                         "cut": cut, "records": records}
        elapsed = time.time() - started
        print(f"  {clip:12} {len(records):3d} centres   {asked} questions   "
              f"{elapsed / max(1, asked):.2f}s each", flush=True)
        args.out.write_text(json.dumps(results, indent=1))

    args.out.write_text(json.dumps(results, indent=1))
    print(f"written {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
