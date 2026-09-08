"""Read the clips the editor flagged in Resolve and stop the edit using them.

The rejection list has been there since the window measurements went in, and it stayed empty
because there was no practical way to fill it: the editor works in Resolve, not in the panel.
Meanwhile the same shots kept coming back — a table centrepiece, a shot of the ceiling, a clip
already objected to twice — and each one was answered with another rule.

Flagging is one keypress in Resolve, on the timeline or in the media pool, and both are
readable through the API. So the flag is the answer: mark a clip once and the edit never
offers it again.

A flag on a timeline clip rejects the whole source clip, not just that cut. That is what the
editor means by it — "bunu niye kullandık tekrar" is about the clip, not the four seconds.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))

MODULES = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules"

from sevenfilm.db import Database
from sevenfilm.services.rejections import reject_clips, rejected_names


def flagged_clip_names() -> tuple[list[str], list[str]]:
    """Every clip flagged in the current timeline or the media pool."""
    sys.path.insert(0, MODULES)
    import DaVinciResolveScript as dvr

    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        raise SystemExit("Resolve'a bağlanılamadı (uygulama açık mı?)")
    project = resolve.GetProjectManager().GetCurrentProject()

    from_timeline: list[str] = []
    timeline = project.GetCurrentTimeline()
    if timeline:
        for item in (timeline.GetItemListInTrack("video", 1) or []):
            if item.GetFlagList():
                from_timeline.append(item.GetName())

    from_pool: list[str] = []
    for clip in (project.GetMediaPool().GetCurrentFolder().GetClipList() or []):
        if clip.GetFlagList():
            path = clip.GetClipProperty("File Path")
            if path:
                from_pool.append(Path(path).name)
    return from_timeline, from_pool


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="df2a4a62-e821-40f7-86fc-b6a9259e9ee9")
    parser.add_argument("--also", nargs="*", default=[],
                        help="ek olarak reddedilecek klip adları")
    parser.add_argument("--reason", default="Resolve'da işaretlendi")
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()

    from_timeline, from_pool = flagged_clip_names()
    names = sorted({*from_timeline, *from_pool, *arguments.also})
    print(f"zaman çizgisinde işaretli: {len(from_timeline)} · "
          f"havuzda işaretli: {len(from_pool)} · elle eklenen: {len(arguments.also)}")
    if not names:
        print("işaretli klip yok — Resolve'da klibi seçip bayrak koyun")
        return 0
    print("  " + ", ".join(names))
    if arguments.dry_run:
        return 0

    database = Database(Path("data/sevenfilm.sqlite3"))
    taken, unknown = reject_clips(database, arguments.project, names, arguments.reason)
    print(f"reddedildi: {len(taken)}" + (f" · tanınmayan: {unknown}" if unknown else ""))
    print(f"listedeki toplam klip: {len(rejected_names(database, arguments.project))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
