"""P6.1 Stage B: run the EXACT unchanged production moment/story logic (moments.py's
project_moments/project_distractions/project_obstructions/project_opening_signs/
project_table_settings algorithms) against the full-project shadow embedding matrix produced by
shadow_full_embedding_recovery.py. Same prompts, same thresholds, same quantiles, same math --
only the embedding SOURCE differs (in-memory shadow array instead of a live DB SELECT), because
the real DB has no embeddings for this project. Never writes to the real database.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, "apps/api")

import numpy as np
from sevenfilm.services.moments import (
    DISTRACTION_PROMPTS,
    DISTRACTION_QUANTILE,
    MICROPHONE_AGAINST,
    MICROPHONE_PROMPTS,
    MICROPHONE_QUANTILE,
    MOMENT_LIFT,
    MOMENT_NAMES,
    MOMENT_PROMPTS,
    MOMENT_SHORTLIST,
    OBSTRUCTION_AGAINST,
    OBSTRUCTION_PROMPTS,
    OBSTRUCTION_QUANTILE,
    OPENING_SIGN_PROMPT,
    OPENING_SIGN_QUANTILE,
    TABLE_SETTING_PROMPT,
    TABLE_SETTING_QUANTILE,
    _text_features,
)


def load_shadow_embeddings():
    data = np.load("/tmp/p61_stage_b_embeddings.npz", allow_pickle=True)
    return list(data["shot_ids"]), data["vectors"]


def shadow_project_moments(shot_ids, vectors):
    text = _text_features(list(MOMENT_PROMPTS.values()))
    if text is None:
        return None, "CLIP unavailable"
    similarity = vectors @ text.T
    found = []
    for index, name in enumerate(MOMENT_PROMPTS):
        column = similarity[:, index]
        middle = float(np.median(column))
        best = float(column.max())
        if middle <= 0 or best < middle * MOMENT_LIFT:
            continue
        order = np.argsort(-column)[:MOMENT_SHORTLIST]
        found.append({
            "name": name, "label": MOMENT_NAMES.get(name, name),
            "shot_ids": [shot_ids[i] for i in order],
            "scores": [round(float(column[i]), 4) for i in order],
            "best": round(best, 4), "median": round(middle, 4),
        })
    return found, None


def shadow_project_distractions(shot_ids, vectors):
    text = _text_features(list(DISTRACTION_PROMPTS.values()))
    if text is None:
        return frozenset(), 0
    similarity = vectors @ text.T
    found = set()
    for index in range(similarity.shape[1]):
        column = similarity[:, index]
        bar = float(np.quantile(column, DISTRACTION_QUANTILE))
        found.update(shot_ids[i] for i, v in enumerate(column) if v >= bar)

    microphones = _text_features([*MICROPHONE_PROMPTS, *MICROPHONE_AGAINST])
    if microphones is not None:
        against = vectors @ microphones.T
        held = against[:, :len(MICROPHONE_PROMPTS)].sum(axis=1) - against[:, len(MICROPHONE_PROMPTS):].sum(axis=1)
        bar = float(np.quantile(held, MICROPHONE_QUANTILE))
        found.update(shot_ids[i] for i, v in enumerate(held) if v >= bar)
    return frozenset(found), len(found)


def shadow_project_obstructions(shot_ids, vectors):
    text = _text_features([*OBSTRUCTION_PROMPTS, OBSTRUCTION_AGAINST])
    if text is None:
        return frozenset()
    similarity = vectors @ text.T
    score = similarity[:, :-1].sum(axis=1) - similarity[:, -1]
    bar = float(np.quantile(score, OBSTRUCTION_QUANTILE))
    return frozenset(shot_ids[i] for i, v in enumerate(score) if v >= bar)


def shadow_top_by_prompt(shot_ids, vectors, prompt, quantile):
    text = _text_features([prompt])
    if text is None:
        return frozenset(), []
    score = (vectors @ text.T)[:, 0]
    bar = float(np.quantile(score, quantile))
    order = np.argsort(-score)
    top = [{"shot_id": shot_ids[i], "score": round(float(score[i]), 4)} for i in order[:10]]
    return frozenset(shot_ids[i] for i, v in enumerate(score) if v >= bar), top


def main() -> int:
    shot_ids, vectors = load_shadow_embeddings()
    print(f"loaded {len(shot_ids)} shadow embeddings")

    moments, err = shadow_project_moments(shot_ids, vectors)
    if err:
        print("MOMENTS FAILED:", err)
        return 1
    print(f"\n=== MOMENTS ({len(moments)} found) ===")
    for m in moments:
        print(f"  {m['name']}: best={m['best']} median={m['median']} n_shots={len(m['shot_ids'])}")

    _distractions, n_distract = shadow_project_distractions(shot_ids, vectors)
    print(f"\n=== DISTRACTIONS: {n_distract} shots flagged ===")

    obstructions = shadow_project_obstructions(shot_ids, vectors)
    print(f"=== OBSTRUCTIONS: {len(obstructions)} shots flagged ===")

    opening_signs, opening_top = shadow_top_by_prompt(shot_ids, vectors, OPENING_SIGN_PROMPT, OPENING_SIGN_QUANTILE)
    print(f"=== OPENING SIGNS: {len(opening_signs)} shots at/above quantile {OPENING_SIGN_QUANTILE} ===")
    for t in opening_top[:5]:
        print(f"    {t}")

    table_settings, _table_top = shadow_top_by_prompt(shot_ids, vectors, TABLE_SETTING_PROMPT, TABLE_SETTING_QUANTILE)
    print(f"=== TABLE SETTINGS: {len(table_settings)} shots ===")

    out = {
        "n_shadow_embeddings": len(shot_ids),
        "moments": moments,
        "distraction_count": n_distract,
        "obstruction_count": len(obstructions),
        "opening_sign_count": len(opening_signs),
        "opening_sign_top10": opening_top[:10],
        "table_setting_count": len(table_settings),
    }
    Path("tools/fixtures/p6_1_stage_b_moments_result.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print("\nwrote tools/fixtures/p6_1_stage_b_moments_result.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
