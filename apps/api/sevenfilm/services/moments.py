"""The moments a wedding film has to contain, found rather than waited for.

Measured on an edit the editor had been picking apart all evening. Of the eight shots that
match each moment best, this is how many reached the film:

    cutting the cake      1 of 8
    feeding the cake      2 of 8
    the kiss              0 of 8
    putting on the ring   0 of 8
    the first dance       0 of 8
    the entrance          0 of 8

All of that footage was indexed and available. The planner has no notion that a wedding has
moments that must be in the film: it scores every shot on quality, category, rhythm and the
day's order, and the ring exchange loses to a technically cleaner shot of somebody walking.
That is what "gelin damadın girişi yok" and "bir hikaye sıralaması yok" were describing.

The affinities come from the CLIP embeddings already stored for every shot, so nothing has to
be re-analysed; only the six prompts need encoding. Where CLIP will not load there are no
moments and the edit is planned exactly as it was.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from ..db import Database

LOGGER = logging.getLogger("sevenfilm")

# What a wedding film is expected to show. Written as what the camera sees rather than as a
# name, because that is what the model matches on.
MOMENT_PROMPTS = {
    "entrance": "a bride and groom entering a room while guests applaud",
    "ring": "putting a wedding ring on a finger, close up of hands",
    "kiss": "a bride and groom kissing",
    "cake": "a bride and groom cutting a wedding cake together with a knife",
    "cake_feed": "a bride and groom feeding each other a piece of cake",
    "first_dance": "a bride and groom dancing together alone on a dance floor",
}
# A floor, and no more than that.
#
# It is tempting to read this as a presence test and it is not one. Eighteen prompts were tried
# against this shoot, including fireworks, a decorated wedding car and signing the register,
# none of which this wedding has. Every one of them cleared 1.25, scoring 1.26 to 1.94 with no
# gap anywhere. Two other tests were built and both failed the same way: how many shots cluster
# near the top (fireworks 21, the ring 1), and how tightly the best shots sit in time — which
# looked decisive until "a mother helping the bride into her dress" came back with the tightest
# spread of all and three shots of the dance floor.
#
# So on this footage CLIP cannot tell a moment that happened from the nearest thing to it. The
# six in MOMENT_PROMPTS are trusted because they were checked by eye on this shoot, not because
# they cleared this. What the floor does is keep out a prompt with no answer at all; a wedding
# with no cake still gets its closest shot to a cake, one cut out of a hundred and ten, and the
# warning below says so.
MOMENT_LIFT = 1.25
# How many of a moment's best shots are treated as candidates for it.
MOMENT_SHORTLIST = 8


# Below this the best answer is weak enough to be worth a second look. Read off the six checked
# by eye on this shoot, whose best scores run 0.305 to 0.348.
MOMENT_CONFIDENT = 0.30

# What to call each moment when telling the editor about it.
MOMENT_NAMES = {
    "entrance": "çiftin girişi",
    "ring": "yüzük",
    "kiss": "öpücük",
    "cake": "pasta kesme",
    "cake_feed": "pasta yedirme",
    "first_dance": "ilk dans",
}


@dataclass(frozen=True)
class Moment:
    """One thing a wedding film should show, and the shots that show it best."""

    name: str
    shot_ids: tuple[str, ...]
    best: float

    @property
    def uncertain(self) -> bool:
        """Worth the editor's eye: the footage may not hold this at all."""
        return self.best < MOMENT_CONFIDENT

    @property
    def label(self) -> str:
        return MOMENT_NAMES.get(self.name, self.name)


def project_moments(database: Database, project_id: str) -> tuple[Moment, ...]:
    """The best answer this shoot has for each moment, best shots first.

    Not a guarantee that the moment happened — see MOMENT_LIFT. `uncertain` marks the ones the
    editor should look at.
    """
    rows = database.fetch_all(
        """SELECT shot_features.shot_id, shot_features.embedding FROM shot_features
           JOIN media_assets ON media_assets.id = shot_features.asset_id
           WHERE media_assets.project_id = ? AND shot_features.embedding IS NOT NULL""",
        (project_id,),
    )
    if not rows:
        return ()
    text = _moment_text_features()
    if text is None:
        return ()
    shot_ids = [str(row["shot_id"]) for row in rows]
    vectors = np.stack([np.frombuffer(row["embedding"], dtype=np.float32) for row in rows])
    vectors = vectors / (np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-9)
    similarity = vectors @ text.T
    found: list[Moment] = []
    for index, name in enumerate(MOMENT_PROMPTS):
        column = similarity[:, index]
        middle = float(np.median(column))
        best = float(column.max())
        if middle <= 0 or best < middle * MOMENT_LIFT:
            continue
        order = np.argsort(-column)[:MOMENT_SHORTLIST]
        found.append(Moment(
            name=name,
            shot_ids=tuple(shot_ids[position] for position in order),
            best=best,
        ))
    return tuple(found)


def _moment_text_features() -> np.ndarray | None:
    """Encode the prompts. Only text, so the images never have to be read again."""
    try:
        import torch

        from .vision import VisionClassifier

        classifier = VisionClassifier()
        if not classifier._load():
            return None
        with torch.inference_mode():
            inputs = classifier._processor(
                text=list(MOMENT_PROMPTS.values()), return_tensors="pt", padding=True
            )
            features = classifier._model.get_text_features(
                **{key: value.to(classifier._device) for key, value in inputs.items()}
            )
            if hasattr(features, "pooler_output"):
                features = features.pooler_output
            encoded = features.cpu().numpy()
        return encoded / (np.linalg.norm(encoded, axis=1, keepdims=True) + 1e-9)
    except Exception as error:  # noqa: BLE001 - optional ML boundary, the edit works without it.
        LOGGER.warning("Moment prompts unavailable, planning without them: %s", error)
        return None
