"""P6.25 -- supervised event-probe guards (read-only).

Locks: external-only annotations (no 15A leakage), the data-sufficiency finding (CAKE thin,
FIRST_DANCE none), the probe result that CLIP features ARE discriminative with supervision (PARTY) but
CAKE is below the promotion gate, and the V7 test-only cake control (miss). No DB/Resolve write.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tools/fixtures"


def _j(name):
    return json.loads((FIX / name).read_text())


def test_annotations_are_external_only_no_15a_leakage():
    lines = (FIX / "p6_25_event_annotations.jsonl").read_text().splitlines()
    for line in lines:
        d = json.loads(line)
        rid = d.get("reference_id", "")
        assert "V7" not in rid and rid != "is edit"
        # no 15A source clip names (C7xxx / DJI_) appear as reference ids
        assert not rid.startswith("ref:C7") and "DJI_" not in rid


def test_grouped_split_and_no_v7_in_training():
    r = _j("p6_25_probe_results.json")
    assert r["leakage"]["v7_or_is_edit_in_training"] is False
    assert "leave-one-wedding-out" in r["leakage"]["split"]


def test_party_is_learnable_features_are_discriminative_with_supervision():
    """The decisive positive: unlike zero-shot P6.24, a supervised probe learns PARTY with high
    precision under grouped leave-one-wedding-out -> the CLIP features DO carry the signal."""
    r = _j("p6_25_probe_results.json")
    party = r["results"]["linear"]["PARTY"]
    assert party["precision"] >= 0.8 and party["recall"] >= 0.8


def test_cake_is_below_the_promotion_gate():
    r = _j("p6_25_probe_results.json")
    cake = r["acceptance"]["CAKE"]
    assert cake["weddings"] == 5                    # only 5 weddings contain labelled cake
    assert cake["linear_precision"] < 0.80 or cake["linear_recall"] < 0.5   # below gate


def test_first_dance_has_insufficient_labelled_evidence():
    r = _j("p6_25_probe_results.json")
    assert r["first_dance_labelled"] == 0
    assert "INSUFFICIENT" in r["acceptance"]["FIRST_DANCE"]


def test_v7_cake_positive_control_is_a_miss_test_only():
    v = _j("p6_25_v7_control.json")
    assert v["model_frozen_before_v7"] is True and v["v7_in_training"] is False
    assert v["cake_positive_control"]["source"] == "C7309.MP4"
    assert v["cake_positive_control"]["detected_as_cake"] is False        # verified cake, not detected
    assert v["v7_shots_predicted_cake"] == []
    # party still transfers to V7's reception (supervision works where evidence exists)
    assert v["v7_prediction_distribution"].get("PARTY", 0) >= 5


def test_promotion_gate_fails_no_corpus_v4():
    r = _j("p6_25_probe_results.json")
    cake_pass = r["acceptance"]["CAKE"]["linear_precision"] >= 0.80 and \
        r["acceptance"]["CAKE"]["linear_recall"] >= 0.80
    first_dance_pass = r["first_dance_labelled"] > 0
    assert not (cake_pass and first_dance_pass)          # gate fails -> corpus not promoted
