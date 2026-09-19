"""P6.26 -- temporal ground-truth audit guards (read-only).

Locks: the contact-sheet limitation is acknowledged; the temporal audit used motion strips (not stills);
every audit record carries temporal_verified evidence; the acceptance events still lack cross-wedding
support; and the discovered external archive is raw (needs annotation). No DB / Resolve / timeline write.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tools/fixtures"


def _summary():
    return json.loads((FIX / "p6_26_audit_summary.json").read_text())


def _audit():
    return [json.loads(x) for x in (FIX / "p6_26_temporal_audit.jsonl").read_text().splitlines() if x.strip()]


def test_contact_sheet_limitation_is_acknowledged():
    s = _summary()
    assert s["contact_sheet_limitation_confirmed"] is True
    assert "temporal" in s["method"]


def test_audit_records_are_temporally_verified_not_thumbnail_only():
    rows = [r for r in _audit() if "decision" in r]
    assert rows
    for r in rows:
        assert r["temporal_verified"] is True and r["evidence"]
        assert r["decision"] in ("CONFIRMED", "PROBABLE", "REJECTED", "UNKNOWN")


def test_first_dance_has_no_confirmed_cross_wedding_support():
    fd = [r for r in _audit() if r.get("event") == "FIRST_DANCE"]
    confirmed = {r["reference_id"] for r in fd if r["decision"] == "CONFIRMED"}
    assert len(confirmed) == 0                       # 0 confirmed isolated first-dances
    s = _summary()["first_dance"]
    assert s["sufficiency"] == "INSUFFICIENT_CROSS_WEDDING_SUPPORT"
    # but it is NOT claimed as absence -- probables exist
    assert s["probable_weddings"] >= 1


def test_cake_action_is_below_five_confirmed_weddings():
    s = _summary()["cake_action"]
    assert s["confirmed_plus_probable_weddings"] < 5
    assert s["sufficiency"] == "INSUFFICIENT_CROSS_WEDDING_SUPPORT"


def test_external_archive_found_and_is_raw():
    a = _summary()["external_archive"]
    assert a["path_required"] is False               # a separate wedding archive is accessible
    assert "raw footage" in a["type"]                # but it needs event annotation (not a final edit)


def test_representation_comparison_was_not_run_prematurely():
    s = _summary()
    assert s["representation_comparison_run"] is False
    assert s["15a_training_examples"] == 0 and s["v7_used"] is False
