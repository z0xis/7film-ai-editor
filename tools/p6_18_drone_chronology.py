"""P6.18 -- shadow-only drone chronology inference + shadow-planner injection.

Timecoded camera shots (SMPTE) are the trusted chronology backbone (`_day_position`). For each
timecodeless drone shot we estimate a `day_position` by embedding-consensus over its most similar
camera anchors (trimmed median of the top-K above a similarity floor), with a confidence tier from
support and dispersion. The drones' embedded `creation_time` (monotonic with filename order, on the
drone's own clock) is used ONLY as an independent monotonicity check at asset level -- never V7/is-edit
timings. Nothing is written to the DB; the planner sees the inference only through a shadow wrapper
that overrides `day_position` for confident drone shots.

Modes:
  holdout  -- hide camera day_positions and measure inference error (objective validation)
  infer    -- write the drone chronology fixture (per-shot estimates + tiers + asset table)
  shadow   -- run the planner three ways (baseline / HIGH / HIGH+MEDIUM) with the overlay injected
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
import os

os.environ.pop("SEVENFILM_DATA_ROOT", None)
DB = ROOT / "data" / "sevenfilm.sqlite3"
P15 = "29cd1e06-0af1-40c4-95bf-77f2add1159f"
FIX = ROOT / "tools" / "fixtures"

MIN_SIM = 0.55
TOPK = 25
HIGH = {"min_support": 8, "max_dispersion": 0.12}
MEDIUM = {"min_support": 5, "max_dispersion": 0.20}


def _load():
    import sqlite3

    from sevenfilm.db import Database
    from sevenfilm.services.media import project_assets
    from sevenfilm.services.planner import _day_position
    db = Database(DB)
    dp = _day_position(project_assets(db, P15))  # asset_id -> day_position (timecoded only)
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT sf.shot_id, sf.asset_id, sf.embedding, m.file_name, m.timecode, m.metadata_json,
                  sf.start_frame
           FROM shot_features sf JOIN media_assets m ON m.id = sf.asset_id
           WHERE m.project_id = ? AND sf.embedding IS NOT NULL ORDER BY sf.asset_id, sf.start_frame""",
        (P15,)).fetchall()
    conn.close()
    cam, drone = [], []
    for r in rows:
        e = np.frombuffer(r["embedding"], dtype=np.float32)
        e = e / (np.linalg.norm(e) + 1e-9)
        rec = {"shot_id": r["shot_id"], "asset_id": r["asset_id"], "emb": e,
               "name": r["file_name"], "start_frame": r["start_frame"]}
        if r["timecode"] and r["asset_id"] in dp:
            rec["day"] = dp[r["asset_id"]]
            cam.append(rec)
        elif r["file_name"].startswith("DJI_"):
            md = json.loads(r["metadata_json"] or "{}")
            rec["ctime"] = md.get("format", {}).get("tags", {}).get("creation_time")
            drone.append(rec)
    return cam, drone


def _consensus(emb, cam_E, cam_Y, exclude_asset=None, cam_A=None):
    sims = cam_E @ emb
    if exclude_asset is not None:
        sims = np.where(cam_A == exclude_asset, -1.0, sims)
    top = np.argpartition(-sims, TOPK)[:TOPK]
    w = sims[top]
    keep = w >= MIN_SIM
    if keep.sum() < MEDIUM["min_support"]:
        return None
    ys = cam_Y[top][keep]
    est = float(np.median(ys))
    dispersion = float(np.percentile(np.abs(ys - est), 75))  # robust spread
    return {"est": round(est, 4), "support": int(keep.sum()), "dispersion": round(dispersion, 4)}


def _tier(c):
    if c is None:
        return "UNRESOLVED"
    if c["support"] >= HIGH["min_support"] and c["dispersion"] <= HIGH["max_dispersion"]:
        return "HIGH"
    if c["support"] >= MEDIUM["min_support"] and c["dispersion"] <= MEDIUM["max_dispersion"]:
        return "MEDIUM"
    return "LOW"


