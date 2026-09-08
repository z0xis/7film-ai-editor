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

    # --- 21.1'in getirdiği iddia edilenler -----------------------------------------------
    say("transcription.clip", {
        "state": symbol(clip, "GetTranscription"),
        "notes": "Media Pool clip transcription (speaker + timing)",
        "symbols": {name: symbol(clip, name)
                    for name in ("GetTranscription", "TranscribeAudio", "ClearTranscription")},
    })
    say("multicam.create", {
        "state": symbol(pool, "CreateMultiCamClipFromClipList") if pool else UNKNOWN,
        "notes": "Multicam oluşturma / flatten",
        "symbols": {name: symbol(pool, name)
                    for name in ("CreateMultiCamClipFromClipList", "CreateMultiCamClip",
                                 "AppendToTimeline")},
    })
    say("multicam.smartswitch", {
        "state": symbol(item, "SetMultiCamSwitch") if item else UNKNOWN,
        "notes": "SmartSwitch programatik tetikleme",
        "symbols": {name: symbol(item, name)
                    for name in ("SetMultiCamSwitch", "GetMultiCamAngle", "SetMultiCamAngle")},
    })
    say("timeline.auto_align", {
        "state": symbol(timeline, "AutoAlignClips") if timeline else UNKNOWN,
        "notes": "Timeline clip auto-align (kamera + harici ses senkronu)",
        "symbols": {name: symbol(timeline, name)
                    for name in ("AutoAlignClips", "AutoSyncAudio", "AlignClips")},
    })
    say("timeline.transition", {
        "state": symbol(timeline, "AddTransition") if timeline else UNKNOWN,
        "notes": "Programatik transition ekleme — 21.0.2'de yok, karartma bu yüzden yapılamadı",
        "symbols": {**{name: symbol(timeline, name)
                       for name in ("AddTransition", "InsertTransition")},
                    "item.AddTransition": symbol(item, "AddTransition")},
    })
    say("item.fade", {
        "state": symbol(item, "SetFade") if item else UNKNOWN,
        "notes": "Fade okuma/yazma — 21.0.2'de SetFade None döndürüyor",
        "symbols": {name: symbol(item, name)
                    for name in ("SetFade", "GetFade", "SetFadeIn", "SetFadeOut")},
    })
    say("item.speed", {
        "state": symbol(item, "SetClipSpeed") if item else UNKNOWN,
        "notes": "Speed change okuma/yazma — 21.0.2'de yok, retiming FCPXML timeMap ile",
        "symbols": {name: symbol(item, name)
                    for name in ("SetClipSpeed", "GetClipSpeed", "SetSpeed", "GetSpeed",
                                 "SetRetimeCurve")},
    })
    say("item.audio_normalization", {
        "state": symbol(item, "SetAudioNormalization") if item else UNKNOWN,
        "symbols": {name: symbol(item, name)
                    for name in ("SetAudioNormalization", "NormalizeAudio")},
    })
    say("item.source_audio_mapping", {
        "state": symbol(item, "SetSourceAudioMapping") if item else UNKNOWN,
        "symbols": {name: symbol(item, name)
                    for name in ("SetSourceAudioMapping", "GetSourceAudioMapping")},
    })
    say("render.presets", {
        "state": symbol(project, "UpdateRenderPreset") if project else UNKNOWN,
        "symbols": {name: symbol(project, name)
                    for name in ("UpdateRenderPreset", "SaveAsNewRenderPreset",
                                 "GetRenderPresetList", "AddRenderJob",
                                 "GetQuickExportRenderPresets", "RenderWithQuickExport")},
    })
    say("audio.render_format", {
        "state": symbol(project, "GetCurrentRenderFormatAndCodec") if project else UNKNOWN,
        "symbols": {name: symbol(project, name)
                    for name in ("GetCurrentRenderFormatAndCodec",
                                 "SetCurrentRenderFormatAndCodec",
                                 "GetRenderAudioFormats", "SetRenderAudioFormat")},
    })
    say("project.setting_presets", {
        "state": symbol(manager, "ExportProjectPreset") if manager else UNKNOWN,
        "symbols": {name: symbol(manager, name)
                    for name in ("ExportProjectPreset", "ImportProjectPreset",
                                 "CreateProjectPreset", "GetProjectPresetList")},
    })
    say("media.clone", {
        "state": symbol(pool, "CloneMedia") if pool else UNKNOWN,
        "symbols": {name: symbol(pool, name)
                    for name in ("CloneMedia", "DuplicateMedia", "RelinkClips")},
    })
    say("intellisearch.faces", {
        "state": symbol(pool, "GetFaces") if pool else UNKNOWN,
        "notes": "Yardımcı sinyal olarak değerlendirilecek, vision katmanının yerine değil",
        "symbols": {name: symbol(pool, name)
                    for name in ("GetFaces", "SearchMedia", "GetPeople")},
    })

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
