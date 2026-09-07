# 7Film AI Editor — oturum durumu

Son güncelleme: 7 Eylül 2026, 17:20. Bu dosya, çalışmayı devralan bir sonraki oturum içindir.

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

## Düğünün kendi anları filmde yoktu

Kurgucu, "benim işaretlememe gerek kalmaması lazım" dedi ve haklıydı. Ölçüm:

| an | en iyi 8 şottan kaçı kurguda |
|---|---|
| pasta kesme | 1/8 |
| pasta yedirme | 2/8 |
| öpüşme | **0/8** |
| yüzük takma | **0/8** |
| ilk dans | **0/8** |
| giriş | **0/8** |

Düğünün öpüşmesi, yüzüğü, ilk dansı ve girişi filmde **hiç yoktu** — hepsi çekimde varken. O
planlar zayıf da değil: kaliteleri 0,41–0,49, çekim medyanı 0,406. Planlayıcının "bir düğün
filminin borçlu olduğu anlar" diye bir kavramı yoktu; yüzük takma anı, teknik olarak daha
temiz bir yürüme planına yeniliyordu.

> **Uyarı — bu kapı bir varlık testi değil.** 18 istem denendi: havai fişek, gelin arabası,
> nikâh imzası dahil, hiçbiri bu düğünde yok. **Hepsi** 1.25 eşiğini geçti (1.26–1.94, arada
> boşluk yok). İki test daha kuruldu, ikisi de çuvalladı: tepeye yakın kaç şot var (havai
> fişek 21, yüzük 1 — tersine), ve en iyi şotların zamanda ne kadar sıkı durduğu (pasta 0,0 dk,
> yemin 11,2 dk — kesin görünüyordu, ta ki "anne gelinliği giydiriyor" **0,3 dk** ile en sıkısı
> çıkana ve üç dans pisti planı taşıyana kadar).
>
> `MOMENT_PROMPTS`'taki altı an **gözle doğrulandığı için** güveniliyor, kapıyı geçtiği için
> değil. Riski sınırlı: olmayan bir an 110 kesimde 1 kesime mal olur. Zayıf eşleşenler
> (`< 0.30`) artık kurgu uyarısında adıyla söyleniyor.

`services/moments.py` bunları **zaten saklı CLIP gömülerinden** buluyor — yeniden analiz yok,
yalnız altı cümle kodlanıyor, 4,5 saniye. Çekimde olmayan an uydurulmuyor (`MOMENT_LIFT`).

