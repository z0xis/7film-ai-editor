# 7Film AI Editor — oturum durumu

Son güncelleme: 4 Eylül 2026, 03:20. Bu dosya, çalışmayı devralan bir sonraki oturum içindir.

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
| `5ea3a9c` | Eski analizler sessizdi; artık damgalanıp arayüzde bildiriliyor |

## Yeniden analiz tamamlandı

`df2a4a62-e821-40f7-86fc-b6a9259e9ee9` (elenora mustafa) projesi 4 Eylül 03:01'de bitti.

- 345 klip, **1405 shot** (önce ~850), en uzun shot tam 5,0 sn — bölme tavanı çalışıyor
- Kategori: **8/8 kullanılıyor**, en büyük sınıf %37 (önce %58 bride), bride+groom %64 (önce %92)
- Müzik de yeniden analiz edildi: 4 eşit çeyrek yerine **9 gerçek bölüm** (%47 low, %28 medium, %26 high)
- Yedek: `data/sevenfilm.sqlite3.backup-20260904-023304`
- Diğer proje (`İS`, 850 shot) hâlâ eski — arayüz bunu bildiriyor

### Üretilen kaba kurgunun ölçümü

| ölçüt | üretilen | referans |
|---|---|---|
| medyan kesim | 0,92 sn | 1,00 sn |
| p25 / p75 | 0,48 / 1,40 sn | 0,64 / 1,60 sn |
| beat hizası ≤120ms | %90 | %61 |
| kesim/saniye | 1,03 | 0,74 |
| 1 karelik flaş | 0 | — |

Kalan en belirgin fark **kesim yoğunluğu**: hâlâ referanslardan ~%40 daha sık kesiyor. Sıradaki
iş bu. Beat hizasının referanstan yüksek olması kasıtlı (makine grid'e oturur, insan editör
bilerek kaydırır) ama isteğe bağlı bir off-beat oranı eklenebilir.

## Doğrulanmamış kalanlar

- **JS Workflow Integration köprüsü**: doğrulama Python scripting API'siyle yapıldı. Kullanıcının gördüğü `errorCode: 2` biçimi JS köprüsüne ait; orada geçersiz öğe exception fırlatıyor, Python'da kısmi ekleme oluyor.
- **CLIP düzeltmesi 11 karelik görsel denetime dayanıyor**; etiketli doğruluk seti yok. `ceremony` az temsil ediliyor olabilir.
- Öncül projeye özgü: aynı klip farklı projede farklı etiketlenebilir.
- Mevcut 6120 timeline item'ın kategorisi `b_roll`'a düştü (kesim noktaları sağlam). O eski kurguları yeniden üretmek daha iyi sonuç verir.
- Eşikler tek gerçek projede kalibre edildi.
- Kesim yoğunluğu referansın ~%140'ı; enerji bölümlerinin dağılımına duyarlı.

## Çalışma biçimi

Önce ölç, sonra değiştir. Bu turda dört iddia ölçümle çürütüldü: sınır dışı karelerin batch'i reddettirdiği, batch'in ya hep ya hiç olduğu, yavaş şarkının yavaş kurgu ürettiği, dinamik aralığı olmayan parçanın "high" sayılmaması gerektiği. Görsel kararlar (kategori, kalite) ekrana bakılarak denetlendi.

## Testler

`.venv/bin/python -m pytest -q` — 94
`node --test integrations/resolve/com.sevenfilm.ai.editor/` — 41
`cd apps/desktop && npm run build`
`.venv/bin/ruff check apps tests integrations` (`tests/test_path_normalization.py` önceden beri kirli)
