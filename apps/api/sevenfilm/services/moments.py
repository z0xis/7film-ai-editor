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
    # Named by what is in the frame — a white dress, a suit, the two of them holding each
    # other. "dancing together alone on a dance floor" was the weakest of the six: of its four
    # best shots two were right, one was a guest with her arms up and one was the entrance
    # corridor, and its best shots were spread over 7.1 minutes of the day rather than the one
    # moment. This phrasing puts all four on the couple, inside a single minute.
    "first_dance": (
        "a bride in a white dress and a groom in a suit slow dancing together,"
        " holding each other"
    ),
}
# What a wedding film should not dwell on. The band plays at every wedding and belongs in the
# background of the party; it is not the subject.
#
# Measured on an edit the editor watched through: of the shots in this shoot's top tenth for
# "a wedding band performing on stage", 25% of the film's cuts were among them — two and a half
# times what an even hand would give. The singer alone ran 17%. "solist çok fazla görünüyor,
# hem bu planda hem genel."
DISTRACTION_PROMPTS = {
    "band": "a wedding band performing on stage with instruments and a singer",
}
# Where a shot stops being a party shot with a band behind it and becomes a shot of the band.
DISTRACTION_QUANTILE = 0.90

# Who is holding the microphone. The band prompt above finds the stage; it does not find the
# singer leaning into the camera or the host announcing over the couple, and the editor kept
# picking those out: "solist çok fazla görünüyor", and again in the closing minute where three
# of twelve cuts were somebody at a microphone.
#
# Asked on its own, this prompt cannot tell a man at a microphone from a groom in a suit: its
# twelve best shots on this shoot held four of the host, one of the singer, and six of the
# groom — including the cake cutting, which the film owes. Subtracting what the film is
# actually about fixes it, the same way the obstruction test does: the twelve best are then
# all twelve singer, host, drummer or DJ, with no groom and no cake among them.
MICROPHONE_PROMPTS = (
    "a man speaking into a handheld microphone",
    "a wedding host announcing into a microphone in front of guests",
)
MICROPHONE_AGAINST = (
    "a photo of the wedding couple, faces visible",
    "a groom in a suit at his own wedding",
)
MICROPHONE_QUANTILE = 0.90


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


def project_embeddings(database: Database, project_id: str) -> dict[str, np.ndarray]:
    """Every shot's CLIP vector, unit length, for comparing shots to each other.

    Already stored, so this costs a read. The perceptual hash cannot do this job: two takes of
    one setup sit 17 bits apart on it, outside the near-duplicate threshold entirely.
    """
    rows = database.fetch_all(
        """SELECT shot_features.shot_id, shot_features.embedding FROM shot_features
           JOIN media_assets ON media_assets.id = shot_features.asset_id
           WHERE media_assets.project_id = ? AND shot_features.embedding IS NOT NULL""",
        (project_id,),
    )
    vectors: dict[str, np.ndarray] = {}
    for row in rows:
        vector = np.frombuffer(row["embedding"], dtype=np.float32)
        norm = float(np.linalg.norm(vector))
        if norm > 0:
            vectors[str(row["shot_id"])] = vector / norm
    return vectors


def project_distractions(database: Database, project_id: str) -> frozenset[str]:
    """The shots this shoot holds that are about something the film is not about.

    Read as a share of the shoot rather than an absolute score, because a band fills more of
    some weddings than others and the question is which of *these* shots are the band's.
    """
    rows = database.fetch_all(
        """SELECT shot_features.shot_id, shot_features.embedding FROM shot_features
           JOIN media_assets ON media_assets.id = shot_features.asset_id
           WHERE media_assets.project_id = ? AND shot_features.embedding IS NOT NULL""",
        (project_id,),
    )
    if not rows:
        return frozenset()
    text = _text_features(list(DISTRACTION_PROMPTS.values()))
    if text is None:
        return frozenset()
    shot_ids = [str(row["shot_id"]) for row in rows]
    vectors = np.stack([np.frombuffer(row["embedding"], dtype=np.float32) for row in rows])
    vectors = vectors / (np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-9)
    similarity = vectors @ text.T
    found: set[str] = set()
    for index in range(similarity.shape[1]):
        column = similarity[:, index]
        bar = float(np.quantile(column, DISTRACTION_QUANTILE))
        found.update(
            shot_id for shot_id, value in zip(shot_ids, column, strict=True) if value >= bar
        )
    microphones = _text_features([*MICROPHONE_PROMPTS, *MICROPHONE_AGAINST])
    if microphones is not None:
        against = vectors @ microphones.T
        held = (
            against[:, : len(MICROPHONE_PROMPTS)].sum(axis=1)
            - against[:, len(MICROPHONE_PROMPTS) :].sum(axis=1)
        )
        bar = float(np.quantile(held, MICROPHONE_QUANTILE))
        found.update(
            shot_id for shot_id, value in zip(shot_ids, held, strict=True) if value >= bar
        )
    return frozenset(found)



