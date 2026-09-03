# 7Film AI Editor

Yerel çalışan, düğün ham görüntülerinden müziğe hizalı ve DaVinci Resolve'da düzenlenebilir kaba kurgu üreten açıklanabilir bir edit asistanı.

Bu ilk sürüm şunları yapar:

- Medya klasörünü, orijinal dosyalara dokunmadan ffprobe ile indeksler.
- Proxy ve thumbnail işlerini kaldığı yerden sürdürülebilen job'lar olarak yürütür.
- PySceneDetect ile shot adayları çıkarır; yerel CLIP modeliyle düğün olayı, kişi ve plan ölçeğini sınıflandırır.
- OpenCV ile netlik, pozlama, kontrast, hareket ve görsel tekrar ölçümü yapar.
- Müzikten BPM ve beat grid çıkarır.
- Şeffaf bir puanlama motoruyla alternatif kaba kurgu planları üretir.
- OTIO ve FCPXML üretir; her seçimin nedenini JSON planında saklar.

## Gereksinimler

- Python 3.12
- FFmpeg (`ffmpeg` ve `ffprobe` PATH içinde)
- Node 20+ (yalnızca React arayüzünü geliştirmek için)

## Hızlı başlangıç

Bu çalışma alanındaki izole kurulum hazırsa macOS'ta `7Film AI Editor.command` dosyasını çift tıklayın veya terminalde çalıştırın:

```bash
./scripts/run_app.sh
```

Arayüz `http://127.0.0.1:8000/` adresinde açılır. İzole ortamı yeniden kurmanız gerekirse:

```bash
cd 7film-ai-editor
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
uvicorn sevenfilm.api:app --reload --app-dir apps/api
```

## DaVinci Resolve Studio eklentisi

Bu sürüm DaVinci Resolve 21'in resmi Workflow Integration API'sini kullanır. Kurulum:

```bash
./scripts/install_resolve_plugin.sh
```

Resolve'u yeniden başlattıktan sonra `Workspace → Workflow Integrations → 7Film AI Editor` yolunu açın. Panel yerel analiz motorunu otomatik başlatır. Kaba kurgu hazır olduğunda **Resolve'a gönder** düğmesi FCPXML'i açık projeye doğrudan aktarır, Edit sayfasına geçer ve seçim gerekçelerini timeline marker'larına yazar.

API dokümantasyonu `http://127.0.0.1:8000/docs`, arayüz ise `http://127.0.0.1:8000/` altında açılır.

## Güvenlik ve veri ilkeleri

- Tüm işlemler varsayılan olarak yereldir.
- Kaynak medya yolları değiştirilmeden saklanır; asıl dosyalar hiçbir zaman yeniden yazılmaz.
- Erişim hakkı olmayan uzak video bağlantıları indirilmez veya kısıtlamaları aşılmaya çalışılmaz.
- FCPXML aktarımından önce Resolve sürümü ve örnek proje ile doğrulama yapılmalıdır.

## Görsel analiz

İlk **Shot’ları çıkar** çalıştırmasında yerel CLIP ağırlıkları proje içindeki `.runtime/huggingface` klasöründen yüklenir. Analiz sırasında görüntüler harici bir servise gönderilmez. Model kullanılamazsa iş durmaz; daha düşük güvenli OpenCV sınıflandırmasına geçer.

v0.3; ingestion, proxy, müzik/shot analizi, 18 videoluk referans ritim profili, semantik görsel sınıflandırma, açıklanabilir kurgu planı ve doğrudan Resolve aktarımını içerir.
