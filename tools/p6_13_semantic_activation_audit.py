"""P6.13 -- Read-only production semantic / moment activation audit. No writes of any kind.

Drives the REAL production moment/eligibility logic against the remediated production DB through a
strictly read-only connection (mode=ro duck-type exposing only fetch_all), and records what the
restored CLIP embeddings now activate: moments, candidate eligibility (`_is_usable`), chronology
availability, drone status, distractions/obstructions/opening_signs. Writes a JSON fixture only.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
DB = ROOT / "data" / "sevenfilm.sqlite3"
P15 = "29cd1e06-0af1-40c4-95bf-77f2add1159f"
ELENORA = "df2a4a62-e821-40f7-86fc-b6a9259e9ee9"
FIXTURE = ROOT / "tools" / "fixtures" / "p6_13_activation_audit.json"


class ReadOnlyDatabase:
    """Only fetch_all, backed by a mode=ro connection -- cannot write even by accident."""

    def __init__(self, path: Path) -> None:
        self._c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        self._c.row_factory = sqlite3.Row

    def fetch_all(self, sql: str, params: tuple = ()) -> list[dict]:
        return [dict(r) for r in self._c.execute(sql, params).fetchall()]

    def fetch_one(self, sql: str, params: tuple = ()):
        row = self._c.execute(sql, params).fetchone()
        return dict(row) if row else None


def main() -> dict:
    from sevenfilm.services.analysis import project_shots
    from sevenfilm.services.moments import (
        project_distractions,
        project_moments,
        project_obstructions,
        project_opening_signs,
    )
    from sevenfilm.services.planner import ABSOLUTE_MIN_QUALITY, MAX_HIGHLIGHT_CLIPPING, _is_usable

    ro = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    ro.row_factory = sqlite3.Row
    db = ReadOnlyDatabase(DB)

    def one(sql, *a):
        return ro.execute(sql, a).fetchone()[0]

    # asset_id -> file_name, timecode (chronology availability)
    asset_rows = ro.execute(
        "SELECT id, file_name, timecode FROM media_assets WHERE project_id=?", (P15,)).fetchall()
    asset_name = {r["id"]: r["file_name"] for r in asset_rows}
    asset_tc = {r["id"]: (r["timecode"] not in (None, "")) for r in asset_rows}
    shot_asset = {r["id"]: r["asset_id"] for r in ro.execute(
        "SELECT s.id, s.asset_id FROM shots s JOIN media_assets m ON m.id=s.asset_id "
        "WHERE m.project_id=?", (P15,)).fetchall()}

    # --- shot_windows audit (read-only) ---
    windows = {
        "total_all_projects": one("SELECT COUNT(*) FROM shot_windows"),
        "for_15a": one("SELECT COUNT(*) FROM shot_windows w JOIN shots s ON s.id=w.shot_id "
                       "JOIN media_assets m ON m.id=s.asset_id WHERE m.project_id=?", P15),
        "orphan_windows": one("SELECT COUNT(*) FROM shot_windows WHERE shot_id NOT IN "
                              "(SELECT id FROM shots)"),
        "distinct_shots_with_windows_15a": one(
            "SELECT COUNT(DISTINCT w.shot_id) FROM shot_windows w JOIN shots s ON s.id=w.shot_id "
            "JOIN media_assets m ON m.id=s.asset_id WHERE m.project_id=?", P15),
    }

    # --- eligibility over all 2638 shots ---
    shots = project_shots(db, P15)
    usable = blocked_quality = blocked_clip = 0
    for sh in shots:
        if _is_usable(sh, ABSOLUTE_MIN_QUALITY, MAX_HIGHLIGHT_CLIPPING):
            usable += 1
        elif sh.technical_quality < ABSOLUTE_MIN_QUALITY:
            blocked_quality += 1
        else:
            blocked_clip += 1
    usable_ids = {sh.id for sh in shots
                  if _is_usable(sh, ABSOLUTE_MIN_QUALITY, MAX_HIGHLIGHT_CLIPPING)}

    # --- moments (real production logic, read-only) ---
    moments = project_moments(db, P15)
    KNOWN = {
        "cake": ["C7309"],
        "first_dance": ["DJI_0528", "DJI_0529"],
    }
    moment_report = {}
    for m in moments:
        srcs = [asset_name.get(shot_asset.get(sid, ""), "?") for sid in m.shot_ids]
        usable_members = sum(1 for sid in m.shot_ids if sid in usable_ids)
        chron_known = sum(1 for sid in m.shot_ids if asset_tc.get(shot_asset.get(sid, ""), False))
        recovered = {}
        for want in KNOWN.get(m.name, []):
            recovered[want] = any(str(s).startswith(want) for s in srcs)
        moment_report[m.name] = {
            "count": len(m.shot_ids),
            "best": round(float(m.best), 4),
            "uncertain": bool(m.uncertain),
            "usable_members": usable_members,
            "chronology_known": chron_known,
            "chronology_unknown": len(m.shot_ids) - chron_known,
            "sources": srcs,
            "shot_ids": list(m.shot_ids),
            "known_recovered": recovered,
        }

    # --- distractions / obstructions / opening_signs ---
    helpers = {
        "distractions": len(project_distractions(db, P15)),
        "obstructions": len(project_obstructions(db, P15)),
        "opening_signs": len(project_opening_signs(db, P15)),
    }

    # --- drone semantic + eligibility + chronology ---
    drones = {}
    for r in ro.execute(
        "SELECT id, file_name, timecode FROM media_assets WHERE project_id=? AND file_name LIKE 'DJI_%' "
        "ORDER BY file_name", (P15,)).fetchall():
        aid = r["id"]
        cats = {row["category"]: row["n"] for row in ro.execute(
            "SELECT category, COUNT(*) n FROM shots WHERE asset_id=? GROUP BY category", (aid,))}
        n = sum(cats.values())
        u = sum(1 for sh in shots if shot_asset.get(sh.id) == aid
                and _is_usable(sh, ABSOLUTE_MIN_QUALITY, MAX_HIGHLIGHT_CLIPPING))
        member_of = [m.name for m in moments
                     if any(shot_asset.get(sid) == aid for sid in m.shot_ids)]
        drones[r["file_name"]] = {
            "shots": n, "usable": u, "categories": cats,
            "timecode": r["timecode"] not in (None, ""), "moment_member_of": member_of,
        }

    result = {
        "production": {
            "assets": one("SELECT COUNT(*) FROM media_assets WHERE project_id=?", P15),
            "shots": len(shots),
            "embeddings": one("SELECT COUNT(*) FROM shot_features sf JOIN media_assets m "
                              "ON m.id=sf.asset_id WHERE m.project_id=? AND embedding IS NOT NULL", P15),
            "tq_zero": one("SELECT COUNT(*) FROM shots s JOIN media_assets m ON m.id=s.asset_id "
                           "WHERE m.project_id=? AND technical_quality=0", P15),
            "clip_labels": one("SELECT COUNT(*) FROM shots s JOIN media_assets m ON m.id=s.asset_id "
                               "WHERE m.project_id=? AND labels_json LIKE '%clip%'", P15),
            "elenora_embeddings": one("SELECT COUNT(*) FROM shot_features sf JOIN media_assets m "
                                      "ON m.id=sf.asset_id WHERE m.project_id=? AND embedding IS NOT NULL", ELENORA),
        },
        "shot_windows": windows,
        "eligibility": {
            "min_quality": ABSOLUTE_MIN_QUALITY, "max_clipping": MAX_HIGHLIGHT_CLIPPING,
            "usable": usable, "blocked_quality": blocked_quality, "blocked_clipping": blocked_clip,
            "total": len(shots),
        },
        "moments": moment_report,
        "helpers": helpers,
        "drones": drones,
        "chronology": {
            "assets_with_timecode": sum(1 for v in asset_tc.values() if v),
            "assets_without_timecode": sum(1 for v in asset_tc.values() if not v),
            "assets_without_tc_names": sorted(asset_name[a] for a, v in asset_tc.items() if not v),
        },
        "db_checksum": hashlib.sha256(DB.read_bytes()).hexdigest(),
    }
    ro.close()
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(result, indent=2, sort_keys=True))
    return result


if __name__ == "__main__":
    out = main()
    slim = {k: v for k, v in out.items() if k not in ("moments", "drones")}
    slim["moment_summary"] = {n: {"count": m["count"], "usable": m["usable_members"],
                                  "chron_known": m["chronology_known"], "best": m["best"],
                                  "recovered": m["known_recovered"]}
                              for n, m in out["moments"].items()}
    print(json.dumps(slim, indent=2, sort_keys=True))
