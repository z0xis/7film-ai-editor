"""Call the 21.1 capabilities and read back what they did.

PRESENT means a symbol is callable. That is not the same as working: on 21.0.2
SetProperty("Opacity", 0) returned True and set no keyframe, and Fusion's SetKeyFrames
accepted a call and stored nothing. So every capability here is invoked and then read back,
and anything that cannot be read back stays UNKNOWN.

Runs in its own timeline, built from the media pool and deleted at the end. The user's
timelines are never touched.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

MODULES = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules"
WORKS, PARTIAL, FAILS, UNKNOWN = "SUPPORTED", "PARTIAL", "UNSUPPORTED", "UNKNOWN"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    arguments = parser.parse_args()

    sys.path.insert(0, MODULES)
    import DaVinciResolveScript as dvr

    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        print("Resolve'a bağlanılamadı"); return 1
    project = resolve.GetProjectManager().GetCurrentProject()
    pool = project.GetMediaPool()
    previous = project.GetCurrentTimeline()

    results: dict[str, dict] = {}

    def record(name, state, detail=""):
        results[name] = {"state": state, "detail": str(detail)[:300]}
        print(f"  {name:<26} {state:<12} {str(detail)[:90]}")

    clips = [c for c in (pool.GetCurrentFolder().GetClipList() or [])
             if (c.GetClipProperty("Type") or "") != "Audio"][:4]
    if len(clips) < 3:
        print("yeterli klip yok"); return 1

    name = "7Film · 21.1 SPIKE"
    for index in range(1, project.GetTimelineCount() + 1):
        one = project.GetTimelineByIndex(index)
        if one and one.GetName() == name:
            pool.DeleteTimelines([one])
    timeline = pool.CreateTimelineFromClips(name, clips[:3])
    if not timeline:
        print("test timeline kurulamadı"); return 1
    project.SetCurrentTimeline(timeline)
    items = timeline.GetItemListInTrack("video", 1) or []
    print(f"test zaman çizgisi: {timeline.GetName()} · {len(items)} klip\n")

    # --- fade ---------------------------------------------------------------------------
    try:
        item = items[-1]
        before = item.GetFades()
        wanted = min(50, max(1, item.GetDuration() // 2))
        ok = item.SetFades({"FadeIn": 0, "FadeOut": wanted})
        after = item.GetFades()
        record("item.fade",
               WORKS if ok and after.get("FadeOut") == wanted else PARTIAL,
               f"{before} → {after} (istenen {wanted})")
    except Exception as error:
        record("item.fade", FAILS, error)

    # --- speed --------------------------------------------------------------------------
    try:
        item = items[0]
        before = item.GetSpeed()
        ok = item.SetSpeed({"Percentage": 50.0})
        after = item.GetSpeed()
        record("item.speed",
               WORKS if ok and abs(after.get("Percentage", 0) - 50.0) < 0.01 else PARTIAL,
               f"{before} → {after}")
    except Exception as error:
        record("item.speed", FAILS, error)

    # --- transition ---------------------------------------------------------------------
    try:
        item = items[0]
        made = item.AddTransition({"type": "Cross Dissolve", "category": "simple",
                                   "position": "end", "alignment": "center", "duration": 25})
        kind = made.GetType() if made else None
        record("timeline.transition", WORKS if made else FAILS,
               f"döndü: {made and made.GetName()} · type {kind}")
    except Exception as error:
        record("timeline.transition", FAILS, error)

    # --- transcription ------------------------------------------------------------------
    try:
        clip = clips[0]
        existing = clip.GetTranscription()
        segments = (existing or {}).get("segments") or []
        record("transcription.read", WORKS if existing else UNKNOWN,
               f"{len(segments)} segment · dil {(existing or {}).get('language')}"
               + (" (önce TranscribeAudio gerekiyor)" if not segments else ""))
    except Exception as error:
        record("transcription.read", FAILS, error)

    # --- auto align ---------------------------------------------------------------------
    try:
        starts = [i.GetStart() for i in items]
        ok = timeline.AutoAlignClips(
            items, {"SyncUsing": resolve.AUTO_ALIGN_CLIPS_USING_TIMECODE})
        moved = [i.GetStart() for i in (timeline.GetItemListInTrack("video", 1) or [])]
        record("timeline.auto_align", WORKS if ok else PARTIAL,
               f"döndü {ok} · başlangıçlar {starts} → {moved}")
    except Exception as error:
        record("timeline.auto_align", FAILS, error)

    # --- audio normalization ------------------------------------------------------------
    try:
        modes = timeline.GetNormalizeAudioModes()
        record("audio.normalization", WORKS if modes else UNKNOWN, f"modlar: {modes}")
    except Exception as error:
        record("audio.normalization", FAILS, error)

    # --- render / quick export presets --------------------------------------------------
    try:
        presets = project.GetRenderPresetList()
        quick = project.GetQuickExportRenderPresets()
        record("render.presets", WORKS if presets else UNKNOWN,
               f"{len(presets or [])} render · {len(quick or [])} quick export")
    except Exception as error:
        record("render.presets", FAILS, error)

    # --- project setting presets --------------------------------------------------------
    try:
        listed = project.GetProjectSettingsPresetList()
        record("project.setting_presets", WORKS if listed is not None else UNKNOWN,
               f"{len(listed or [])} preset")
    except Exception as error:
        record("project.setting_presets", FAILS, error)

    # --- media storage clone ------------------------------------------------------------
    try:
        storage = resolve.GetMediaStorage()
        status = storage.GetCloneStatus()
        record("media.clone", WORKS if status is not None else UNKNOWN, f"durum: {status}")
    except Exception as error:
        record("media.clone", FAILS, error)

    # --- inspector properties -----------------------------------------------------------
    try:
        properties = items[0].GetProperties()
        record("item.properties", WORKS if properties else UNKNOWN,
               f"{len(properties)} property")
        results["item.properties"]["names"] = sorted(properties)
    except Exception as error:
        record("item.properties", FAILS, error)

    pool.DeleteTimelines([timeline])
    if previous:
        project.SetCurrentTimeline(previous)
    print(f"\ntest zaman çizgisi silindi · geri dönüldü: {previous and previous.GetName()}")

    report = {"measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "version": resolve.GetVersionString(), "results": results}
    if arguments.out:
        arguments.out.parent.mkdir(parents=True, exist_ok=True)
        arguments.out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"yazıldı: {arguments.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
