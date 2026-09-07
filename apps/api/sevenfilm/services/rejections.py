"""Clips and shots the editor has told the edit to leave alone.

Some of what makes a shot unusable cannot be measured here at any sensible cost. A man
standing in a doorway behind a couple is fifteen ten-thousandths of the frame: the face
detector finds him in every frame of the 4K original and in none of the proxy, and upscaling
the proxy does not bring him back because the information is not in it. Measuring the whole
shoot at full resolution is 661 milliseconds a frame, an hour and three quarters. A bride
catching her step has no measure at all.

The editor sees both in a second. This is where that goes, so it is spent once and kept.

Clips are named the way the editor names them — C1968, or C1968.MP4 — because that is what
Resolve shows them in the timeline and the inspector.
"""

from __future__ import annotations

from ..db import Database, now


def _match(name: str) -> str:
    """The stem, upper-cased: C1968, C1968.MP4 and c1968.mp4 are one clip."""
    return name.strip().upper().rsplit(".", 1)[0].rsplit("/", 1)[-1]


def reject_clips(
    database: Database, project_id: str, names: list[str], reason: str = ""
) -> tuple[list[str], list[str]]:
    """Mark clips unusable by name. Returns the names taken and the ones not recognised."""
    rows = database.fetch_all(
        "SELECT id, path FROM media_assets WHERE project_id = ?", (project_id,)
    )
    by_name: dict[str, str] = {}
    for row in rows:
        by_name[_match(str(row["path"]))] = str(row["id"])
    taken: list[str] = []
    unknown: list[str] = []
    for name in names:
        asset_id = by_name.get(_match(name))
        if asset_id is None:
            unknown.append(name)
            continue
        database.execute(
            """INSERT OR REPLACE INTO rejections (project_id, asset_id, shot_id, reason, created_at)
               VALUES (?, ?, NULL, ?, ?)""",
            (project_id, asset_id, reason, now()),
        )
        taken.append(name)
    return taken, unknown


def restore_clips(database: Database, project_id: str, names: list[str]) -> list[str]:
    """Take clips off the list again, for when a rejection turns out to be wrong."""
    rows = database.fetch_all(
        "SELECT id, path FROM media_assets WHERE project_id = ?", (project_id,)
    )
    by_name = {_match(str(row["path"])): str(row["id"]) for row in rows}
    restored: list[str] = []
    for name in names:
        asset_id = by_name.get(_match(name))
        if asset_id is None:
            continue
        database.execute(
            "DELETE FROM rejections WHERE project_id = ? AND asset_id = ? AND shot_id IS NULL",
            (project_id, asset_id),
        )
        restored.append(name)
    return restored


def project_rejections(
    database: Database, project_id: str
) -> tuple[frozenset[str], frozenset[str]]:
    """The clip ids and shot ids this project's edits must not draw on."""
    rows = database.fetch_all(
        "SELECT asset_id, shot_id FROM rejections WHERE project_id = ?", (project_id,)
    )
    assets = frozenset(
        str(row["asset_id"]) for row in rows if row["shot_id"] is None
    )
    shots = frozenset(
        str(row["shot_id"]) for row in rows if row["shot_id"] is not None
    )
    return assets, shots


def rejected_names(database: Database, project_id: str) -> list[str]:
    """What is on the list, named the way the editor named it, newest first."""
    rows = database.fetch_all(
        """SELECT media_assets.path, rejections.reason FROM rejections
           JOIN media_assets ON media_assets.id = rejections.asset_id
           WHERE rejections.project_id = ? AND rejections.shot_id IS NULL
           ORDER BY rejections.created_at DESC""",
        (project_id,),
    )
    return [str(row["path"]).rsplit("/", 1)[-1] for row in rows]
