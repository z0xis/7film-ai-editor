# 7Film AI Editor — oturum durumu

Son güncelleme: 7 Eylül 2026, 04:30. Bu dosya, çalışmayı devralan bir sonraki oturum içindir.

Bu tur, kurgucunun Resolve'da kurguyu izleyip **plan plan** şikâyet etmesiyle geçti. Yedi ayrı
şikâyet geldi; hepsi ölçüldü, beşi tek bir kök sebepten çıktı.

---

## Kök sebep: şot 0,2 saniyeden yargılanıyordu

Bir şotun kalitesi, ortasından alınan üç kareden ölçülüyordu — üçü **0,1 saniye arayla**, yani
toplam 0,2 saniye. Kadraj (yüz oranı, kenar) ise bunlardan **tek ortancasından**. Sonra
planlayıcı, şotun neresinin iyi olduğunu hiç sormadan, parçayı **aritmetikle** kesiyordu:
her zaman "şot başı + sabit pay". Yani kesim, sahne dedektörünün kestiği yerin dibinden
başlıyordu — kadrajın en oynak olduğu yer tam orası.

Kurgucunun gösterdiği altı klipte de kötü an kesimin içindeydi ve ölçüm oraya bakmamıştı:

| klip | şikâyet | saklanan | gerçek |
|---|---|---|---|
| C2075 | kafa kesik | kenar 0,00 | **0,76** |
| C2076 | kadraj kenarı | kenar 0,00 | **1,00** |
| C2155 | estetik değil | — | keskinlik **9** (çekim 45–78) |
| C2181 | kalabalık arasından | kenar 0,00 | **1,00 baştan sona** |
| C1968 | kapıda duran adam | 2 yüz | **3 yüz** |

**Çözüm:** `shot_windows` tablosu — her şot boyunca yarım saniyede bir keskinlik, yüz oranı,
kadraj kenarı, yüz sayısı, arkadaki insan sayısı. Planlayıcı girişi bu pencerelerden seçiyor;
bir dizideki **en kötü yarım saniye** diziyi belirliyor (bir kesim, onu bozan kare kadar
iyidir). Şot boydan boya kötüyse "burada kullanılabilir an yok" deyip eleniyor — yoksa giriş
başka bir kötü ana kayardı.

```
kötü yarım saniye içeren kesim   %40 → %15
çok kötü (<0)                    %19 →  %6
C2181 ve C2155                   kurgudan tamamen elendi
```

**Bedeli:** sahne serisi 34 → 25, ardışık aynı kategori %28 → %23. Sekansın sonraki planları
çoğu kez daha kötü kadrajlı olanlar ve artık reddediliyorlar. Bilerek yapılan bir takas.

### Proxy'den ölçmek hataydı

Pencereler önce hız için proxy'den ölçüldü. Ölçüm bunu yakaladı:

```
orijinal 3840×2160 → kapıdaki adam 3 karede de BULUNDU (0,38 / 0,57 / 0,69)
proxy    1280×720  → 3 karede de BULUNAMADI
proxy ×2, ×3       → geri gelmiyor; ×3'te bulduğu şeyler yanlış boyutta
```

Adamın yüzü kadrajın on binde 1,5'i. Bilgi proxy'de yok. Artık **orijinallerden** ölçülüyor:
kare başına 661 ms, 1405 şot için ~2 saat, tek seferlik. `analyze_shots` sonunda otomatik.

---

## Bu turda kapatılanlar

| Commit | Ne düzeltildi |
|---|---|
| `88d88d6` | Kurgu günü kaybediyordu; sabahki masa 125. sn'deydi. Klip günün neresinde, artık puanda |
| `a99ee63` | Sekans muafiyeti klibin **tüm geçmişini** affediyordu; pasta 7 kesim veriyordu → 3 |
| `f3f5ef9` | Kayıt sonu savrulması; klip sonunun son 4 karesi 2× oynak, kesim oraya düşüyordu |
| `6e2fc3f` | `shot_windows`: şot boydan boya ölçülüyor, kesim ana göre seçiliyor |
| `9ab9420` | Kullanılabilir anı olmayan şot eleniyor (tek pencere değil, **dizi** üzerinden) |
| `7a5fb26` | Ret listesi: kurgucunun "bu klibi kullanma" dediği klipler |
| `db6934f` | Pencereler orijinalden ölçülüyor (proxy arkadaki insanı göremiyor) |
| `64c022f` | Yavaş çekim: müziğin sakin bölümünde tutulan planlar %50 hızda |
| `f6393bd` | Retime'lı plan FCPXML ile teslim ediliyor (API hız veremiyor) |
| `2c79be7` | 50 fps kurgu 25'lik monitörde oynatılıyordu — takılmanın sebebi |
| `17d364f` | Bir andan filme tek insansız plan (aynı tabela iki kez giriyordu) |
| `79ff9a2` | Film **bitiyor**: son plan referanslardaki gibi tutuluyor |
| `218a1bf` | "Hareketli müzik" hedefi elle yazılmıştı ve bu çekimde karşılığı yoktu |

---

## Ölçülmüş Resolve gerçekleri (bu turda eklenenler)

