"""YouTube linkinden indirme (yt-dlp). Araç kuruluma gömülmez: ilk kullanımda GitHub'dan
%LOCALAPPDATA%\\kamug\\tools\\yt-dlp.exe olarak indirilir ve günde en fazla bir kez kendini günceller.
Yalnızca kullanıcının hakkına sahip olduğu videolar için (ör. kendi videoları)."""
import os
import re
import time
import urllib.request

from .config import DATA_DIR, prefs

TOOL_DIR = os.path.join(DATA_DIR, "tools")
TOOL_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"

_YT = re.compile(r"(?:https?://)?(?:www\.|m\.|music\.)?(?:youtube\.com/(?:watch\?\S*?v=|shorts/|live/|embed/)"
                 r"|youtu\.be/)[\w-]{6,}\S*", re.I)

_ANY = re.compile(r"https?://[^\s<>\"']+", re.I)

QUALITIES = ["best", "1080", "720", "480"]     # yalnızca ses: içerik seçimi (format_args)
# Oturum (üyelere özel / gizli videolar): tarayıcının çerezleri ya da dışa aktarılmış cookies.txt
BROWSERS = ["firefox", "chrome", "edge", "brave", "opera", "vivaldi"]


def exe_path():
    return os.path.join(TOOL_DIR, "yt-dlp.exe")


def installed():
    p = exe_path()
    return os.path.isfile(p) and os.path.getsize(p) > 1_000_000


def find_url(text):
    """Metindeki ilk link (yoksa None). yt-dlp YouTube dışında binlerce siteyi ve sayfaya gömülü videoları da
    tanır; "youtu.be/..." gibi http'siz YouTube linkleri de kabul edilir."""
    m = _ANY.search(text or "") or _YT.search(text or "")
    if not m:
        return None
    url = m.group(0)
    return url if url.lower().startswith("http") else "https://" + url


def default_folder():
    return prefs.get("yt_folder") or os.path.join(os.path.expanduser("~"), "Videos", "kamug")


