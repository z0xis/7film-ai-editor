"""P6.24 -- fine wedding-event detection guards (read-only).

Locks the honest negative result: zero-shot CLIP + multi-frame + temporal context + prompt ensembles
does NOT reliably detect fine wedding events. Asserts on the committed detection/validation fixture.
No production DB / Resolve / timeline write is involved.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tools/fixtures"


def _j(name):
    return json.loads((FIX / name).read_text())


def test_event_taxonomy_and_method_are_recorded():
    d = _j("p6_24_event_detection.json")
    for ev in ("CAKE", "FIRST_DANCE", "BOUQUET", "ENTRANCE", "CEREMONY", "KINA"):
        assert ev in d["events"]
    assert "multi-frame" in d["method"] and "prompt ensembles" in d["method"]


def test_cake_is_a_total_detection_miss():
    """V7 (and several references) verifiably contain cake, yet CAKE is never the argmax event -> a
    SEMANTIC_EXTRACTION_MISS even with a dedicated multi-frame detector, not an absence of cake."""
    d = _j("p6_24_event_detection.json")
    assert d["cake_argmax_count"] == 0


def test_first_dance_cannot_be_distinguished_from_couple_portraits():
    d = _j("p6_24_event_detection.json")
    fd = [s for s in d["validation"]["samples"] if s["pred"] == "FIRST_DANCE"]
    assert fd and all(not s["correct"] for s in fd)          # all first-dance preds were couple portraits
    assert all("portrait" in s["actual"] or "not dancing" in s["actual"] for s in fd)


def test_sampled_precision_is_effectively_zero():
    d = _j("p6_24_event_detection.json")
    assert d["validation"]["precision_sampled"] == 0.0
    assert len(d["validation"]["samples"]) >= 9


def test_confidence_is_overwhelmingly_low_none_high():
    d = _j("p6_24_event_detection.json")
    conf = d["confidence_distribution"]
    assert conf.get("HIGH", 0) == 0
    total = sum(conf.values())
    assert conf.get("LOW", 0) + conf.get("UNKNOWN", 0) >= 0.85 * total


def test_fine_event_arc_is_unreliable_not_integrated():
    """The fine-event learned arc is dominated by over-fired CEREMONY/BOUQUET/SPARKLER on references
    that are actually couple/party -- so it is NOT promoted into the planning corpus."""
    d = _j("p6_24_event_detection.json")
    arc = d["fine_event_learned_arc"]
    assert arc.count("CEREMONY") + arc.count("BOUQUET") + arc.count("SPARKLER_SENDOFF") >= 6
    # the reliable coarse arc (P6.23) remains the working structure
    assert "COUPLE" in d["coarse_category_arc"]
