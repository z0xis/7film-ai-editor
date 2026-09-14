"""Ask what separates the part of a clip the editor used from the part he left.

Every earlier round asked which half second of a clip was the best one and answered it with a
score. This asks the prior question, and asks it the way the data can actually answer: given a
clip he used, can anything already measured tell his stretch of it from the rest of the same
clip?

The primary number is a within-clip pairwise ranking: take one window he used and one he did
not, from the same clip, and see whether the feature puts his higher. Chance is 50%. Nothing
about the clip as a whole can cheat this — not how bright it is, not who is in it, not what
shutter it was shot at — because both sides of every pair come from the same file. It is the
metric the earlier rounds should have been using.

Three separations are kept apart because they are different questions:

  used against unused   the primary one: which stretch of the clip
  entry neighbourhood   the second: where in that stretch it starts
  preparation and tail  what comes before the shot and after it, at matched length

Everything is measured on the stored half-second grid, and only on windows exactly one step
after the window they were measured against, so no comparison is between readings that span
different intervals. That flaw produced a headline result two rounds ago and it is not
repeated.

Read-only. No production code, no threshold, no plan, no timeline, no Resolve.
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from sevenfilm.config import database_path
from sevenfilm.db import Database
from sevenfilm.services.media import project_assets
from sevenfilm.services.moments import project_embeddings, project_obstructions
from sevenfilm.services.windows import asset_windows

EVEN_STEP = 25
RATE_FPS = 50
SEED = 20260914
FOLDS = 5
BOOTSTRAPS = 2000

# The entry neighbourhood: how close to his in-point a window has to be to count as the place
# he came in, rather than somewhere else in the stretch he used. One window either side.
ENTRY_FRAMES = EVEN_STEP

# Feature groups, kept apart so each one's contribution can be read on its own. The two at the
# end are here to be shown to carry nothing: a clip has one shutter and one place in the song,
# so neither can separate two windows of the same clip. That is a fact about the question, not
# a fault in the feature, and it is reported rather than hidden by mixing them in.
GROUPS: dict[str, tuple[str, ...]] = {
    "A quality": ("sharpness", "crisp"),
    "B motion": ("motion", "motion_pct"),
    "C face/subject": ("face_count", "face_ratio", "face_present", "face_ratio_change"),
    "D composition/edge": ("face_edge", "bystanders"),
    "E content/embedding": ("content_typical", "content_change"),
    "F sequence context": ("like_previous", "like_next"),
    "G same-source progression": ("clip_position", "after_previous_use"),
    "H music context": ("music_section_level",),
    "I camera/shutter mode": ("low_shutter",),
}
CONSTANT_WITHIN_CLIP = ("H music context", "I camera/shutter mode")

# What the annotation said the editor was reacting to, put to the content model as questions.
#
# These are written from the visual audit's own vocabulary before any of them was measured, and
# each is a pair so the answer is a contrast rather than a raw similarity — CLIP's absolute
# scores drift with exposure and framing, a difference between two prompts much less. They test
# whether the representation already in the project can see the things the audit named. They
# are not a detector and nothing is trained on them.
PROBES: dict[str, tuple[str, str]] = {
    "probe_facing": (
        "a person facing the camera, face visible",
        "the back of a person's head turned away from the camera"),
    "probe_unobstructed": (
        "a clear unobstructed view of people",
        "a blurred body in the foreground blocking the view"),
    "probe_interaction": (
        "two people looking at each other",
        "people looking in different directions"),
    "probe_composed": (
        "a well composed photograph, the subject centred and clear",
        "a badly framed snapshot, the subject cut off at the edge"),
    "probe_cake": (
        "a couple cutting a wedding cake with a knife",
        "a couple standing beside a table"),
}
GROUPS["E2 content probes"] = tuple(PROBES)

# What a vision-language model says is in the frame, read in by --semantic. Split into the two
# families the audit separated: things that say the shot is spoiled, and things that say there
# is something worth cutting to. The split is the hypothesis this round tests — that the
# editor's rule is mostly the first kind.
SEMANTIC_NEGATIVE = ("sem_foreground_blur", "sem_back_turned")
SEMANTIC_POSITIVE = ("sem_couple_visible", "sem_people_present", "sem_facing_camera",
                     "sem_interaction", "sem_expression", "sem_action_underway",
                     "sem_well_framed")
SEMANTIC_EVENT = ("sem_cake_cutting",)
SEMANTIC_ALL = SEMANTIC_NEGATIVE + SEMANTIC_POSITIVE + SEMANTIC_EVENT


def pairwise(rows, key, label="used") -> tuple[float, int]:
    """How often this feature puts a used window above an unused one from the same clip."""
    wins = ties = total = 0
    by_clip: dict[str, list] = {}
    for row in rows:
        by_clip.setdefault(row["clip"], []).append(row)
    for group in by_clip.values():
        used = [r[key] for r in group if r[label] and r[key] is not None]
        rest = [r[key] for r in group if not r[label] and r[key] is not None]
        for a in used:
            for b in rest:
                total += 1
                if a > b:
                    wins += 1
                elif a == b:
                    ties += 1
    if not total:
        return float("nan"), 0
    return (wins + ties / 2) / total, total


def clip_bootstrap(rows, key, label="used", rng=None):
    """A confidence interval that resamples clips, because windows inside one are not free."""
    by_clip: dict[str, list] = {}
    for row in rows:
        by_clip.setdefault(row["clip"], []).append(row)
    names = list(by_clip)
    if len(names) < 4:
        return None
    draws = []
    for _ in range(BOOTSTRAPS):
        picked = rng.choices(names, k=len(names))
        sample = [dict(r, clip=f"{name}#{index}")
                  for index, name in enumerate(picked) for r in by_clip[name]]
        value, total = pairwise(sample, key, label)
        if total:
            draws.append(value)
    if not draws:
        return None
    draws.sort()
    return draws[int(0.025 * len(draws))], draws[int(0.975 * len(draws))]


def sign_over_clips(rows, key, label="used"):
    """Per clip, does the median used window beat the median unused one? A vote per clip."""
    from scipy.stats import binomtest

    by_clip: dict[str, list] = {}
    for row in rows:
        by_clip.setdefault(row["clip"], []).append(row)
    wins = decided = 0
    for group in by_clip.values():
        used = [r[key] for r in group if r[label] and r[key] is not None]
        rest = [r[key] for r in group if not r[label] and r[key] is not None]
        if not used or not rest:
            continue
        a, b = st.median(used), st.median(rest)
        if a == b:
            continue
        decided += 1
        wins += a > b
    if decided < 6:
        return None
    return wins, decided, binomtest(wins, decided).pvalue


def grouped_folds(clips, folds=FOLDS):
    ordered = sorted(clips)
    return [[clip for index, clip in enumerate(ordered) if index % folds == fold]
            for fold in range(folds)]


def model_pairwise(rows, features, rng) -> tuple[float, int]:
    """A small logistic regression, scored the same way, never seeing a clip it was fit on."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    usable = [f for f in features
              if any(r.get(f) is not None for r in rows)
              and len({r.get(f) for r in rows if r.get(f) is not None}) > 1]
    if not usable:
        return float("nan"), 0
    # Only rows that have every feature. Filling a gap with a zero would let the model read
    # the gap itself: the semantic answers exist only around the cut, and every window he used
    # is around the cut, so "this value is missing" would be most of the label.
    rows = [r for r in rows if all(r.get(f) is not None for f in usable)]
    if not rows:
        return float("nan"), 0
    clips = {r["clip"] for r in rows}
    scored: list[dict] = []
    for held in grouped_folds(clips):
        train = [r for r in rows if r["clip"] not in held]
        test = [r for r in rows if r["clip"] in held]
        if not test or len({r["used"] for r in train}) < 2:
            continue
        matrix = np.array([[float(r[f]) for f in usable] for r in train])
        target = np.array([int(r["used"]) for r in train])
        scaler = StandardScaler().fit(matrix)
        model = LogisticRegression(max_iter=2000, C=1.0).fit(scaler.transform(matrix), target)
        probe = np.array([[float(r[f]) for f in usable] for r in test])
        predicted = model.predict_proba(scaler.transform(probe))[:, 1]
        scored.extend(dict(r, _p=float(p)) for r, p in zip(test, predicted, strict=True))
    return pairwise(scored, "_p")