def install(progress=None, cancelled=lambda: False):
    """yt-dlp.exe'yi indirir. progress(indirilen, toplam). Hata olursa OSError."""
    os.makedirs(TOOL_DIR, exist_ok=True)
    tmp = exe_path() + ".part"
    req = urllib.request.Request(TOOL_URL, headers={"User-Agent": "kamug"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            got = 0
            while True:
                if cancelled():
                    raise InterruptedError
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if progress:
                    progress(got, total)
        if os.path.getsize(tmp) < 1_000_000:
            raise OSError("yt-dlp.exe")
        os.replace(tmp, exe_path())
        prefs.set("yt_checked", time.time())
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def needs_update_check():
    return time.time() - float(prefs.get("yt_checked", 0) or 0) > 24 * 3600


def update_command():
    return [exe_path(), "-U"]


def mark_checked():
    prefs.set("yt_checked", time.time())


def sub_langs():
    """İndirilecek altyazı dilleri: arayüz dili önce, sonra İngilizce."""
    first = "tr" if prefs.get("language", "tr") == "tr" else "en"
    return [first] + [x for x in ("tr", "en") if x != first]


def is_playlist(url):
    """Linkte oynatma listesi var mı (YouTube list=, /playlist)?"""
    low = (url or "").lower()
    return "list=" in low or "/playlist" in low


def playlist_only(url):
    """Link doğrudan listeyi mi gösteriyor (içinde tek bir video yok)?"""
    low = (url or "").lower()
    return is_playlist(url) and "v=" not in low and "youtu.be/" not in low


def _common(cookies="", impersonate=False):
    cmd = ["--encoding", "utf-8"]
    import shutil
    if not shutil.which("deno") and shutil.which("node"):
        cmd += ["--js-runtimes", "node"]      # YouTube'un JS denetimi için (deno yoksa node kullanılabilir)
    if cookies:
        cmd += ["--cookies", cookies] if cookies.lower().endswith(".txt") else ["--cookies-from-browser", cookies]
    if impersonate:
        # Bot korumalı siteler (Cloudflare 403): istekleri gerçek bir Chrome gibi gönder (yt-dlp'nin kendi önerisi)
        cmd += ["--impersonate", "chrome", "--extractor-args", "generic:impersonate"]
    return cmd


def format_args(quality="best", content="both"):
    """content: both (görüntü + ses) | video (yalnızca görüntü, sessiz) | audio (yalnızca ses, m4a)."""
    if quality == "audio":              # eski tercih
        content = "audio"
    if content == "audio":
        return ["-f", "ba[ext=m4a]/ba"]
    res = "res" if quality in ("best", "audio") else f"res:{quality}"
    if content == "video":
        return ["-f", "bv/bv*", "-S", f"{res},ext:mp4"]
    return ["-f", "bv*+ba/b", "-S", f"{res},ext:mp4:m4a", "--merge-output-format", "mp4"]


def download_command(url, folder, quality="best", ffmpeg=None, subs=True, cookies="", impersonate=False,
                     content="both", name=None):
    """Tek video için yt-dlp komutu. İlerleme satırları "kamug-progress <inen> <toplam> <tahmini> <hız>", dosya
    bitince "kamug-file <yol>". name: uzantısız dosya adı şablonu (listede "003 - %(title)s [%(id)s]")."""
    out = os.path.join(folder, (name or "%(title).150B [%(id)s]") + ".%(ext)s")
    cmd = [exe_path(), "--newline", "--no-playlist", "--no-mtime", "--progress",
           "--progress-template", "download:kamug-progress %(progress.downloaded_bytes)s %(progress.total_bytes)s "
                                  "%(progress.total_bytes_estimate)s %(progress.speed)s",
           "--print", "after_move:kamug-file %(filepath)s",
           "-o", out] + _common(cookies, impersonate)
    if ffmpeg:
        cmd += ["--ffmpeg-location", ffmpeg]
    if subs and content != "audio" and quality != "audio":
        # Elle yazılmış altyazı varsa o, yoksa otomatik; videonun yanına "<ad>.tr.srt" (VLC kendisi açar).
        # Altyazı inemezse video yine insin.
        langs = ",".join(f"{x}.*" for x in sub_langs()) + ",-live_chat"   # tr, tr-TR, en-US ... (sohbet hariç)
        cmd += ["--write-subs", "--write-auto-subs", "--sub-langs", langs, "--convert-subs", "srt",
                "--ignore-errors"]
    cmd += format_args(quality, content)
    if content == "audio" or quality == "audio":
        cmd += ["-x", "--audio-format", "m4a"]
    return cmd + ["--", url]


_INFO = ("kamug-entry %(playlist_index|0)s\t%(id)s\t%(duration|)s\t%(filesize,filesize_approx|)s\t"
         "%(playlist_title|)s\t%(playlist_count|)s\t%(webpage_url,url|)s\t%(title)s")


def info_command(url, flat=False, playlist=False, quality="best", content="both", cookies="", impersonate=False):
    """Bilgi al (indirmeden): her video için bir "kamug-entry" satırı. flat=True: listedeki adlar ve süreler hemen
    (boyut yok); flat=False: her videonun seçilen kalitedeki boyutu da (yavaş, satır satır gelir)."""
    cmd = [exe_path(), "--simulate", "--ignore-errors", "--yes-playlist" if playlist else "--no-playlist",
           "-O", _INFO] + _common(cookies, impersonate)
    if flat:
        cmd += ["--flat-playlist"]
    else:
        cmd += format_args(quality, content)
    return cmd + ["--", url]


def parse_entry(line):
    """"kamug-entry" satırı → {index, id, duration, size, playlist, count, url, title} ya da None."""
    line = line.rstrip("\r\n")
    if not line.startswith("kamug-entry "):
        return None
    parts = (line[len("kamug-entry "):].split("\t") + [""] * 8)[:8]

    def num(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None
    idx, vid, dur, size, pl, count, url, title = parts
    return {"index": int(num(idx) or 0), "id": vid, "duration": num(dur), "size": num(size),
            "playlist": "" if pl in ("NA", "") else pl, "count": int(num(count) or 0),
            "url": "" if url in ("NA", "") else url, "title": title}


def safe_name(text, limit=100):
    """Klasör / dosya adı için Windows'ta geçersiz karakterleri at."""
    out = "".join("_" if c in '<>:"/\\|?*' or ord(c) < 32 else c for c in (text or "")).strip(" .")
    return out[:limit] or "playlist"


def blocked(text):
    """Site bot koruması (ör. Cloudflare) yüzünden mi reddetti?"""
    low = (text or "").lower()
    return "cloudflare" in low or "impersonate" in low or "anti-bot" in low


def parse_line(line):
    """("progress", oran 0-1 | None, hız B/s | None, sıra | None, adet | None) | ("file", yol)
    | ("phase", "merge") | None"""
    line = line.strip()
    if line.startswith("kamug-progress "):
        parts = line.split()[1:]

        def num(s):
            try:
                return float(s)
            except (TypeError, ValueError):
                return None
        got, total, est, speed, idx, n = (num(p) for p in (parts + [None] * 6)[:6])
        total = total or est
        return ("progress", (got / total) if got is not None and total else None, speed,
                int(idx) if idx else None, int(n) if n else None)
    if line.startswith("kamug-file "):
        return ("file", line[len("kamug-file "):].strip())
    if line.startswith("[Merger]") or line.startswith("[ExtractAudio]"):
        return ("phase", "merge")
    return None


def error_hint(text):
    """Bilinen hatalar için i18n anahtarı: oturum gerekiyor / tarayıcı çerezleri okunamadı."""
    low = (text or "").lower()
    if blocked(text):
        return "yt_blocked"
    if any(k in low for k in ("cookie", "dpapi", "decrypt")) and ("could not" in low or "failed" in low):
        return "yt_cookie_failed"
    if any(k in low for k in ("sign in", "members", "private video", "login", "confirm your age")):
        return "yt_need_login"
    return None


def last_error(text):
    """yt-dlp çıktısından okunur hata satırı."""
    errs = [ln.strip() for ln in (text or "").splitlines() if ln.strip().startswith("ERROR")]
    return (errs[-1] if errs else (text or "").strip()[-300:]).replace("ERROR: ", "")
