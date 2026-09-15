import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from shadow_semantic_escalation import (
    DeepPrediction,
    FastPrediction,
    cache_key,
    decide,
    route,
)


def test_r0_never_escalates():
    pred = FastPrediction("venue", 0.1, "detail", 0.05)
    assert route(pred, "r0").escalate is False


def test_r3_escalates_on_non_story_critical_top1():
    pred = FastPrediction("venue", 0.9, "detail", 0.1)
    decision = route(pred, "r3")
    assert decision.escalate is True
    assert "venue" in decision.reason


def test_r3_does_not_escalate_story_critical_top1():
    pred = FastPrediction("ceremony", 0.9, "venue", 0.1)
    assert route(pred, "r3").escalate is False


def test_router_is_deterministic():
    pred = FastPrediction("bride", 0.5, "venue", 0.4)
    results = {route(pred, "r4").escalate for _ in range(20)}
    assert results == {route(pred, "r4").escalate}


def test_router_has_no_ground_truth_or_event_fields():
    """The router signature only accepts FastPrediction (category/scores) -- it structurally
    cannot see an event label, filename, or golden-corpus annotation."""
    import inspect

    sig = inspect.signature(route)
    param_names = set(sig.parameters) - {"router"}
    assert param_names == {"pred"}
    fast_fields = {f for f in FastPrediction.__dataclass_fields__}
    assert "event_label" not in fast_fields
    assert "ground_truth" not in fast_fields
    assert "filename" not in fast_fields


def test_deep_accept_for_supported_event():
    deep = DeepPrediction(event_present="cake_cutting", confidence=0.98, reason="knife on cake")
    decision, _reason = decide(deep)
    assert decision == "DEEP_ACCEPT"


def test_deep_abstain_for_unresolved_entrance():
    """Entrance has 2/2 FN evidence from P5.2 (both single-frame and temporal) -- must never be
    silently accepted just because Qwen returned a non-'none' label for it."""
    deep = DeepPrediction(event_present="entrance", confidence=0.95, reason="bride walking")
    decision, reason = decide(deep)
    assert decision == "DEEP_ABSTAIN"
    assert "unresolved" in reason


def test_deep_abstain_on_parse_failure_not_treated_as_correct():
    deep = DeepPrediction(event_present="none", confidence=0.0, reason="", parse_failed=True)
    decision, _ = decide(deep)
    assert decision == "DEEP_ABSTAIN"


def test_fast_only_when_not_escalated():
    decision, _reason = decide(None)
    assert decision == "FAST_ONLY"


def test_high_self_reported_confidence_alone_does_not_force_accept():
    """A 0.99 self-reported confidence on an event outside the supported set must still abstain
    -- confidence is not treated as a calibrated probability."""
    deep = DeepPrediction(event_present="ceremony_action", confidence=0.99, reason="looks confident")
    decision, _ = decide(deep)
    assert decision == "DEEP_ABSTAIN"


def test_cache_key_changes_with_model_identity():
    k1 = cache_key("fp1", 1.5, "openai/clip-vit-base-patch32", None, "v1", "a1")
    k2 = cache_key("fp1", 1.5, "google/siglip2-so400m-patch14-384", None, "v1", "a1")
    assert k1 != k2


def test_cache_key_changes_with_prompt_version():
    k1 = cache_key("fp1", 1.5, "openai/clip-vit-base-patch32", None, "v1", "a1")
    k2 = cache_key("fp1", 1.5, "openai/clip-vit-base-patch32", None, "v2", "a1")
    assert k1 != k2


def test_temporal_frames_never_requested_by_deep_prediction_contract():
    """The shadow DeepPrediction contract carries a single source_frame, never a
    before/current/after triple -- P5.2 showed temporal input adds no value at higher cost."""
    fields = DeepPrediction.__dataclass_fields__
    assert "source_frame" in fields
    assert "before_frame" not in fields
    assert "after_frame" not in fields