def report_feature(name, rows, key, rng, label="used") -> None:
    value, total = pairwise(rows, key, label)
    if not total:
        print(f"  {name:26} no pairs")
        return
    interval = clip_bootstrap(rows, key, label, rng)
    sign = sign_over_clips(rows, key, label)
    span = f"[{interval[0]:.3f}, {interval[1]:.3f}]" if interval else "n/a"
    votes = (f"clips {sign[0]:3d}/{sign[1]:3d}  p {sign[2]:.3f}" if sign
             else "too few clips to vote")
    print(f"  {name:26} {value:.3f}  CI {span:16} pairs {total:7d}   {votes}")


def build_rows(database, project_id, canonical, manual, cuts, shutter, classes,
               vectors, order, semantic=None):
    """One row per measured window of every clip in the set, with what is known about it."""
    assets = {asset.name: asset for asset in project_assets(database, project_id)}
    by_asset = asset_windows(database, project_id)
    shot_vectors = project_embeddings(database, project_id)
    probe_axes = probe_directions() if vectors else {}
    obstructed = project_obstructions(database, project_id)
    every = sorted(w.sharpness for windows in by_asset.values() for w in windows)
    bar = every[len(every) // 2] if every else 1.0

    shots = {}
    for row in database.fetch_all(
            """SELECT shots.id, shots.asset_id, shots.start_frame, shots.duration_frames,
                      shots.category, shots.shot_scale
               FROM shots JOIN media_assets ON media_assets.id = shots.asset_id
               WHERE media_assets.project_id = ?""", (project_id,)):
        shots[str(row["id"])] = dict(row)

    rows = []
    for clip in sorted(canonical):
        asset = assets.get(clip)
        # Every interval the edit takes from this clip, not just the first. A clip the editor
        # used twice has two used stretches, and calling the second one "unused" would put the
        # answer on the wrong side of the comparison.
        intervals = [(c["source_in"], c["source_in"] + c["frames"])
                     for c in cuts if c["clip"] == clip]
        if asset is None or not intervals:
            continue
        used_in = min(start for start, _ in intervals)
        windows = sorted(by_asset.get(asset.id, ()), key=lambda w: w.asset_frame)
        even = [w for index, w in enumerate(windows)
                if index and w.asset_frame - windows[index - 1].asset_frame == EVEN_STEP]
        if len(even) < 4:
            continue
        motions = sorted(w.motion for w in even)
        span = max(1, max(w.asset_frame for w in even) - min(w.asset_frame for w in even))
        first = min(w.asset_frame for w in even)

        # The cut that came before this one on the editor's timeline, and the one after, so a
        # candidate can be asked how it follows and how it leads.
        place = order.get(clip)
        previous_shot = order_shot(cuts, place - 1, assets, shots) if place else None
        next_shot = order_shot(cuts, place + 1, assets, shots) if place is not None else None
        previous_vector = shot_vectors.get(previous_shot) if previous_shot else None
        next_vector = shot_vectors.get(next_shot) if next_shot else None

        mode = shutter.get(clip, {})
        earlier_uses = [end for start, end in intervals if start != used_in]
        centre = np.mean([vectors[f"{clip}:{w.asset_frame}"] for w in even
                          if f"{clip}:{w.asset_frame}" in vectors], axis=0) \
            if vectors and any(f"{clip}:{w.asset_frame}" in vectors for w in even) else None

        for index, window in enumerate(even):
            key = f"{clip}:{window.asset_frame}"
            vector = vectors.get(key) if vectors else None
            previous_window = even[index - 1] if index else None
            shot = shots.get(window.shot_id, {})
            row = {
                "clip": clip, "frame": window.asset_frame,
                "used": any(start <= window.asset_frame < end for start, end in intervals),
                "entry": any(abs(window.asset_frame - start) <= ENTRY_FRAMES
                             for start, _ in intervals),
                "class": classes.get(clip, "CONTINUOUS_ACTION"),
                "mode": mode.get("mode", "UNKNOWN"),
                "category": shot.get("category", ""), "scale": shot.get("shot_scale", ""),
                "obstructed": window.shot_id in obstructed,
                "sharpness": window.sharpness, "crisp": window.sharpness / bar if bar else 1.0,
                "motion": window.motion,
                "motion_pct": sum(1 for m in motions if m < window.motion) / len(motions),
                "face_count": window.face_count, "face_ratio": window.face_ratio,
                "face_present": 1.0 if window.face_count else 0.0,
                "face_ratio_change": (
                    abs(window.face_ratio - previous_window.face_ratio)
                    if previous_window else None),
                "face_edge": -window.face_edge, "bystanders": window.bystanders,
                "clip_position": (window.asset_frame - first) / span,
                # Where this window sits relative to the OTHER cuts the edit takes from this
                # same clip. Never relative to this cut: that would be the answer written into
                # the question.
                "after_previous_use": 1.0 if any(
                    window.asset_frame >= other for other in earlier_uses) else 0.0,
                "music_section_level": mode.get("section_level", 0.0),
                "low_shutter": 1.0 if mode.get("mode") == "CREATIVE_LOW_SHUTTER" else 0.0,
                "content_typical": (
                    float(vector @ centre) if vector is not None and centre is not None
                    else None),
                "content_change": None,
            **{name: (float(vector @ probe_axes[name]) if vector is not None
                      and probe_axes else None) for name in PROBES},
            **_semantic_of(semantic, key),
                "like_previous": (
                    float(vector @ previous_vector)
                    if vector is not None and previous_vector is not None else None),
                "like_next": (
                    float(vector @ next_vector)
                    if vector is not None and next_vector is not None else None),
            }
            if vector is not None and previous_window is not None:
                earlier = vectors.get(f"{clip}:{previous_window.asset_frame}")
                if earlier is not None:
                    row["content_change"] = -float(vector @ earlier)
            rows.append(row)
    return rows, bar


def _semantic_of(semantic, key) -> dict[str, float | None]:
    """One window's answers, with the two charges flipped so higher always means better."""
    said = (semantic or {}).get(key)
    if not said:
        return {name: None for name in SEMANTIC_ALL} | {
            f"neg_{name}": None for name in SEMANTIC_NEGATIVE}
    out = {name: said.get(name) for name in SEMANTIC_ALL}
    for name in SEMANTIC_NEGATIVE:
        value = said.get(name)
        out[f"neg_{name}"] = None if value is None else 1.0 - value
    return out


def probe_directions() -> dict[str, np.ndarray]:
    """One unit direction per probe: the positive prompt minus the negative one."""
    from sevenfilm.services.moments import _text_features

    axes: dict[str, np.ndarray] = {}
    for name, (positive, negative) in PROBES.items():
        features = _text_features([positive, negative])
        if features is None:
            return {}
        direction = features[0] - features[1]
        norm = float(np.linalg.norm(direction))
        if norm > 0:
            axes[name] = direction / norm
    return axes


def order_shot(cuts, place, assets, shots):
    """The shot the cut at this place on the timeline came from, if it can be found."""
    if place < 0 or place >= len(cuts):
        return None
    cut = cuts[place]
    asset = assets.get(cut["clip"])
    if asset is None:
        return None
    candidates = [s for s in shots.values() if s["asset_id"] == asset.id]
    if not candidates:
        return None
    return str(min(candidates,
                   key=lambda s: abs(s["start_frame"] - cut["source_in"]))["id"])


def neighbourhood(rows):
    """Each clip cut down to the stretch he used plus the matched bands either side of it."""
    kept = []
    by_clip: dict[str, list] = {}
    for row in rows:
        by_clip.setdefault(row["clip"], []).append(row)
    for group in by_clip.values():
        group.sort(key=lambda r: r["frame"])
        used = [r for r in group if r["used"]]
        if not used:
            continue
        length = used[-1]["frame"] - used[0]["frame"] + EVEN_STEP
        low, high = used[0]["frame"] - length, used[-1]["frame"] + length
        band = [r for r in group if low <= r["frame"] <= high]
        if any(r["used"] for r in band) and any(not r["used"] for r in band):
            kept.extend(band)
    return kept


def clip_spread(rows) -> dict[str, float]:
    """How alike a clip's own windows are, as the median cosine between neighbours.

    A clip whose windows all look the same has no editorially different stretches in it, so
    picking the wrong half second of it costs nothing. This is the nearest thing to a measure
    of equivalence that the material already supports — it is a description, not a metric to
    be scored against.
    """
    out: dict[str, float] = {}
    by_clip: dict[str, list] = {}
    for row in rows:
        by_clip.setdefault(row["clip"], []).append(row)
    for clip, group in by_clip.items():
        values = [r["content_change"] for r in group if r.get("content_change") is not None]
        if len(values) >= 4:
            out[clip] = -st.median(values)
    return out


def region_table(rows, keys, bar) -> None:
    """Preparation, the stretch he used, and the tail — at matched length, same grid."""
    by_clip: dict[str, list] = {}
    for row in rows:
        by_clip.setdefault(row["clip"], []).append(row)
    bands: dict[str, dict[str, list[float]]] = {
        "PRE": {}, "USED": {}, "POST": {}}
    for group in by_clip.values():
        group.sort(key=lambda r: r["frame"])
        used = [r for r in group if r["used"]]
        if not used:
            continue
        length = used[-1]["frame"] - used[0]["frame"] + EVEN_STEP
        pre = [r for r in group if used[0]["frame"] - length <= r["frame"] < used[0]["frame"]]
        post = [r for r in group
                if used[-1]["frame"] < r["frame"] <= used[-1]["frame"] + length]
        for name, band in (("PRE", pre), ("USED", used), ("POST", post)):
            if not band:
                continue
            for key in keys:
                values = [r[key] for r in band if r.get(key) is not None]
                if values:
                    bands[name].setdefault(key, []).append(st.median(values))
    print(f"  {'feature':22} {'PRE':>10} {'USED':>10} {'POST':>10}   clips")
    for key in keys:
        cells = []
        for name in ("PRE", "USED", "POST"):
            values = bands[name].get(key, [])
            cells.append(f"{st.median(values):10.3f}" if values else f"{'-':>10}")
        count = len(bands["USED"].get(key, []))
        print(f"  {key:22} {''.join(cells)}   {count:4d}")


def main() -> int:
    import random

    parser = argparse.ArgumentParser()
    parser.add_argument("project_id")
    parser.add_argument("--compare", type=Path, required=True)
    parser.add_argument("--manual", type=Path, required=True)
    parser.add_argument("--cuts", type=Path, required=True)
    parser.add_argument("--shutter", type=Path, required=True)
    parser.add_argument("--classes", type=Path, required=True)
    parser.add_argument("--vectors", type=Path)
    parser.add_argument("--semantic", type=Path)
    parser.add_argument("--out", type=Path, default=Path("signal_discovery.json"))
    args = parser.parse_args()

    from shutter_audit import read_cuts, shutter_mode

    rng = random.Random(SEED)
    canonical = {row["clip"] for row in json.loads(args.compare.read_text())}
    manual = json.loads(args.manual.read_text())
    cuts = read_cuts(args.cuts)
    classes = json.loads(args.classes.read_text())
    readings = json.loads(args.shutter.read_text())
    shutter = {}
    for clip, value in readings.items():
        mode, exposure, angle = shutter_mode(value)
        shutter[clip] = {"mode": mode, "exposure": exposure, "angle": angle}
    order = {}
    for index, cut in enumerate(cuts):
        order.setdefault(cut["clip"], index)

    vectors = {}
    if args.vectors and args.vectors.exists():
        loaded = np.load(args.vectors, allow_pickle=False)
        for key, vector in zip(loaded["keys"], loaded["vectors"], strict=True):
            norm = float(np.linalg.norm(vector))
            if norm > 0:
                vectors[str(key)] = vector / norm

    semantic = {}
    if args.semantic and args.semantic.exists():
        semantic = json.loads(args.semantic.read_text())
        # A charge is worth more as a reason to refuse than as a reason to prefer, so the two
        # negatives are flipped here and nowhere else: every feature in this file reads
        # "higher is more like what he used".
        GROUPS["S1 semantic defect"] = tuple(f"neg_{name}" for name in SEMANTIC_NEGATIVE)
        GROUPS["S2 semantic content"] = SEMANTIC_POSITIVE
        GROUPS["S3 semantic event"] = SEMANTIC_EVENT

    database = Database(database_path())
    rows, bar = build_rows(database, args.project_id, canonical, manual, cuts,
                           shutter, classes, vectors, order, semantic)
    clips = {r["clip"] for r in rows}
    used = sum(1 for r in rows if r["used"])
    print(f"B) DATASET — {len(rows)} windows over {len(clips)} clips; "
          f"{used} inside the stretch he used, {len(rows) - used} outside")
    print(f"   the shoot's median sharpness is {bar:.1f}")
    print(f"   window-level content vectors: {'yes, ' + str(len(vectors)) if vectors else 'none'}")

    print("\nC) SHUTTER MODE IN THIS SET")
    for mode in sorted({r["mode"] for r in rows}):
        group = {r["clip"] for r in rows if r["mode"] == mode}
        print(f"   {mode:22} {len(group):3d} clips")
    print("\nD) EDITORIAL TYPE IN THIS SET")
    for name in sorted({r["class"] for r in rows}):
        group = {r["clip"] for r in rows if r["class"] == name}
        print(f"   {name:22} {len(group):3d} clips")

    every = [f for features in GROUPS.values() for f in features]

    print("\nH) TASK A — USED AGAINST UNUSED, every clip")
    print("   within-clip pairwise ranking; 0.500 is chance")
    for group, features in GROUPS.items():
        if group in CONSTANT_WITHIN_CLIP:
            continue
        for key in features:
            report_feature(f"{group[0]}  {key}", rows, key, rng)
    for group in CONSTANT_WITHIN_CLIP:
        print(f"  {group:26} carries nothing here by construction: one value per clip")

    for label, wanted in (("I) NORMAL SHUTTER ONLY", "NORMAL_SHUTTER"),
                          ("J) CREATIVE LOW SHUTTER ONLY", "CREATIVE_LOW_SHUTTER")):
        subset = [r for r in rows if r["mode"] == wanted]
        names = {r["clip"] for r in subset}
        print(f"\n{label} — {len(names)} clips")
        if len(names) < 6:
            print("   LOW SAMPLE / INSUFFICIENT EVIDENCE")
            continue
        for group, features in GROUPS.items():
            if group in CONSTANT_WITHIN_CLIP:
                continue
            for key in features:
                report_feature(f"{group[0]}  {key}", subset, key, rng)

    print("\nK) PREPARATION, USED, TAIL — matched length, same grid")
    region_table(rows, ("sharpness", "motion", "face_count", "face_ratio", "face_edge",
                        "content_typical", "content_change", "like_previous"), bar)

    print("\nTASK A2 — USED AGAINST ITS OWN NEIGHBOURHOOD ONLY")
    print("   the same test, but the unused side is just the matched PRE and POST bands next")
    print("   to the cut rather than the whole clip. Coarse and fine, told apart.")
    near = neighbourhood(rows)
    print(f"   {len({r['clip'] for r in near})} clips, "
          f"{sum(1 for r in near if r['used'])} used windows, "
          f"{sum(1 for r in near if not r['used'])} neighbouring windows")
    for group, features in GROUPS.items():
        if group in CONSTANT_WITHIN_CLIP:
            continue
        for key in features:
            report_feature(f"{group[0]}  {key}", near, key, rng)
    value, total = model_pairwise(near, every, rng)
    print(f"  {'combined model':26} {value:.3f}   pairs {total:7d}")

    print("\nR2) HOW ALIKE A CLIP IS TO ITSELF — a proxy for editorial equivalence")
    spreads = clip_spread(rows)
    if spreads:
        ordered = sorted(spreads.items(), key=lambda kv: kv[1])
        print("   median cosine between a clip's own windows, most uniform first")
        for clip, value in ordered[:5]:
            print(f"     {clip:12} {value:.3f}   uniform: any stretch looks like any other")
        for clip, value in ordered[-5:]:
            print(f"     {clip:12} {value:.3f}   varied: the clip changes along its length")
        print(f"   across the set: median {st.median(list(spreads.values())):.3f}, "
              f"above 0.90 on {sum(1 for v in spreads.values() if v > 0.90)}/{len(spreads)}")

    print("\nTASK B — THE ENTRY NEIGHBOURHOOD against the rest of the clip")
    for group, features in GROUPS.items():
        if group in CONSTANT_WITHIN_CLIP:
            continue
        for key in features:
            report_feature(f"{group[0]}  {key}", rows, key, rng, label="entry")

    print("\nV) FEATURE-GROUP ABLATION — clip-grouped, held-out clips only")
    for group, features in GROUPS.items():
        if group in CONSTANT_WITHIN_CLIP:
            print(f"  {group:26}  excluded: constant within a clip")
            continue
        value, total = model_pairwise(rows, list(features), rng)
        print(f"  {group:26} {value:.3f}   pairs {total:7d}")
    value, total = model_pairwise(rows, every, rng)
    print(f"  {'J combined':26} {value:.3f}   pairs {total:7d}")

    if semantic:
        print("\nT) EXISTING AGAINST SEMANTIC, ON EXACTLY THE SAME ROWS")
        print("   the semantic answers exist only around each cut, so every comparison below")
        print("   is restricted to those windows and the frozen baseline is recomputed there.")
        existing = [f for group, features in GROUPS.items()
                    if not group.startswith(("S1", "S2", "S3"))
                    and group not in CONSTANT_WITHIN_CLIP
                    for f in features]
        semantic_features = [f for group, features in GROUPS.items()
                             if group.startswith(("S1", "S2", "S3")) for f in features]
        graded = [r for r in rows if all(r.get(f) is not None for f in semantic_features)]
        print(f"   {len(graded)} windows over {len({r['clip'] for r in graded})} clips")
        for name, chosen in (("existing features only", existing),
                             ("semantic only", semantic_features),
                             ("semantic defect only", list(GROUPS["S1 semantic defect"])),
                             ("existing + semantic", existing + semantic_features)):
            value, total = model_pairwise(graded, chosen, rng)
            print(f"  {name:26} {value:.3f}   pairs {total:7d}")

    print("\nW) SHUTTER-CONDITIONAL ABLATION")
    for wanted in ("NORMAL_SHUTTER", "CREATIVE_LOW_SHUTTER"):
        subset = [r for r in rows if r["mode"] == wanted]
        if len({r["clip"] for r in subset}) < 6:
            print(f"  {wanted:22} LOW SAMPLE / INSUFFICIENT EVIDENCE")
            continue
        print(f"  {wanted}")
        for group, features in GROUPS.items():
            if group in CONSTANT_WITHIN_CLIP:
                continue
            value, total = model_pairwise(subset, list(features), rng)
            print(f"    {group:24} {value:.3f}   pairs {total:7d}")
        value, total = model_pairwise(subset, every, rng)
        print(f"    {'combined':24} {value:.3f}   pairs {total:7d}")

    print("\nX) EVENT-CONDITIONAL DIAGNOSTIC")
    for wanted, name in ((False, "NON_EVENT"), (True, "ACTION_EVENT")):
        subset = [r for r in rows if (r["class"] == "ACTION_EVENT") == wanted]
        names = {r["clip"] for r in subset}
        if len(names) < 6:
            print(f"  {name:22} {len(names)} clips — LOW SAMPLE / INSUFFICIENT EVIDENCE")
            continue
        value, total = model_pairwise(subset, every, rng)
        print(f"  {name:22} {len(names):3d} clips   combined {value:.3f}   pairs {total:7d}")

    args.out.write_text(json.dumps(rows, indent=1, default=float))
    print(f"\nwritten {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
