"""Who is in which clip, and which of them is the couple.

The identities come from Resolve's face analysis. What makes them worth having is that the
same person keeps the same label across a shoot — measured, not assumed. What Resolve will not
do is take a name through the API, and asking the editor to label faces defeats the point of
the tool, so the names are derived from our own shot categories instead: the bride is the
identity whose appearances lean to the bride's shots.

This module is the platform-independent side of that. Resolve's labels come in through a tool;
everything below stores and reads them in our own schema, so an edit built on this signal does
not depend on Resolve being installed.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from ..db import Database

# Which categories speak for which half of the couple.
BRIDE_CATEGORIES = frozenset({"bride", "bride_prep"})
GROOM_CATEGORIES = frozenset({"groom", "groom_prep"})
# How one-sided an identity has to be before the side is believed, as a share of its
# couple-related appearances. Below it the answer is "couple?" rather than a guess.
BRIDE_SHARE = 0.6
# How many clips an identity has to appear in before it can hold a role.
#
# Without this the noise wins: a face seen once, in one bride shot, scores a perfect 1.00 and
# sorts above the bride herself at 0.71 across ten clips.
MIN_CLIPS = 5
UNCERTAIN = "couple?"


def decide_roles(
    people_by_asset: Mapping[str, Sequence[str]],
    categories_by_asset: Mapping[str, Sequence[str]],
) -> dict[str, dict[str, object]]:
    """Work out which identity is the bride and which the groom.

    Frequency alone picks the wrong people: a guest in the background of everything appears in
    more clips than either half of the couple. What separates them is how one-sided it is.
    """
    appearances = Counter(
        identity for identities in people_by_asset.values() for identity in identities
    )
    side: dict[str, Counter] = defaultdict(Counter)
    for asset_id, identities in people_by_asset.items():
        for category in categories_by_asset.get(asset_id, ()):
            which = ("bride" if category in BRIDE_CATEGORIES
                     else "groom" if category in GROOM_CATEGORIES else None)
            if which:
                for identity in identities:
                    side[identity][which] += 1

    def lean(identity: str) -> float | None:
        bride, groom = side[identity]["bride"], side[identity]["groom"]
        total = bride + groom
        return None if total == 0 else bride / total

    leans = {identity: lean(identity) for identity in appearances}
    eligible = [
        identity for identity, value in leans.items()
        if value is not None and appearances[identity] >= MIN_CLIPS
    ]
    # Ranked by how much evidence there is, not by how clean the ratio looks.
    brides = sorted((i for i in eligible if leans[i] >= BRIDE_SHARE),
                    key=lambda i: (-side[i]["bride"], -leans[i]))
    grooms = sorted((i for i in eligible if leans[i] <= 1 - BRIDE_SHARE),
                    key=lambda i: (-side[i]["groom"], leans[i]))

    def settled(ordered: list[str]) -> str | None:
        """The clear winner, or nothing. Two identities carrying identical evidence cannot be
        told apart, and taking the first is inventing an answer."""
        if not ordered:
            return None
        if len(ordered) > 1:
            first, second = ordered[0], ordered[1]
            if (side[first], leans[first], appearances[first]) == (
                side[second], leans[second], appearances[second]
            ):
                return None
        return ordered[0]

    roles: dict[str, str] = {}
    bride = settled(brides)
    if bride:
        roles[bride] = "bride"
    groom = settled(grooms)
    if groom and groom not in roles:
        roles[groom] = "groom"
    if not roles:
        for identity, _ in appearances.most_common(2):
            roles[identity] = UNCERTAIN

    return {
        identity: {
            "role": role,
            "clips": appearances[identity],
            "bride_shots": side[identity]["bride"],
            "groom_shots": side[identity]["groom"],
        }
        for identity, role in roles.items()
    }


def store_people(
    database: Database, project_id: str, people_by_asset: Mapping[str, Sequence[str]]
) -> int:
    """Replace this project's identities with the ones measured."""
    now = datetime.now(UTC).isoformat(timespec="seconds")
    database.execute("DELETE FROM asset_people WHERE project_id = ?", (project_id,))
    rows = [
        (project_id, asset_id, identity, now)
        for asset_id, identities in people_by_asset.items()
        for identity in identities
    ]
    for row in rows:
        database.execute(
            "INSERT OR REPLACE INTO asset_people "
            "(project_id, asset_id, identity, created_at) VALUES (?, ?, ?, ?)", row)
    return len(rows)


def store_roles(
    database: Database, project_id: str, roles: Mapping[str, Mapping[str, object]]
) -> int:
    now = datetime.now(UTC).isoformat(timespec="seconds")
    database.execute("DELETE FROM people_roles WHERE project_id = ?", (project_id,))
    for identity, found in roles.items():
        database.execute(
            "INSERT OR REPLACE INTO people_roles "
            "(project_id, identity, role, clips, bride_shots, groom_shots, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (project_id, identity, str(found["role"]), int(found["clips"]),
             int(found["bride_shots"]), int(found["groom_shots"]), now))
    return len(roles)


def project_people(database: Database, project_id: str) -> dict[str, frozenset[str]]:
    """Every asset's identities."""
    rows = database.fetch_all(
        "SELECT asset_id, identity FROM asset_people WHERE project_id = ?", (project_id,))
    found: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        found[str(row["asset_id"])].add(str(row["identity"]))
    return {asset_id: frozenset(identities) for asset_id, identities in found.items()}


def project_roles(database: Database, project_id: str) -> dict[str, str]:
    """Identity to role, with the uncertain ones left out — a "couple?" is not an answer the
    edit can use."""
    rows = database.fetch_all(
        "SELECT identity, role FROM people_roles WHERE project_id = ?", (project_id,))
    return {str(row["identity"]): str(row["role"]) for row in rows
            if str(row["role"]) != UNCERTAIN}


def couple_assets(database: Database, project_id: str) -> frozenset[str]:
    """The assets holding either half of the couple.

    Presence, not importance: a crowded reception frame lists everyone in it, including a guest
    at the back. What this answers is the other question — which clips have neither of them in.
    """
    roles = project_roles(database, project_id)
    wanted = {identity for identity, role in roles.items() if role in ("bride", "groom")}
    if not wanted:
        return frozenset()
    return frozenset(
        asset_id for asset_id, identities in project_people(database, project_id).items()
        if identities & wanted
    )
