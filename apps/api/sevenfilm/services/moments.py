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
# How far above the footage's own middle a shot has to sit before it counts as showing the
# moment at all. Measured on this shoot the best match for each moment runs 0.30 to 0.35
# against a median of 0.20 to 0.25, so the moments that are really there stand well clear —
# and a wedding with no cake does not get a cake anyway.
MOMENT_LIFT = 1.25
# How many of a moment's best shots are treated as candidates for it.
MOMENT_SHORTLIST = 8


@dataclass(frozen=True)
class Moment:
    """One thing a wedding film should show, and the shots that show it best."""

    name: str
    shot_ids: tuple[str, ...]
    best: float


def project_moments(database: Database, project_id: str) -> tuple[Moment, ...]:
    """The moments this shoot actually contains, best shots first.

    A moment the footage does not hold is left out rather than filled with the least bad
    thing: a wedding without a cake should not be given one.
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
