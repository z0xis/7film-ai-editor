"""P6.26 -- temporal ground-truth audit: dense frame strips over candidate event regions.

Contact-sheet stills cannot tell FIRST_DANCE from a couple portrait or crowd dance. This generates a
dense horizontal strip of frames sampled across a time window (revealing motion/action over time) for
CAKE and FIRST_DANCE candidate regions, so labels can be temporally verified. Artifacts are gitignored.
No DB / Resolve / timeline write.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / "data" / "references" / "media"
TIER2 = ROOT / "data" / "reference_editor" / "tier2"
OUT = ROOT / "data" / "reference_editor" / "temporal_audit"


def strip(stem: str, start_s: float, end_s: float, tag: str, n: int = 8) -> Path | None:
    path = MEDIA / f"{stem}.mkv"
    if not path.is_file():
        return None
    OUT.mkdir(parents=True, exist_ok=True)
    dur = max(0.5, end_s - start_s)
    tmp = OUT / f"_{stem}_{tag}"
    tmp.mkdir(exist_ok=True)
    times = [start_s + dur * i / (n - 1) for i in range(n)]
    frames = []
    for k, t in enumerate(times):
        f = tmp / f"{k:02d}.jpg"
        subprocess.run(["ffmpeg", "-y", "-i", str(path), "-ss", str(t), "-frames:v", "1",
                        "-vf", "scale=-2:135", str(f)], capture_output=True, check=False)
        if f.is_file():
            frames.append(f)
    if not frames:
        return None
    out = OUT / f"{stem}_{tag}.jpg"
    inp = []
    for f in frames:
        inp += ["-i", str(f)]
    subprocess.run(["ffmpeg", "-y", *inp, "-filter_complex",
                    f"hstack=inputs={len(frames)}[o]", "-map", "[o]", "-frames:v", "1", str(out)],
                   capture_output=True, check=False)
    for f in frames:
        f.unlink(missing_ok=True)
    tmp.rmdir()
    return out


def cake_candidates() -> list[tuple[str, float, float, str]]:
    ann = ROOT / "tools" / "fixtures" / "p6_25_event_annotations.jsonl"
    out = []
    for line in ann.read_text().splitlines():
        d = json.loads(line)
        if d.get("event") != "CAKE":
            continue
        stem = d["reference_id"].split(":", 1)[1]
        shots = json.loads((TIER2 / f"{stem}.json").read_text())["shots"]
        idx = d["shots"]
        a = shots[idx[0]]["start_s"]
        b = shots[idx[-1]]["end_s"]
        out.append((stem, max(0, a - 1.0), b + 2.0, "cake"))
    return out


def first_dance_candidates(max_per_ref: int = 1) -> list[tuple[str, float, float, str]]:
    """Reception-half runs of couple shots (>=3 consecutive) -> the strongest first-dance candidates."""
    out = []
    for t2 in sorted(TIER2.glob("*.json")):
        shots = json.loads(t2.read_text())["shots"]
        runs, cur = [], []
        for s in shots:
            if s.get("category") == "couple" and s.get("story_position", 0) >= 0.45:
                cur.append(s)
            else:
                if len(cur) >= 3:
                    runs.append(cur)
                cur = []
        if len(cur) >= 3:
            runs.append(cur)
        runs.sort(key=lambda r: -len(r))
        for j, r in enumerate(runs[:max_per_ref]):
            out.append((t2.stem, r[0]["start_s"], r[-1]["end_s"], f"fd{j}"))
    return out


def run(kind: str):
    cands = cake_candidates() if kind == "cake" else first_dance_candidates()
    made = []
    for stem, a, b, tag in cands:
        p = strip(stem, a, b, tag)
        if p:
            made.append({"ref": stem, "start_s": round(a, 1), "end_s": round(b, 1), "tag": tag,
                         "strip": p.name})
    (OUT / f"index_{kind}.json").write_text(json.dumps(made, indent=1, sort_keys=True))
    return made


if __name__ == "__main__":
    kind = sys.argv[1] if len(sys.argv) > 1 else "cake"
    for m in run(kind):
        print(m["ref"], m["tag"], m["start_s"], m["end_s"], m["strip"])
