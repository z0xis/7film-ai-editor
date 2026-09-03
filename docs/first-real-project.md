# İlk gerçek proje doğrulaması

Bu kontrolü hakları size ait küçük bir düğün projesinde yapın. Bir kopya üzerinde çalışın; uygulama orijinalleri değiştirmez ama Resolve import doğrulaması her sistemde farklı davranabilir.

1. `python scripts/check_system.py` ile Python 3.12, FFmpeg/ffprobe ve paketleri doğrulayın.
2. API'yi çalıştırın: `uvicorn sevenfilm.api:app --reload --app-dir apps/api`.
3. Arayüzden proje oluşturun, sonra yalnızca ham video klasörünü indeksleyin.
4. İlk çalışmada birkaç klip için kaynak yol, FPS, süre ve timecode’un doğru kaydedildiğini kontrol edin.
5. Proxy/thumbnail ve shot analizi job'larını çalıştırın. Placeholder etiketlerin henüz AI görsel tanıma olmadığını hesaba katın.
6. Müzik analizinden sonra 120 saniyelik timeline oluşturun. Her item'ın kaynak in/out, timeline in/out, skor ve seçim nedenini gözden geçirin.
7. FCPXML'i DaVinci Resolve'a içe aktarın. Medya offline olmamalı; olursa path eşlemesi, disk bağlantısı ve Resolve sürümünü kaydedin.
8. Keep rate, replacement rate, trim error ve kaba kurgu için harcanan süreyi kaydedin. Bu metrikler v0.2 stil profili için temel veridir.

## Bilinen v0.1 sınırları

- Görüntü etiketleri deterministik placeholder'lardır; henüz kişi/duygu/olay algılayan model yoktur.
- Müzik dosyası hedef süreden uzun veya eşit olmalıdır; otomatik müzik edit'i yoktur.
- Hız rampası, renk, Fusion, sync audio ve Resolve scripting bu aşamaya dahil değildir.
- Referans video analizi ve kişisel Style Profile v0.2 kapsamındadır.

