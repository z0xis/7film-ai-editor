"""Ask a vision-language model the questions the visual audit asked, one window at a time.

The frozen finding this exists to test: everything the eye gave as a reason for the editor's
choice — the foreground clearing, the subject turning round, the shot being over — is invisible
to every measurement the project has. Sharpness, motion, face counts and the stored CLIP vectors
all sit at or near chance on exactly those clips.

This puts the same questions to a model that can answer them in words. No model is downloaded:
SmolVLM is already in the project's runtime cache beside the CLIP the analyser uses.

How a question is scored. The model is asked a yes-or-no question about one frame and the
answer taken as the probability it puts on "Yes" against "No" in its very next token. No text is
parsed, nothing is generated, and the same prompt always gives the same number. A free
description is generated only for the frames a person will read afterwards.

What is deliberately not asked. The model is never asked which frame is better, which one an
editor would use, or whether a shot is good. It is asked what is in front of the camera. Whether
those answers say anything about the editor's choice is a separate question, settled by
`signal_discovery.py` against his real cuts, and it is settled after the answers are in.

Read-only. Nothing here is imported by the planner and nothing reaches a plan or a timeline.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

MEDIA = Path("/Users/ibrahimsoylu/Desktop/ELENORA MUSTAFA/KLIP/CLIP")
MODEL = "HuggingFaceTB/SmolVLM-Instruct"
FRAME_WIDTH = 768

# One question per category of the frozen annotation taxonomy, written before any of them was
# run over the set. None was dropped or reworded after seeing a result: a question that turns
# out to carry nothing is a finding about the model, not a question to replace.
#
# They ask what is in the picture, never what is good about it. "Is the view blocked" is a fact
# about the frame; "is this a good moment to cut" is the thing being predicted, and asking the
# model for it directly would be scoring the answer against itself.
QUESTIONS: dict[str, str] = {
    "sem_couple_visible": "Can you clearly see the bride and groom in this picture?",
    "sem_people_present": "Are there people in this picture?",
    "sem_foreground_blur": "Is there a large blurred person or object very close to the camera?",
    "sem_facing_camera": "Is the main person facing the camera?",
    "sem_back_turned": "Is the main person's back turned to the camera?",
    "sem_interaction": "Are the people looking at each other?",
    "sem_expression": "Is someone smiling or laughing?",
    "sem_action_underway": "Are the people in the middle of doing something?",
    "sem_cake_cutting": "Is the knife already cutting into the cake?",
    "sem_well_framed": (
        "Are the people well framed, and not cut off by the edge of the picture?"),
}

# The shoot is 10-bit S-Log3 and looks grey and flat as it comes off the file. The analyser
# undoes the curve before it shows a frame to CLIP for the same reason: a model trained on
# ordinary photographs reads a log frame as a different picture.
GAMMA = 1 / 1.6


class Probe:
    """SmolVLM, loaded once, asked yes-or-no questions about single frames."""

    def __init__(self, device: str = "mps", model_name: str = MODEL) -> None:
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor

        self.torch = torch
        self.device = device
        self.processor = AutoProcessor.from_pretrained(
            model_name, local_files_only=True, do_image_splitting=False)
        self.model = AutoModelForImageTextToText.from_pretrained(
            model_name, local_files_only=True, dtype=torch.float16).to(device).eval()
        tokenizer = self.processor.tokenizer
        # The two answers are read off the one token that differs between them, so a question
        # costs one pass rather than two.
        self.yes = tokenizer(" Yes", add_special_tokens=False)["input_ids"][0]
        self.no = tokenizer(" No", add_special_tokens=False)["input_ids"][0]

    def _prompt(self, question: str) -> str:
        messages = [{"role": "user", "content": [
            {"type": "image"}, {"type": "text", "text": question + " Answer Yes or No."}]}]
        return self.processor.apply_chat_template(messages, add_generation_prompt=True)

    def ask(self, image, questions: dict[str, str]) -> dict[str, float]:
        """The probability of Yes for each question, on one frame."""
        out: dict[str, float] = {}
        for key, question in questions.items():
            encoded = self.processor(
                text=self._prompt(question), images=[image], return_tensors="pt",
            ).to(self.device)
            with self.torch.inference_mode():
                logits = self.model(**encoded).logits[0, -1].float()
            pair = self.torch.tensor([logits[self.yes], logits[self.no]])
            out[key] = round(float(self.torch.softmax(pair, 0)[0]), 4)
        return out

    def describe(self, image, words: int = 40) -> str:
        """One sentence, for a person to read beside the numbers."""
        messages = [{"role": "user", "content": [
            {"type": "image"},
            {"type": "text", "text": "Describe this photograph in one sentence."}]}]
        prompt = self.processor.apply_chat_template(messages, add_generation_prompt=True)
        encoded = self.processor(
            text=prompt, images=[image], return_tensors="pt").to(self.device)
        with self.torch.inference_mode():
            generated = self.model.generate(
                **encoded, max_new_tokens=words, do_sample=False)
        return self.processor.batch_decode(
            generated[:, encoded["input_ids"].shape[1]:], skip_special_tokens=True)[0].strip()


def frame_at(capture, frame: int, cv2):
    """One frame off the file, lifted out of log and scaled down, or None."""
    from PIL import Image

    capture.set(cv2.CAP_PROP_POS_FRAMES, frame)
    ok, picture = capture.read()
    if not ok or picture is None:
        return None
    height, width = picture.shape[:2]
    picture = cv2.resize(picture, (FRAME_WIDTH, max(1, height * FRAME_WIDTH // width)))
    table = np.array([min(255, int(255 * (i / 255) ** GAMMA)) for i in range(256)], np.uint8)
    picture = cv2.LUT(picture, table)
    return Image.fromarray(cv2.cvtColor(picture, cv2.COLOR_BGR2RGB))


def wanted_frames(rows) -> dict[str, list[int]]:
    """The windows to ask about: the stretch he used and the matched bands either side.

    The same neighbourhood the frozen baseline was measured on, so the two numbers can be put
    beside each other without an asterisk.
    """
    by_clip: dict[str, list] = {}
    for row in rows:
        by_clip.setdefault(row["clip"], []).append(row)
    out: dict[str, list[int]] = {}
    for clip, group in by_clip.items():
        group.sort(key=lambda r: r["frame"])
        used = [r for r in group if r["used"]]
        if not used:
            continue
        length = used[-1]["frame"] - used[0]["frame"] + 25
        low, high = used[0]["frame"] - length, used[-1]["frame"] + length
        band = [r["frame"] for r in group if low <= r["frame"] <= high]
        if band:
            out[clip] = band
    return out


def main() -> int:
    import cv2

    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=Path, required=True,
                        help="signal_discovery.py's output, for the window positions")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--device", default="mps")
    parser.add_argument("--describe", action="store_true",
                        help="also write one sentence per frame, for reading by eye")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    rows = json.loads(args.rows.read_text())
    plan = wanted_frames(rows)
    if args.limit:
        plan = dict(sorted(plan.items())[: args.limit])
    total = sum(len(frames) for frames in plan.values())
    print(f"{total} windows over {len(plan)} clips, "
          f"{len(QUESTIONS)} questions each")

    probe = Probe(device=args.device)
    answers: dict[str, dict] = {}
    done = 0
    started = time.time()
    for clip, frames in sorted(plan.items()):
        capture = cv2.VideoCapture(str(MEDIA / clip))
        if not capture.isOpened():
            print(f"  {clip}: cannot open")
            continue
        try:
            for frame in frames:
                picture = frame_at(capture, frame, cv2)
                if picture is None:
                    continue
                record = probe.ask(picture, QUESTIONS)
                if args.describe:
                    record["description"] = probe.describe(picture)
                answers[f"{clip}:{frame}"] = record
                done += 1
        finally:
            capture.release()
        rate = (time.time() - started) / max(1, done)
        print(f"  {clip:12} {len(frames):3d} windows   {done}/{total}   "
              f"{rate:.2f}s each, {rate * (total - done) / 60:.0f} min left", flush=True)
        args.out.write_text(json.dumps(answers, indent=1))

    args.out.write_text(json.dumps(answers, indent=1))
    print(f"written {args.out}  {len(answers)} windows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
