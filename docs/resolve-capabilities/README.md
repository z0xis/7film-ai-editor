# Resolve 21.1 — capability keşfi

Üç ayrı tablo: Scripting API, Native MCP, ve 7Film için kullanılabilirlik. Üçü aynı şey değil.

**Yöntem.** Her satır ya çağrılıp geri okunarak doğrulandı ya da `UNKNOWN` bırakıldı. `PRESENT`
(sembol çağrılabilir) ile `SUPPORTED` (çağrıldı ve yaptığı iş geri okundu) ayrı tutuluyor —
21.0.2'de `SetProperty("Opacity", 0)` `True` döndürüp hiçbir şey yapmamıştı, Fusion'ın
`SetKeyFrames`'i çağrıyı kabul edip keyframe yazmamıştı.

**İlk turda 21.0.2 → 21.1 farkı yalnızca üç satır çıkmıştı; sebebi Resolve değil bendim:**
probe tahmin edilen isimlerle soruyordu. Gerçek adlar `SetFades` (tekil değil), `SetSpeed`
(`SetClipSpeed` değil), `AddTransition` (Timeline'da değil **TimelineItem**'da), media cloning
ise `MediaPool`'da değil **MediaStorage**'da. Probe artık tahmin listesi yerine `dir()`
yüzeyinden üretiliyor: [capability_probe.py](../../tools/resolve/capability_probe.py).

**İkinci kaynak.** `Developer/Scripting/CHANGELOG.md` ve `DaVinciResolveScript.pyi` 21.1 ile
birlikte kuruluyor; imzalar ve TypedDict alanları oradan doğrulandı. Runtime keşfinden daha
güvenilir olduğu için capability adları bu iki dosyaya göre yazıldı.

## A) Resolve 21.1 Scripting API