def run_holdout() -> dict:
    cam, _ = _load()
    E = np.stack([r["emb"] for r in cam]); Y = np.array([r["day"] for r in cam])
    A = np.array([r["asset_id"] for r in cam])
    rng = np.random.default_rng(0)
    idx = rng.choice(len(E), min(300, len(E)), replace=False)
    errs = []; region_ok = 0; region_n = 0
    for i in idx:
        c = _consensus(E[i], E, Y, exclude_asset=A[i], cam_A=A)
        if c is None:
            continue
        errs.append(abs(c["est"] - Y[i]))
        region_n += 1
        region_ok += int(min(4, int(c["est"] * 5)) == min(4, int(Y[i] * 5)))
    errs = np.array(errs)
    out = {"n": len(errs), "median_err": round(float(np.median(errs)), 4),
           "p90_err": round(float(np.percentile(errs, 90)), 4), "mean_err": round(float(errs.mean()), 4),
           "event_region_accuracy": round(region_ok / max(1, region_n), 3)}
    (FIX / "p6_18_holdout.json").write_text(json.dumps(out, indent=2, sort_keys=True))
    return out


def infer() -> dict:
    cam, drone = _load()
    E = np.stack([r["emb"] for r in cam]); Y = np.array([r["day"] for r in cam])
    est = {}
    for d in drone:
        c = _consensus(d["emb"], E, Y)
        est[d["shot_id"]] = {"est": c["est"] if c else None, "tier": _tier(c),
                             "support": c["support"] if c else 0,
                             "dispersion": c["dispersion"] if c else None,
                             "asset": d["name"], "start_frame": d["start_frame"]}
    # asset-level monotonicity check against drone creation_time order
    ctimes = {d["name"]: d["ctime"] for d in drone}

    def ctime_key(name):
        t = ctimes.get(name)
        return datetime.fromisoformat(t) if t else datetime.min.replace(tzinfo=UTC)
    per_asset = defaultdict(list)
    for v in est.values():
        if v["est"] is not None:
            per_asset[v["asset"]].append(v["est"])
    asset_order = sorted(per_asset, key=ctime_key)
    asset_median = {n: float(np.median(per_asset[n])) for n in per_asset}
    monotonic_pairs = 0; total_pairs = 0
    for i in range(len(asset_order) - 1):
        a, b = asset_order[i], asset_order[i + 1]
        total_pairs += 1
        monotonic_pairs += int(asset_median[a] <= asset_median[b] + 0.05)
    tiers = defaultdict(int)
    for v in est.values():
        tiers[v["tier"]] += 1
    result = {"estimates": est,
              "tier_counts": dict(tiers),
              "asset_median_day": {n: round(asset_median[n], 3) for n in asset_order},
              "asset_creation_order": asset_order,
              "asset_monotonic_fraction": round(monotonic_pairs / max(1, total_pairs), 3)}
    (FIX / "p6_18_drone_chronology.json").write_text(json.dumps(result, indent=2, sort_keys=True))
    return {k: v for k, v in result.items() if k != "estimates"}


def run_shadow(tiers_allowed) -> dict:
    data = json.loads((FIX / "p6_18_drone_chronology.json").read_text())["estimates"]
    inferred = {sid: v["est"] for sid, v in data.items()
                if v["est"] is not None and v["tier"] in tiers_allowed}
    _spec = importlib.util.spec_from_file_location("p6_14_shadow", ROOT / "tools/p6_14_shadow_planner.py")
    h = importlib.util.module_from_spec(_spec)
    tag = "+".join(sorted(tiers_allowed)) or "baseline"
    # patch the planner to override day_position for confident drone shots (shadow only)
    from sevenfilm.services import planner
    real = planner._score_candidate

    def wrapped(shot, **kw):
        if shot.id in inferred:
            kw = dict(kw); kw["day_position"] = inferred[shot.id]
        return real(shot, **kw)

    planner._score_candidate = wrapped
    _spec.loader.exec_module(h)
    # Set the output AFTER exec_module (which resets the module's own FIXTURE), before main().
    h.FIXTURE = FIX / f"p6_18_shadow_{tag}.json"
    try:
        out = h.main()
    finally:
        planner._score_candidate = real
    return out


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "holdout"
    if mode == "holdout":
        print(json.dumps(run_holdout(), indent=2))
    elif mode == "infer":
        print(json.dumps(infer(), indent=2))
    elif mode == "shadow_high":
        run_shadow({"HIGH"})
        print("wrote HIGH shadow")
    elif mode == "shadow_highmed":
        run_shadow({"HIGH", "MEDIUM"})
        print("wrote HIGH+MEDIUM shadow")
