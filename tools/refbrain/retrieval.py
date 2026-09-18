"""P6.22 -- deterministic reference-sequence retrieval.

Given a target query (story position, desired pacing/scale/role/event), return the top-K most similar
HUMAN reference sequences, with full provenance and a reason. Similarity = cosine over the structured
descriptor, blended with structured-attribute agreement. Retrieval NEVER returns target shot ids -- it
returns grammar (which reference taught what). Deterministic: fixed ordering, ties broken by id.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "data" / "reference_editor" / "corpus" / "corpus.json"


def _cos(a, b):
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class Retriever:
    def __init__(self, corpus_path: Path = CORPUS, exclude_references=(), allowed_tiers=(1, 2)):
        corpus = json.loads(Path(corpus_path).read_text())
        self.exclude = set(exclude_references)
        self.allowed_tiers = set(allowed_tiers)
        self.sequences = [
            s for s in corpus["sequences"]
            if s["reference_id"] not in self.exclude and s["tier"] in self.allowed_tiers
        ]
        self.edits = {e["reference_id"]: e for e in corpus["edits"]}

    def active_references(self):
        refs = sorted({s["reference_id"] for s in self.sequences})
        return refs

    def retrieve(self, query_descriptor, *, story_role=None, event_type=None,
                 want_tier=None, k=5):
        scored = []
        for s in self.sequences:
            if want_tier is not None and s["tier"] != want_tier:
                continue
            sim = _cos(query_descriptor, s["descriptor"])
            bonus = 0.0
            if story_role and s["story_role"] == story_role:
                bonus += 0.15
            if event_type and s["event_type"] == event_type:
                bonus += 0.10
            score = sim + bonus
            scored.append((score, s))
        # deterministic: sort by score desc, then sequence_id asc
        scored.sort(key=lambda t: (-t[0], t[1]["sequence_id"]))
        out = []
        for score, s in scored[:k]:
            out.append({
                "sequence_id": s["sequence_id"], "reference_id": s["reference_id"],
                "tier": s["tier"], "similarity": round(score, 4),
                "story_role": s["story_role"], "event_type": s["event_type"],
                "n_shots": s["n_shots"], "duration_s": s["duration_s"],
                "scale_pattern": s["scale_pattern"],
                "why": f"role={s['story_role']} event={s['event_type']} "
                       f"pos={s['story_position']} tier{s['tier']}",
            })
        return out