Bir tuzak: bonus koşulsuzken kronolojiyi eziyor (0,10'a karşı 0,064) ve filmin ilk 22 saniyesi
öpüşme–giriş–pasta–yüzük–ilk dans diye sıralanıyordu. Artık yalnız film günün o kısmına
geldiğinde veriliyor. 8 seed'de altı anın hepsi, hepsinde, ve sırayla: giriş 7 sn → öpüşme 10
→ yüzük 12 → pasta 25 → ilk dans 35.

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
| `df65b61` | Ret uçları **ölüydü**: kök mount'tan sonra tanımlanmışlar; kapanış kırıntıya düşüyordu |
| `d726c51` | Düğünün anları (öpüşme/yüzük/ilk dans/giriş) filme giriyor |
| `2217daf` | An bonusu kronolojiyi ezmesin — an kendi zamanında gelsin |
| `1a67fe8` | Yavaş çekim barajı: çekimin ortasının altındaki hiçbir şey uzatılmıyor |
| `4ce77bc` | İndekslenmiş dosya bir daha okunmuyordu; 16 dikey klip yatay kayıtlıydı |
| `7494d11` | An kapısının varlık ispatladığı iddiası yanlıştı; zayıf eşleşme artık söyleniyor |
| `08fcfea` | Yavaş çekimli klip **dosyanın başından** oynuyordu, seçilen andan değil |
| `28ad3cc` | Detay/mekân planı asla yavaşlatılmıyor (masadaki çiçek 4 saniye yavaştı) |
| `c72a979` | `ilk dans` istemi kadrajda ne olduğuyla adlandırıldı; 4'te 2 → 4'te 4 |
| `4b235be` | Orkestra filmin dörtte birini alıyordu; dengeli payına (%10) indi |
| `aa754f1` | Aynı kurulumun iki çekimi arka arkaya kesiliyordu (0.939 benzerlik) |
| `d1b95c4` | Masa planları var olmayan yüzlerden puanlanıyordu (dedektör 12–53 sahte yüz) |

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
- **İndekslenmiş dosya bir daha okunmuyordu** (`if existing is None` ve başka hiçbir şey). Bu
  yüzden sonradan gelen metadata düzeltmeleri eski çekimlere hiç ulaşmıyordu: döndürme
  düzeltmesi yazıldı, ama bu çekimin 16 dikey klibi ilk verilen yatay şekliyle kaldı.
  Proxy'leri doğruydu (ffmpeg matrisi uyguluyor), FCPXML ise 3840x2160 ilan ediyordu.
  Artık her dosya yeniden probe ediliyor (~50 ms) ve değişen alanlar düzeltiliyor.
- **Kök mount her şeyi yutuyor.** `app.mount("/", StaticFiles…)` kendinden **sonra** tanımlanan
  her yolu yutar. Ret uçları böyle ölü kalmıştı: panel kutuyu gösterir, kutu hiçbir şey yapmaz.
  O mount dosyanın en sonunda kalmalı.
- **timeMap taşıyan klibin `start` giriş noktası yok sayılıyor.** Retime edilen klip
  medyanın başından oynuyor; dört yazım biçimi denendi, retime üreten ikisi de aynı şeyi
  yaptı. Çare: retime edilen klibe **kendi `asset` girdisini** vermek, `start`'ı giriş
  noktası olacak şekilde — o zaman "medyanın başı" doğru yer oluyor.
- **Kare sayısıyla retime aranmaz.** 25 fps'lik bir klipte 2 saniye 50 kaynak karesi ama
  50 fps timeline'da 100 karedir; saniye üzerinden karşılaştırın.
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
- **`İS` projesi aynı çekimin terk edilmiş kopyası.** Ölçüldü: 345 klibinin 345'i
  `elenora mustafa` ile aynı dosya, hiç kurgusu ve müziği yok, ondan önce (2 Eylül)
  oluşturulmuş. Analiz etmek ~5 saatte zaten var olanı üretmek olur — yapılmadı. Kurgucu
  isterse silinebilir; silme geri alınamaz olduğu için ona bırakıldı.
- **Kullanılacak parçadan puanlama DENENDİ VE DAHA KÖTÜ ÇIKTI.** Şot puanı "şotun en iyi
  yeri"nden geliyor; kullanılan parça daha kötü olabiliyor (ensesi görünen plan −0.12).
  `window_quality`'i "girişten itibaren en iyi dizi" yapmayı denedim: kötü kesim %20→%26,
  çok kötü %7→%14, gün akışı 0.82→0.74. Sebep: zaten kesim vermiş bir şotun kalan bölgesi
  doğal olarak zayıf, ve şot *kullanılmış olduğu için* cezalanıyor. Geri alındı. Boşluk
  duruyor; başka bir çözüm gerek (belki puan yerine süzgeç).
- **Yüz dedektörü masalarda büyük sahte yüzler buluyor** — kaselerde, sandalyelerde,
  çiçeklerde, kadrajın %4.8'ine kadar. "Okunamaz yüz" tabanı bunları yakalamıyor. Bu yüzden
  `detail`/`venue` planlarında yüz terimleri hiç uygulanmıyor.
- **Kesim temposu müziğe uyuyor** (ölçüldü): low 1.94 sn, high 0.50 sn, low 1.48 sn medyan
  kesim. "Müzikle uyum yok" şikâyeti tempo değilse içerikle ilgilidir; ölçüsü yok.
- **Ön plan tıkanıklığı ölçülemiyor.** Kurgucu "önden geçen adam" dedi; ölçtüm ve hiçbir
  sinyal yok: pencere puanı 0,77–0,88, yüz oranı şot boyunca düz (0,012), "arkadaki" tanımı
  *küçük ve uzak* yüzler olduğu için önden geçen biri özne sanılıyor. Şikâyet edilen kesimin
  karelerine tek tek bakıldığında ise temiz çıktı — bu yüzden bir dedektör kurulmadı. Önce
  hangi karede olduğunu görmek gerekiyor.
- **Bir düzensizlik:** yavaş çekim barajı `d726c51`'in içinde kazara gitti ve mesajında
  geçmiyor. Commit değiştirilmedi; `1a67fe8` kaydı ve testi ayrıca taşıyor.
- Hazırlık setinde 3 yanlış etiket duruyor; dört düzeltme denemesi de ölçümde daha kötü çıktı.

---

## Değişmeyen çalışma kuralları

- **Bir düzeltmeden sonra kurguyu Resolve'a yeniden gönder.** Kurgucu iki tur boyunca eski
  timeline'a bakarken "düzeldi" dendi. Timeline adına saat koyun.
- **Doğrularken neyi doğrulamadığını sor.** Yavaş çekimde hız 0.50× diye doğrulandı ve
  *nereden başladığı* hiç kontrol edilmedi; klip yanlış yerden oynuyordu.
- **Kendi ölçüm betiğin de sessizce boş çalışabilir.** "345 klipte 0 uyuşmazlık" sonucu
  aldım; `ffprobe` PATH'te olmadığı için 345 dosyanın hepsi `except` ile atlanmıştı. Bir
  ölçüm sıfır sorun bulduğunda, önce kaç şeye gerçekten baktığını yazdır.
- Ölç, sonra değiştir. Bu turda dört kez ölçüm benim varsayımımı çürüttü:
  proxy'nin yeterli olduğu (değildi), referansların detayı yalnız bırakmadığı (bırakıyor),
  ağırlığın hareket sorununu çözeceği (hedef yanlıştı), sekans ölçümünün kategoriyle
  yapılabileceği (yapılamaz).
- Sabitler **taranarak** seçilir ve yorumunda ölçüm yazar. En hafif yeterli değer alınır.
- Test düşerse önce **testin önermesi** doğru mu diye bakılır; davranış kötüleşmediyse
  test düzeltilir ve commit mesajında neden düzeltildiği yazılır.
- Her iş ayrı commit; iki Python ortamı + node + ruff + `git diff --check` yeşil olmadan
  commit yok.
