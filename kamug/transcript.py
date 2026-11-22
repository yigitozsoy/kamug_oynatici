"""Transkript (konuşmayı metne dökme) ve sonuç deposu.

Motor: whisper.cpp (MIT, işlemcide çalışır). Program ve model kuruluma gömülmez: ilk kullanımda
%LOCALAPPDATA%\\kamug\\tools\\whisper ve ...\\models içine bir kez iner. Ses ffmpeg ile 16 kHz mono WAV'a çevrilir.
Sonuçlar video dosyasının içeriğinden üretilen anahtarla %LOCALAPPDATA%\\kamug\\transcripts içinde saklanır
(dosya adı değişse de bulunur); ekrandaki yazıların (OCR) kare görselleri de yanındaki klasörde."""
import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.request
import zipfile

from .config import DATA_DIR, prefs
from .i18n import t

TOOL_DIR = os.path.join(DATA_DIR, "tools", "whisper")
GPU_DIR = os.path.join(DATA_DIR, "tools", "whisper-gpu")
MODEL_DIR = os.path.join(DATA_DIR, "models")
STORE_DIR = os.path.join(DATA_DIR, "transcripts")

# Denenmiş sürüm sabitlenir (çıktı biçimi değişmesin). Yalnızca gereken dosyalar zipten çıkarılır.
WHISPER_URL = "https://github.com/ggml-org/whisper.cpp/releases/download/b5907/whisper-bin-x64.zip"
WHISPER_SIZE_MB = 9
# NVIDIA ekran kartı sürümü (isteğe bağlı): zip ~700 MB; uzaktan zipin içinden yalnızca gereken dosyalar alınır
GPU_URL = "https://github.com/ggml-org/whisper.cpp/releases/download/b5907/whisper-bin-win-cuda-12.4.0-x64.zip"
GPU_SIZE_MB = 680
_GPU_KEEP = re.compile(r"(whisper-cli\.exe|whisper\.dll|ggml[\w-]*\.dll|cublas64_12\.dll|cublasLt64_12\.dll|"
                       r"cudart64_12\.dll)$", re.I)
_HF = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
MODELS = {   # anahtar: (dosya, yaklaşık MB)
    "fast": ("ggml-base-q5_1.bin", 60),
    "balanced": ("ggml-small-q5_1.bin", 182),
    "best": ("ggml-large-v3-turbo-q5_0.bin", 548),
}
VAD_URL = "https://huggingface.co/ggml-org/whisper-vad/resolve/main/ggml-silero-v5.1.2.bin"
VAD_FILE = "ggml-silero-v5.1.2.bin"
LANGS = ["auto", "tr", "en"]
PARTS = ("speech", "speech_en", "ocr")      # depodaki sekmeler
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ------------------------------------------------------------------ araç / model
def whisper_exe(gpu=None):
    if gpu is None:
        gpu = use_gpu()
    return os.path.join(GPU_DIR if gpu else TOOL_DIR, "whisper-cli.exe")


def gpu_installed():
    return all(os.path.isfile(os.path.join(GPU_DIR, n)) for n in
               ("whisper-cli.exe", "ggml-cuda.dll", "cublasLt64_12.dll", "cudart64_12.dll"))


def use_gpu():
    return bool(prefs.get("tr_gpu", False)) and gpu_installed()


_NVIDIA = None


def has_nvidia():
    """NVIDIA ekran kartı (ve sürücüsü) var mı? (nvidia-smi sürücüyle birlikte gelir)"""
    global _NVIDIA
    if _NVIDIA is None:
        exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvidia-smi.exe")
        try:
            r = subprocess.run([exe, "-L"], capture_output=True, timeout=10, creationflags=NO_WINDOW)
            _NVIDIA = r.returncode == 0 and b"GPU" in r.stdout
        except (OSError, subprocess.TimeoutExpired):
            _NVIDIA = False
    return _NVIDIA


def model_key():
    k = prefs.get("tr_model", "balanced")
    return k if k in MODELS else "balanced"


def model_path(key=None):
    return os.path.join(MODEL_DIR, MODELS[key or model_key()][0])


def vad_path():
    return os.path.join(MODEL_DIR, VAD_FILE)


def missing_downloads(key=None):
    """İndirilmesi gerekenler: [(ad, url, hedef, yaklaşık MB, zip mi)]."""
    out = []
    if not os.path.isfile(whisper_exe()):
        out.append(("whisper.cpp", WHISPER_URL, os.path.join(TOOL_DIR, "whisper.zip"), WHISPER_SIZE_MB, True))
    mp = model_path(key)
    if not os.path.isfile(mp):
        out.append((MODELS[key or model_key()][0], _HF + MODELS[key or model_key()][0], mp,
                    MODELS[key or model_key()][1], False))
    if not os.path.isfile(vad_path()):
        out.append((VAD_FILE, VAD_URL, vad_path(), 1, False))
    if prefs.get("tr_gpu", False) and not gpu_installed():
        out.append(("whisper.cpp (NVIDIA)", GPU_URL, GPU_DIR, GPU_SIZE_MB, "remote-zip"))
    return out


