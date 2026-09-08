"""Run Resolve's face analysis over the shoot and store the identities as our own data.

Resolve labels the same person "Face 2" from clip to clip, which is the part that makes this
worth having. It will not let a name be set through the API, so the names are not asked for
here: which identity is the bride and which the groom is worked out from our own shot
categories afterwards, and the editor is not asked to label anything.

Slow: 13-14 seconds a clip in Faster mode. Resumable — a clip that already carries a People
field is skipped, so it can be stopped and restarted.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

MODULES = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--better", action="store_true",
                        help="104 sn/klip yerine 14; bu iş için gerekmiyor")
    arguments = parser.parse_args()

    sys.path.insert(0, MODULES)
    import DaVinciResolveScript as dvr

    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        print("Resolve'a bağlanılamadı"); return 1
    pool = resolve.GetProjectManager().GetCurrentProject().GetMediaPool()
    clips = [c for c in (pool.GetCurrentFolder().GetClipList() or [])
             if (c.GetClipProperty("Type") or "") != "Audio"]
    if arguments.limit:
        clips = clips[:arguments.limit]

    found: dict[str, list[str]] = {}
    if arguments.out.exists():
        found = json.loads(arguments.out.read_text())

    started = time.time()
    done = skipped = 0
    for index, clip in enumerate(clips, 1):
        path = clip.GetClipProperty("File Path")
        if not path:
            continue
        name = Path(path).stem
        if name in found:
            skipped += 1
            continue
        people = (clip.GetMetadata() or {}).get("People")
        if not people:
            clip.AnalyzeForIntellisearch(True, arguments.better)
            people = (clip.GetMetadata() or {}).get("People")
        found[name] = [f.strip() for f in (people or "").split(",") if f.strip()]
        done += 1
        if done % 5 == 0 or index == len(clips):
            arguments.out.write_text(json.dumps(found, indent=1, ensure_ascii=False))
            elapsed = time.time() - started
            left = (len(clips) - index) * (elapsed / max(done, 1))
            print(f"{index}/{len(clips)} · yeni {done} · atlanan {skipped} · "
                  f"geçen {elapsed/60:.1f} dk · kalan ~{left/60:.0f} dk", flush=True)

    arguments.out.write_text(json.dumps(found, indent=1, ensure_ascii=False))
    identities = {face for faces in found.values() for face in faces}
    print(f"bitti: {len(found)} klip · {len(identities)} ayrı kimlik · "
          f"{(time.time()-started)/60:.1f} dk")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
