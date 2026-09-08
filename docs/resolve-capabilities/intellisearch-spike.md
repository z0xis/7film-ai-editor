# IntelliSearch — paketler kurulduktan sonraki ölçüm

İlk ölçümde iki sebeple kapalı görünüyordu: AI paketleri kurulu değildi ve API'de arama/yüz
okuma metodu yoktu. Paketler kurulunca ikincisi yanlış çıktı — **okuma yolu var, sadece adı
`search` değil**: analiz sonucu klibin metadata'sına yazılıyor.

## Gerçek çıktı

```python
clip.AnalyzeForIntellisearch(identifyFaces=True, isBetterMode=False)
clip.GetMetadata()["People"]   # "Face 8,Face 20,Face 34,Face 11,Face 28,Face 2"
```

Aynı değer `GetClipProperty("People")` ile de okunuyor. Analizden önce alan hiç yok; sonra
tek alan olarak beliriyor (`GetMetadata()` bu projede yalnızca `People` döndürüyor).

## Ölçülenler

| Soru | Sonuç |
|---|---|
| Okunabiliyor mu | **Evet** — `GetMetadata()["People"]`, virgülle ayrılmış kimlik listesi |
| Kimlikler klipler arası tutarlı mı | **Evet.** 11 klipte 36 ayrı kimlik; `Face 2` 8 klipte, `Face 11` ve `Face 28` 7'şer klipte görünüyor. Numaralar proje genelinde artıyor ve tekrar ediyor, klip başına sıfırlanmıyor |
| API'den isim verilebiliyor mu | **Hayır.** `SetMetadata("People", …)` her biçimde `None` döndürüyor — alan salt okunur. İsimlendirme Resolve arayüzünden yapılır, API yalnızca okur |
| Hız | Faster 13–14 sn/klip · Better **104 sn/klip**. 408 kliplik bu çekim için Faster ≈ 95 dakika, Better ≈ 12 saat |
| Kalıcılık | Metadata alanı olarak duruyor; `Project.ResetIntellisearchAnalysis()` ile sıfırlanıyor |

## Sınır: varlık bilgisi, önem bilgisi değil

Kalabalık bir salon karesinde 13 kimliğe kadar çıkıyor — arka sırada oturan misafir de listeye
giriyor. Yani `People` "bu kişi bu klipte **var**" der, "bu klip **onun hakkında**" demez.

Bizim kendi verimiz bunun tam tersini biliyor: `face_ratio` kimin kadrajda büyük olduğunu,
`face_edge` kimin kenarda kaldığını, `bystanders` kaç kişinin geçtiğini ölçüyor — ama **kim**
olduğunu bilmiyor. İki taraf birbirini tamamlıyor: kimlik Resolve'dan, önem bizden.

## 7Film için kullanım

Gelin ve damadın kimliği bir kez arayüzden isimlendirilirse:

- **"gelin ve damat hiç yok"** planları ayırt edilir — düğün filminin merkezi olmayan planlar.
- **"solist çok fazla görünüyor"** — solistin kimliği bir kez işaretlenince, o kimliğin baskın
  olduğu planlar sayılabilir. Bugün bunu CLIP'e sorulan bir metin istemiyle yapıyoruz.
- Aile/misafir dengesi ölçülebilir hale gelir.

Yerine geçmez, yanına eklenir: sınıflandırma, kalite, kadraj ve tekrar tespiti bizde kalır.

## Karar

Bir sonraki adım için **ön koşul**: gelin ve damadın Resolve arayüzünde isimlendirilmesi.
İsimlendirme olmadan `Face 2` bir numaradır ve düğün zekâsına bağlanamaz.