class _HttpFile:
    """Uzaktaki dosyayı (Range istekleriyle) okunabilir/aranabilir dosya gibi gösterir: zipin tamamı inmez."""

    def __init__(self, url):
        r = urllib.request.urlopen(urllib.request.Request(url, method="HEAD",
                                                          headers={"User-Agent": "kamug"}), timeout=30)
        self.orig, self.url, self.size, self.pos = url, r.url, int(r.headers["Content-Length"]), 0

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.pos
        if n == 0 or self.pos >= self.size:
            return b""
        end = min(self.size, self.pos + n) - 1
        import time
        for k in range(6):
            try:
                req = urllib.request.Request(self.url, headers={"Range": f"bytes={self.pos}-{end}",
                                                                "User-Agent": "kamug"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    d = r.read()
                self.pos += len(d)
                return d
            except Exception:
                if k == 5:
                    raise
                time.sleep(2 + 3 * k)
                if k == 2:      # imzalı indirme adresinin süresi dolmuş olabilir: yeniden çöz
                    self.url = urllib.request.urlopen(urllib.request.Request(
                        self.orig, method="HEAD", headers={"User-Agent": "kamug"}), timeout=30).url


def install_remote_zip(url, dest_dir, keep, progress=None, cancelled=lambda: False):
    """Uzaktaki zipten yalnızca keep'e uyan dosyaları dest_dir'e çıkarır (önce .part klasörüne)."""
    tmp = dest_dir + ".part"
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    z = zipfile.ZipFile(_HttpFile(url))
    items = [i for i in z.infolist() if keep.match(os.path.basename(i.filename))]
    total = sum(i.file_size for i in items) or 1
    got = 0
    for i in items:
        with z.open(i) as src, open(os.path.join(tmp, os.path.basename(i.filename)), "wb") as dst:
            while True:
                if cancelled():
                    raise InterruptedError
                chunk = src.read(1 << 20)
                if not chunk:
                    break
                dst.write(chunk)
                got += len(chunk)
                if progress:
                    progress(got, total)
    shutil.rmtree(dest_dir, ignore_errors=True)
    os.replace(tmp, dest_dir)


def fetch(url, dest, progress=None, cancelled=lambda: False):
    """url → dest (önce .part'a). progress(indirilen, toplam). İptalde InterruptedError."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": "kamug"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            got = 0
            while True:
                if cancelled():
                    raise InterruptedError
                chunk = r.read(512 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if progress:
                    progress(got, total)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def install_whisper_zip(zpath):
    """Zipten yalnızca whisper-cli ve DLL'lerini TOOL_DIR'e çıkarır, zipi siler."""
    keep = re.compile(r"(whisper-cli\.exe|whisper\.dll|ggml[\w-]*\.dll)$", re.I)
    with zipfile.ZipFile(zpath) as z:
        for n in z.namelist():
            base = os.path.basename(n)
            if keep.match(base):
                with z.open(n) as src, open(os.path.join(TOOL_DIR, base), "wb") as dst:
                    dst.write(src.read())
    os.remove(zpath)
    if not os.path.isfile(whisper_exe()):
        raise OSError("whisper-cli.exe")


def download_all(key=None, progress=None, cancelled=lambda: False):
    """Eksik program / modelleri indirir. progress(ad, indirilen, toplam)."""
    for name, url, dest, _mb, is_zip in missing_downloads(key):
        prog = (lambda a, b, n=name: progress(n, a, b)) if progress else None
        if is_zip == "remote-zip":
            install_remote_zip(url, dest, _GPU_KEEP, prog, cancelled)
            continue
        fetch(url, dest, prog, cancelled)
        if is_zip:
            install_whisper_zip(dest)


# ------------------------------------------------------------------ komutlar
def threads():
    return max(2, min(8, (os.cpu_count() or 4) // 2))


def audio_command(ffmpeg, video, wav):
    return [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", video, "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "pcm_s16le", wav]


def whisper_command(wav, out_base, lang=None, key=None, translate=False, gpu=None):
    """translate: konuşmayı İngilizceye çevirerek yazar (whisper'ın kendi çevirisi; yalnızca İngilizceye)."""
    lang = lang or prefs.get("tr_lang", "auto")
    gpu = use_gpu() if gpu is None else gpu
    cmd = [whisper_exe(gpu), "-m", model_path(key), "-f", wav, "-l", lang if lang in LANGS else "auto",
           "-t", str(threads()), "-oj", "-of", out_base]
    if translate:
        cmd.append("-tr")
    if not gpu:
        cmd.append("-ng")
    if os.path.isfile(vad_path()):
        # Sessiz / müzikli yerlerde uydurma metin çıkmasın; konuşma olmayan kısımlar atlanır (hız da artar)
        cmd += ["--vad", "-vm", vad_path()]
    return cmd


_LIVE = re.compile(r"^\[(\d+):(\d+):(\d+)[.,](\d+)\s*-->\s*(\d+):(\d+):(\d+)[.,](\d+)\]\s*(.*)$")


def parse_live(line):
    """whisper-cli'nin canlı çıktısı "[00:00:01.000 --> 00:00:05.460]  metin" → (başlangıç ms, bitiş ms, metin)."""
    m = _LIVE.match(line.strip())
    if not m:
        return None
    g = [int(x) for x in m.groups()[:8]]
    a = ((g[0] * 60 + g[1]) * 60 + g[2]) * 1000 + int(str(g[3]).ljust(3, "0")[:3])
    b = ((g[4] * 60 + g[5]) * 60 + g[6]) * 1000 + int(str(g[7]).ljust(3, "0")[:3])
    return a, b, m.group(9).strip()


def read_whisper_json(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        d = json.load(f)
    segs = []
    for s in d.get("transcription", []):
        txt = (s.get("text") or "").strip()
        if not txt or _is_noise(txt):
            continue
        o = s.get("offsets") or {}
        segs.append({"s": int(o.get("from", 0)), "e": int(o.get("to", 0)), "t": txt})
    return segs, (d.get("result") or {}).get("language")


def _is_noise(txt):
    """[MÜZİK], (alkış), ♪ … gibi konuşma olmayan etiketler."""
    t = txt.strip()
    return bool(re.fullmatch(r"[\[\(（【♪♫*].*[\]\)）】♪♫*]|[♪♫\s.]+", t))


# ------------------------------------------------------------------ altyazıdan transkript
_SRT_TIME = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")
_VTT_TIME = re.compile(r"(?:(\d+):)?(\d+):(\d+)\.(\d+)\s*-->\s*(?:(\d+):)?(\d+):(\d+)\.(\d+)")


def _ms(h, m, s, frac):
    return ((int(h or 0) * 60 + int(m)) * 60 + int(s)) * 1000 + int(str(frac).ljust(3, "0")[:3])


def parse_subtitle_text(text):
    """SRT / VTT metni → segmentler (biçim etiketleri temizlenir, art arda aynı satırlar birleşir)."""
    segs = []
    blocks = re.split(r"\r?\n\s*\r?\n", text.replace("﻿", ""))
    for b in blocks:
        lines = [ln for ln in b.splitlines() if ln.strip()]
        for i, ln in enumerate(lines):
            m = _SRT_TIME.search(ln)
            if m:
                a, e = _ms(*m.groups()[:4]), _ms(*m.groups()[4:])
            else:
                m = _VTT_TIME.search(ln)
                if not m:
                    continue
                g = m.groups()
                a, e = _ms(g[0], g[1], g[2], g[3]), _ms(g[4], g[5], g[6], g[7])
            body = " ".join(lines[i + 1:])
            body = re.sub(r"<[^>]+>|\{[^}]*\}", "", body).replace("\\N", " ").strip()
            body = re.sub(r"\s+", " ", body)
            if body and not _is_noise(body):
                if segs and segs[-1]["t"] == body:
                    segs[-1]["e"] = e
                else:
                    segs.append({"s": a, "e": e, "t": body})
            break
    return segs


def sidecar_subtitle(video):
    """Videoyla aynı adlı altyazı dosyası (Film.srt, Film.tr.srt, Film.en.vtt …)."""
    d, base = os.path.dirname(video), os.path.splitext(os.path.basename(video))[0].lower()
    try:
        names = os.listdir(d)
    except OSError:
        return None
    cands = [n for n in names if n.lower().startswith(base) and os.path.splitext(n)[1].lower() in (".srt", ".vtt")]
    if not cands:
        return None
    first = "tr" if prefs.get("language", "tr") == "tr" else "en"
    cands.sort(key=lambda n: (f".{first}." not in n.lower(), len(n)))
    return os.path.join(d, cands[0])


def embedded_subtitle_text(ffmpeg, video):
    """Videonun içindeki ilk (metin) altyazı izi SRT olarak; yoksa None."""
    try:
        r = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", video, "-map", "0:s:0", "-f", "srt",
                            "-"], capture_output=True, timeout=120, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0 or not r.stdout.strip():
        return None
    return r.stdout.decode("utf-8", "replace")


def has_subtitle_source(video, has_embedded=False):
    return bool(sidecar_subtitle(video)) or has_embedded


def from_subtitles(ffmpeg, video):
    """Mevcut altyazıdan transkript: önce yandaki dosya, yoksa videonun içindeki iz. (segmentler, kaynak adı)"""
    sp = sidecar_subtitle(video)
    if sp:
        from .series import subtitle_charenc
        enc = subtitle_charenc(sp) or "utf-8"
        try:
            with open(sp, encoding=enc, errors="replace") as f:
                return parse_subtitle_text(f.read()), os.path.basename(sp)
        except (OSError, LookupError):
            pass
    txt = embedded_subtitle_text(ffmpeg, video)
    if txt:
        return parse_subtitle_text(txt), "embedded"
    return [], None


# ------------------------------------------------------------------ depo
def file_key(path):
    """İçerikten anahtar (boyut + baştan / sondan 1 MB): ad değişse de aynı transkript bulunur."""
    h = hashlib.sha1()
    try:
        size = os.path.getsize(path)
        h.update(str(size).encode())
        with open(path, "rb") as f:
            h.update(f.read(1 << 20))
            if size > 2 << 20:
                f.seek(-(1 << 20), os.SEEK_END)
                h.update(f.read(1 << 20))
    except OSError:
        h.update(os.path.normcase(path).encode("utf-8", "replace"))
    return h.hexdigest()[:20]


def store_path(key):
    return os.path.join(STORE_DIR, key + ".json")


def frames_dir(key):
    return os.path.join(STORE_DIR, key)


def load(key):
    try:
        with open(store_path(key), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save(key, data):
    os.makedirs(STORE_DIR, exist_ok=True)
    tmp = store_path(key) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, store_path(key))


def remove(key, part=None):
    """part: None (hepsi) | "speech" | "speech_en" | "ocr"."""
    d = load(key)
    if part:
        d.pop(part, None)
    if not part or part == "ocr":
        import shutil
        shutil.rmtree(frames_dir(key), ignore_errors=True)
    if part and any(d.get(k) for k in PARTS):
        save(key, d)
    else:
        try:
            os.remove(store_path(key))
        except OSError:
            pass


# ------------------------------------------------------------------ dışa aktarma
def fmt_ts(ms, srt=False):
    ms = max(0, int(ms))
    h, m, s, r = ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000
    if srt:
        return f"{h:02d}:{m:02d}:{s:02d},{r:03d}"
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def to_srt(segs):
    out = []
    for i, s in enumerate(segs, 1):
        out.append(f"{i}\n{fmt_ts(s['s'], True)} --> {fmt_ts(s['e'], True)}\n{s['t']}\n")
    return "\n".join(out)


def speaker_name(n):
    return t("tr_speaker_n", n=n)


def to_txt(segs, stamps=True):
    out, last = [], None
    for s in segs:
        spk = s.get("spk")
        if spk and spk != last:
            if out:
                out.append("")
            out.append(speaker_name(spk) + ":")
            last = spk
        out.append((f"[{fmt_ts(s['s'])}] " if stamps else "") + s["t"])
    return "\n".join(out) + "\n"


def frames_txt(frames, stamps=True):
    """Ekrandaki yazılar → düz metin (gelişmiş okumada formüller $LaTeX$ olarak kalır)."""
    out = []
    for fr in frames:
        txt = (fr.get("t") or "").strip()
        if txt:
            out.append(f"[{fmt_ts(fr.get('s', 0))}]\n{txt}" if stamps else txt)
    return "\n\n".join(out) + ("\n" if out else "")


def paragraphs(segs, max_chars=420, gap_ms=2500):
    """Segmentleri okunur paragraflara toplar: [(başlangıç ms, metin)]. Uzun duraklamada, uzunlukta ya da konuşmacı
    değişince bölünür; konuşmacılar ayrıldıysa paragraf "Konuşmacı N: " ile başlar."""
    out, cur, start, last_end, spk = [], [], None, None, None

    def flush():
        txt = " ".join(cur)
        out.append((start, (speaker_name(spk) + ": " + txt) if spk else txt))
    for s in segs:
        if cur and (s["s"] - (last_end or 0) > gap_ms or sum(len(x) for x in cur) > max_chars
                    or s.get("spk") != spk):
            flush()
            cur, start = [], None
        if start is None:
            start = s["s"]
            spk = s.get("spk")
        cur.append(s["t"])
        last_end = s["e"]
    if cur:
        flush()
    return out


def temp_dir():
    d = os.path.join(tempfile.gettempdir(), "kamug_transcript")
    os.makedirs(d, exist_ok=True)
    return d
