"""Read the temporal probe's answers against the editor's cuts and the order controls.

Four things have to hold before a temporal signal can be called one, and each is reported on its
own rather than folded into a score:

  A  on the cake, the stretch he used reads further into the action than the preparation
  B  reversing or shuffling the frames changes the answer
  C  five copies of the centre frame do not give the same answer as the real strip
  D  on clips with no event in them, the model does not keep finding one

The within-clip ranking is the same one used for every earlier feature: a used centre against an
unused one from the same clip, 0.500 is chance. With one cake and three other events, these are
diagnostics, and no interval here should be read as certainty.

Read-only.
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from pathlib import Path


def pairwise(records, condition, key, positive=True) -> tuple[float, int]:
    used = [r[condition][key] for r in records
            if r["band"] == "USED" and key in r.get(condition, {})]
    rest = [r[condition][key] for r in records
            if r["band"] != "USED" and key in r.get(condition, {})]
    wins = ties = total = 0
    for a in used:
        for b in rest:
            total += 1
            if (a > b) if positive else (a < b):
                wins += 1
            elif a == b:
                ties += 1
    return ((wins + ties / 2) / total if total else float("nan")), total


def band_medians(records, condition, key):
    out = {}
    for band in ("PRE", "USED", "POST"):
        values = [r[condition][key] for r in records
                  if r["band"] == band and key in r.get(condition, {})]
        out[band] = st.median(values) if values else None
    return out


def fmt(value):
    return f"{value:.3f}" if isinstance(value, float) else "  -  "


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", type=Path)
    args = parser.parse_args()
    data = json.loads(args.results.read_text())

    cake = data.get("C2075.MP4")
    if cake:
        records = cake["records"]
        print(f"I) C2075 — {len(records)} centres, cut at {cake['cut']}")
        print(f"   PRE {sum(r['band'] == 'PRE' for r in records)}  "
              f"USED {sum(r['band'] == 'USED' for r in records)}  "
              f"POST {sum(r['band'] == 'POST' for r in records)}")
        print(f"   {'condition':10} {'question':14} {'PRE':>7} {'USED':>7} {'POST':>7} "
              f"{'pairwise':>9}")
        for condition in ("single", "forward", "static", "reversed", "shuffled", "no_centre"):
            for key, positive in (("t_knife_in", True), ("t_not_started", False),
                                  ("t_underway", True), ("t_begins", True),
                                  ("t_changes", True)):
                if not any(key in r.get(condition, {}) for r in records):
                    continue
                medians = band_medians(records, condition, key)
                value, _ = pairwise(records, condition, key, positive)
                print(f"   {condition:10} {key:14} {fmt(medians['PRE']):>7} "
                      f"{fmt(medians['USED']):>7} {fmt(medians['POST']):>7} {value:9.3f}")

        print("\nK-N) ORDER CONTROLS ON THE CAKE — mean absolute change from forward")
        for condition in ("reversed", "shuffled", "static", "no_centre"):
            for key in ("t_knife_in", "t_not_started", "t_underway", "t_begins", "t_changes"):
                deltas = [abs(r[condition][key] - r["forward"][key]) for r in records
                          if key in r.get(condition, {}) and key in r.get("forward", {})]
                if deltas:
                    print(f"   {condition:10} {key:14} {st.mean(deltas):.3f}   "
                          f"max {max(deltas):.3f}")

    print("\nJ) OTHER ACTION EVENTS — generic questions, forward order  (LOW SAMPLE)")
    for clip, entry in sorted(data.items()):
        if entry["class"] != "ACTION_EVENT" or clip == "C2075.MP4":
            continue
        records = entry["records"]
        cells = []
        for key in ("t_underway", "t_begins", "t_changes"):
            value, _ = pairwise(records, "forward", key)
            static, _ = pairwise(records, "static", key)
            reverse = st.mean([abs(r["reversed"][key] - r["forward"][key]) for r in records
                               if "reversed" in r]) if records else float("nan")
            cells.append(f"{key} fwd {value:.2f} static {static:.2f} |rev-fwd| {reverse:.3f}")
        print(f"   {clip:12} n={len(records):2d}  " + "   ".join(cells))

    print("\nO) NON-EVENT CONTROLS — how often the model says a new action begins")
    for clip, entry in sorted(data.items()):
        if entry["class"] == "ACTION_EVENT":
            continue
        records = entry["records"]
        begins = [r["forward"]["t_begins"] for r in records if "forward" in r]
        changes = [r["forward"]["t_changes"] for r in records if "forward" in r]
        static = [r["static"]["t_begins"] for r in records if "static" in r]
        used = band_medians(records, "forward", "t_underway")
        print(f"   {clip:12} {entry['label'] or entry['class']:22} n={len(records):2d}  "
              f"P(begins) median {st.median(begins):.3f}  >0.5 on "
              f"{sum(b > 0.5 for b in begins)}/{len(begins)}   "
              f"P(changes) {st.median(changes):.3f}   static P(begins) "
              f"{st.median(static):.3f}   underway PRE/USED/POST "
              f"{fmt(used['PRE'])}/{fmt(used['USED'])}/{fmt(used['POST'])}")

    events = [e for c, e in data.items() if e["class"] == "ACTION_EVENT"]
    others = [e for c, e in data.items() if e["class"] != "ACTION_EVENT"]
    for name, group in (("events", events), ("non-events", others)):
        begins = [r["forward"]["t_begins"] for e in group for r in e["records"]
                  if "forward" in r]
        static = [r["static"]["t_begins"] for e in group for r in e["records"]
                  if "static" in r]
        if begins:
            print(f"   {name:10} P(begins) forward median {st.median(begins):.3f}  "
                  f"static {st.median(static):.3f}   >0.5 forward "
                  f"{sum(b > 0.5 for b in begins)}/{len(begins)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
