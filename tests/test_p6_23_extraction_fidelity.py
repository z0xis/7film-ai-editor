"""P6.23 -- reference extraction fidelity + Tier-2 semantic enrichment guards.

Locks the fixed V7 audio extraction (two songs + crossfade + entrance SFX -- the P6.22 "one song" was
an extraction bug), the semantic enrichment of the 18 render-only references, and the fact that
retrieval now changes sequence STRUCTURE. Read-only; asserts on committed fixtures.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tools/fixtures"


def _j(name):
    return json.loads((FIX / name).read_text())


# --- V7 audio fidelity (the critical contradiction) --------------------------------------------

def test_v7_has_two_songs_not_one():
    f = _j("p6_23_v7_audio_fidelity.json")
    assert f["audio_tracks"] == 4
    assert len(f["music_sections"]) == 2                     # P6.22 wrongly reported one
    names = sorted(s["track"] for s in f["music_sections"])
    assert any("Ordinary" in n for n in names)
    assert any("Wella Kole" in n for n in names)
    assert "EXTRACTION_BUG" in f["root_cause"]


def test_v7_music_transition_has_crossfade_and_entrance_sfx():
    f = _j("p6_23_v7_audio_fidelity.json")
    assert len(f["music_transitions"]) == 1
    t = f["music_transitions"][0]
    assert 77.0 < t["at_s"] < 81.0                           # ~78-80s (matches prior audit)
    assert t["crossfade_s"] > 1.0                            # songs overlap -> crossfade
    assert "SFX_ENTRANCE_v2.wav" in t["entrance_sfx"]
    assert t["energy_delta"] == "up"


# --- Tier-2 semantic enrichment ----------------------------------------------------------------

def test_tier2_is_now_semantic_not_duration_only():
    s = _j("p6_22_corpus_summary.json")
    assert s["build_version"] == 2
    assert s["counts"]["semantic_shots"] == s["counts"]["shots"]   # every shot carries semantics
    assert s["counts"]["episodes"] > 300                          # real event episodes (was ~102)
    t2 = [e for e in s["edits"] if e["tier"] == 2]
    assert len(t2) == 18
    for e in t2:
        assert "category(model)" in e["evidence"] and "motion" in e["evidence"]


def test_retrieval_examples_carry_real_scale_patterns():
    ex = _j("p6_22_retrieval_examples.json")
    real = 0
    for hits in ex.values():
        for h in hits:
            if any(x != "?" for x in h.get("scale_pattern", [])):
                real += 1
    assert real >= 1                                           # scales come from actual detected shots


# --- structure now transfers -------------------------------------------------------------------

def test_retrieval_changes_structure_and_stays_leakage_clean():
    h = _j("p6_22_holdout.json")
    assert h["leakage_check"]["clean"] is True
    abl = h["ablation"]
    assert abl["retrieval_event_order_differs_from_off"] is True
    # the learned arc is reference-driven (not the fixed canonical arc)
    assert abl["retrieval_event_order"] != abl["off_event_order"]


# --- cake positive control: detection miss != absence ------------------------------------------

def test_cake_is_a_semantic_extraction_miss_not_absence():
    """V7 verifiably contains cake (C7309). The Tier-2 CLIP vocabulary has no cake event, so the
    reference-learned arc cannot include CAKE -- that is SEMANTIC_EXTRACTION_MISS, not 'no cake'."""
    h = _j("p6_22_holdout.json")
    v7_events = h["v7_structure"]["event_order"]
    assert "CAKE" in v7_events                                 # V7 DOES contain cake (verified)
    # the render-only learned arc has no CAKE token -> a detection limit, documented as such
    assert "CAKE" not in h["ablation"]["retrieval_event_order"]
