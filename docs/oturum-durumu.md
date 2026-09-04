# 7Film AI Editor — oturum durumu

Son güncelleme: 4 Eylül 2026, 04:10. Bu dosya, çalışmayı devralan bir sonraki oturum içindir.

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
| `c8a0af9` | Referans tempo her kesimde aşağı yuvarlanıyordu; kesirli tutulup artık devrediliyor |
| `51e87ed` | Adapter rasyonel saniyeyi okuyamıyordu (müzik sınırı kayboluyordu); API sözleşme testi |

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
| medyan kesim | **1,00 sn** | 1,00 sn |
| p25 / p75 | 0,52 / 1,48 sn | 0,64 / 1,60 sn |
| beat hizası ≤120ms | %86 | %61 |
| kesim/saniye | 0,92 | 0,74 |
| 1 karelik flaş | 0 | — |

## Gerçek Resolve'da uçtan uca doğrulandı

Eklentinin `importTimeline` akışının tamamı, gönderilen adapter koduyla, gerçek malzeme
üzerinde Resolve Studio 21.0.2'de çalıştırıldı (geçici proje, sonra silindi):

```
V1 klip     : 141 / 141   batch hatası yok
en kısa klip: 14 kare     1 karelik klip yok
ses         : A1 müzik (kare 0'dan), A2/A3 boş, kamera sesi yok
marker      : 141 adet, hepsi tam kesim başlarında, gerekçe metniyle
```

Ayrıca `AddMarker` ölçüldü: **timeline başlangıcına göreli kare** alıyor, yani `main.js`'in ham
`timeline_in.start_frame` kullanması doğru. (Timeline 90000'de başlıyor; mutlak kare vermek
marker'ı timeline'ın dışına atardı. Kod doğruydu, "düzeltmek" hata olurdu.)

Testler eklentinin gerçekten kullandığı ortamda da geçiyor:
`.runtime/mamba-root/envs/sevenfilm/bin/python -m pytest -q` — bu, `.venv` değil.

## Doğrulanmamış kalanlar

- **JS Workflow Integration köprüsü**: Resolve menüsünden tıklama gerektirdiği için doğrudan
  çalıştırılamadı. Adapter mantığının tamamı Python scripting API'si üzerinden gerçek Resolve'da
  doğrulandı; kalan tek fark köprünün hata biçimi (`errorCode: 2` exception olarak gelir,
  Python'da kısmi ekleme olur). Kullanıcı eklentiyi bir kez açtığında bu da kapanır.
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
