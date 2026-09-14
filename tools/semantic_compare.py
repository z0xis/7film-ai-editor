"""Put three stretches of a clip side by side, unlabelled, and see whether the model invents one.

The single most important thing the visual audit found is that on 15 of 35 clips there is
nothing to see: the stretch the editor used and the stretches either side of it show the same
thing, and any system that insists one of them is better is making it up. So a semantic layer
has to be able to say "these are the same" — and that is what this measures, before anything
else is asked of it.

Three frames go in as A, B and C in a shuffled order. Nothing tells the model which is which,
nothing calls one of them the editor's, and the question never mentions editing. Every question
carries a "Same" option, and the answer is read as the probability of each letter in the model's
next token rather than parsed out of a sentence.

Each clip is asked twice under two different shuffles. Two numbers come out of that: how often
the model's answer survives the shuffle, and how often it simply prefers a position.

Read-only. No model is downloaded; nothing is written to a plan or a timeline.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from semantic_probe import MEDIA, Probe, frame_at

SEED = 20260914
LETTERS = ("A", "B", "C")
BANDS = ("PRE", "USED", "POST")

# Both questions are about what is in the pictures. Neither asks which one to cut to: the model
# is not told an edit exists.
QUESTIONS = {
    "clearest": ("In which picture can you see the people most clearly? "
                 "Answer A, B, C, or Same if there is no difference."),
    "different": ("Do these three pictures show the same thing or something different? "
                  "Answer Same or Different."),
}
CHOICES = {"clearest": ("A", "B", "C", "Same"), "different": ("Same", "Different")}


class Comparer(Probe):
    def choose(self, images, question: str, options) -> dict[str, float]:
        """The probability of each option, read off the model's next token."""
        content = [{"type": "image"} for _ in images]
        content.append({"type": "text", "text": question})
        prompt = self.processor.apply_chat_template(
            [{"role": "user", "content": content}], add_generation_prompt=True)
        encoded = self.processor(
            text=prompt, images=list(images), return_tensors="pt").to(self.device)
        with self.torch.inference_mode():
            logits = self.model(**encoded).logits[0, -1].float()
        tokenizer = self.processor.tokenizer
        picked = []
        for option in options:
            token = tokenizer(" " + option, add_special_tokens=False)["input_ids"][0]
            picked.append(logits[token])
        spread = self.torch.softmax(self.torch.tensor(picked), 0)
        return {option: round(float(value), 4)
                for option, value in zip(options, spread, strict=True)}


def cut_map(path: Path) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for part in path.read_text().strip().split(";"):
        fields = part.split("|")
        if len(fields) < 5 or not fields[0].upper().endswith(".MP4"):
            continue
        clip, start, end, doubled, source = fields[:5]
        source, start, end = int(source), int(start), int(end)
        slowed = source > 0 and abs(int(doubled) - 2 * source) <= 8
        frames = (end - start) // (2 if slowed else 1)
        out.setdefault(clip, (source, max(1, frames)))
    return out


def main() -> int:
    import cv2

    parser = argparse.ArgumentParser()
    parser.add_argument("--cuts", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--device", default="mps")
    args = parser.parse_args()

    annotations = {k: v for k, v in json.loads(args.annotations.read_text()).items()
                   if not k.startswith("_")}
    cuts = cut_map(args.cuts)
    rng = random.Random(SEED)
    probe = Comparer(device=args.device)

    results = {}
    for index, clip in enumerate(sorted(annotations), 1):
        if clip not in cuts:
            continue
        start, frames = cuts[clip]
        pictures = {}
        capture = cv2.VideoCapture(str(MEDIA / clip))
        if not capture.isOpened():
            continue
        try:
            for band, base in zip(BANDS, (start - frames, start, start + frames), strict=True):
                picture = frame_at(capture, base + frames // 2, cv2)
                if picture is not None:
                    pictures[band] = picture
        finally:
            capture.release()
        if len(pictures) < 3:
            continue

        runs = []
        for _ in range(2):
            order = list(BANDS)
            rng.shuffle(order)
            images = [pictures[band] for band in order]
            answers = {
                name: probe.choose(images, question, CHOICES[name])
                for name, question in QUESTIONS.items()
            }
            # Put the letters back onto the bands, so the result is about the clip and not
            # about where a picture happened to sit.
            clearest = {order[LETTERS.index(letter)]: value
                        for letter, value in answers["clearest"].items()
                        if letter in LETTERS}
            runs.append({
                "order": order,
                "by_letter": answers["clearest"],
                "by_band": clearest,
                "same": answers["clearest"]["Same"],
                "different": answers["different"],
            })
        results[clip] = {
            "label": annotations[clip]["primary"],
            "runs": runs,
        }
        print(f"{index:3d}/{len(annotations)}  {clip:12} {annotations[clip]['primary']}",
              flush=True)
        args.out.write_text(json.dumps(results, indent=1))

    args.out.write_text(json.dumps(results, indent=1))
    print(f"written {args.out}  {len(results)} clips")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
