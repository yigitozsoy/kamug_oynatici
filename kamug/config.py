"""Uygulama yolları, kalıcı tercihler ve kaldığın yerden devam kayıtları."""
import json
import os
import sys
import threading

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
    RES_DIR = getattr(sys, "_MEIPASS", BASE_DIR)
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    RES_DIR = BASE_DIR

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

_LOCAL = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
DATA_DIR = os.path.join(_LOCAL, "kamug")
OLD_DATA_DIR = os.path.join(_LOCAL, "gamma")       # 3.0.x ve öncesinin veri klasörü (ilk açılışta taşınır)
if not os.path.isdir(DATA_DIR) and os.path.isfile(os.path.join(OLD_DATA_DIR, "preferences.json")):
    # Tercihler, konum kayıtları, transkriptler, indirilmiş modeller bir kez taşınır (aynı disk: anında)
    try:
        os.rename(OLD_DATA_DIR, DATA_DIR)
    except OSError:                                # eski sürüm açıksa vb.: bu açılışta eski klasör kullanılır
        DATA_DIR = OLD_DATA_DIR
CACHE_DIR = os.path.join(DATA_DIR, "cache")
THUMB_DIR = os.path.join(CACHE_DIR, "thumbs")
PREFS_FILE = os.path.join(DATA_DIR, "preferences.json")
POSITIONS_FILE = os.path.join(DATA_DIR, "positions.json")
SYNC_FILE = os.path.join(DATA_DIR, "media_sync.json")

for _d in (DATA_DIR, CACHE_DIR, THUMB_DIR):
    os.makedirs(_d, exist_ok=True)


def asset(name: str) -> str:
    return os.path.join(ASSETS_DIR, name)


DEFAULTS = {
    "language": "tr",
    "theme": "dark",            # dark | light
    "volume": 100,
    "muted": False,
    "autoplay": True,
    "loop": "off",              # off | all | one
    "shuffle": False,
    "resume": True,
    "pinned": False,
    "pip_enabled": True,        # Mini oynatıcı (PiP) özelliği açık mı
    "pin_enabled": True,        # Sabitleme özelliği açık mı
    "sidebar_visible": True,
    "theater": False,
    "sort": "explorer",         # explorer | name | name_desc | date | date_asc | size | size_asc | type
    "filter": "all",            # all | video | audio | image
    "slideshow_seconds": 4,
    "hw_decode": True,
    "single_instance": True,
    "background_ready": False,  # Windows açılışında gizli başla, kapatınca gizlen (background.py)
    "sub_size": 100,            # %
    "sub_color": "#ffffff",
    "sub_bg": 0,                # 0..255 arka plan opaklığı
    "sub_outline": 4,           # 0, 2, 4, 6
    "sub_bold": False,
    "sub_margin": 24,
    "sub_encoding": "auto",
    "sub_font": "Segoe UI Semibold",
    "recent": [],
    "window_geometry": None,
    "snapshot_dir": "",
    "accent": "gray",
    "show_search": False,
    "show_open_buttons": False,
    "show_quick_buttons": False,
    "series_suggest": True,     # dağınık adlı dizi açılınca bildirim
    "series_subs": True,        # sezon-bölüm numarasıyla eşleşen altyazıyı otomatik aç
    "intro_auto": True,         # bölüm açılınca introyu arka planda ara
    "series_name_format": "dash",
    "yt_enabled": False,        # YouTube linkinden indir (varsayılan kapalı)
    "yt_quality": "best",
    "yt_folder": "",
    "yt_subs": True,            # altyazıları da indir
    "yt_content": "both",       # both | video (sessiz) | audio
    "yt_parallel": 1,           # oynatma listesi: 1 = sırayla, 3 = aynı anda
    "yt_link_action": "ask",    # Ctrl+V / sürüklenen link: ask (indirme penceresi) | stream (indirmeden izle)
    "yt_stream_quality": "1080",  # indirmeden izlerken en yüksek çözünürlük
    "transcript_enabled": False,  # Transkript paneli (konuşma + ekrandaki yazılar)
    "tr_model": "balanced",     # fast | balanced | best (whisper.cpp modeli)
    "tr_lang": "auto",          # auto | tr | en
    "tr_gpu": False,
    "ocr_engine": "windows",    # windows (hızlı) | vlm (gelişmiş okuma: el yazısı + formüller, ~2,9 GB iner)            # NVIDIA ekran kartıyla hızlandır (CUDA sürümü ayrıca iner)
    "yt_cookies": "",           # "" | tarayıcı adı | cookies.txt yolu
    "dev_mode": False,          # Shift+" ile açılır; açıkken " geliştirici konsolunu açar (console.py)
    "console_history": [],
}


class _JsonStore:
    def __init__(self, path, defaults=None):
        self.path = path
        self.data = dict(defaults or {})
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self.data.update(loaded)
        except (OSError, ValueError):
            pass

    def save(self):
        with self._lock:
            tmp = self.path + ".tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=1)
                os.replace(tmp, self.path)
            except OSError:
                pass


class Prefs(_JsonStore):
    def __init__(self):
        super().__init__(PREFS_FILE, DEFAULTS)

    def get(self, key, default=None):
        if key in self.data:
            return self.data[key]
        return DEFAULTS.get(key, default)

    def set(self, key, value):
        if self.data.get(key) == value:
            return
        self.data[key] = value
        self.save()

    def add_recent(self, path: str):
        rec = [p for p in self.get("recent", []) if os.path.normcase(p) != os.path.normcase(path)]
        rec.insert(0, path)
        self.set("recent", rec[:12])


class PositionStore(_JsonStore):
    """Uzun videolarda kaldığın yerden devam (YouTube gibi)."""
    MAX = 400

    def __init__(self):
        super().__init__(POSITIONS_FILE)

    def get(self, path):
        return self.data.get(os.path.normcase(path))

    def set(self, path, ms, length):
        key = os.path.normcase(path)
        if length <= 0 or length < 120_000 or ms < 15_000 or ms > length - 20_000:
            if key in self.data:
                del self.data[key]
                self.save()
            return
        self.data.pop(key, None)
        self.data[key] = int(ms)
        if len(self.data) > self.MAX:
            for k in list(self.data.keys())[: len(self.data) - self.MAX]:
                del self.data[k]
        self.save()


class SyncStore(_JsonStore):
    """Dosyaya özel ses/altyazı gecikmesi."""

    def __init__(self):
        super().__init__(SYNC_FILE)

    def get(self, path):
        return self.data.get(os.path.normcase(path))

    def set(self, path, audio_ms, sub_ms):
        self.data[os.path.normcase(path)] = {"audio_delay": int(audio_ms), "sub_delay": int(sub_ms)}
        self.save()


prefs = Prefs()
positions = PositionStore()
sync_store = SyncStore()