# A body between the camera and what the shot is of.
#
# The editor kept finding these: "alakasız sırt var", "çok kötü kafanın arkası görünüyor
# sadece", "kötü kadraj". Nothing in the planner could see them — the face detector reads a
# blurred shoulder across the lens as no face at all, which is also what an empty room looks
# like.
#
# CLIP can, and the vectors are already stored, so this costs a read. Read as a share of the
# shoot rather than an absolute score, because how crowded a wedding is varies. Verified by
# looking: the top of this shoot is an arm sweeping across the lens over a table of guests and
# a blurred head filling the right third of the frame, and the bottom is the couple facing the
# camera with their faces clear.
OBSTRUCTION_PROMPTS = (
    "the back of a person's head filling the frame, blocking the view",
    "a person's back turned to the camera in the foreground",
)
# Subtracted, so a shot that also shows faces is not condemned for having a guest in it.
OBSTRUCTION_AGAINST = "a photo of the wedding couple, faces visible"
OBSTRUCTION_QUANTILE = 0.90


def project_obstructions(database: Database, project_id: str) -> frozenset[str]:
    """The shots with something in front of the subject rather than the subject."""
    rows = database.fetch_all(
        """SELECT shot_features.shot_id, shot_features.embedding FROM shot_features
           JOIN media_assets ON media_assets.id = shot_features.asset_id
           WHERE media_assets.project_id = ? AND shot_features.embedding IS NOT NULL""",
        (project_id,),
    )
    if not rows:
        return frozenset()
    text = _text_features([*OBSTRUCTION_PROMPTS, OBSTRUCTION_AGAINST])
    if text is None:
        return frozenset()
    shot_ids = [str(row["shot_id"]) for row in rows]
    vectors = np.stack([np.frombuffer(row["embedding"], dtype=np.float32) for row in rows])
    vectors = vectors / (np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-9)
    similarity = vectors @ text.T
    score = similarity[:, :-1].sum(axis=1) - similarity[:, -1]
    bar = float(np.quantile(score, OBSTRUCTION_QUANTILE))
    return frozenset(
        shot_id for shot_id, value in zip(shot_ids, score, strict=True) if value >= bar
    )


# What a wedding film opens on when the shoot rolled one.
#
# Steering the opening to the `detail` category was right about the category and wrong about
# the shot: this shoot's best-scoring detail is a table centrepiece, and the editor had already
# rejected that image several times over — "alakasız yerde çiçek", "bi detay planı böyle
# olmaz", and finally "hala yarak gibi giriş planları... hala onu koyuyon".
#
# What the shoot actually has is a mirror lettered with the couple's names, the word
# hoşgeldiniz and the date, filmed four times in the first minute of the day. CLIP separates
# the two cleanly: on this prompt the sign clips take the top four places (0.305-0.334) and
# the centrepiece falls to 726th of 1405, while on a table-setting prompt the centrepiece is
# first and the sign is 66th.
OPENING_SIGN_PROMPT = (
    "a wedding welcome sign with the couple's names and the date written on it"
)
# The top of the shoot, not a share of it: a wedding has one welcome sign or none.
OPENING_SIGN_QUANTILE = 0.99
# And what it does not open on.
TABLE_SETTING_PROMPT = "a set dining table with a flower centrepiece and glasses"
TABLE_SETTING_QUANTILE = 0.95


def _top_by_prompt(
    database: Database, project_id: str, prompt: str, quantile: float
) -> frozenset[str]:
    """The shots this shoot holds that look most like `prompt`."""
    rows = database.fetch_all(
        """SELECT shot_features.shot_id, shot_features.embedding FROM shot_features
           JOIN media_assets ON media_assets.id = shot_features.asset_id
           WHERE media_assets.project_id = ? AND shot_features.embedding IS NOT NULL""",
        (project_id,),
    )
    if not rows:
        return frozenset()
    text = _text_features([prompt])
    if text is None:
        return frozenset()
    shot_ids = [str(row["shot_id"]) for row in rows]
    vectors = np.stack([np.frombuffer(row["embedding"], dtype=np.float32) for row in rows])
    vectors = vectors / (np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-9)
    score = (vectors @ text.T)[:, 0]
    bar = float(np.quantile(score, quantile))
    return frozenset(
        shot_id for shot_id, value in zip(shot_ids, score, strict=True) if value >= bar
    )


def project_opening_signs(database: Database, project_id: str) -> frozenset[str]:
    """The welcome sign, if this shoot filmed one."""
    return _top_by_prompt(
        database, project_id, OPENING_SIGN_PROMPT, OPENING_SIGN_QUANTILE
    )


def project_table_settings(database: Database, project_id: str) -> frozenset[str]:
    """Laid tables and their centrepieces, which the film does not open on."""
    return _top_by_prompt(
        database, project_id, TABLE_SETTING_PROMPT, TABLE_SETTING_QUANTILE
    )

def _moment_text_features() -> np.ndarray | None:
    """Encode the moment prompts. Only text, so the images never have to be read again."""
    return _text_features(list(MOMENT_PROMPTS.values()))


def _text_features(prompts: list[str]) -> np.ndarray | None:
    try:
        import torch

        from .vision import VisionClassifier

        classifier = VisionClassifier()
        if not classifier._load():
            return None
        with torch.inference_mode():
            inputs = classifier._processor(
                text=prompts, return_tensors="pt", padding=True
            )
            features = classifier._model.get_text_features(
                **{key: value.to(classifier._device) for key, value in inputs.items()}
            )
            if hasattr(features, "pooler_output"):
                features = features.pooler_output
            encoded = features.cpu().numpy()
        return encoded / (np.linalg.norm(encoded, axis=1, keepdims=True) + 1e-9)
    except Exception as error:  # noqa: BLE001 - optional ML boundary, the edit works without it.
        LOGGER.warning("CLIP prompts unavailable, planning without them: %s", error)
        return None
