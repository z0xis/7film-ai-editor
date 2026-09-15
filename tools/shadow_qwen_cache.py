"""P5.4: shadow-only Qwen result cache. Key = source fingerprint (path+start_frame) + model_id +
model_revision + prompt_version + algorithm_version. Not a production cache -- lives entirely in
tools/fixtures/p5_4_qwen_cache.json, read/written only by shadow harness scripts.
"""

from __future__ import annotations

import json
from pathlib import Path

CACHE_PATH = Path("tools/fixtures/p5_4_qwen_cache.json")
MODEL_ID = "Qwen/Qwen3-VL-4B-Instruct"
PROMPT_VERSION = "p5.2-single-frame-v1"
ALGORITHM_VERSION = "p5.4-shadow-v1"


def make_key(path: str, start_frame: int) -> str:
    return f"{path}::{start_frame}::{MODEL_ID}::{PROMPT_VERSION}::{ALGORITHM_VERSION}"


def load_cache() -> dict:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text())
    return {}


def save_cache(cache: dict) -> None:
    CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False))


def seed_from_p53(cache: dict, p53_results: list[dict], router_data: list[dict]) -> int:
    """Seed the P5.4 cache from P5.3's already-computed real Qwen calls, keyed the same way, so
    identical (path, start_frame) pairs are not re-run."""
    by_index = {e["frame_index"]: e for e in router_data}
    seeded = 0
    for r in p53_results:
        meta = by_index.get(r["frame_index"])
        if not meta:
            continue
        key = make_key(meta["path"], meta["start_frame"])
        if key not in cache:
            cache[key] = {
                "raw": r["raw"], "parsed": r["parsed"], "parse_failed": r["parse_failed"],
                "exception": r["exception"], "latency_s": r["latency_s"], "source": "p5.3-fresh",
            }
            seeded += 1
    return seeded
