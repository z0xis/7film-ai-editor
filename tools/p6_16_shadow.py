"""P6.16 -- run the (fixed) production planner shadow and write tools/fixtures/p6_16_fixed_shadow.json.

Thin wrapper over the P6.14 shadow harness: same read-only, write-hardened, no-persistence run over
the real production state, but the planner now carries the P6.16 false-early-stop fix. Kept separate
from p6_14_shadow_plan.json so the historical broken baseline stays intact for comparison.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("p6_14_shadow", ROOT / "tools/p6_14_shadow_planner.py")
h = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(h)

# Redirect the harness output to the P6.16 fixture, leaving the P6.14 baseline untouched.
h.FIXTURE = ROOT / "tools" / "fixtures" / "p6_16_fixed_shadow.json"

if __name__ == "__main__":
    import json
    out = h.main()
    print(json.dumps({k: v for k, v in out.items() if k not in ("all_items", "moment_coverage")},
                     indent=2, sort_keys=True, default=str))
