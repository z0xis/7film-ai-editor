# Resolve 21.1 transcription — ölçüm

Üretim zekâsına dokunulmadı. Yalnızca Media Pool öğelerinde transkript üretildi ve okundu.

## Gerçek API

| Soru | Cevap |
|---|---|
| Hangi nesnede | `MediaPoolItem.TranscribeAudio(useSpeakerDetection=None, transcribeAsNestedClip=False)` üretir, `MediaPoolItem.GetTranscription(useNestedClipTranscription=False)` okur, `ClearTranscription()` siler. Aynı üçü `Folder` üzerinde de var (toplu çalıştırma). |
| Hangi medyada | Ses akışı olan klipler. Bu çekimin tamamı 2 kanal PCM kamera sesi taşıyor ve hepsinde çalıştı. |
| Dil | Proje ayarı: `SetSetting("transcriptionLanguage", "tr")`. Varsayılan `auto`. **`AUTO_CAPTION_TURKISH` sabiti (20.0) ve `"Turkish"` kabul edilmiyor; yalnızca ISO kodu (`"tr"`) alınıyor.** |

## Gerçek şema

```
{ "language": "tr",
  "segments": [
    { "start": "09:31:01:43",      # kaynak timecode'u, saniye değil
      "end":   "09:31:03:41",
      "text":  " Speaker 1'in söylediği",
      "speaker": "Speaker 1" | None,
      "words": [ {"start": "...", "end": "...", "text": "..."} ] } ] }
```

- **Segment timing: var**, ama **timecode string** olarak ve klibin kaynak saatinde — sıfırdan
  değil. Kareye çevirmek için klibin kendi başlangıç timecode'u gerekiyor.
- **Word-level timing: var** (`words[]`, segment başına). 121 saniyelik klipte 22 segment,
  95 kelime.
- **Speaker: var**, `useSpeakerDetection=True` verildiğinde. Değer `"Speaker 1"` gibi üretilmiş
  bir etiket, isim değil. Konuşma olmayan segmentlerde `None`.
- **Confidence: YOK.** Ne segmentte ne kelimede. Segment anahtarları tam olarak
  `start, end, text, words`; kelime anahtarları `start, end, text`.
- Sessizlik `(...)`, müzik `(Music)` / `🎵🎵🎵` / `(Upbeat Music)` olarak işaretleniyor.

## Ölçülen davranış

| Soru | Sonuç |
|---|---|
| Süre | 45 sn klip 9.8 sn, 70 sn klip 29.2 sn, 121 sn klip 27.3 sn. Klip uzunluğuyla orantılı değil, içerikle ilgili. |
| Cache | **Var.** Transkript varken `TranscribeAudio` 0.0 saniyede dönüyor ve eski sonucu bırakıyor — **dil ayarı değişse bile**. Yeniden üretmek için `ClearTranscription()` şart. Bu bir tuzak: dil düzeltilip yeniden çağrıldığında hiçbir şey olmaz ve sessizce eski dilin çıktısı kalır. |
| Kalıcılık | **Var.** `SaveProject` → `CloseProject` → `LoadProject` sonrası üç klibin segment sayıları birebir aynı (5, 2, 22). Dil ayarı da kalıyor. |
| Çoklu konuşmacı | Bu çekimde ayrı konuşmacılar oluşmadı — tek `Speaker 1` etiketi çıktı. Birden fazla konuşmacıyı ayırıp ayıramadığı **UNKNOWN**: doğrulayacak malzeme yok. |
| Türkçe | Dil `tr` olarak ayarlanınca çıktı `tr` geliyor ve **müziği doğru tanıyor** (🎵). Konuşma metni bu çekimde güvenilir değil — aşağıya bakın. |
| Kamera sesi vs harici kayıt | Bu çekimde harici kayıt yok, **karşılaştırılamadı**. |
| Resolve UI ile eşleşme | **UNKNOWN** — ölçülmedi. |

## Asıl sonuç: bu çekimde konuşma yok

Otomatik dil tespiti Türkçe bir klibi **Korece** sandı ve Korece saçma metin üretti. Dil elle
`tr` yapılınca dil doğru geldi ama metin hâlâ anlamsız: *"that you'll seeirable together
helping me"*, *"Altyazı M.K."*, *"Herifler anlandı mercil Evliyim'mhasMusic"*.

Sebep transkripsiyonun kötülüğü değil, **kaynak**: bu düğünün tamamı canlı müzikli bir salonda,
kamera üstü mikrofonla, uzaktan kaydedilmiş. Transkript bunu doğru okuyor — konuşma yerine
`(Music)` ve `🎵` yazıyor. Yani ölçüm, aracın değil malzemenin sınırını gösteriyor.

**7Film için doğrudan sonuç: harici ses kaydı olmayan düğünlerde transcription'ın kurguya
katacağı bir sinyal yok.** Yemin veya konuşma seçimi ancak yaka/masa mikrofonu ya da ayrı
recorder kaydı olan çekimlerde anlamlı olur.

## Önerilen normalize veri modeli

Resolve'un gerçek çıktısına göre, varsayıma göre değil. Platformdan bağımsız kalır: alanlar
Resolve'a değil, "konuşma nerede ve kim söylüyor" sorusuna bağlı.

```
SpeechSegment
  asset_id: str            # bizim medya kimliğimiz, Resolve'unki değil
  start: TimeRange         # kare tabanlı, klibin kaynak timecode'undan çevrilmiş
  text: str
  speaker: str | None      # "Speaker 1" gibi üretilmiş etiket; isim değil
  words: tuple[SpeechWord] # (start: TimeRange, text: str)
  kind: "speech" | "music" | "silence"   # (Music)/(...)/🎵 işaretlerinden türetilir
```

Bilerek dışarıda bırakılanlar:

- **confidence** — Resolve vermiyor, uydurmak yanlış olur.
- **language** — segment değil klip özelliği; asset düzeyinde tutulur.
- Timecode string'i — sınırda karea çevrilir, içeride hiçbir yerde string zaman taşınmaz
  (`exporter._timecode_frames` zaten bu dönüşümü yapıyor).

`kind` alanı bu çekimin öğrettiği şey: çıktının çoğu konuşma değil, ve müzik/sessizlik
işaretlerini metin sanmak en büyük tuzak.

## Capability matrisi kaydı

| Yetenek | Durum |
|---|---|
| Transkript üretme ve okuma | **SUPPORTED** |
| Segment timing | **SUPPORTED** (timecode string, kaynak saatinde) |
| Word-level timing | **SUPPORTED** |
| Speaker etiketi | **PARTIAL** — etiket üretiliyor, çoklu konuşmacı ayrımı doğrulanamadı |
| Confidence | **UNSUPPORTED** — alan yok |
| Türkçe | **PARTIAL** — dil ayarı çalışıyor, bu çekimde metin kalitesi kaynak yüzünden düşük |
| Cache | **SUPPORTED** — ve dil değişince kendini yenilemiyor, `ClearTranscription` şart |
| Kalıcılık | **SUPPORTED** — proje kapanıp açılınca duruyor |
| UI ile eşleşme | **UNKNOWN** |
