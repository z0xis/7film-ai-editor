# 7Film AI Editor — oturum durumu

Son güncelleme: 4 Eylül 2026, 02:45. Bu dosya, çalışmayı devralan bir sonraki oturum içindir.

## Bu turda kapatılan hatalar

| Commit | Ne düzeltildi |
|---|---|
| `9d20f2b` | Kamera sesi A1'e geliyordu (`CreateTimelineFromClips` mediaType'ı yok sayıyor); müzik A1'e, kare 0'a |
| `dc57ed8` | Kullanılamaz görüntü (bulanık/patlamış) elemesi; referans görünümüne göre seçim |
| `92c2dde` | Kesimler müziğin gerçek yapısına ve referans temposuna oturuyor |
| `2f8b5e6` | Donuk kareler; kalite eşiği gerçek malzemeye göre kalibre |
| `3bc5a0a` | `endFrame` HARİÇ (dahil değil) — gerçek Resolve Studio 21.0.2'de doğrulandı |
| `a597f0a` | CLIP her şeye "bride" diyordu; öncül çekim genelinden ölçülüp çıkarılıyor |
| `a244d2a` | Analiz devam ettirilebilir; yeniden etiketleme 162 sn yerine 5,4 sn |
| `37769f2` | Kayıtlı kurgular yeniden analizde sessizce boşalıyordu |
| `4bc5b62` | Eklenti `timeline-builder.js`'i kurmuyordu — hiç açılmazdı |

## Şu an arka planda çalışan iş

Gerçek projenin (`df2a4a62-e821-40f7-86fc-b6a9259e9ee9`, 345 klip) yeniden analizi.

- Çalıştırıcı: `data/.reanalysis.py`, ayrık bir bash sarmalayıcı içinden, 5 denemeye kadar yeniden dener
- Günlük: `data/reanalysis.log`
- Yedek: `data/sevenfilm.sqlite3.backup-20260904-023304` (690 medya, 1700 shot, 20 timeline, 6120 item)
- İlerleme sorgusu: `SELECT COUNT(DISTINCT asset_id) FROM shot_features` — hedef 345

Kesilirse zararsız: `analyze_shots` kodlanmış klipleri atlar, yeniden çalıştırmak kaldığı yerden devam eder.

## Bittiğinde yapılacaklar

1. Kategori dağılımını ölç: düzeltme öncesi %92 bride+groom idi, örneklemde %67'ye indi. Tam veride ne çıktığını gör.
2. Yeni bir kurgu üret ve `beat_alignment_ratio` ile medyan kesim süresini referans profiliyle karşılaştır (ölçüt: referans medyan 1,00 sn, p25/p75 0,64/1,60, beat hizası %61).
3. Resolve'da eklentiyi gerçekten çalıştır: Workspace > Workflow Integrations > 7Film AI Editor. Bu, JS köprüsünün doğrulanmadığı tek katman.

## Doğrulanmamış kalanlar

- **JS Workflow Integration köprüsü**: doğrulama Python scripting API'siyle yapıldı. Kullanıcının gördüğü `errorCode: 2` biçimi JS köprüsüne ait; orada geçersiz öğe exception fırlatıyor, Python'da kısmi ekleme oluyor.
- **CLIP düzeltmesi 11 karelik görsel denetime dayanıyor**; etiketli doğruluk seti yok. `ceremony` az temsil ediliyor olabilir.
- Öncül projeye özgü: aynı klip farklı projede farklı etiketlenebilir.
- Mevcut 6120 timeline item'ın kategorisi `b_roll`'a düştü (kesim noktaları sağlam). O eski kurguları yeniden üretmek daha iyi sonuç verir.
- Eşikler tek gerçek projede kalibre edildi.

## Çalışma biçimi

Önce ölç, sonra değiştir. Bu turda dört iddia ölçümle çürütüldü: sınır dışı karelerin batch'i reddettirdiği, batch'in ya hep ya hiç olduğu, yavaş şarkının yavaş kurgu ürettiği, dinamik aralığı olmayan parçanın "high" sayılmaması gerektiği. Görsel kararlar (kategori, kalite) ekrana bakılarak denetlendi.

## Testler

`.venv/bin/python -m pytest -q` — 94
`node --test integrations/resolve/com.sevenfilm.ai.editor/` — 41
`cd apps/desktop && npm run build`
`.venv/bin/ruff check apps tests integrations` (`tests/test_path_normalization.py` önceden beri kirli)
