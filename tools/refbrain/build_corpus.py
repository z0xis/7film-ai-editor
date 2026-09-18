"""P6.22 -- deterministic reference corpus builder (read-only; writes only sidecar JSON).

Ingests:
  Tier-1 rich edits  : V7 (narrative) + is edit (selects) raw Resolve traces, mapped to 15A shots for
                       category / shot_scale / chronology (read-only DB).
  Tier-2 render-only : the 18 references, from data/references/7film-style-profile.json (durations,
                       section medians, story position) -- the only per-shot evidence available for them.

Everything is deterministic (sorted iteration, no randomness). No production DB / Resolve / timeline
write; output goes to data/reference_editor/corpus/.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))
RAW = ROOT / "data" / "reference_editor" / "raw"
OUT = ROOT / "data" / "reference_editor" / "corpus"
DB = ROOT / "data" / "sevenfilm.sqlite3"
P15 = "29cd1e06-0af1-40c4-95bf-77f2add1159f"
PROFILE = ROOT / "data" / "references" / "7film-style-profile.json"

from tools.refbrain.schema import (
    CATEGORY_EVENT,
    SCHEMA_VERSION,
    STORY_ROLES,
    ReferenceEdit,
    ReferenceEventEpisode,
    ReferenceSequence,
    ReferenceShot,
    ReferenceTransition,
)


def _fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.is_file() else "absent"


def _shot_lookup():
    """asset_name -> sorted list of (source_start, source_dur, category, scale); plus asset day_position."""
    from sevenfilm.db import Database
    from sevenfilm.services.media import project_assets
    from sevenfilm.services.planner import _day_position
    day = _day_position(project_assets(Database(DB), P15))  # asset_id -> day_position
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """SELECT m.file_name, s.asset_id, s.start_frame, s.duration_frames,
                  s.category, s.shot_scale
           FROM shots s JOIN media_assets m ON m.id = s.asset_id
           WHERE m.project_id = ? ORDER BY m.file_name, s.start_frame""", (P15,)).fetchall()
    con.close()
    by_name: dict[str, list] = {}
    for r in rows:
        by_name.setdefault(r["file_name"], []).append(
            (r["start_frame"], r["duration_frames"], r["category"], r["shot_scale"],
             day.get(r["asset_id"])))
    return by_name


def _match(by_name, name, source_in):
    """The 15A shot whose source range contains source_in (fallback: nearest)."""
    shots = by_name.get(name)
    if not shots:
        return None
    for start, dur, cat, scale, dp in shots:
        if start <= source_in < start + dur:
            return cat, scale, dp
    nearest = min(shots, key=lambda s: abs(s[0] - source_in))
    return nearest[2], nearest[3], nearest[4]


def _ingest_rich(trace: dict, by_name) -> tuple[ReferenceEdit, list[ReferenceShot]]:
    rid = trace["name"]
    fps = trace["fps"]
    start = trace["start"]
    shots = []
    for i, (name, tl_start, tl_dur, left) in enumerate(trace["items"]):
        m = _match(by_name, name, left)
        cat, scale, dp = m if m else (None, None, None)
        shots.append(ReferenceShot(
            reference_id=rid, shot_index=i,
            timeline_in=tl_start - start, timeline_out=tl_start - start + tl_dur,
            duration_s=round(tl_dur / fps, 3),
            source_asset=name, source_in=left, source_out=left + tl_dur,
            category=cat, shot_scale=scale, event=CATEGORY_EVENT.get(cat or "", "OTHER"),
            day_position=dp))
    dur = sum(s.duration_s for s in shots)
    edit = ReferenceEdit(
        reference_id=rid, source="Resolve:15 Agustos", tier=1, kind=trace["kind"],
        project=trace["project"], duration_s=round(dur, 2), fps=fps, n_shots=len(shots),
        music_tracks=[a[0] for a in trace.get("audio", [])],
        available_evidence=["timeline_order", "source_in_out", "category", "shot_scale", "chronology"]
        + (["music"] if trace.get("audio") else []))
    return edit, shots


def _ingest_tier2(profile: dict) -> tuple[list[ReferenceEdit], list[ReferenceShot]]:
    edits, shots = [], []
    for ref in sorted(profile.get("references", []), key=lambda r: r["id"]):
        rid = f"ref:{ref['id']}"
        durs = ref.get("shot_durations_seconds") or []
        for i, d in enumerate(durs):
            shots.append(ReferenceShot(
                reference_id=rid, shot_index=i, timeline_in=-1, timeline_out=-1,
                duration_s=round(float(d), 3)))
        edits.append(ReferenceEdit(
            reference_id=rid, source=ref.get("url", "render_only"), tier=2, kind="render_only",
            project=ref.get("title", rid), duration_s=round(float(ref.get("duration_seconds", 0)), 2),
            fps=0.0, n_shots=len(durs),
            music_tracks=[], available_evidence=["shot_durations", "bpm", "section_medians",
                                                 "story_position"]))
    return edits, shots


def _segment_events(shots: list[ReferenceShot]) -> list[ReferenceEventEpisode]:
    """Group consecutive shots sharing an event into episodes (rich edits only)."""
    episodes = []
    if not shots or shots[0].timeline_in < 0:
        return episodes
    total = shots[-1].timeline_out / 1.0
    fps_dur = total  # timeline_out is in frames-from-start
    run = [shots[0]]
    for s in shots[1:]:
        if s.event == run[-1].event:
            run.append(s)
        else:
            episodes.append(_episode(run, fps_dur))
            run = [s]
    episodes.append(_episode(run, fps_dur))
    return episodes


def _episode(run, total_frames) -> ReferenceEventEpisode:
    return ReferenceEventEpisode(
        reference_id=run[0].reference_id, event_type=run[0].event or "OTHER",
        timeline_start_s=round(run[0].timeline_in / 50.0, 2),
        timeline_end_s=round(run[-1].timeline_out / 50.0, 2),
        n_shots=len(run), phases=[s.shot_scale or "?" for s in run][:6])


def _story_role(position: float) -> str:
    return STORY_ROLES[min(len(STORY_ROLES) - 1, int(position * len(STORY_ROLES)))]


def _descriptor(window, position, total_dur) -> list[float]:
    scales = {"wide": 0, "medium": 1, "close_up": 2, "detail": 3}
    mean_dur = sum(s.duration_s for s in window) / len(window)
    mean_scale = sum(scales.get(s.shot_scale or "medium", 1) for s in window) / len(window)
    reuse = 1.0 if len({s.source_asset for s in window}) < len(window) else 0.0
    drone = sum(1 for s in window if (s.source_asset or "").startswith("DJI_")) / len(window)
    return [round(position, 4), round(mean_dur, 4), round(mean_scale, 4), round(reuse, 4),
            round(drone, 4), round(len(window) / 5.0, 4)]


def _sequences(shots: list[ReferenceShot], tier: int, window_sizes=(2, 3, 4, 5)) -> list[ReferenceSequence]:
    seqs = []
    if not shots:
        return seqs
    rich = shots[0].timeline_in >= 0
    total_dur = (shots[-1].timeline_out / 50.0) if rich else sum(s.duration_s for s in shots)
    n = len(shots)
    for w in window_sizes:
        for i in range(n - w + 1):
            win = shots[i:i + w]
            if rich:
                mid = (win[0].timeline_in + win[-1].timeline_out) / 2 / 50.0
                pos = mid / total_dur if total_dur else 0.0
            else:
                pos = (i + w / 2) / n
            assets = [s.source_asset for s in win]
            reuse = len({a for a in assets if a}) < len([a for a in assets if a])
            fwd = False
            for a in set(assets):
                if a and assets.count(a) > 1:
                    ins = [s.source_in for s in win if s.source_asset == a and s.source_in is not None]
                    fwd = fwd or (ins == sorted(ins) and len(ins) > 1)
            seqs.append(ReferenceSequence(
                sequence_id=f"{shots[0].reference_id}#w{w}i{i}",
                reference_id=shots[0].reference_id, tier=tier,
                story_role=_story_role(pos),
                event_type=win[len(win) // 2].event or "OTHER",
                story_position=round(pos, 4),
                timeline_start_s=round(win[0].timeline_in / 50.0, 2) if rich else -1.0,
                duration_s=round(sum(s.duration_s for s in win), 3),
                n_shots=w, shot_indices=[s.shot_index for s in win],
                scale_pattern=[s.shot_scale or "?" for s in win],
                category_pattern=[s.category or "?" for s in win],
                shot_durations_s=[s.duration_s for s in win],
                source_reuse=reuse, forward_progression=fwd,
                descriptor=_descriptor(win, pos, total_dur)))
    return seqs


def _transitions(shots: list[ReferenceShot]) -> list[ReferenceTransition]:
    from itertools import pairwise
    trans = []
    for a, b in pairwise(shots):
        if a.event != b.event and a.timeline_in >= 0:
            trans.append(ReferenceTransition(
                reference_id=a.reference_id, at_s=round(b.timeline_in / 50.0, 2),
                before_event=a.event or "OTHER", after_event=b.event or "OTHER",
                before_energy=None, after_energy=None, song_seam=False, energy_delta="flat"))
    return trans


def build() -> dict:
    by_name = _shot_lookup()
    edits, shots, seqs, episodes, transitions = [], [], [], [], []

    for fname in sorted(RAW.glob("*_trace.json")):
        trace = json.loads(fname.read_text())
        edit, es = _ingest_rich(trace, by_name)
        edits.append(edit)
        shots += es
        seqs += _sequences(es, tier=1)
        episodes += _segment_events(es)
        transitions += _transitions(es)

    profile = json.loads(PROFILE.read_text())
    t2_edits, t2_shots = _ingest_tier2(profile)
    edits += t2_edits
    by_ref: dict[str, list] = {}
    for s in t2_shots:
        by_ref.setdefault(s.reference_id, []).append(s)
    for rid in sorted(by_ref):
        seqs += _sequences(by_ref[rid], tier=2)
    shots += t2_shots

    corpus = {
        "schema_version": SCHEMA_VERSION,
        "build_version": 1,
        "source_fingerprint": {"db": _fingerprint(DB)[:12], "style_profile": _fingerprint(PROFILE)},
        "created_from": ["Resolve:IS EDIT - AI CUT V7", "Resolve:is edit",
                         "data/references/7film-style-profile.json (18 refs)"],
        "counts": {"edits": len(edits), "shots": len(shots), "sequences": len(seqs),
                   "episodes": len(episodes), "transitions": len(transitions),
                   "tier1_edits": sum(1 for e in edits if e.tier == 1),
                   "tier2_edits": sum(1 for e in edits if e.tier == 2)},
        "edits": [e.to_dict() for e in edits],
        "episodes": [e.to_dict() for e in episodes],
        "transitions": [t.to_dict() for t in transitions],
        "sequences": [s.to_dict() for s in seqs],
        "shots": [s.to_dict() for s in shots],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "corpus.json").write_text(json.dumps(corpus, indent=1, sort_keys=True))
    return corpus


if __name__ == "__main__":
    c = build()
    print(json.dumps({"schema": c["schema_version"], **c["counts"],
                      "fingerprint": c["source_fingerprint"]}, indent=2))
