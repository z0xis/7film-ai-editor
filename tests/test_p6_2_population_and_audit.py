import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

ROOT = Path(__file__).resolve().parents[1]


def test_manifest_human_labels_use_closed_vocabulary():
    manifest = json.loads((ROOT / "tools/fixtures/p6_2_human_audit_manifest.json").read_text())
    allowed = {"TRUE_MATCH", "PLAUSIBLE_MATCH", "AMBIGUOUS", "FALSE_POSITIVE"}
    for c in manifest["candidates"]:
        assert c["human_label"] in allowed
    for c in manifest["opening_sign_top10_audit"] + manifest["distraction_sanity_sample"]:
        assert c["human_label"] in allowed


def test_manifest_covers_all_six_frozen_moments():
    manifest = json.loads((ROOT / "tools/fixtures/p6_2_human_audit_manifest.json").read_text())
    names = {c["moment_name"] for c in manifest["candidates"]}
    assert names == {"entrance", "ring", "kiss", "cake", "cake_feed", "first_dance"}


def test_frozen_shortlists_match_p6_1_fixture_unmodified():
    """P6.2 must audit the exact P6.1 shortlists -- not regenerate them after seeing labels."""
    p61 = json.loads((ROOT / "tools/fixtures/p6_1_stage_b_moments_result.json").read_text())
    manifest = json.loads((ROOT / "tools/fixtures/p6_2_human_audit_manifest.json").read_text())
    by_moment = {}
    for c in manifest["candidates"]:
        by_moment.setdefault(c["moment_name"], set()).add(c["shot_id"])
    for m in p61["moments"]:
        assert by_moment[m["name"]] == set(m["shot_ids"])


def test_moment_prompts_and_lift_still_unchanged():
    from sevenfilm.services.moments import MOMENT_LIFT, MOMENT_PROMPTS

    assert MOMENT_LIFT == 1.25
    assert MOMENT_PROMPTS["entrance"] == "a bride and groom entering a room while guests applaud"
    assert MOMENT_PROMPTS["ring"] == "putting a wedding ring on a finger, close up of hands"


def test_human_labels_never_imported_by_runtime_moment_code():
    """No production or shadow moment-computation module reads the P6.2 manifest."""
    for path in [
        ROOT / "apps/api/sevenfilm/services/moments.py",
        ROOT / "apps/api/sevenfilm/services/planner.py",
        ROOT / "tools/shadow_moments_full.py",
    ]:
        source = path.read_text()
        assert "p6_2_human_audit_manifest" not in source
        assert "human_label" not in source
