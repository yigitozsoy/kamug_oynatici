# kamug — Claude için proje notları

Bu dosya Claude Code'un her oturumda okuduğu proje belleği. Önceki uzun geliştirme sohbetinin özeti:
proje ne, nasıl çalışıyor, geliştirici nasıl çalışmayı seviyor, nelerde dikkatli olmak gerekiyor.
Yeni bir işe başlamadan önce baştan sona oku.

---

## 1. Proje nedir

**kamug**, Yiğit Özsoy'un Windows için yazdığı, **YouTube görünümlü, VLC motorlu
evrensel medya oynatıcısı**. Video, müzik ve görselleri tek pencerede açar; içinde görsel ve video düzenleyici vardır.

### tamga ailesi
Kullanıcının uygulamaları **tamga** ailesi (hep küçük harf, Göktürkçe adlar; işaret = adın baş harfinin Göktürk harfi):
**erk** (planlayıcı, `Desktop\erk`) · **bediz** (Bambu Lab yazıcı aracı, `Desktop\bediz`) · **kamug** (bu repo,
Göktürkçe "hepsi") · **yazıt** (not / ekran kaydı / çizim; ASCII yazımı `yazit`, repo klasörü `Desktop\yazıt`).
- **Kullanıcı uygulamaların eski adlarını (gamma, alpha, beta, delta) hiçbir yerde görmek istemiyor** (2026-11-22).
  Arayüzde, README'de, yorumlarda, notlarda hep yeni adları yaz. Eski ad yalnızca uyumluluk için zorunlu kimliklerde kalır:
  Inno **AppId**, ProgID adları `gamma.video/audio/image/model` (Windows UserChoice bunlara bağlı; değişirse varsayılan
  seçim düşer ve MOTW uyarısı çıkar), küçük resim CLSID'leri, eski kurulumu / veri klasörünü (`config.OLD_DATA_DIR`)
  taşıyan kod, yazıt notunun iç biçim adı `"delta-note"` ve eski bağlantı anahtarı `"gamma"`.
- Logo: Göktürk "k" (dikey gövde + sola yükselen iki eğik kol), `packaging/make_logo.py` üretir (logo.png beyaz, logo.ico).
- Paket `kamug/`, exe `kamug.exe`, kurulum `{autopf}\kamug`, veri `%LOCALAPPDATA%\kamug`.
- yazıt notları `.yazit`; bağlantı `"ln": {"kamug": yol, "t": sn}`.

- Repo: https://github.com/yigitozsoy/kamug_oynatici (özel, GPL-3.0; eski adı gamma_player, GitHub yönlendirir)
- Sürüm tek yerde: `kamug/__init__.py` → `__version__`
- Dil: Python 3.13/3.14 · PyQt6 · python-vlc (libVLC 3.0.x) · Pillow + pillow-heif + imagecodecs (JPEG XL) ·
  imageio-ffmpeg (ffmpeg ikilisi) · numpy
- Yalnızca **Windows 10/11 64-bit** hedefleniyor. Win32 API'leri (ctypes) serbestçe kullanılıyor.
- Arayüz metinleri **Türkçe varsayılan**, İngilizce ikinci dil.

