"""P5.4: router precision tightening tests -- R4b frozen definition, accept-policy invariants
under the new evidence (ceremony_action stays abstain even when real positives were found for
it), and cache-key provenance for the shadow Qwen cache.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from shadow_qwen_cache import ALGORITHM_VERSION, MODEL_ID, PROMPT_VERSION, make_key
from shadow_semantic_escalation import (
    DeepPrediction,
    FastPrediction,
    decide,
    route,
)


def test_r4b_is_strict_subset_of_r3():
    """R4b must never escalate something R3 wouldn't -- by construction (R3 AND margin<0.3)."""
    cases = [
        FastPrediction("venue", 0.3, "detail", 0.29),
        FastPrediction("venue", 0.6, "detail", 0.1),
        FastPrediction("ceremony", 0.5, "venue", 0.1),
        FastPrediction("bride", 0.9, "venue", 0.05),
    ]
    for pred in cases:
        r3 = route(pred, "r3").escalate
        r4b = route(pred, "r4b").escalate
        if r4b:
            assert r3, "R4b escalated a case R3 would not -- violates the frozen R3-superset invariant"


def test_r4b_frozen_formula_unchanged():
    """The R4b threshold (margin<0.3, not_story_critical) must not have been loosened to chase
    a specific case's result -- pinned by exact boundary values."""
    just_under = FastPrediction("venue", 0.5, "detail", 0.21)  # margin = 0.29 < 0.3
    just_over = FastPrediction("venue", 0.5, "detail", 0.19)   # margin = 0.31 > 0.3
    assert route(just_under, "r4b").escalate is True
    assert route(just_over, "r4b").escalate is False


def test_ceremony_action_still_abstains_even_with_real_positive_evidence():
    """P5.4 found real (if occasionally hallucinated) ceremony_action calls on live data. The
    accept policy must still abstain -- P5.2/P5.3 never established a clean positive record for
    this event type, and this package explicitly does not add it to the allowlist."""
    deep = DeepPrediction(event_present="ceremony_action", confidence=0.95, reason="ring exchange")
    decision, _ = decide(deep)
    assert decision == "DEEP_ABSTAIN"


def test_entrance_still_unresolved():
    deep = DeepPrediction(event_present="entrance", confidence=0.9, reason="walking")
    decision, _ = decide(deep)
    assert decision == "DEEP_ABSTAIN"


def test_cache_key_includes_full_provenance():
    key = make_key("/some/path.MP4", 100)
    assert MODEL_ID in key
    assert PROMPT_VERSION in key
    assert ALGORITHM_VERSION in key
    assert "/some/path.MP4" in key
    assert "100" in key


def test_cache_key_differs_for_different_source_frame():
    k1 = make_key("/some/path.MP4", 100)
    k2 = make_key("/some/path.MP4", 200)
    assert k1 != k2
