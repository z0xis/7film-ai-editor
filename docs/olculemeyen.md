# Ölçemediğimiz kusur

Editörün en sık işaretlediği plan tipi — "arkadan kocaman kafa", "alakasız sırt", "bu ne amk
nasıl plan", "burda napıyorlar" — ölçtüğümüz hiçbir sayıda görünmüyor. Bu belge, o sonuca
nasıl varıldığını ve hangi yolların denenip elendiğini tutuyor, aynı denemeler tekrarlanmasın
diye.

## Kanıt: reddedilenler teknik olarak daha iyi

Editörün ve incelemenin reddettiği 16 klip (180 shot) ile kalan 1225 shot karşılaştırıldı.
Cohen'in d'si ile:

| ölçüt | reddedilen | kalan | d |
|---|---|---|---|
| teknik kalite | 0.412 | 0.397 | **+0.27** |
| estetik | 0.898 | 0.781 | **+0.41** |
| netlik | 25.2 | 23.0 | **+0.28** |
| en düşük netlik | 20.8 | 18.6 | +0.27 |
| yüz oranı | 0.012 | 0.012 | 0.01 |
| yüz kenar | 0.083 | 0.049 | 0.15 |
| yüz sayısı | 5.94 | 5.13 | 0.25 |
| geçen kişi | 2.22 | 1.81 | 0.19 |
| hareket | 0.249 | 0.299 | −0.31 |
| pencere hareketi | 17.7 | 21.9 | −0.43 |

Hiçbiri güçlü değil (|d| > 0.8 yok, > 0.5 bile yok). Ve işaretin yönü asıl mesele: reddedilen
planlar **daha keskin, daha kaliteli ve estetik skoru daha yüksek**. Kusur, resmin kendisinde
değil.

Tek zayıf sinyal durgunluk (d = −0.43), ve o zaten cezalandırılıyor.

## Denenip elenen yollar

| yol | ölçüm | sonuç |
|---|---|---|
| Geometrik kompozisyon — öznenin kadrajdaki konumu | kötü 0.312, iyi 0.332 | ayrım 0.020, gürültü |
| Geometrik — üst üçte birin boşluğu | kötü 0.965, iyi 0.951 | ayrım 0.015, gürültü |
| CLIP'e yargı sordurmak ("iyi/kötü kompozisyon") | kötü 0.031, iyi 0.045 | ayrım 0.014, gürültü |
| Reddedilenlere CLIP benzerliği | %99 eşikte planların %25'i "benziyor" | uygulanamaz |
| Bölgesel netlik (3×3 ızgara, en bulanık/en net) | kötü 0.135, iyi 0.142 | ayrım 0.007; üstelik iyi kapanış adayını en kötü sayıyor |
| Netlik tabanı | bulanık kesim 3.1 → 1.0 | **gönderildi**, ama hedef planı elemedi |
| Tavan prompt'u (CLIP) | boş tavanı buluyor, editörün kastettiğini bulmuyor | geri alındı |

## Bugünkü çözüm

Kurgu üretildikten sonra kareler ızgaraya dizilip inceleniyor
([review_cut.py](../tools/resolve/review_cut.py) ve contact sheet), kötü planlar ret listesine
yazılıyor ([collect_flags.py](../tools/resolve/collect_flags.py)). Liste birikimli: bir kez
elenen bir daha gelmiyor.

Bu editörün işi değil — "niye ben işaretliyorum o zaman eklenti niye var". Ama kalıcı da değil:
her kurgudan sonra bir tur gerekiyor.

## Kalıcı çözüm için gereken

Gerçek bir görsel-dil modeli: kareye bakıp "bu plan bir düğün filminde neyi anlatıyor"
sorusuna cevap verebilen. CLIP bunu yapamıyor — benzerlik ölçüyor, yargı vermiyor. Yerel bir
VLM (4–8 GB) bu boşluğu kapatabilir; maliyeti kurulum ve 1405 plan için işlem süresi.

## Altıncı yol: görsel-dil modeline sordum (2026-09-08)

Ölçüler göremiyorsa belki bir model *bakarak* görür diye denedim. Editörün elediği
klipler ile tuttukları aynı soruyla modele soruldu; kliplerin en yüz-yoğun karesi
512 px'e ölçeklenip verildi.

| model | doğruluk | kötüleri yakalama | hız |
|---|---|---|---|
| SmolVLM-500M-Instruct | 7/11 | C2133'ü yakaladı | 5.5 sn/kare |
| SmolVLM-Instruct (2.2B) | 6/14 (%43) | **0/8** | 54 sn/kare |

2.2B on dört karenin on dördüne de "USABLE" dedi — tek bir istisna yok. Sabit cevap,
yargı değil. 500M'in 7/11'i de aynı sebeple sayılmaz: o da tek kelimeye yapışmıştı,
yalnızca diğer kelimeye; soruyu özelleştirince ("birinin sırtı kamerayı kapatıyor mu?")
neredeyse her şeye "no" dedi. İki modelin ikisi de kliplere bakmadan cevap veriyor.

Sonuç: bu boyuttaki açık VLM'ler düğün karesinin kullanılabilirliğini ayırt etmiyor.
Daha büyük/kapalı bir modele gitmek 500 kliplik bir çekimde hem ücretli hem de
her klibi dışarı göndermek demek — üretime alınmadı.

Yan not: test için `torchvision 0.29.0` **yalnızca `.venv`** içine kuruldu
(torch 2.14.0 sabit kaldı, 574 test geçti). Üretim ortamı
`.runtime/mamba-root/envs/sevenfilm` **değişmedi** ve bu koda üretimde ihtiyaç yok.

## Netlik ölçüsü yanlıştı — ama bulgu değişmedi (2026-09-09)

Yukarıdaki tabloların birinde netlik 25.2'ye karşı 23.0 yazıyordu ve bunun bir açıklaması
yoktu. Açıklaması şuydu: netlik 4K karede ölçülüyordu ve orada Laplacian varyansı odağı
değil **sensör gürültüsünü** okuyor. Filmin açılışındaki neon tabela — gözle en net kare —
çekimin en bulanık %1'inde görünüyordu; editörün bulanık dediği iki gelin planı %45'te.

Ölçüm sabit 640 piksel genişlikte yapılınca sıralama düzeldi ve kesimin gerçekten gösterdiği
kareyle uyum 0.50'den 0.96'ya çıktı. 1405 shot yeniden ölçüldü. Kurgudaki en bulanık kesim
7.7'den 36.2'ye, açılışınki 10.7'den 42.8'e çıktı; süre 150.0 saniyede kaldı.

Sonra asıl soru yeniden soruldu. Düzeltilmiş ölçüyle:

| ölçü | elenen | tutulan | Cohen d |
|---|---|---|---|
| netlik | 196.5 | 138.2 | −0.37 |
| en kötü yarım saniyenin netliği | 151.2 | 98.5 | −0.39 |
| estetik | 0.863 | 0.789 | −0.25 |
| teknik kalite | 0.394 | 0.400 | +0.11 |

Editörün elediği klipler hâlâ tuttuklarından **daha keskin**. Fark artık gürültüden değil:
o klipler gerçekten daha net. Elenme sebepleri netlik değildi — arkadan kafa, anlamsız
kadraj, solist. Bu belgenin merkezi bulgusu ayakta ve artık doğru bir ölçüyle duruyor.
