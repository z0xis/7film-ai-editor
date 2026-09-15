import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from shadow_budget_router import priority_score


def test_priority_score_deterministic():
    pred = {"top1": "venue", "top1_score": 0.5, "margin": 0.1}
    s1 = priority_score(pred)
    s2 = priority_score(pred)
    assert s1 == s2


def test_priority_score_has_no_ground_truth_or_event_fields():
    import inspect

    sig = inspect.signature(priority_score)
    assert list(sig.parameters) == ["pred"]


def test_priority_score_higher_for_non_story_critical_and_ambiguous():
    clear_story_critical = {"top1": "ceremony", "top1_score": 0.9, "margin": 0.6}
    ambiguous_container = {"top1": "venue", "top1_score": 0.3, "margin": 0.02}
    assert priority_score(ambiguous_container) > priority_score(clear_story_critical)


def test_priority_score_uses_only_generic_signals():
    """The function signature and body must never reference event labels or filenames --
    guarded structurally, not just by convention."""
    import inspect

    source = inspect.getsource(priority_score)
    for forbidden in ("event_label", "ground_truth", "filename", "ceremony_action", "first_dance"):
        assert forbidden not in source
