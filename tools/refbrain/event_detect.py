"""P6.24 -- fine wedding-EVENT detection for the render-only (Tier-2) references.

Not single-frame -> label. For each shot we sample THREE frames (early/mid/late), score them against
per-event PROMPT ENSEMBLES (positive prompts minus confusable negatives) using the project's own CLIP
text tower, then combine multi-frame + temporal-neighbour + motion + a soft story-position prior into a
calibrated event with a confidence band. EVENT != category. Deterministic. Output:
data/reference_editor/tier2_events/<id>.json (gitignored). No DB/Resolve write.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))
MEDIA = ROOT / "data" / "references" / "media"
TIER2 = ROOT / "data" / "reference_editor" / "tier2"
OUT = ROOT / "data" / "reference_editor" / "tier2_events"

# event -> positive prompts + confusable negatives (event != category)
EVENT_PROMPTS = {
    "PREPARATION": {
        "pos": ["a bride getting ready with makeup and hair before the wedding",
                "wedding preparation, getting dressed, hair and makeup"],
        "neg": ["a dance party", "a wedding ceremony", "cutting a cake"]},
    "ENTRANCE": {
        "pos": ["the newlyweds making a grand entrance into the reception",
                "bride and groom entering the wedding party as guests cheer"],
        "neg": ["people simply walking outdoors", "a couple standing still", "guests dancing"]},
    "CEREMONY": {
        "pos": ["a wedding ceremony with the couple at the altar",
                "the wedding ceremony, officiant and vows"],
        "neg": ["a dance party", "a cake table", "getting ready in a room"]},
    "RING": {
        "pos": ["close-up of exchanging wedding rings", "putting the wedding ring on the finger"],
        "neg": ["a wide venue shot", "a crowd dancing", "a cake"]},
    "KISS": {
        "pos": ["the bride and groom kissing", "a wedding kiss between the couple"],
        "neg": ["guests dancing", "a cake table", "a wide landscape"]},
    "CAKE": {
        "pos": ["bride and groom cutting the wedding cake together",
                "the wedding cake cutting ceremony with the couple holding the knife"],
        "neg": ["a decorated cake table with no people", "a couple standing near a cake not cutting it",
                "guests dancing at a party"]},
    "FIRST_DANCE": {
        "pos": ["the newlywed couple performing their first dance alone",
                "bride and groom dancing together as the sole focus on the dance floor"],
        "neg": ["a crowd of guests dancing at the party", "many people dancing together",
                "a group celebration on the dance floor"]},
    "BOUQUET": {
        "pos": ["the bride tossing the bouquet to the guests",
                "bouquet toss, flowers thrown into a crowd of women"],
        "neg": ["a bride holding her bouquet in a portrait", "a flower arrangement on a table",
                "a couple posing"]},
    "PARTY": {
        "pos": ["guests dancing and celebrating at the wedding party",
                "a lively wedding reception dance floor with a crowd"],
        "neg": ["the couple alone dancing", "a quiet ceremony", "getting ready"]},
    "KINA": {
        "pos": ["a traditional henna night celebration with traditional dress",
                "kina gecesi, traditional Turkish wedding henna ceremony"],
        "neg": ["a western white-dress dance party", "a ceremony at an altar", "cutting a cake"]},
    "SPARKLER_SENDOFF": {
        "pos": ["a sparkler send-off with the couple and sparklers at night",
                "guests holding sparklers celebrating the couple"],
        "neg": ["a daytime portrait", "a cake table", "a quiet ceremony"]},
}

# soft story-position prior (mean, spread) per event -- a PRIOR, never a hard label
POSITION_PRIOR = {
    "PREPARATION": (0.15, 0.25), "ENTRANCE": (0.45, 0.2), "CEREMONY": (0.35, 0.3),
    "RING": (0.35, 0.3), "KISS": (0.4, 0.3), "CAKE": (0.6, 0.25),
    "FIRST_DANCE": (0.6, 0.25), "BOUQUET": (0.75, 0.2), "PARTY": (0.8, 0.25),
    "KINA": (0.7, 0.3), "SPARKLER_SENDOFF": (0.9, 0.15),
}
EVENTS = list(EVENT_PROMPTS)
CONF = [("HIGH", 0.06), ("MEDIUM", 0.03), ("LOW", 0.0)]


def _text_features(clf, prompts):
    proc, model, torch, dev = clf._processor, clf._model, clf._torch, clf._device
    ti = proc(text=prompts, return_tensors="pt", padding=True)
    ti = {k: v.to(dev) for k, v in ti.items()}
    with torch.inference_mode():
        tf = model.get_text_features(**ti)
        if hasattr(tf, "pooler_output"):
            tf = tf.pooler_output
        tf = tf / tf.norm(dim=-1, keepdim=True)
    return tf.float().cpu().numpy()


def _prior(event, pos):
    mu, sig = POSITION_PRIOR.get(event, (0.5, 0.5))
    return float(np.exp(-0.5 * ((pos - mu) / sig) ** 2))  # 0..1 gaussian


def detect_one(path: Path, enriched: dict, clf, prompt_feats) -> dict:
    scenes = [(s["start_s"], s["end_s"]) for s in enriched["shots"]]
    cap = cv2.VideoCapture(str(path))
    # sample 3 frames per shot
    frames, owner = [], []
    for i, (a, b) in enumerate(scenes):
        for t in (a + (b - a) * 0.2, (a + b) / 2, a + (b - a) * 0.8):
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, img = cap.read()
            if ok:
                frames.append(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
                owner.append(i)
    cap.release()
    feats = clf.encode(frames) if frames else None
    # per-shot raw event score = mean(pos sim) - max(neg sim), averaged over that shot's frames
    raw = [dict.fromkeys(EVENTS, -1.0) for _ in scenes]
    if feats is not None:
        by_shot: dict[int, list] = {}
        for f_idx, sh in enumerate(owner):
            by_shot.setdefault(sh, []).append(feats[f_idx])
        for sh, fl in by_shot.items():
            fa = np.stack(fl)
            ev_scores = {}
            for ev in EVENTS:
                pf, nf = prompt_feats[ev]
                pos = (fa @ pf.T).mean(axis=1).mean()
                neg = (fa @ nf.T).max(axis=1).mean()
                ev_scores[ev] = float(pos - neg)
            raw[sh] = ev_scores
    # temporal smoothing over neighbours
    smoothed = []
    for i in range(len(scenes)):
        acc = dict.fromkeys(EVENTS, 0.0)
        wsum = 0.0
        for j, w in ((i, 0.6), (i - 1, 0.2), (i + 1, 0.2)):
            if 0 <= j < len(scenes):
                for ev in EVENTS:
                    acc[ev] += w * raw[j][ev]
                wsum += w
        smoothed.append({ev: acc[ev] / wsum for ev in EVENTS})
    # combine with soft prior + assign
    shots_out = []
    for i, (a, b) in enumerate(scenes):
        pos = enriched["shots"][i]["story_position"]
        combined = {ev: smoothed[i][ev] + 0.02 * _prior(ev, pos) for ev in EVENTS}
        ranked = sorted(combined.items(), key=lambda kv: -kv[1])
        top, top_v = ranked[0]
        margin = top_v - ranked[1][1]
        band = next((name for name, thr in CONF if margin >= thr), "LOW")
        conf = band if top_v > 0 else "UNKNOWN"
        shots_out.append({
            "shot_index": i, "story_position": pos,
            "top_event": top if conf != "UNKNOWN" else "UNKNOWN",
            "event_confidence": conf, "margin": round(margin, 4),
            "top_score": round(top_v, 4),
            "event_scores": {ev: round(combined[ev], 4) for ev in EVENTS},
            "category": enriched["shots"][i].get("category"),
            "motion_band": enriched["shots"][i].get("motion_band"),
        })
    return {"reference_id": enriched["reference_id"], "video": path.name,
            "n_shots": len(scenes), "model": "clip-vit-base-patch32",
            "shots": shots_out}


def run(only: str | None = None) -> dict:
    from sevenfilm.services.vision import VisionClassifier
    clf = VisionClassifier()
    if not clf._load():
        raise RuntimeError("CLIP unavailable")
    prompt_feats = {ev: (_text_features(clf, p["pos"]), _text_features(clf, p["neg"]))
                    for ev, p in EVENT_PROMPTS.items()}
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {}
    for ef in sorted(TIER2.glob("*.json")):
        enriched = json.loads(ef.read_text())
        stem = ef.stem
        if only and stem != only:
            continue
        path = MEDIA / f"{stem}.mkv"
        if not path.is_file():
            continue
        res = detect_one(path, enriched, clf, prompt_feats)
        (OUT / f"{stem}.json").write_text(json.dumps(res, indent=1, sort_keys=True))
        from collections import Counter
        summary[res["reference_id"]] = dict(Counter(s["top_event"] for s in res["shots"]))
    return summary


if __name__ == "__main__":
    only = sys.argv[1] if len(sys.argv) > 1 else None
    print(json.dumps(run(only), indent=2, sort_keys=True))
