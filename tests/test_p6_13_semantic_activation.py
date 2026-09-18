"""P6.13 -- Read-only production semantic / moment activation audit guards.

Assert the recorded conclusions of tools/p6_13_semantic_activation_audit.py (a strictly read-only
audit of the remediated production DB). These are accepted-production regression guards: they lock
that the P6.12 remediation actually activated moments and candidate eligibility, and that the audit
tool performs no writes.
"""

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tools/fixtures/p6_13_activation_audit.json"
TOOL = ROOT / "tools/p6_13_semantic_activation_audit.py"


def _r():
    return json.loads(FIX.read_text())


def test_audit_tool_is_read_only():
    src = TOOL.read_text()
    ast.parse(src)
    assert "mode=ro" in src
    for w in ("INSERT INTO", "DELETE FROM", "UPDATE ", "replace_rows", '.insert("'):
        assert w not in src, f"audit tool must not write: {w}"


def test_production_is_semantically_full():
    p = _r()["production"]
    assert p["shots"] == 2638
    assert p["embeddings"] == 2638
    assert p["tq_zero"] == 0
    assert p["clip_labels"] == 2638
    assert p["elenora_embeddings"] == 1405  # cross-project untouched


def test_eligibility_blocker_resolved():
    e = _r()["eligibility"]
    # Pre-remediation ~2327/2638 were blocked by tq=0; now nearly all shots are usable.
    assert e["total"] == 2638
    assert e["usable"] >= 2600
    assert e["blocked_quality"] <= 30


def test_all_six_moment_families_active_and_usable():
    m = _r()["moments"]
    assert set(m) == {"entrance", "ring", "kiss", "cake", "cake_feed", "first_dance"}
    for name, fam in m.items():
        assert fam["count"] >= 1, name
        # every shortlisted moment member passes _is_usable (reaches the candidate pool)
        assert fam["usable_members"] == fam["count"], name


def test_known_good_sources_recovered():
    m = _r()["moments"]
    assert m["cake"]["known_recovered"].get("C7309") is True
    assert m["first_dance"]["known_recovered"].get("DJI_0528") is True
    assert m["first_dance"]["known_recovered"].get("DJI_0529") is True


def test_shot_windows_clean_after_p6_12():
    w = _r()["shot_windows"]
    assert w["orphan_windows"] == 0
    assert w["distinct_shots_with_windows_15a"] == 2638


def test_helpers_activated_consistent_with_shadow():
    h = _r()["helpers"]
    assert h["obstructions"] == 264       # exact match to P6.1 shadow
    assert h["distractions"] >= 400       # ~494 shadow; activation confirmed
    assert h["opening_signs"] >= 1


def test_chronology_gap_is_exactly_the_ten_drones():
    c = _r()["chronology"]
    assert c["assets_without_timecode"] == 10
    assert all(n.startswith("DJI_") for n in c["assets_without_tc_names"])


def test_first_dance_chronology_hazard_present():
    """The true isolated first-dance shots are the drone ones, which lack timecode; the timecoded
    members are camera shots. This is the carried-forward chronology hazard, not a semantic gap."""
    fd = _r()["moments"]["first_dance"]
    assert fd["chronology_unknown"] >= 1
    assert fd["known_recovered"].get("DJI_0528") is True
