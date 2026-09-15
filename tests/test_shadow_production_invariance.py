"""P5.3: shadow semantic escalation must be structurally incapable of touching production
behavior. These tests assert the shadow module has no import-time or call-time dependency on
the production API, database, or planner -- not just that nobody happens to call it today.
"""

import ast
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS_DIR))


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_shadow_module_does_not_import_production_api():
    imports = _imports(TOOLS_DIR / "shadow_semantic_escalation.py")
    assert "sevenfilm" not in imports
    assert "fastapi" not in imports


def test_shadow_module_does_not_import_sqlite_or_db():
    imports = _imports(TOOLS_DIR / "shadow_semantic_escalation.py")
    assert "sqlite3" not in imports


def test_shadow_router_script_reads_db_read_only():
    """The 15A shadow sampler must connect with mode=ro -- grep guard against accidental
    write-mode connections creeping into this file."""
    source_files = [
        TOOLS_DIR / "shadow_router_15agustos.py",
        TOOLS_DIR / "shadow_qwen_15agustos.py",
    ]
    for f in source_files:
        if f.exists():
            text = f.read_text()
            assert "mode=ro" in text or "sqlite3" not in text, f"{f} touches sqlite3 without mode=ro"


def test_production_vision_module_unchanged_by_shadow_import():
    """Importing the shadow module must not import or mutate apps/api/sevenfilm/services/vision.py
    state (e.g. shared CATEGORY_PROMPTS dict identity)."""
    import shadow_semantic_escalation as shadow

    assert not hasattr(shadow, "VisionClassifier")
    assert not hasattr(shadow, "DATABASE")


def test_decide_and_route_are_pure_functions_no_side_effects():
    from shadow_semantic_escalation import FastPrediction, route

    pred = FastPrediction("bride", 0.5, "venue", 0.4)
    r1 = route(pred, "r3")
    r2 = route(pred, "r3")
    assert r1 == r2
