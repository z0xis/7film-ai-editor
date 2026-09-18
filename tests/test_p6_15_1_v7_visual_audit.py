"""P6.15.1 -- V7 bounded visual reference audit guards (read-only).

Locks the visual-audit conclusions (frames extracted read-only from proxies, inspected, deleted).
No Resolve/timeline/DB write; no personal media committed.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tools/fixtures/p6_15_1_v7_visual_audit.json"


def _a():
    return json.loads(FIX.read_text())


def test_intro_cake_first_dance_outro_are_coherent():
    a = _a()
    assert a["intro"]["result"].startswith("COHERENT")
    assert "COHERENT" in a["cake"]["result"] or "TRUE_MATCH" in a["cake"]["result"]
    assert "COHERENT" in a["first_dance"]["result"]
    assert a["bouquet_outro"]["result"] == "COHERENT"


def test_first_dance_is_a_real_forward_reuse_sequence():
    fd = _a()["first_dance"]
    assert fd["reuse"] == "GOOD_FORWARD_REUSE"
    assert "1202" in fd["sources"][0] and "10500" in fd["sources"][1]


def test_bouquet_causal_order_is_correct():
    b = _a()["bouquet_outro"]
    assert "CORRECT" in b["causal_order"]


def test_useful_coherent_story_exists_after_planner_stop():
    r = _a()["early_stop_reinterpretation"]
    assert r["useful_coherent_story_after_planner_stop"] == "YES"
    assert any("first dance" in m for m in r["material"])


def test_no_writes_and_no_frames_committed():
    s = _a()["safety"]
    assert s["resolve_writes"] == 0
    assert s["db_writes"] == 0
    assert s["timeline_changes"] == 0
    assert s["frames_committed"] is False


def test_p6_16_requirements_are_recorded():
    reqs = _a()["p6_16_design_requirements"]
    assert len(reqs) >= 5
    assert any("reception" in r for r in reqs)
