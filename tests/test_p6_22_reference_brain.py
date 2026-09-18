"""P6.22 -- reference-conditioned editor brain foundation guards.

The full corpus lives under data/ (gitignored, media-derived); these tests assert on the committed
summary fixtures and, when the sidecar corpus is present locally, verify determinism + no leakage by
re-running. Nothing here writes the production DB / a timeline / Resolve.
"""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tools/fixtures"
CORPUS = ROOT / "data/reference_editor/corpus/corpus.json"


def _j(name):
    return json.loads((FIX / name).read_text())


# --- corpus schema / tiers ---------------------------------------------------------------------

def test_corpus_has_two_tiers_with_provenance():
    s = _j("p6_22_corpus_summary.json")
    assert s["schema_version"] == "p6.22.1"
    assert s["counts"]["tier1_edits"] == 2          # V7 + is edit (rich)
    assert s["counts"]["tier2_edits"] == 18         # the 18 render-only references
    # every edit keeps provenance (a source + evidence list)
    for e in s["edits"]:
        assert e["reference_id"] and e["evidence"]
        assert e["tier"] in (1, 2)


def test_tier1_is_rich_tier2_is_render_only():
    s = _j("p6_22_corpus_summary.json")
    t1 = [e for e in s["edits"] if e["tier"] == 1]
    t2 = [e for e in s["edits"] if e["tier"] == 2]
    for e in t1:
        assert "source_in_out" in e["evidence"] and "category" in e["evidence"]
    for e in t2:
        assert e["kind"] == "render_only" and "source_in_out" not in e["evidence"]


# --- retrieval returns grammar, not target shots -----------------------------------------------

def test_retrieval_examples_return_reference_grammar_not_shot_ids():
    ex = _j("p6_22_retrieval_examples.json")
    for hits in ex.values():
        for h in hits:
            assert h["reference_id"].startswith("ref:")   # holdout -> Tier-2 references only
            assert "why" in h and h["story_role"]
            # no target (15A) shot id is ever returned
            assert "shot_id" not in h


# --- holdout: no leakage, ablation behaviour ---------------------------------------------------

def test_holdout_excludes_15a_human_edits_no_leakage():
    h = _j("p6_22_holdout.json")
    assert h["leakage_check"]["clean"] is True
    assert "IS EDIT - AI CUT V7" not in h["plan_holdout"]["active_references"]
    assert "is edit" not in h["plan_holdout"]["active_references"]


def test_stage1_plan_is_abstract_no_shot_ids():
    h = _j("p6_22_holdout.json")
    plan = h["plan_holdout"]
    assert plan["role_order"] and plan["event_order"]
    for seq in plan["sequences"]:
        assert "shot_scale_roles" in seq and "duration_target_s" in seq
        assert "shot_id" not in json.dumps(seq)          # abstract only


def test_retrieval_now_changes_sequence_order_not_only_pacing():
    """P6.23: after Tier-2 semantic enrichment the retrieval-learned arc drives the event ORDER, which
    now differs from the off/aggregate canonical arc (P6.22's gap is closed)."""
    h = _j("p6_22_holdout.json")
    abl = h["ablation"]
    assert abl["retrieval_durations"] != abl["off_durations"]                 # pacing still changes
    assert abl["retrieval_event_order_differs_from_off"] is True              # ...and now ORDER too
    assert abl["retrieval_event_order_differs_from_aggregate"] is True


def test_v7_used_only_after_generation():
    h = _j("p6_22_holdout.json")
    # V7 appears only in the post-hoc comparison + ground-truth structure, never in retrieval
    assert h["v7_structure"]["song_count"] == 2          # P6.23: two songs (fixed extraction)
    assert "holdout_vs_v7" in h["comparison"]


# --- determinism (only when the sidecar corpus is present) -------------------------------------

@pytest.mark.skipif(not CORPUS.is_file(), reason="sidecar corpus not built in this environment")
def test_retrieval_and_stage1_are_deterministic():
    import sys
    sys.path.insert(0, str(ROOT))
    from tools.refbrain.eval_holdout import run
    a = run()
    b = run()
    assert a == b
    assert a["ablation"]["retrieval_durations"] == b["ablation"]["retrieval_durations"]
