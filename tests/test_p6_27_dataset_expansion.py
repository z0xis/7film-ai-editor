"""P6.27 -- event-rich dataset expansion / coverage guards (read-only).

Locks: the thorough temporal audit of all 18 finals + Elenora reconnaissance; the coverage gate is
computed honestly and NOT weakened; both acceptance events FAIL the >=8-wedding gate from the accessible
archive; no model trained; 15A/V7 untouched. No DB / Resolve / timeline write.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tools/fixtures"


def _cov():
    return json.loads((FIX / "p6_27_coverage.json").read_text())


def _v3():
    return [json.loads(x) for x in (FIX / "p6_27_temporal_audit_v3.jsonl").read_text().splitlines() if x.strip()]


def test_thorough_audit_records_are_temporally_verified_finals():
    hdr = _v3()[0]
    assert hdr["source_type"] == "FINAL_EDIT"
    rows = [r for r in _v3() if r.get("decision") in ("PROBABLE", "CONFIRMED", "REJECTED")]
    assert rows
    for r in rows:
        # every FINAL_EDIT verdict carries temporal evidence; the raw Elenora candidate is flagged
        if r.get("source_type") == "RAW_FOOTAGE" or r.get("reference_id") == "elenora_mustafa":
            continue
        assert r["temporal_verified"] is True and r["evidence"]


def test_coverage_gate_is_not_weakened_and_both_events_fail():
    c = _cov()
    assert c["coverage_gate"]["threshold_weddings"] == 8
    assert c["gate_not_weakened"] is True
    assert "FAIL" in c["coverage_gate"]["FIRST_DANCE"]
    assert "FAIL" in c["coverage_gate"]["CAKE_ACTION"]


def test_first_dance_has_zero_confirmed_across_the_cinematic_finals():
    c = _cov()["thorough_temporal_audit_18_finals"]["FIRST_DANCE"]
    assert c["confirmed_weddings"] == 0           # 9 probable are ambiguous, unsafe as positives
    assert c["probable_weddings"] >= 5


def test_accessible_archive_cannot_meet_the_gate():
    c = _cov()["archive_inventory"]
    assert c["external_cinematic_finals"] == 18
    assert c["real_documentary_weddings_accessible"] == 1     # only Elenora (raw)
    assert c["client_wedding_finals_accessible"] == 0
    assert c["15a_excluded"] is True


def test_no_model_trained_and_15a_v7_untouched():
    c = _cov()
    assert c["model_trained"] is False
    assert c["15a_training_examples"] == 0 and c["v7_used"] is False


def test_elenora_is_one_raw_candidate_not_relied_on_alone():
    c = _cov()["archive_inventory"]["elenora_mustafa"]
    assert "raw footage" in c["type"]
    # and the max-coverage math shows one wedding cannot satisfy the gate
    mc = _cov()["max_available_coverage"]
    assert "~1" in mc["FIRST_DANCE_confirmed"]
