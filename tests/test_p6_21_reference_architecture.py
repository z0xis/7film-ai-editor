"""P6.21 -- reference-learning architecture audit guards (read-only, no writes).

Locks the audit's factual findings: (1) the reference style profile IS runtime-active (the ablation
changes the plan), (2) it is the ONLY reference-derived planner input, (3) there is no reference DB
table and no cross-project retrieval, (4) the timeline is a greedy fill-to-duration loop, not a
story/sequence state machine. These are architecture facts, not behaviour changes.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tools/fixtures"
PLANNER = (ROOT / "apps/api/sevenfilm/services/planner.py").read_text()
API = (ROOT / "apps/api/sevenfilm/api.py").read_text()
DB = (ROOT / "apps/api/sevenfilm/db.py").read_text()


def _abl():
    return json.loads((FIX / "p6_21_reference_ablation.json").read_text())


def test_reference_profile_is_runtime_active():
    """Removing the 18-reference style profile changes the plan -- so it is not pure documentation."""
    a = _abl()
    assert a["reference_count_in_profile"] == 18
    assert a["A_vs_B"]["identical"] is False          # style_profile=None yields a different plan
    assert a["A_normal"]["hash"] != a["B_no_reference"]["hash"]
    # the influence is large: the deliverable collapses without the reference pacing/arc/hold rules
    assert a["B_no_reference"]["n"] < a["A_normal"]["n"]


def test_style_profile_is_the_only_reference_derived_planner_input():
    """The single reference artifact the runtime loads is the aggregate style-profile JSON."""
    assert '"references" / "7film-style-profile.json"' in API
    # no reference-edit corpus / retrieval / cross-project embedding is wired into the planner
    for token in ("analogous", "retrieve_sequence", "reference_edit", "cross_project", "reference_embedding"):
        assert token not in PLANNER


def test_no_reference_database_table_exists():
    """References never became a queryable DB representation -- only aggregate constants in a JSON."""
    tables = [line.split()[-1] for line in DB.splitlines() if "CREATE TABLE IF NOT EXISTS" in line]
    assert "reference_edits" not in tables and "reference_shots" not in tables
    assert "learned_grammar" not in tables and "reference_sequences" not in tables


def test_timeline_is_a_greedy_fill_loop_not_a_story_state_machine():
    """The core is a single scored loop to target duration; the arc is only progress-indexed scoring."""
    assert "while current_frame < target_frames:" in PLANNER
    # no first-class phase/climax/section-role state variable drives selection
    assert "self.phase" not in PLANNER and "current_phase =" not in PLANNER


def test_intro_outro_are_duration_ramps_not_sequences():
    """Intro/outro exist only as reference-derived ramps layered on the same loop."""
    assert "OPENING_SECONDS" in PLANNER and "OPENING_CATEGORIES" in PLANNER
    assert "CLOSING_SCALE" in PLANNER
