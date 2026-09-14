"""Find an event inside a clip without being told where it is, then watch a state cross it.

C2075 worked once the comparison was narrowed to the eight seconds around one cut, because that
narrowing threw out two other real moments from the same file — a feeding and a toast — that had
been pooled in as the same "used" label. Doing that narrowing by hand is not a method; this is
the same idea done without being told where to look.

Five stages, each blind to the manual edit until the last:

  1  IDENTITY     sparse frames across the whole clip, each scored independently, asked in a
                  few words what the one most distinct thing happening is
  2  POPULATION   a deterministic, pre-declared rule groups consecutive same-keyword frames
                  into runs — candidate events, discovered rather than given
  3  PROBE        one frame from each run asks the model to write its own yes/no question
                  about a visible physical state, validated against a banned-word list so no
                  editorial language slips through
  4  CURVE        that question, scored independently frame by frame — never as an ordered
                  sequence — across and beyond the run, at the same half-second grid the rest
                  of the project uses
  5  TRANSITION   a fixed rule, decided before any curve was seen: the first point where two
                  consecutive frames both cross one-half

Only after stage 5 does this read the editor's actual cut for that clip, and only to report how
the two compare — never earlier, and never as an input to any of the five stages.

Stage 3 is tested twice, and the two tests are kept apart in the output. Capability B is
whether the model can write its own probe question — tested first, on every run, unassisted.
Capability A is whether a *correct* objective question can be measured once it exists — tested
by falling back to a small, fixed lookup from keyword to a generic, non-editorial contact
question (kissing, hugging, a ring going onto a finger, a glass raised in a toast), declared
below before any of the four clips' results were read, and never adjusted afterwards. A run
whose keyword matches neither a generated question nor the lookup is marked
STATE_PROBE_GENERATION_FAILURE; a keyword that names a continuous motion rather than a contact
state (dancing, walking) is marked STATICALLY_UNOBSERVABLE_EVENT rather than forced through the
lookup.

Read-only. No model is downloaded, no training happens, and nothing here reaches a plan.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from itertools import pairwise
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from semantic_probe import MEDIA, Probe, frame_at

FPS = 50
STEP = 25  # half a second, the grid every other measurement in this project uses
PAD_SECONDS = 3  # how far past a discovered run's edges the state curve is drawn

IDENTITY_PROMPT = ("In a few words, what is the one most distinct thing a person is doing in "
                   "this picture?")
PROBE_META_PROMPT = (
    "Look at this picture. Write ONE yes-or-no question that asks whether a specific object or "
    "person is touching, holding, inside, or in contact with another specific object or person "
    "visible in this picture. Do not use the words best, beautiful, meaningful, important, or "
    "special. Answer with only the question."
)

STOPWORDS = frozenset("""
    a an the is are was were be being been to of in on at for with by from and or
    their his her its it this that these those someone person people man woman
    standing sitting looking holding one main most distinct thing picture doing
