"""Work out which identity is the bride and which is the groom, without asking anyone.

Resolve labels the same person "Face 2" across the shoot but will not take a name through the
API, and asking the editor to label them defeats the point — "ben uğraşacaksam ne faydası
var". The labels do not have to be given: they can be read off our own shot categories.

The reasoning, in order:

  * The two people who appear in the most clips of a wedding are the couple. Everyone else —
    a parent, a friend, the singer — is in a fraction of it.
  * Which of the two is the bride is then settled by where they appear: our classifier already
    calls each shot bride / groom / bride_prep / groom_prep, and the bride is the identity that
    leans to the bride shots.

Both steps are measured against footage rather than assumed, and the result carries the
evidence with it so a wrong match is visible rather than silent.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))

from sevenfilm.db import Database
from sevenfilm.services.analysis import project_shots
from sevenfilm.services.media import project_assets

# Which categories speak for which half of the couple.
BRIDE_CATEGORIES = ("bride", "bride_prep")
GROOM_CATEGORIES = ("groom", "groom_prep")
# How much more one-sided an identity has to be before the side is believed. Below it the
# match is reported as uncertain rather than guessed.
LEAN = 1.5
# How many clips an identity has to appear in before it can hold a role.
#
# Without this the noise wins: a face seen once, in one bride shot, scores a perfect 1.00 lean
# and sorts above the bride herself at 0.71 across ten clips. Measured on a partial pass of
# this shoot, that is exactly what happened — the only role found was a groom seen in two
# clips.
MIN_CLIPS = 5


def name_people(
    people_by_clip: dict[str, list[str]], categories_by_clip: dict[str, list[str]]
) -> dict:
    """Return the roles found, with the counts they were found from."""
    appearances = Counter(face for faces in people_by_clip.values() for face in faces)
    side: dict[str, Counter] = defaultdict(Counter)
    for clip, faces in people_by_clip.items():
        for category in categories_by_clip.get(clip, ()):
            for face in faces:
                if category in BRIDE_CATEGORIES:
                    side[face]["bride"] += 1
                elif category in GROOM_CATEGORIES:
                    side[face]["groom"] += 1

    # Frequency alone picks the wrong people. A guest who is in the background of everything —
    # or a photographer, or a waiter — appears in more clips than either half of the couple,
    # and a first version of this pushed the groom out of the top two entirely.
    #
    # What separates the couple from a constant bystander is not how often they appear but how
    # *one-sided* it is: the bride is in the bride's preparation and not the groom's, while the
    # guest is in both. So the side ratio decides, and frequency only breaks ties.
    def lean_of(face: str) -> float | None:
        bride, groom = side[face]["bride"], side[face]["groom"]
        return None if bride + groom == 0 else bride / (bride + groom)

    leans = {face: lean_of(face) for face in appearances}
    bride_share = LEAN / (LEAN + 1)          # 1.5 kat = payın %60'ı
    candidates = [face for face, lean in leans.items() if lean is not None]
    # Sorted by how much evidence there is, not by how clean it looks: an identity in 36 bride
    # shots at 0.71 is a better answer than one in a single shot at 1.00.
    seen_enough = [face for face in candidates if appearances[face] >= MIN_CLIPS]
    brides = sorted((f for f in seen_enough if leans[f] >= bride_share),
                    key=lambda f: (-side[f]["bride"], -leans[f]))
    grooms = sorted((f for f in seen_enough if leans[f] <= 1 - bride_share),
                    key=lambda f: (-side[f]["groom"], leans[f]))

    def settled(ordered: list[str]) -> str | None:
        """The clear winner, or nothing. Two identities with identical evidence — the same
        lean, seen the same number of times — cannot be told apart, and picking the first is
        inventing an answer. Early in an analysis this is the common case."""
        if not ordered:
            return None
        if len(ordered) > 1:
            best, next_best = ordered[0], ordered[1]
            if ((side[best], leans[best], appearances[best])
                    == (side[next_best], leans[next_best], appearances[next_best])):
                return None
        return ordered[0]

    roles: dict[str, str] = {}
    bride = settled(brides)
    if bride:
        roles[bride] = "bride"
    groom = settled(grooms)
    if groom and groom not in roles:
        roles[groom] = "groom"
    # Nothing leaned far enough: say so rather than name the two most frequent faces.
    if not roles:
        for face, _ in appearances.most_common(2):
            roles[face] = "couple?"

    detail = {face: {"clips": appearances[face], "bride_shots": side[face]["bride"],
                     "groom_shots": side[face]["groom"], "lean": leans.get(face)}
              for face in roles}
    return {"roles": roles, "detail": detail,
            "identities": len(appearances), "clips": len(people_by_clip),
            "ranking": appearances.most_common(8)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--people", type=Path, required=True)
    parser.add_argument("--project", default="df2a4a62-e821-40f7-86fc-b6a9259e9ee9")
    arguments = parser.parse_args()

    people_by_clip = json.loads(arguments.people.read_text())
    database = Database(Path("data/sevenfilm.sqlite3"))
    assets = {asset.id: asset.name.rsplit(".", 1)[0]
              for asset in project_assets(database, arguments.project)}
    categories: dict[str, list[str]] = defaultdict(list)
    for shot in project_shots(database, arguments.project):
        name = assets.get(shot.asset_id)
        if name:
            categories[name].append(shot.category)

    found = name_people(people_by_clip, categories)
    print(f"{found['clips']} klip · {found['identities']} kimlik")
    print(f"en sık görünenler: {found['ranking']}")
    print("\nbulunan roller:")
    for face, role in found["roles"].items():
        counts = found["detail"][face]
        lean = counts.get("lean")
        print(f"  {face:10} → {role:9} ({counts['clips']} klipte · "
              f"gelin planı {counts['bride_shots']} · damat planı {counts['groom_shots']}"
              + (f" · taraf {lean:.2f})" if lean is not None else ")"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