- **`TimelineItem.SetProperty` hız veremiyor.** Yalnız Pan/Tilt/Zoom/Crop/RetimeProcess.
  Dokümandaki "Speed" seslendirme ayarı. Yani `AppendToTimeline` yolu yavaş çekim üretemez.
- **FCPXML `timeMap` çalışıyor** — ama `time` ve `value` klibin **medya saatinde mutlak**
  olmalı. Göreli yazılınca Resolve **0,01×** döndürüyor: sessizce yanlış, hata yok.
  ```
  timept time="{start}"                    value="{start}"
  timept time="{start + timeline_süresi}"  value="{start + kaynak_süresi}"
  ```
- **Exporter'ın FCPXML'i tam içe aktarılıyor**: 50 fps, 150,0 sn, 111 klip, boşluk 0,
  müzik A1'de, **proxy'ler zaten bağlı**. Yani FCPXML artık gerçek bir yol, yedek değil.
- **`videoMonitorFormat` yazılabiliyor**, `timelinePlaybackFrameRate` yazılamıyor.
  Yeni timeline projenin monitör formatını alıyor, kendi hızını değil.
- **`MediaPoolItem.SetClipProperty('FPS', …)` çalışıyor** ama klibin *tüm proje* boyunca
  yorumunu değiştirir — yavaş çekim için kullanılmadı, kullanılmamalı.

---

## Referans ölçümleri (18 film, 1219 plan)

| ölçüt | referans |
|---|---|
| medyan plan | 1,00 sn |
| **son plan** | **3,17 sn** (genelin 3,17 katı) |
| son 5 plan | 1,62 sn |
| 3 sn+ ile biten | 9/18 |
| tutulan planların %20'si | `detail` |
| detay planlarının %49'u | yalnız duruyor |

Son satır önemli: "dans arasına tek çiçek" deseni bu stilde **normal**. Oradaki sorun yerleşim
değil, o belirli planın kendisiydi.

> Uyarı: referans sınıflandırması zayıf. 1219 planda hiç `party` veya `groom` çıkmadı,
> yalnız 5 kategori göründü. Kategori tabanlı referans çıkarımlarına güvenmeyin; **süre**
> tabanlı olanlar (yukarıdaki ilk üç satır) sağlam.

---

## Ölçülemeyenler — ve ret listesi

İki şey hiçbir çözünürlükte ölçülemedi:

- **"Gelin takılıyor"** — bir tökezlemenin hareket/keskinlik/yüz karşılığı yok.
- **"Shota hazırlık"** (damat saçını düzeltiyor) — kadraj ve keskinlik temiz, sorun anlamda.

Kurgucu bunları bir saniyede görüyor. Bu yüzden **ret listesi** var: klip adı yazılıyor
(`C1968`, `C1968.MP4`, büyük-küçük fark etmez — Resolve'un gösterdiği gibi), o proje için
hiçbir kurguya bir daha girmiyor. Puanlamadan **önce** çıkarılıyor. Panelde "Kullanılmasın".

Bu listenin **ölçülebileni ölçmemenin bahanesi olmadığına** dikkat edin: arkadaki adam
ölçülebiliyordu ve ölçüldü (orijinal çözünürlük). Liste yalnız ölçülemeyen için.

Şu an listede: `C1968`, `C1989`, `C2155`, `C2181`, `C1891`.

---

## Şu an çalışan / bekleyen

- **Tam çözünürlüklü pencere ölçümü** arka planda sürüyor (1405 şot, ~2 saat).
  Bitince: etkisini yeniden ölç, `WINDOW_QUALITY_WEIGHT`'i gerekirse yeniden tara,
  Resolve'a gönder ve **kontakt sayfasıyla gözle bak**.
- **Eklenti yeniden kuruldu** (`scripts/install_resolve_plugin.sh`) — kurulu kopya repo'nun
  kopyasıdır ve repo değişince kendiliğinden değişmez. Yavaş çekim ve monitör düzeltmesi
  ancak yeniden kurulumla gelir. Eski motorlar kapatıldı; panel açılınca yenisi doğar.
- `İS` projesinin 850 şotu hâlâ analiz edilmemiş.
- Hazırlık setinde 3 yanlış etiket duruyor; dört düzeltme denemesi de ölçümde daha kötü çıktı.

---

## Değişmeyen çalışma kuralları

- Ölç, sonra değiştir. Bu turda dört kez ölçüm benim varsayımımı çürüttü:
  proxy'nin yeterli olduğu (değildi), referansların detayı yalnız bırakmadığı (bırakıyor),
  ağırlığın hareket sorununu çözeceği (hedef yanlıştı), sekans ölçümünün kategoriyle
  yapılabileceği (yapılamaz).
- Sabitler **taranarak** seçilir ve yorumunda ölçüm yazar. En hafif yeterli değer alınır.
- Test düşerse önce **testin önermesi** doğru mu diye bakılır; davranış kötüleşmediyse
  test düzeltilir ve commit mesajında neden düzeltildiği yazılır.
- Her iş ayrı commit; iki Python ortamı + node + ruff + `git diff --check` yeşil olmadan
  commit yok.