| Yetenek | Gerçek API | Durum | Nasıl doğrulandı |
|---|---|---|---|
| Timeline item fade | `TimelineItem.Get/SetFades(FadeInfo)` | **SUPPORTED** | `SetFades({"FadeOut":50})` → geri okuma `FadeOut: 50.0` |
| Timeline item speed | `TimelineItem.Get/SetSpeed(SpeedOptions)` | **PARTIAL — doğrulanmış render, koşullu güvensiz** | Render FCPXML timeMap ile birebir aynı (aynı ilk kare, aynı ilerleme, aynı son kare) ama **süreyi her zaman korumuyor**: test timeline'ında ortadaki klip 100 karesini korudu, gerçek kurguda ilk klip 126→252 olup arkasındaki iki klibi ezdi. Üretimde koşulsuz güvenilir sayılmıyor; her uygulamadan sonra süre doğrulanıyor, bozulursa tüm timeline FCPXML'e düşüyor |
| Transition ekleme | `TimelineItem.AddTransition(TransitionOptions)` | **PARTIAL** | `Dip To Color Dissolve` bir `TimelineItem` döndürdü; `Cross Dissolve` her parametre birleşiminde `None` |
| Audio normalization | `Timeline.GetNormalizeAudioModes`, `NormalizeAudioLevel` | **SUPPORTED** | 6 mod listelendi (Sample Peak, True Peak, ITU-R BS.1770-1/-4, ATSC A/85…) |
| Render preset | `Project.UpdateRenderPreset`, `SetQuickExportEnabledForRenderPreset` | **SUPPORTED** | 37 render + 10 quick export preset okundu |
| Audio render format | `Project.GetAudioRenderFormats/Codecs` | PRESENT | imza doğrulandı, çağrılmadı |
| Project setting preset | `Project.*ProjectSettingsPreset*` | **SUPPORTED** | 3 preset listelendi |
| Media cloning | `MediaStorage.StartCloneMedia/StopCloneMedia/GetCloneStatus/SetCloneToolSettings` | **SUPPORTED** | `GetCloneStatus()` → `{JobStatus: Complete}` |
| Inspector property | `TimelineItem.Get/SetProperties` | **SUPPORTED** | 32 property (21.0.2'de 26) |
| Transcription | `MediaPoolItem.TranscribeAudio(useSpeakerDetection)` + `GetTranscription()` | **UNKNOWN** | şema doğrulandı (`segments[].speaker/start/end/text/words`); bu çekimde transkript yok, `TranscribeAudio` henüz çalıştırılmadı |
| Auto-align | `Timeline.AutoAlignClips(items, AutoAlignOptions)` | **PARTIAL** | `False` döndü; test klipleri zaten timecode'da hizalıydı, waveform modu denenmedi |
| Multicam | `MediaPool.CreateMulticamClip`, `TimelineItem.FlattenMulticam`, `PerformMulticamSmartSwitch` | PRESENT | imzalar doğrulandı, çağrılmadı |
| IntelliSearch / yüz | `MediaPoolItem.AnalyzeForIntellisearch(identifyFaces, isBetterMode)` | PRESENT | 21.0'dan beri var, 21.1 yeniliği değil |

## B) Resolve 21.1 Native MCP

Bundle: `DaVinci Resolve.app/Contents/Resources/DaVinciResolve.mcpb` (node sunucu,
`server/index.js`). **14 tool, 0 prompt, 0 resource.**

`launch_resolve`, `get_resolve_status`, `get_whats_new`, `get_scripting_api`,
`search_scripting_api`, `get_scripting_docs`, `run_script`, `run_script_unsafe`,
`list_dctls`, `list_luts`, `update_dctl`, `delete_dctl`, `delete_lut`, `generate_lut`

**En önemli bulgu: MCP ayrı bir capability seti sunmuyor.** Timeline, klip, fade, speed veya
render için tek bir tool yok. `run_script` sandbox'lı bir Python 3.14 çalıştırıp `resolve` ve
`project` nesnelerini enjekte ediyor — yani MCP, Scripting API'nin **sarmalayıcısı**, alternatifi
değil. `run_script` dosya sistemi/ağ/süreç erişimini engelliyor; `run_script_unsafe` açıyor.

Sonuç: MCP bir *asistan köprüsü*, bir *execution backend* değil. 7Film zaten kendi sürecinden
Scripting API'yi doğrudan çağırıyor; araya MCP koymak bir katman ve bir sandbox kısıtı ekler,
yeni yetenek getirmez. MCP'nin bizim için değeri **geliştirme sırasında API keşfi**
(`search_scripting_api`, `get_scripting_docs`).

## C) 7Film için kullanılabilirlik

| Yetenek | Backend | Doğrulandı | Fallback | 7Film kullanımı | Öncelik |
|---|---|---|---|---|---|
| Fade out | Scripting | evet | FCPXML yok (Resolve `adjust-opacity` yutuyor) | **Kapanış karartması** — "outro olmamış yine sert" | **1** |
| Speed | Scripting (koşullu) | render evet, davranış hayır | **FCPXML `timeMap` + klip başına asset — kaldırılmayacak** | Ağır çekim. API yolu yalnızca güvenli deneme: süre doğrulaması zorunlu, bozulursa tüm timeline fallback | **2** |
| Transition | Scripting (kısmi) | kısmen | fade yeterli | Kapanışta Dip To Color; ara geçiş kullanmıyoruz | 3 |
| Transcription + speaker | Scripting | hayır | yok | Yeminler, konuşmalar, duygusal diyalog seçimi | 3 |
| Audio normalization | Scripting | evet | yok | Konuşma/müzik dengesi (kaba kurgu sonrası) | 4 |
| Render/Quick Export preset | Scripting | evet | elle | Wedding master / social / preview çıktıları | 4 |
| Auto-align | Scripting | kısmen | yok | Harici ses kaydı senkronu (bu çekimde yok) | 5 |
| Multicam + SmartSwitch | Scripting | hayır | yok | Tören/konuşma çok kameralı montaj | 5 |
| Media cloning | Scripting | evet | `rsync` | Çekim yedekleme (kapsam dışı) | 6 |
| IntelliSearch / yüz | Scripting | hayır | kendi CLIP+YuNet hattımız | **Yalnızca yardımcı sinyal.** Kendi ölçütlerimizin bu çekimde ne yaptığını sayılarla biliyoruz, Resolve'unkileri bilmiyoruz | 6 |

## Değişmeyecek olan

`planner.py`, `moments.py`, `analysis.py`, `vision.py`, `windows.py`, `music.py`, referans stil
profili ve `TimelinePlan` temsili. Edit kararları platformdan bağımsız kalır; Resolve yalnızca
yürütme katmanıdır.