### Geçmiş
Proje önce başka bir yapay zekâ aracıyla (Antigravity) başladı, sonra Claude ile baştan yeniden yazıldı.
Eski kod repoda değil, `C:\Users\yigit\OneDrive\Desktop\gamma_arsiv\` içinde (`_eski_kod`, örnek video).
O klasöre dokunma, kullanıcı istemedikçe silme.

---

## 2. Geliştiriciyle çalışma tarzı (EN ÖNEMLİ BÖLÜM)

### İletişim
- Kullanıcı **Türkçe**, gündelik ve hızlı yazar; yazım hataları olur, niyeti anla. Cevapları **Türkçe** ver.
- Genelde **ekran görüntüsü + kısa cümle** ile istek verir: "bu niye mor, youtubedaki böyle", "bunlar defaultta
  burda olmasın". Görüntüdeki **tam olarak işaret edilen yeri** değiştir, fazlasını yapma.
- Bir mesajda **çok sayıda istek** sıralar. Hepsini tek tek yap, hiçbirini atlama; sonunda madde madde neyin
  yapıldığını yaz. Yapamadığın ya da doğrulayamadığın bir şey varsa açıkça söyle.
- Teknik terim bilmeyebilir. Sonucu **kullanıcının gözünden** anlat ("artık sağ tık menüsünde ICO'ya çevir var"),
  iç detayları (fonksiyon adları, mimari) yalnızca gerekiyorsa kısaca.
- Soru sormak yerine **makul varsayılanla ilerle** ve ne seçtiğini söyle. Gerçekten kullanıcıya ait bir karar
  varsa (isim, herkese açık bir şey yayınlamak) sor.
- "Yok onu ben yaptım" gibi düzeltmeler gelir: test sırasında kullanıcı da uygulamayı elle kullanıyor olabilir,
  beklenmeyen bir durum görünce hemen kodu suçlama.

### Tasarım zevki
- **Referans her zaman YouTube**: düzen, zaman çubuğu, ses kaydırıcısı, tam ekran simgesi, duraklat/oynat
  animasyonu (ortada büyüyerek kaybolan daire), tooltip rengi, 2x hız (sağ tarafa basılı tutunca). Kullanıcı
  "YouTube'daki gibi" derse **birebir benzet**, yorum katma.
- **Sade varsayılanlar, her şey açılıp kapatılabilir.** Kullanıcının sevdiği desen:
  1. Yeni özellik eklenir,
  2. **varsayılanda gizli/kapalı** gelir (arama çubuğu, dosya aç düğmeleri, ekran görüntüsü / 16:9 germe düğmeleri),
  3. **Tercihler › Kişiselleştirme**'den açılır, yeri değiştirilebilir.
  Yani: *"çok fazla kişiselleştirme ekle ama default böyle gelsin."* Varsayılan görünümü bozma.
- Renk: **gri vurgu rengi** (kırmızı değil), AMOLED siyah koyu tema; 5 koyu + 5 açık tema çeşidi var.
  Mor/eflatun tonlar istemiyor (bir kez tooltip yanlışlıkla mor çıktı, şikâyet etti).
- Gereksiz tekrar sevmez: aynı düğme iki yerde olmasın (ör. "Düzenle" iki kez vardı, teke indirildi;
  dosya aç düğmeleri logoya basınca zaten çıkıyor, üst çubuktan kaldırıldı).
- Simgeler karışmasın: oynatıcı ayarları ⚙, uygulama tercihleri "•••" (kamug yazısıyla hizalı).
- Hizalama ve oran detaylarına dikkat eder (simge yazıyla ortalı mı, önizleme kutusu fazla büyük mü).
- Hızlı ve akıcı his ister: zaman sayacı takılmadan aksın, animasyonlar YouTube kadar yumuşak olsun.

### İş akışı kuralları
- **Her değişiklikten sonra kurulum dosyası DERLEME.** Derleme ~4-5 dk sürüyor ve kullanıcı arka arkaya
  istek veriyor. Kaynakta yap, test et, "derlenmedi" de. Kullanıcı "bitti / derle" deyince derle.
- Önce **gerçekten çalıştırıp doğrula**, sonra "oldu" de. Kullanıcı "test et, güzel oluyor mu bak" der.
- Commit/push **yalnızca istenince**. Herkese açık yayın (push, etiket, release) öncesi onay al.
- Kişisel bilgileri (e-posta vb.) koda, commit'e, dış servislere koyma. Commit kimliği bu repoda yerel
  olarak `Yiğit Özsoy <yigitozsoy@users.noreply.github.com>` ayarlı.

---

## 3. Klasör yapısı

```
main.py                 kaynaktan başlatıcı (python main.py [dosya|klasör])
kamug/
  app.py                giriş: tek örnek (QLocalServer), --new-window, Türkçe Qt çevirisi, restart()
  window.py             MainWindow: düzen, oynatma, PiP, pin, tam ekran, Snap, dosya işlemleri (en büyük dosya)
  overlay.py            video üstü kontroller (ayrı saydam üst pencere, aşağıya bak)
  popup_menu.py         ⚙ menü altyapısı · player_menu.py menü sayfaları
  sidebar.py            sağdaki "Bu klasörde" listesi (model + delegate, küçük resimler)
  titlebar.py           özel başlık çubuğu (çerçevesiz pencere)
  views.py              ana sayfa, müzik görünümü (kapak + etiketler), alttaki bilgi çubuğu
  image_viewer.py       zoom/pan/kırpma/damlalık
  model_io.py           3D okuma (STL/OBJ/PLY/OFF/glTF/GLB/3MF, numpy) + yazılımla küçük resim çizimi
  model_viewer.py       3D görüntüleyici (QOpenGLWidget, GLSL 1.20; döndür/kaydır/yakınlaştır)
  image_editor.py       görsel düzenleyici paneli (render() saf fonksiyon, DEFAULT_STATE)
  video_editor.py       kes/kırp/filigran/altyazı gömme diyaloğu (ffmpeg komutu üretir)
  bgremove.py           arka plan kaldırma (numpy, kenara bağlı bölge yayılımı)
  watermark.py          yazı/logo filigranı (Qt ile PNG çizilir, ffmpeg overlay)
  vlc_engine.py         libVLC sarmalayıcı
  thumbs.py             ffmpeg: küçük resim, süre, kare önizleme, kapak, etiket, dalga formu; iş havuzu
  image_io.py           tüm görsel formatlarını okuma/yazma (HEIC/JXL tembel yüklenir)
  library.py            klasör tarama, sıralama (Gezgin sırası dahil), MediaItem
  config.py             yollar, Prefs (%LOCALAPPDATA%\kamug\preferences.json)
  layout_prefs.py       kişiselleştirme: düğme sırası/görünürlüğü, davranış ayarları
  theme.py              temalar, vurgu renkleri, stil sayfası
  icons.py              Material SVG yolları · i18n.py  t("anahtar") metinleri (tr, en)
  dialogs.py            Tercihler (kategorili), Medya bilgisi, Kısayollar, Dönüştür
  cli.py · console.py   komut kapısı run(win, argv) → (kod, metin): status / open / play / pause / seek / list / jump /
                        vol / speed / theme / pref …; `python -m kamug.cli <komut>` çalışan kamug'a tek örnek
                        sunucusundan gider ("cli
" + JSON, app.serve cevabı geri yazar). Geliştirici konsolu: Esc'nin
                        altındaki tuş (tarama kodu 41, TR-Q "): Shift+" prefs dev_mode, mod açıkken " konsolu açar/kapatır.
                        Panel başlık çubuğunun altına düzene girer, içeriği iter (VLC'nin yerel penceresi üstüne binmez).
  shortcuts.py · formats.py · shell.py (sağ tık menüsü kaydı) · widgets.py (ToggleSwitch vb.)
  assets/               logo.png (beyaz Γ, arayüzde renklendirilir), logo.ico
tests/smoke_test.py     uçtan uca test (çekirdek + gerçek arayüz)
packaging/              build.ps1, kamug.spec (PyInstaller), installer.iss (Inno Setup), make_meta.py
.github/workflows/build.yml   v* etiketi gelince derleyip Releases'a koyar
docs/                   README ekran görüntüleri
```

---

## 4. Mimari ve bilinen tuzaklar

Bunlar zor bulunmuş şeyler. Değiştirmeden önce nedenini anla.

- **Overlay ayrı pencere:** VLC kendi yerel (native) HWND'sine çizer; Qt widget'ları üstünde görünmez
  ("airspace" sorunu). Bu yüzden video kontrolleri `Qt.Tool | WindowDoesNotAcceptFocus` olan **ayrı, çerçevesiz,
  saydam bir üst pencere** (`overlay.py`). Fare olaylarını yakalamak için alfa=1 dolgu kullanılıyor.
  Ana pencere taşınınca/boyutlanınca overlay'in konumu senkronlanır.
- **Native kardeş widget'lar:** `AA_DontCreateNativeWidgetSiblings` + video_host'ta `WA_NativeWindow` ve
  `WA_DontCreateNativeAncestors`. Bu olmazsa başlık çubuğu da native olur ve **pencere sürüklenemez**.
- **Windows Snap:** pencere çerçevesiz ama WS_THICKFRAME/WS_CAPTION stilleri ekli; `nativeEvent` içinde
  WM_NCCALCSIZE (büyütülünce çalışma alanı) ve WM_NCHITTEST (boş başlık çubuğu = HTCAPTION, kenarlar)
  işleniyor. Başlık çubuğunda ayrıca `startSystemMove` yedeği var.
- **3D kısayolları:** 1 zemine yatan yüz (`lay_next_face`), 2 kesit (`cycle_section`; Shift+tekerlek / Shift+ok
  kaydırır, shader'da `u_clip` + arka yüzler düz koyu = kesit yüzeyi), 3 ölçü, 4 üçgenler, 5 ızgara, 6 döndür,
  7/8/9 önden/yandan/üstten, 0 sıfırla.
- **python-vlc tembel içe aktarılır** (`vlc_engine._load`): import libvlc DLL'lerini yüklüyor; bilgisayar yeni
  açılınca pencere geç görünüyordu. `VLC_ERROR` için `vlc_engine.VLC_ERROR` oku (from-import eski değeri tutar).
- **VLC ısınması:** `vlc_engine.warm_up()` pencere kurulurken arka plan iş parçacığında ilk videoda gereken eklenti
  DLL'lerini (`_WARM_PLUGINS`) yükler ve bir D3D11 aygıtını açık tutar (GPU sürücüsü). İlk görüntü ~140 ms erken
  (soğuk açılışta daha fazla). Yeni bir demux/çözücü eklentisi gerekirse listeye ekle.
- **Tıklama = anında duraklat (YouTube gibi):** overlay tek tıkta beklemeden `video_clicked` yayar; çift tıklamada
  bir kez daha yayıp durumu geri alır. `VLCEngine.toggle()` 0,8 sn içindeki ikinci çağrıda VLC'nin (geç güncellenen)
  durumuna değil önceki hedefin tersine bakar ve yeni durumu döndürür. Bezel animasyonu 340 ms, yalnızca orta bölge çizilir.
- **Yazı tipi yedekleri:** `theme.install_font_fallbacks()` (app.py) Segoe UI ailesine Yu Gothic UI, Malgun Gothic,
  Nirmala UI, Segoe UI Historic (Göktürk/Orhun, runik) vb. yedekleri ekler; yoksa Qt Göktürk'ü hiç çizemiyordu.
  VLC altyazısı ve ffmpeg gömmesi kendi yedeklerini zaten buluyor. UTF-8 olmayan harici altyazı gömülürken
  `charenc` eklenir (`VideoEditorDialog._sub_charenc`).
- **VLC motoru tembel:** açılışı hızlandırmak için `_ensure_engine()` ile ilk event döngüsünde ya da ilk
  oynatılabilir dosyada oluşturulur. `self.engine` None olabilir, kullanmadan önce kontrol et.
- **Küçük resimler tembel:** `ThumbnailService.request()` yalnızca açık dosyanın ±40 komşusunu kuyruğa alır;
  geri kalanı sidebar satırı çizilince `ensure()` ile istenir.
- **Thread kuralı:** iş parçacıklarında yalnızca QImage/PIL; QPixmap'i ana iş parçacığında üret.
- **QSS renk tuzağı:** `#606060f0` Qt'de **#AARRGGBB** olarak okunur (tooltip mor çıktı). Saydam renk için
  `rgba(...)` yaz. `QColor("rgba(...)")` geçersiz, `theme.qcolor()` kullan.
- **pyqtProperty adı** `pos` gibi QWidget metotlarıyla çakışmasın (ToggleSwitch'te `knob`).
- **Görsel düzenleyici kaydetme:** Kaydet/Farklı kaydet/kapat önce açık kırpma çerçevesini uygular (`_end_crop(True)`),
  `closed` sinyali kırpma modunu kapatır. Üzerine kaydedince dosya listesi değişmediği için `lib.refresh()` bir şey
  yapmaz: `_on_image_saved` boyut/tarih/çözünürlüğü elle yeniler, küçük resmi `request_one(force=True)` ile siler-çizer.
  `save_pil(meta_from=...)` ICC profilini ve EXIF'i (yön=1) korur.
- **Filigran WYSIWYG:** önizlemede ve çıktıda aynı Qt PNG'si kullanılır (`scale2ref` + `overlay`).
- **Altyazı gömme:** `setpts=PTS+A/TB,subtitles=...,setpts=PTS-STARTPTS` (kesilen parçada zamanlama doğru kalsın).
  Windows yolunda iki nokta kaçışı: `C\:/...`.
- **Gezgin sırası:** varsayılan sıralama, klasörün Windows Gezgini'ndeki sırası (PowerShell Shell.Application COM).
- **ffmpeg yolu:** `thumbs._find_ffmpeg()` imageio_ffmpeg'i import etmeden ikiliyi bulur (donmuş exe'de `_MEIPASS`).
- **Donmuş (PyInstaller) exe:** VLC `<exe>\vlc\` içine gömülü; önce oraya, sonra Program Files VLC'ye bakılır.
  build.ps1 gömülü eklentiler için `vlc-cache-gen.exe` ile `plugins.dat` üretir; o olmadan VLC her açılışta ~350
  eklenti DLL'sini yükler (yeni kurulumda Defender yüzünden ilk açılış çok yavaş, 3.0.0'da böyleydi).
- **3D (3.0):** `ModelViewer` ilk modelde oluşturulur (PAGE_MODEL = 4, `model_host` içinde). Alttaki kontrol
  satırı resim satırıyla ortak (`overlay.set_model_mode`): slayt düğmesi = otomatik döndür, sığdır = görünümü
  sıfırla, döndür = modeli çevir. **QOpenGLWidget KULLANMA:** ana pencereye ilk eklenince Qt bütün pencereyi
  yeniden oluşturuyor (HWND değişir → pencere kapanıp açılır, VLC görüntüsü kaybolur, Snap stilleri gider).
  Çizim `_GLView(QOpenGLWindow)` içinde, `createWindowContainer` ile (WA_DontCreateNativeAncestors); `ModelViewer`
  bir QWidget sarmalayıcıdır ve `__getattr__` ile her şeyi `_GLView`'e aktarır. `QT_WIDGETS_RHI` ile baştan
  OpenGL'li pencere de çözer ama açılışa ~0,7 sn ekliyor. `image()` her zaman FBO'ya yeniden çizer; kapanışta
  `release_gl` (aboutToQuit). Smoke test 3D'den sonra pencere kimliğinin değişmediğini denetler.
- **Yalnızca ses içeren mp4:** VLC "vout 0" olayını her zaman göndermiyor; `load_item` her videoda 1,2 sn sonra
  `_check_audio_only` çağırır. Karar `has_vout` + `video_track_count()` ile verilir (görüntü geç gelse de yanılmaz).
- **Kapanışta çökme:** küçük resim işi (büyük model) uygulama kapanırken sürüyorsa silinmiş sinyale emit → PyQt
  abort (0xC0000409). `_ThumbJob._emit` + `ThumbnailService.closed` (aboutToQuit'te shutdown) bunu engeller. Modeller Y-yukarıya çevrilir (STL/PLY/OFF/3MF Z-yukarı kabul edilir).
  `kamug.spec`'te QtOpenGL / QtOpenGLWidgets artık hariç tutulmamalı.
  İç UV düzeni OBJ gibidir (v=0 resmin altı); glTF okurken 1-v yapılır, GL'ye doku `flipped(Vertical)` yüklenir.
  Ölçüler (`D`, `model_dims`, varsayılan kapalı): glTF metre, diğerleri mm kabul edilir (`dims_unit`).
  Saydam PNG: `ModelViewer.image(transparent=True)` ekran dışı FBO'da 2 kat çizer, boşluğu kırpar.
  Dönüştürme: `model_io.export_model` → STL/OBJ(+mtl+png)/3MF(renkli)/GLB/PLY; metre↔mm ve Y↔Z-yukarı çevrilir.
- **Diziler (series.py, intro.py, series_dialog.py):** `series.parse` dosya adından bölüm (SxxEyy, 3x13, "3. Sezon 13.
  Bölüm", anime "- 13") ya da film (Ad.2010) çıkarır; `series_for` aynı klasördeki aynı başlıklı bölümleri toplar.
  Video açılınca `window._setup_series`: bilgi çubuğunda "Dizi/Film" düğmesi, eşleşen altyazıyı açar (ad farklı olsa
  da numaradan; "aot" gibi kısaltma ya da klasörde başka dizi yoksa kabul), introyu yükler/arar. Kayıtlar
  `%LOCALAPPDATA%\kamug\series.json` (elle aralık, bölüm başına otomatik aralık, referans parmak izi, auto_skip).
  İntro bulma: bölüm başlarının ses parmak izi (8 kHz, 0,1 sn adım, WIN 4096; sessiz kareler rastgele) karşılaştırılır,
  ≥20 sn ortak bölüm = intro; ilk bulunan referans sonraki bölümlerde tekrar kullanılır. "İntroyu atla" düğmesi
  overlay'de sağ altta (`set_skip`). Altyazı gömme: `embed_command` yeniden kodlamadan mkv'ye ekler (varsayılan iz),
  orijinal Geri Dönüşüm Kutusu'na. Toplu yeniden adlandırma `window.apply_renames` (açık dosya, konum kayıtları dahil).
- **Linkten indir (ytdl.py, ytdl_dialog.py; varsayılan kapalı, `yt_enabled`):** yt-dlp kuruluma gömülmez, ilk
  kullanımda GitHub'dan `%LOCALAPPDATA%\kamug\tools\yt-dlp.exe` olarak indirilir, günde bir kez `-U`. İndirme QProcess ile;
  `--progress-template` "kamug-progress ..." ve `--print after_move:kamug-file ...` satırları okunur, bitince
  `open_paths`. Tetikleyiciler: ana sayfadaki "Linkten aç", Ctrl+V (panoda YouTube linki varsa; yoksa eski V davranışı),
  pencereye link sürükleme, başlık çubuğundaki indir düğmesi (`download`, yalnızca yt_enabled açıkken görünür).
  **Fotoğraflar:** yt-dlp video bulamazsa (`photo_candidate`) ya da link doğrudan fotoğrafsa (`photo_first`: TikTok
  /photo/, Pinterest, Reddit galerisi/i.redd.it, Imgur…) gallery-dl (`tools\gallery-dl.exe`, ilk gerekince iner,
  günde bir `--update`) gönderideki tüm dosyaları indirir; yollar `output.mode=pipe` satırlarından, olmazsa klasör
  taramasıyla. Gerçek sitelerle denenmedi (araç indirip çalıştırmak bu oturumda izinli değildi). Basılı tutunca hızlanma: `hold_rate` (1.5–4x), `hold_area` (anywhere | right).
- **Transkript ve OCR (transcript.py, screen_text.py, transcript_panel.py, yazit_export.py; varsayılan kapalı,
  `transcript_enabled`):** bilgi çubuğunda "Transkript" düğmesi → sağ panelde (`self.right`, `_tr_panel`) sekmeler
  Konuşma | Ekrandaki yazılar, satıra tıklayınca o ana gider, `_tick` → `set_time`. Konuşma: whisper.cpp **b5907 CPU**
  (sabit sürüm) + model (`tr_model` fast/balanced/best) + silero VAD, ilk kullanımda `%LOCALAPPDATA%\kamug\tools\whisper`
  ve `models` içine iner (kuruluma gömülmez). Canlı satırlar stdout'tan (`parse_live`), sonuç `-oj` JSON. "Mevcut
  altyazıyı kullan" yandaki .srt/.vtt ya da gömülü izden. OCR: ffmpeg 1 fps 160x90 gri kare, değişen piksel oranı
  (`pick_moments`; ortalama fark küçük yazı değişimini kaçırıyordu), kare +0,5 sn'den alınır (geçiş karesi olmasın),
  Windows.Media.Ocr tek PowerShell sürecinde, `dedupe`. Bölge seçimi `RegionDialog`. Sonuçlar içerik anahtarıyla
  (`file_key`) `%LOCALAPPDATA%\kamug\transcripts\<key>.json` (+ kare klasörü). İşler `SpeechJob`/`OcrJob` (QThread),
  panel kapansa da sürer. yazıt notu (`yazit_export.py`): `build_note` (yazılar önceden `\n` ile bölünür, görsel z = -3e6 + sıra),
  paragraflarda `"ln": {"kamug": yol, "t": sn}`; yazıt'ın not klasörü/`kamug` altına `.yazit` olarak kaydedilip `yazit.exe`
  ile açılır (not klasörü yazıt tercihlerindeki `notes_dir`, yoksa Resimler\yazit).
  **`--at=SANİYE`:** `app._parse_at`; çalışan örneğe `\x01at=ms` satırı gider; `open_paths(paths, start_ms)` aynı dosya
  açıksa yalnızca o ana atlar. yazıt tarafı `kamuglink.py` (Ctrl+tık / sağ tık "kamug'da aç").
  **Aşama 5:** İngilizce çeviri = whisper `-tr`, depoda `speech_en` sekmesi ("Çeviri (EN)" çipi yalnızca varsa);
  large-v3-turbo çeviri yapamadığı için "best" seçiliyse çeviride "balanced" kullanılır. Konuşmacı ayırma
  `speakers.py` (numpy MFCC ort+sapma, ≤2 sn parçalar, küresel k-ortalama, otomatikte siluet ≥ 0,4; tek ses 0,27–0,36,
  iki ses 0,69 ölçüldü), satırlara `spk`; panelde ad konuşmacı değişince, TXT/yazıt paragrafları "Konuşmacı N:".
  Ekran kartı: `tr_gpu` (yalnızca `has_nvidia()`), CUDA 12.4 zipinin tamamı inmez: `_HttpFile` Range istekleriyle
  yalnızca gereken DLL'ler `tools\whisper-gpu`'ya (~680 MB indirme, 1,2 GB disk); CPU sürümü yedek olarak hep iner,
  GPU çalışmazsa `SpeechJob.reset` + işlemciyle tekrar. Tesseract eklenmedi: yalnızca yönetici izni isteyen kurulum
  dosyası var, Windows OCR yeterli bulundu.
  **Sayfa gruplama:** `screen_text.group_pages` — tahtaya yazıldıkça aynı sayfa defalarca yakalanmasın: eski "mürekkebin"
  (ortancadan >40 fark) ≥%85'i yeni karede varsa aynı sayfa, kayıt güncellenir (son 8 sayfaya bakar; geri dönüş de olur).
  **Gelişmiş okuma (`vlm_ocr.py`, `ocr_engine` = windows | vlm, varsayılan windows):** llama.cpp **b12606 Vulkan**
  (`llama-mtmd-cli.exe` + gerekli DLL'ler, `tools\llama`) + **Qwen3-VL-4B** Q4_K_M + mmproj Q8 (`models\`, ~2,9 GB toplam),
  ilk kullanımda onayla iner. El yazısı/Türkçe/formül ($LaTeX$) okur. **`-ngl` VERME** (4 GB RTX 3050 Ti'de 99 çöküyor,
  otomatik yerleştirme çalışıyor); `--temp 0 --repeat-penalty 1.1 -c 8192`. İstem katı: "soruları çözme, tamamlama"
  (yoksa model çözüm uyduruyor). 2B model satır atlıyordu. `clean()` kod çiti / tabular / tekrar döngüsünü temizler.
  Kayıtta LaTeX kalır (yazıt, TXT, kopyala); panelde `RowModel.math` → `to_display` (σ, ≤, (a)/(b), x²).
  `data["ocr"]["engine"]` hangi yolla okunduğunu tutar. Panelde boş durumda ve ••• menüsünde diğer yol düğmesi.
- **Kenar okları (‹ ›):** videoda/seste overlay kendisi çizer (`paint_arrow`, tıklama `_arrow_at`); görselde
  `ImageViewer`'ın alt widget'ları (`EdgeArrow`), saydamlık `overlay.controls_opacity` sinyalini izler. 3D'de yok
  (GL penceresi üstünde Qt widget'ı görünmez). Tercih `edge_arrows` (varsayılan açık). İleri/geri artık türe
  bakmaz: karışık klasörde listedeki sıradaki medyaya geçer (slayt gösterisi ve otomatik oynatma kendi türünde kalır).
- **Dosya türü kaydının onarımı:** `.jpg` vb. UserChoice'u `gamma.image`'a bağlıyken ProgID anahtarı silinirse Windows
  her MOTW dosyada güvenlik uyarısı sorar. Kurulu exe açılışta `shell.repair_file_types()` ile eksikleri yazar.
  **Dikkat:** buradaki python (Python install manager, WindowsApps) MSIX paketi; `winreg` ile HKCU\Software\Classes'a
  yazdıkları sanal kayıt defterine gider, gerçek kayıt için `reg`/PowerShell kullan.
- **3MF okuma hızı:** `<mesh>` blokları ElementTree'ye verilmez (`_cut_meshes`); köşe/üçgenler tırnak içi
  değerlerden numpy ile okunur (`_quoted_cols`), Bambu'nun `paint_color` gibi öznitelikleri önce atılır, olmazsa
  düzenli ifade yoluna düşülür. Kullanıcı gömülü 3MF önizleme resmini istemedi (kendi çizimimiz kalsın).
- **3D küçük resim sınırları:** `model_thumb_count` (açık dosyaya en yakın N model, listede görünen sıraya göre,
  varsayılan 20) ve `model_thumb_mb` (varsayılan 20 MB). Sınır dışı model önbelleğe "resim yok" yazılmadan simgeyle
  gösterilir; açılınca yüklü modelden çizilir (`store_model_thumb`). Model küçük resimleri `_MODEL_LOCK` ile tek tek.
- **STEP / IGES (isteğe bağlı):** motor gmsh (OpenCASCADE içinde, tek ~85 MB DLL). Exe'ye gömülmez
  (`kamug.spec` EXCLUDES "gmsh"); build.ps1 `gmsh.py` + DLL'i `build\dist\kamug\step\` içine kopyalar, kurulumda
  "step" görevi (Ek bileşenler, varsayılan tikli) seçilmezse klasör kurulmaz/silinir ve CAD uzantıları kaydedilmez.
  `model_io.load_cad`: `occ.importShapes` + `mesh.importStl()` (hızlı BRepMesh; `generate` çok yavaş), renk yüzey →
  hacim sırasıyla, hacim/alan `occ.getMass` ile kesin (üçgenler kapalı değil). gmsh iş parçacığı güvenli değil →
  kilit; Türkçe/Unicode yolu açamaz → geçici ASCII kopya; tek girişlik önbellek her çağrıda yeni Part döndürür
  (Z-yukarı çevirisi iki kez uygulanmasın). gmsh yoksa `ModelError("cad_missing")`. Gezgin küçük resmi yok.
- **Gezgin küçük resimleri (STL/OBJ/PLY/OFF/GLB/glTF):** `packaging/thumbnail/KamugThumbs.cs` — .NET Framework 4
  COM sunucusu, build.ps1 Windows'taki `csc.exe` ile derler (`/r:System.Drawing.dll`, doku çözmek için).
  İki sınıf: `Provider` (IInitializeWithStream; .stl .obj .ply .off .glb) ve `FileProvider` (IInitializeWithFile,
  CLSID {437a1563…}; .gltf — harici .bin/doku yan klasörden okunur). Biçim içerikten tanınır. GLB/glTF'de
  malzeme rengi + PNG/JPEG doku (512 px'e küçültülür), PLY/OFF'ta renkler çizilir; Draco/meshopt atlanır.
  Kurulum, regasm olmadan HKCU CLSID (mscoree.dll + CodeBase) ve `SystemFileAssociations\.<uzantı>\ShellEx\{e357fccd…}` yazar.
- **Kurulum görünümü:** Inno Setup **6.7+ gerekir** (`WizardStyle=modern dynamic windows11 hidebevels`, Windows'un
  açık/koyu temasını izler; arka plan #ffffff / #0f0f0f). Sihirbaz görselleri (Γ logosu, açık/koyu, %100-%200 DPI)
  `make_meta.py` → `build\wizard\` içinde üretilir, yolları `version.iss`'te `WizSmall`/`WizLarge` tanımları.
  Lisans sayfası kaldırıldı (GPL onay istemez; LICENSE.txt yine kurulur).
- **Kurulumdaki "Dosya türleri" sayfası:** installer.iss [Code] içinde TNewCheckListBox (gruplar + tek tek uzantılar,
  hepsi tikli). Liste `make_meta.py` → `extensions_code.iss`; kayıtlar `Check: AssocSel('.mp4')`. Güncellemede
  yalnızca kaldırılan tikler `AssocOff` olarak saklanır (yeni türler tikli gelir).
  Köşedeki uygulama simgesini Gezgin kendisi ekler (varsayılan uygulamanın simgesi). 3MF'nin kendi gömülü
  önizlemesi var, ona dokunulmuyor. C# 5 sözdizimi kullan (csc 4.x eski).
  `DisableProcessIsolation=1` şart: yalıtılmış önizleme işlemi (dllhost) HKCU COM kayıtlarını görmüyor
  (REGDB_E_CLASSNOTREG). Bu yüzden DLL Gezgin'in içinde çalışır; 200 MB üstü dosyalar atlanır, bellek idareli
  kullanılır. Gezgin DLL'i kilitler, yeniden derlemede dosya meşgul olabilir. Kurulum bu yüzden
  `CloseApplicationsFilter=*.exe` kullanır (yoksa Gezgin'i kapatmayı öneriyor, kapatınca masaüstü gidiyor) ve
  ssInstall'da kilitli DLL'in adını `KamugThumbs.dll.N.old` yapıp yenisini yazar (`MoveAsideThumbDll`). Kullanıcının bilgisayarında
  test için `build\thumbnail\KamugThumbs.dll` HKCU'ya kayıtlı (2026-11-12); kurulum bunu kurulum klasörüne çevirir.

### Kod yazım alışkanlıkları
- Yorumlar ve docstring'ler **Türkçe**. Kullanıcıya görünen her metin `i18n.py`'de `(tr, en)` çifti olarak
  eklenir ve `t("anahtar")` ile kullanılır; düz metin yazma.
- Yeni tercih: `config.DEFAULTS` (veya kişiselleştirme ise `layout_prefs`) + Tercihler arayüzü + i18n.
- Yeni düğme: kişiselleştirme listesine ekle ki kullanıcı gizleyip taşıyabilsin.
- Python yama betiği yazarken heredoc içindeki `"\n"` / `"\\"` kaçışlarına dikkat: daha önce dosyalara gerçek
  satır sonu ve bozuk karakter girdi. Çok satırlı değişikliklerde Edit aracını tercih et.

---

## 5. Test

```powershell
python tests/smoke_test.py            # çekirdek + gerçek arayüz (pencere ekran dışında, ses yok), ~25 sn
python tests/smoke_test.py --show     # pencereyi görerek
python tests/smoke_test.py --no-gui   # yalnızca çekirdek
python tests/smoke_test.py --shots <klasör>   # geliştirici konsolunun ekran görüntüsü (console.png)
```

- **Kullanıcıyı rahatsız etme:** kullanıcı aynı bilgisayarda çalışıyor. Arayüz testi ekranda pencere açmamalı ve ses
  çalmamalı: `KAMUG_SILENT=1` (VLC `--aout=dummy`) ve pencere ekran dışında/odak çalmadan. Kendi sürücü betiklerinde de
  aynısını yap; testi gereksiz yere tekrar tekrar koşturma.
- Test **gerçek tercihlere dokunmaz**: `LOCALAPPDATA` geçici klasöre yönlendirilir; medyayı ffmpeg ile üretir.
- Kendi test/sürücü betiklerinde de **mutlaka** `os.environ["LOCALAPPDATA"]` değerini geçici bir klasöre
  ayarla. Bir kez test betiği gerçek tercihlere `single_instance=False` yazmıştı.
- Görsel doğrulama için `widget.grab()` veya VLC anlık görüntüsü kullan. **Ekranın bir bölgesini yakalama**:
  kullanıcının diğer pencereleri (tarayıcı vb.) görüntüye girdi. Yanlışlıkla girerse dosyayı sil ve içeriğini anlatma.
- **VLC:** VLC şu an bilgisayarda kurulu. Kullanıcı, kamug'u bir süre kullanıp sorunlar giderildikten sonra
  kaldırmayı düşünüyor. Kaynaktan çalıştırma, testler ve yerel derleme `C:\Program Files\VideoLAN\VLC`
  gerektirir. Kaldırılmışsa önce
  `winget install VideoLAN.VLC` ile kur (kurulu kamug'un kendi gömülü VLC'si var, ona dokunma).
- Lint: `python -m pyflakes kamug` temiz olmalı.
- Yeni özellik eklenince `tests/smoke_test.py`'ye bir adım eklemek iyi olur.

---

## 6. Derleme ve sürüm yayınlama

**Yerel derleme** (yalnızca kullanıcı isteyince):
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\build.ps1
```
Çıktı: `build\installer\kamug-setup-<sürüm>.exe` ve `kamug-portable-<sürüm>.zip`.
Inno Setup kullanıcı başına kurulu: `%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe`.

**Yeni sürüm yayınlama** (kullanıcı "yayınla" deyince):
1. Değişikliği yap, `python tests/smoke_test.py` geçsin.
2. `kamug/__init__.py` içinde sürümü artır (hata düzeltmesi 2.0.1, yeni özellik 2.1.0).
3. Commit → `git push` → `git tag vX.Y.Z` → `git push origin vX.Y.Z`.
4. GitHub Actions (~5 dk) kurulumu derleyip Releases'a ekler. Durum, kimlik doğrulamasız API ile izlenebilir:
   `https://api.github.com/repos/yigitozsoy/kamug_oynatici/actions/runs?per_page=1`
   (`gh` CLI kurulu değil.)

Kurulum programı aynı AppId ile **üstüne kurar**, ayarlar (`%LOCALAPPDATA%\kamug`) korunur. Uygulamada
otomatik güncelleme yok; kullanıcılar yeni kurulumu indirir.

Kurulum `PrivilegesRequired=lowest` (yönetici izni yok); "Birlikte aç" / Varsayılan uygulamalar kaydı
(RegisteredApplications/Capabilities) ve isteğe bağlı "Open with kamug" sağ tık menüsü ekler.
Windows programın kendini varsayılan yapmasına izin vermez; kullanıcı Ayarlar › Varsayılan uygulamalar'dan seçer.
Exe imzasız, bu yüzden SmartScreen "Yine de çalıştır" uyarısı normal.
ProgID'lerde `EditFlags=0x10000` (FTA_OpenIsSafe) var: yoksa internetten inen (MOTW) dosyaları açarken Windows
"Güvenlik uyarısı - Bilinmeyen yayımcı" sorar. Bu uyarının imzayla ilgisi yok (jpg imzalanamaz).

---

## 7. Açık işler / fikirler

- `build.yml` içindeki actions sürümleri Node.js 20 uyarısı veriyor (checkout, setup-python, upload-artifact,
  action-gh-release). Yeni (Node 24) sürümlerine yükselt.
- Kurulum dosyası adını sürümsüz yapmak (`kamug-setup.exe`) → web sitesindeki
  `releases/latest/download/...` linki hiç değişmez. Kullanıcıya önerildi, karar verilmedi.
- Uygulama içi "yeni sürüm var" bildirimi (GitHub Releases API) — önerildi, yapılmadı.
- `docs/` ekran görüntüleri eski arayüzden (eski logo, ⚙ tercih simgesi); güncellenebilir.
