"""What the installed DaVinci Resolve actually exposes to scripting.

Run it against whatever version is installed and it writes a capability matrix. Run it again
after an upgrade and the diff is the answer to "what did 21.1 give us?" — measured, not read
off a release note.

Two things this session already learned the hard way and this file encodes:

  * `hasattr` lies. Resolve's remote proxy answers every attribute name, returning None for
    the ones it does not implement, so `hasattr(item, "SetFade")` is True on 21.0.2 where
    SetFade does not exist. Only `callable(getattr(...))` separates them.
  * A method that exists may still refuse the arguments, and a call that returns True may
    still not have done anything. So each probe records what it could check and no more:
    PRESENT means the symbol is callable, WORKS means a call returned something usable, and
    UNKNOWN stays UNKNOWN.

Nothing here modifies the user's project: it opens no timeline it did not create, and the
one timeline it does create is deleted before it exits.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

MODULES = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules"

# Absent, present, and the states in between. UNKNOWN is a real answer and is never upgraded
# to a working one by assumption.
ABSENT = "UNSUPPORTED"
PRESENT = "PRESENT"        # the symbol is callable; the call was not made or not verifiable
WORKS = "SUPPORTED"        # called, and the result showed it did something
PARTIAL = "PARTIAL"        # called, and it did some of what the name promises
UNKNOWN = "UNKNOWN"


def symbol(owner: object, name: str) -> str:
    """PRESENT if the name is really callable on this object, UNSUPPORTED if the proxy is
    answering with None, UNKNOWN if there is no object to ask."""
    if owner is None:
        return UNKNOWN
    return PRESENT if callable(getattr(owner, name, None)) else ABSENT


def surface(owner: object) -> list[str]:
    """Every public name this object really exposes.

    Asking by a guessed name is how the first run of this probe reported fades, speed and
    transitions as absent on 21.1: the methods are `SetFades`, `SetSpeed` and `AddTransition`,
    and it had asked for `SetFade`, `SetClipSpeed` and a Timeline-level AddTransition. dir()
    does work through the remote proxy, so the matrix is built from what is there rather than
    from what was expected.
    """
    if owner is None:
        return []
    try:
        return sorted(name for name in dir(owner) if not name.startswith("_"))
    except Exception:
        return []


def find(owner: object, *needles: str) -> dict[str, str]:
    """The names this object exposes that mention any of `needles`."""
    lowered = tuple(needle.lower() for needle in needles)
    return {
        name: symbol(owner, name)
        for name in surface(owner)
        if any(needle in name.lower() for needle in lowered)
    }


def state_of(matches: dict[str, str]) -> str:
    if not matches:
        return ABSENT
    return PRESENT if any(value == PRESENT for value in matches.values()) else ABSENT


def probe(connect=None) -> dict:
    sys.path.insert(0, MODULES)
    import DaVinciResolveScript as dvr

    resolve = (connect or dvr.scriptapp)("Resolve")
    if resolve is None:
        return {"error": "Resolve'a bağlanılamadı (uygulama açık mı?)"}

    manager = resolve.GetProjectManager()
    project = manager.GetCurrentProject() if manager else None
    pool = project.GetMediaPool() if project else None
    timeline = project.GetCurrentTimeline() if project else None
    items = (timeline.GetItemListInTrack("video", 1) or []) if timeline else []
    item = items[0] if items else None
    clips = (pool.GetCurrentFolder().GetClipList() or []) if pool else []
    clip = clips[0] if clips else None

    report = {
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "product": resolve.GetProductName(),
        "version": resolve.GetVersionString(),
        "project": project.GetName() if project else None,
        "timeline": timeline.GetName() if timeline else None,
        "media_pool_clips": len(clips),
        "capabilities": {},
    }
    say = report["capabilities"].__setitem__
    report["surface"] = {
        "TimelineItem": surface(item), "Timeline": surface(timeline),
        "MediaPool": surface(pool), "MediaPoolItem": surface(clip),
        "Project": surface(project), "ProjectManager": surface(manager),
    }

    def capability(name: str, owner: object, *needles: str, notes: str = "") -> None:
        matches = find(owner, *needles)
        say(name, {"state": UNKNOWN if owner is None else state_of(matches),
                   "notes": notes, "symbols": matches})

    # --- 21.1'in getirdiği iddia edilenler -----------------------------------------------
    capability("transcription.clip", clip, "transcri",
               notes="Media Pool clip transcription (speaker + timing)")
    capability("multicam.create", pool, "multicam",
               notes="Multicam oluşturma")
    capability("multicam.flatten_switch", item, "multicam",
               notes="Flatten ve SmartSwitch")
    capability("timeline.auto_align", timeline, "align",
               notes="Timeline clip auto-align")
    capability("mediapool.auto_sync", pool, "sync",
               notes="Kamera + harici ses senkronu")
    capability("timeline.transition", item, "transition",
               notes="Programatik transition — TimelineItem üzerinde")
    capability("item.fade", item, "fade",
               notes="Fade okuma/yazma; 21.0.2'de yoktu")
    capability("item.speed", item, "speed",
               notes="Speed change; 21.0.2'de yoktu, retiming FCPXML timeMap ile")
    capability("audio.normalization", timeline, "normali",
               notes="Timeline clip audio normalization")
    capability("audio.source_mapping", item, "audiochannelmapping",
               notes="Source audio mapping (timeline item)")
    capability("audio.clip_mapping", clip, "audiomapping",
               notes="Source audio mapping (media pool item)")
    capability("render.presets", project, "renderpreset", "quickexport",
               notes="Render preset güncelleme ve Quick Export preset")
    capability("audio.render_format", project, "audiorender",
               notes="Audio render format/codec sorgulama")
    capability("project.setting_presets", project, "projectsettingspreset",
               notes="Project setting preset oluştur/güncelle/import/export")
    capability("media.clone", pool, "clone", "relink", "replace",
               notes="Media cloning; birebir CloneMedia yok, Relink/Replace var")
    capability("intellisearch", clip, "intellisearch",
               notes="Yardımcı sinyal olarak; vision katmanının yerine değil")
    capability("intellisearch.project", project, "intellisearch")
    capability("item.reframe", item, "reframe", "stabilize", "magicmask",
               notes="SmartReframe / Stabilize / MagicMask — bonus")
    capability("item.properties", item, "propert",
               notes="Inspector property okuma/yazma")

    # --- Bu oturumda ölçülmüş, üzerine kurduğumuz gerçekler -------------------------------
    inspector = {}
    if item:
        properties = item.GetProperty()
        inspector = {
            "readable_count": len(properties) if isinstance(properties, dict) else UNKNOWN,
            "names": sorted(properties) if isinstance(properties, dict) else UNKNOWN,
        }
    say("item.inspector_properties", {
        "state": WORKS if inspector.get("names") else UNKNOWN,
        "notes": "21.0.2: 26 property; Opacity yazılabiliyor ama keyframe yok",
        "detail": inspector,
    })
    say("timeline.import_fcpxml", {
        "state": symbol(pool, "ImportTimelineFromFile") if pool else UNKNOWN,
        "notes": "Bugünkü yürütme yolu: retimed plan + müzik sönümü buradan geçiyor",
    })
    say("timeline.export", {
        "state": symbol(timeline, "Export") if timeline else UNKNOWN,
        "notes": "Doğrulama için: Resolve'un ne aldığını geri okumakta kullanılıyor",
    })
    say("fusion.comp", {
        "state": symbol(item, "AddFusionComp") if item else UNKNOWN,
        "notes": "21.0.2: comp eklenebiliyor, SetKeyFrames uzak proxy üzerinden keyframe "
                 "kabul etmiyor; son comp silinemiyor",
    })
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="raporun yazılacağı JSON dosyası")
    parser.add_argument("--compare", type=Path, help="önceki bir raporla karşılaştır")
    arguments = parser.parse_args()

    report = probe()
    if "error" in report:
        print(report["error"]); return 1

    print(f"{report['product']} {report['version']} · proje {report['project']} · "
          f"{report['media_pool_clips']} klip")
    width = max(len(name) for name in report["capabilities"])
    for name, entry in report["capabilities"].items():
        print(f"  {name:<{width}}  {entry['state']}")

    if arguments.compare and arguments.compare.exists():
        before = json.loads(arguments.compare.read_text())
        print(f"\n{before['version']} → {report['version']} farkı:")
        changed = False
        for name, entry in report["capabilities"].items():
            was = before["capabilities"].get(name, {}).get("state", "—")
            if was != entry["state"]:
                changed = True
                print(f"  {name}: {was} → {entry['state']}")
        if not changed:
            print("  değişiklik yok")

    if arguments.out:
        arguments.out.parent.mkdir(parents=True, exist_ok=True)
        arguments.out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"\nyazıldı: {arguments.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