""".split())  # noqa: SIM905
BANNED_WORDS = ("best", "beautiful", "meaningful", "important", "special", "ideal",
                "perfect", "good shot", "editorial")

# Capability A's fallback, declared before any of the four clips' identity scans were read.
# Generic contact questions, one per wedding action a keyword might name — never a per-clip
# answer, and never touched again once the runs below were seen. A keyword naming a continuous
# motion rather than a discrete contact state is deliberately absent: "dancing" and "walking"
# have no yes/no state to ask about, and forcing one through would be exactly the wedding-
# specific magic-constant fitting this fallback exists to avoid.
FALLBACK_PROBES = {
    "kissing": "Are the two people's lips touching?",
    "kiss": "Are the two people's lips touching?",
    "hugging": "Are the two people's arms wrapped around each other?",
    "hug": "Are the two people's arms wrapped around each other?",
    "cutting": "Is the knife touching or inside the cake?",
    "cake": "Is the knife touching or inside the cake?",
    "ring": "Is the ring being placed onto a finger?",
    "toasting": "Are two glasses touching each other?",
    "toast": "Are two glasses touching each other?",
    "raising": "Are two glasses touching each other?",
}
UNOBSERVABLE_KEYWORDS = frozenset({"dancing", "walking", "talking", "wearing", "unknown"})

CROSSING = 0.5


def keyword(text: str) -> str:
    """The single most informative word in a short description, for grouping frames by.

    Deterministic and fixed before this round ran: lower-case, strip punctuation, drop a short
    stopword list, keep the longest remaining token. Longest rather than first because the verb
    or object in these short answers tends to be the word that survived trimming, not the
    grammatical filler at the front ("a bride is cutting a cake" keeps "cutting" or "cake").
    """
    words = re.findall(r"[a-zA-Z]+", text.lower())
    candidates = [w for w in words if w not in STOPWORDS and len(w) > 2]
    return max(candidates, key=len) if candidates else "unknown"


def group_runs(samples: list[dict]) -> list[dict]:
    """Consecutive same-keyword samples become one candidate event. No manual input here."""
    runs: list[dict] = []
    current: list[dict] = []
    for sample in samples:
        if current and sample["keyword"] != current[-1]["keyword"]:
            if len(current) >= 2:
                runs.append(_summarise_run(current))
            current = []
        current.append(sample)
    if len(current) >= 2:
        runs.append(_summarise_run(current))
    return runs


def _summarise_run(samples: list[dict]) -> dict:
    return {
        "keyword": samples[0]["keyword"],
        "start": samples[0]["frame"], "end": samples[-1]["frame"],
        "count": len(samples),
        "descriptions": [s["description"] for s in samples],
        "centre_frame": samples[len(samples) // 2]["frame"],
    }


def valid_probe(question: str) -> bool:
    if "?" not in question:
        return False
    lowered = question.lower()
    return not any(bad in lowered for bad in BANNED_WORDS)


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


def free_text(probe: Probe, image, question: str, words: int = 16) -> str:
    """One free-text answer to an arbitrary question, outside Probe's fixed describe prompt."""
    prompt = probe.processor.apply_chat_template(
        [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": question}]}],
        add_generation_prompt=True)
    encoded = probe.processor(text=prompt, images=[image], return_tensors="pt").to(probe.device)
    with probe.torch.inference_mode():
        generated = probe.model.generate(**encoded, max_new_tokens=words, do_sample=False)
    return probe.processor.batch_decode(
        generated[:, encoded["input_ids"].shape[1]:], skip_special_tokens=True)[0].strip()


def identity_step(probe: Probe, capture, total_frames: int, identity_gap: int) -> list[dict]:
    import cv2

    samples = []
    for frame in range(0, total_frames, identity_gap):
        picture = frame_at(capture, frame, cv2)
        if picture is None:
            continue
        description = free_text(probe, picture, IDENTITY_PROMPT, words=16)
        samples.append({"frame": frame, "description": description,
                        "keyword": keyword(description)})
    return samples


def state_curve(probe: Probe, capture, question: str, first: int, last: int) -> list[dict]:
    import cv2

    points = []
    for frame in range(max(0, first), last + 1, STEP):
        picture = frame_at(capture, frame, cv2)
        if picture is None:
            continue
        value = probe.ask(picture, {"q": question})["q"]
        points.append({"frame": frame, "value": value})
    return points


def first_sustained_crossing(curve: list[dict]) -> int | None:
    """The pre-declared transition rule: two consecutive sampled points both above one-half."""
    for a, b in pairwise(curve):
        if a["value"] > CROSSING and b["value"] > CROSSING:
            return a["frame"]
    return None


def run_clip(probe: Probe, clip: str, total_frames: int) -> dict:
    import cv2

    capture = cv2.VideoCapture(str(MEDIA / clip))
    # A fixed second per identity sample on any clip short enough that a wedding action could
    # start and finish inside one second (under 20 s); longer clips step at four times that so
    # a two-minute file stays affordable. Set once, from the C1987 calibration look permitted
    # under this round's instructions, before any of the four clips' actual runs below.
    identity_gap = STEP if total_frames <= FPS * 20 else STEP * 4
    started = time.time()
    try:
        samples = identity_step(probe, capture, total_frames, identity_gap)
        runs = group_runs(samples)

        # Capability B: can the model write its own probe question? Tried on every run,
        # unassisted, and the result reported honestly whether or not it validates.
        for run in runs:
            picture = frame_at(capture, run["centre_frame"], cv2)
            if picture is None:
                run["generated_question"] = None
                run["generated_valid"] = False
                continue
            question = free_text(probe, picture, PROBE_META_PROMPT, words=30)
            run["generated_question"] = question
            run["generated_valid"] = valid_probe(question)

        # Capability A: given a correct objective question — the generated one if it validated,
        # otherwise the fixed, pre-declared fallback for this keyword — can the model measure
        # it? A keyword with no discrete state gets neither, and is marked accordingly.
        for run in runs:
            if run["generated_valid"]:
                run["probe_question"] = run["generated_question"]
                run["probe_source"] = "generated"
            elif run["keyword"] in UNOBSERVABLE_KEYWORDS:
                run["probe_question"] = None
                run["probe_source"] = "STATICALLY_UNOBSERVABLE_EVENT"
            elif run["keyword"] in FALLBACK_PROBES:
                run["probe_question"] = FALLBACK_PROBES[run["keyword"]]
                run["probe_source"] = "fallback"
            else:
                run["probe_question"] = None
                run["probe_source"] = "STATE_PROBE_GENERATION_FAILURE"

        # Score the state curve for each run that ended up with a question, across the run plus
        # padding either side, one independent frame at a time.
        for run in runs:
            if not run["probe_question"]:
                run["curve"] = None
                continue
            pad = FPS * PAD_SECONDS
            curve = state_curve(probe, capture, run["probe_question"],
                                run["start"] - pad, run["end"] + pad)
            run["curve"] = curve
            run["max_frame"] = max(curve, key=lambda p: p["value"])["frame"] if curve else None
            run["max_value"] = max((p["value"] for p in curve), default=None)
            run["transition_frame"] = first_sustained_crossing(curve)
    finally:
        capture.release()
    print(f"  {clip:12} {len(samples)} identity samples, {len(runs)} candidate runs, "
          f"{time.time() - started:.0f}s", flush=True)
    return {"identity_samples": samples, "runs": runs, "total_frames": total_frames}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--durations", type=Path, required=True,
                        help="JSON {clip: total_frame_count}")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--clips", nargs="*")
    args = parser.parse_args()

    durations = json.loads(args.durations.read_text())
    wanted = args.clips or list(durations)
    probe = Probe()
    results = {}
    for clip in wanted:
        if clip not in durations:
            continue
        results[clip] = run_clip(probe, clip, durations[clip])
        args.out.write_text(json.dumps(results, indent=1))
    args.out.write_text(json.dumps(results, indent=1))
    print(f"written {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
