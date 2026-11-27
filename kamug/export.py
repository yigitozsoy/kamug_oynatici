"""kamug-export: bir YouTube videosunu (ya da oynatma listesini) pencere açmadan tek klasöre dışa aktarır.

    kamug-export <link> --out <klasör> [--lang tr] [--whisper] [--no-auto-subs] [--ocr windows|vlm] ...

Çıktı (tek video; listede her video kendi alt klasöründe, en üstte listenin meta.json'u):
    meta.json         başlık, kanal, yayın tarihi, süre (+ transkriptin ve karelerin kaynağı)
    transcript.txt    [SS:DD:SS.mmm --> SS:DD:SS.mmm] metin
                      kaynak sırası: elle yazılmış altyazı → YouTube'un otomatik altyazısı (orijinal dil)
                      → yerel Whisper (whisper.cpp; araç ve model ilk kullanımda iner)
    frames/0001_00m12s.png   yalnızca görüntünün değişip durulduğu anlardaki benzersiz kareler
    ocr.json          [{zaman, saniye, dosya, metin}] (Windows OCR ya da --ocr vlm: gelişmiş okuma)

kamug'un uygulama içindeki parçalarını kullanır (ytdl, transcript, screen_text, vlm_ocr); kamug açık olmasa da çalışır.
Çıkış kodu: 0 başarılı, 1 bir ya da daha fazla video aktarılamadı, 2 kullanım hatası.
"""
import argparse
import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

from . import __version__
from . import ytdl
from . import transcript as tr
from .config import prefs
from .i18n import t

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
TMP_NAME = ".kamug-export-tmp"


class ExportError(Exception):
    pass


# ------------------------------------------------------------------ çıktı (stderr; stdout yalnızca sonuç yolu)
_quiet = False


def log(msg):
    if not _quiet:
        print(msg, file=sys.stderr, flush=True)


def _progress(label, ratio):
    if not _quiet and sys.stderr.isatty():
        pct = max(0, min(100, int(ratio * 100)))
        print(f"\r  {label} %{pct:<3d}", end="", file=sys.stderr, flush=True)


def _progress_end():
    if not _quiet and sys.stderr.isatty():
        print("\r" + " " * 60 + "\r", end="", file=sys.stderr, flush=True)


# ------------------------------------------------------------------ yardımcılar
def ts_full(ms):
    """12345 → 00:00:12.345"""
    ms = max(0, int(ms))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d}.{ms % 1000:03d}"


def frame_stamp(sec):
    """Kare dosya adındaki zaman: 00m12s, 1 saatten uzunsa 01h02m03s."""
    s = int(sec)
    h, m, s = s // 3600, s // 60 % 60, s % 60
    return f"{h:02d}h{m:02d}m{s:02d}s" if h else f"{m:02d}m{s:02d}s"


def transcript_text(segs):
    return "".join(f"[{ts_full(s['s'])} --> {ts_full(s['e'])}] {s['t']}\n" for s in segs)


def _iso_date(d):
    """20240501 → 2024-05-01"""
    d = str(d or "")
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if re.fullmatch(r"\d{8}", d) else (d or None)


def build_meta(info):
    dur = info.get("duration")
    return {
        "id": info.get("id"),
        "url": info.get("webpage_url") or info.get("original_url"),
        "title": info.get("title"),
        "channel": info.get("channel") or info.get("uploader"),
        "channel_url": info.get("channel_url") or info.get("uploader_url"),
        "upload_date": _iso_date(info.get("upload_date") or info.get("release_date")),
        "duration": dur,
        "duration_text": tr.fmt_ts(dur * 1000) if dur else None,
        "language": info.get("language"),
    }


def parse_json3(text):
    """YouTube'un json3 altyazısı (otomatik altyazıda temiz: VTT'deki gibi kayan, tekrarlı satırlar yok) → segmentler."""
    try:
        d = json.loads(text)
    except ValueError:
        return []
    segs = []
    for ev in d.get("events") or []:
        if not ev.get("segs"):
            continue
        txt = re.sub(r"\s+", " ", "".join(s.get("utf8", "") for s in ev["segs"])).strip()
        if not txt or tr._is_noise(txt):
            continue
        a = int(ev.get("tStartMs", 0))
        segs.append({"s": a, "e": a + int(ev.get("dDurationMs", 0)), "t": txt})
    for i in range(len(segs) - 1):              # otomatik altyazıda satırlar üst üste biner
        segs[i]["e"] = max(segs[i]["s"], min(segs[i]["e"], segs[i + 1]["s"]))
    return segs


def _lang_match(key, lang):
    return bool(lang) and (key == lang or key.split("-")[0] == lang.split("-")[0])


def pick_subtitle(info, lang=None, allow_auto=True):
    """Kullanılacak altyazı: ("subtitles" | "auto_captions", dil anahtarı) ya da None.
    Elle yazılmış altyazı videonun dilinde (ya da --lang) olmalı; dil bilinmiyorsa arayüz dili, İngilizce, ilk olan.
    Otomatik altyazıda yalnızca orijinal dil (YouTube her dile çeviri de sunar; çeviri transkript değildir)."""
    want = lang or info.get("language")
    manual = {k: v for k, v in (info.get("subtitles") or {}).items() if k != "live_chat" and v}
    if manual:
        if want:
            k = next((k for k in manual if k == want), None) or next((k for k in manual if _lang_match(k, want)), None)
            if k:
                return "subtitles", k
        elif not lang:
            for pref in ytdl.sub_langs():
                k = next((k for k in manual if _lang_match(k, pref)), None)
                if k:
                    return "subtitles", k
            return "subtitles", next(iter(manual))
    if allow_auto:
        auto = {k: v for k, v in (info.get("automatic_captions") or {}).items() if v}
        k = next((k for k in auto if k.endswith("-orig")), None)
        if k is None and want:
            k = next((k for k in auto if k == want), None) or next((k for k in auto if _lang_match(k, want)), None)
        if k:
            return "auto_captions", k
    return None


def _same_frame(a, b):
    """İki küçültülmüş gri kare neredeyse aynı mı (aynı slayta geri dönülmüş)?"""
    import numpy as np
    d = np.abs(a - b)
    return float(d.mean()) < 4.0 and float((d > 24).mean()) < 0.01


def _small_gray(path):
    import numpy as np
    from PIL import Image
    with Image.open(path) as im:
        return np.asarray(im.convert("L").resize((64, 36)), dtype=np.int16)


# ------------------------------------------------------------------ yt-dlp
def _ytdlp(args, cookies="", stream=None):
    """yt-dlp'yi çalıştırır → (kod, stdout, stderr). stream(satır): stdout satır satır (ilerleme)."""
    if "--" in args:                 # link her zaman en sonda, "--" ardından
        i = args.index("--")
        cmd = [ytdl.exe_path()] + args[:i] + ytdl._common(cookies) + args[i:]
    else:
        cmd = [ytdl.exe_path()] + args + ytdl._common(cookies)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    if stream is None:
        r = subprocess.run(cmd, capture_output=True, env=env, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
        return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, creationflags=NO_WINDOW,
                         stdin=subprocess.DEVNULL)
    out = []
    import threading
    err = []
    th = threading.Thread(target=lambda: err.append(p.stderr.read()), daemon=True)
    th.start()
    for raw in p.stdout:
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        out.append(line)
        stream(line)
    p.wait()
    th.join(5)
    return p.returncode, "\n".join(out), (err[0] if err else b"").decode("utf-8", "replace")


def _fail_text(err):
    key = ytdl.error_hint(err)
    return t(key) if key else ytdl.last_error(err)[:300]


def ensure_ytdlp():
    if not ytdl.installed():
        log(t("ex_installing_ytdlp"))
        ytdl.install(lambda a, b: _progress("yt-dlp", a / b if b else 0))
        _progress_end()
        ytdl.mark_checked()
    elif ytdl.needs_update_check():           # YouTube sık değişiyor; eski sürüm adresleri çözemiyor
        log(t("ex_updating_ytdlp"))
        subprocess.run(ytdl.update_command(), capture_output=True, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
        ytdl.mark_checked()


def probe(url, playlist, cookies):
    """Linkteki videolar: ("video", None, [link]) ya da ("playlist", liste bilgisi, [link, ...])."""
    if not playlist:
        return "video", None, [url]
    code, out, err = _ytdlp(["-J", "--flat-playlist", "--yes-playlist", "--", url], cookies)
    try:
        d = json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise ExportError(_fail_text(err))
    if d.get("_type") != "playlist":
        return "video", None, [url]
    links = []
    for e in d.get("entries") or []:
        if not e:
            continue
        u = e.get("url") or e.get("webpage_url")
        if u and not u.startswith("http") and e.get("id"):
            u = f"https://www.youtube.com/watch?v={e['id']}"
        if u:
            links.append(u)
    info = {"id": d.get("id"), "url": d.get("webpage_url") or url, "title": d.get("title"),
            "channel": d.get("channel") or d.get("uploader"), "count": len(links)}
    return "playlist", info, links


def fetch_info(url, cookies, tmp):
    code, out, err = _ytdlp(["-J", "--no-playlist", "--ignore-no-formats-error", "--", url], cookies)
    line = next((ln for ln in reversed(out.splitlines()) if ln.startswith("{")), None)
    if code != 0 or not line:
        raise ExportError(_fail_text(err))
    path = os.path.join(tmp, "info.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write(line)
    return json.loads(line), path


def _fetch_subtitle_direct(info, kind, key):
    """Altyazıyı bilgideki adresten doğrudan al (~0,3 sn; yt-dlp'yi yeniden çalıştırmak ~10 sn). Olmazsa None."""
    import urllib.request
    tracks = (info.get("automatic_captions" if kind == "auto_captions" else "subtitles") or {}).get(key) or []
    tracks = [f for f in tracks if f.get("url") and f.get("protocol") in (None, "http", "https")
              and f.get("ext") in ("json3", "vtt", "srt")]
    tracks.sort(key=lambda f: ("json3", "vtt", "srt").index(f["ext"]))
    for f in tracks:
        try:
            req = urllib.request.Request(f["url"], headers=f.get("http_headers") or {"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                text = r.read(20_000_000).decode("utf-8", "replace")
        except Exception:
            continue
        segs = parse_json3(text) if f["ext"] == "json3" else tr.parse_subtitle_text(text)
        if segs:
            return segs
    return None


def download_subtitle(info, info_path, kind, key, tmp, cookies):
    segs = _fetch_subtitle_direct(info, kind, key)
    if segs:
        return segs
    fmt = "json3" if kind == "auto_captions" else "vtt/srt/best"
    flag = "--write-auto-subs" if kind == "auto_captions" else "--write-subs"
    base = os.path.join(tmp, "sub")
    code, _out, err = _ytdlp(["--load-info-json", info_path, "--skip-download", flag, "--sub-langs", key,
                              "--sub-format", fmt, "-o", base + ".%(ext)s"], cookies)
    files = sorted(glob.glob(base + ".*"))
    files = [f for f in files if not f.endswith(".part")]
    if not files:
        return []
    with open(files[0], encoding="utf-8", errors="replace") as f:
        text = f.read()
    return parse_json3(text) if files[0].endswith(".json3") else tr.parse_subtitle_text(text)


def download_media(info_path, fmt, name, tmp, cookies, label):
    from .thumbs import FFMPEG
    tpl = "download:kamug-progress %(progress.downloaded_bytes)s %(progress.total_bytes)s " \
          "%(progress.total_bytes_estimate)s"

    def on_line(line):
        p = ytdl.parse_line(line)
        if p and p[0] == "progress" and p[1] is not None:
            _progress(label, p[1])
    args = ["--load-info-json", info_path, "-f", fmt, "--newline", "--progress", "--progress-template", tpl,
            "--no-part", "-o", os.path.join(tmp, name + ".%(ext)s")]
    if FFMPEG:
        args += ["--ffmpeg-location", FFMPEG]
    code, _out, err = _ytdlp(args, cookies, stream=on_line)
    _progress_end()
    files = [f for f in glob.glob(os.path.join(tmp, name + ".*")) if not f.endswith((".part", ".ytdl"))]
    if code != 0 or not files:
        raise ExportError(_fail_text(err))
    return max(files, key=os.path.getsize)


# ------------------------------------------------------------------ transkript
def whisper_transcript(audio, tmp, lang, model, duration_ms):
    from .thumbs import FFMPEG
    missing = tr.missing_downloads(model)
    if missing:
        mb = sum(m[3] for m in missing)
        log(t("ex_whisper_download", mb=mb))
        tr.download_all(model, lambda name, a, b: _progress(name, a / b if b else 0))
        _progress_end()
    wav = os.path.join(tmp, "audio.wav")
    r = subprocess.run(tr.audio_command(FFMPEG, audio, wav), capture_output=True, creationflags=NO_WINDOW)
    if r.returncode != 0 or not os.path.isfile(wav):
        raise ExportError(r.stderr.decode("utf-8", "replace")[-300:])
    out_base = os.path.join(tmp, "whisper")
    for gpu in ([True, False] if tr.use_gpu() else [False]):    # ekran kartı çalışmazsa işlemciyle tekrar
        cmd = tr.whisper_command(wav, out_base, lang=lang, key=model, gpu=gpu)
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW,
                             stdin=subprocess.DEVNULL)
        for raw in p.stdout:
            seg = tr.parse_live(raw.decode("utf-8", "replace"))
            if seg and duration_ms > 0:
                _progress("Whisper", seg[1] / duration_ms)
        p.wait()
        _progress_end()
        if p.returncode == 0 and os.path.isfile(out_base + ".json"):
            segs, detected = tr.read_whisper_json(out_base + ".json")
            return segs, detected
    raise ExportError(t("ex_whisper_failed"))


def make_transcript(info, info_path, tmp, opts):
    """→ (segmentler, {"source", "language"})"""
    if not opts.whisper:
        pick = pick_subtitle(info, opts.lang, allow_auto=not opts.no_auto_subs)
        if pick:
            kind, key = pick
            log(t("ex_step_subs_auto" if kind == "auto_captions" else "ex_step_subs", lang=key))
            segs = download_subtitle(info, info_path, kind, key, tmp, opts.cookies)
            if segs:
                return segs, {"source": kind, "language": key.replace("-orig", "")}
            log(t("ex_subs_empty"))
    log(t("ex_step_whisper"))
    audio = download_media(info_path, "ba[ext=m4a]/ba/b", "audio", tmp, opts.cookies, t("ex_dl_audio"))
    lang = opts.lang or info.get("language") or prefs.get("tr_lang", "auto")
    dur = int((info.get("duration") or 0) * 1000)
    segs, detected = whisper_transcript(audio, tmp, lang, opts.model, dur)
    return segs, {"source": "whisper", "language": detected or lang, "model": opts.model or tr.model_key()}


# ------------------------------------------------------------------ kareler + OCR
def make_frames(video, out_dir, tmp, duration, ocr_engine):
    """Sahne değişimi anlarındaki benzersiz kareler → frames/ + [{time, seconds, file, text}]."""
    from . import screen_text as st
    from .thumbs import FFMPEG
    pages = st.scan_changes(FFMPEG, video, duration=duration, progress=lambda r: _progress(t("ex_scan"), r))
    _progress_end()
    cand = []
    for i, (sec, cap) in enumerate(pages):
        at = cap + 0.5 if not duration or cap + 0.5 < duration - 0.2 else cap     # geçiş karesine denk gelmesin
        dest = os.path.join(tmp, f"c_{i:05d}.png")
        if st.extract_frame(FFMPEG, video, at, dest, width=1920):
            cand.append((sec, dest))
        _progress(t("ex_frames"), (i + 1) / max(1, len(pages)))
    _progress_end()
    kept, smalls = [], []
    for sec, path in cand:                       # aynı slayta geri dönülmüşse ikinci kez alınmaz
        try:
            g = _small_gray(path)
        except OSError:
            continue
        if any(_same_frame(g, o) for o in smalls):
            continue
        smalls.append(g)
        kept.append((sec, path))
    fdir = os.path.join(out_dir, "frames")
    if os.path.isdir(fdir):
        shutil.rmtree(fdir, ignore_errors=True)
    os.makedirs(fdir, exist_ok=True)
    final = []
    for n, (sec, path) in enumerate(kept, 1):
        name = f"{n:04d}_{frame_stamp(sec)}.png"
        shutil.move(path, os.path.join(fdir, name))
        final.append((sec, os.path.join(fdir, name)))
    texts = [""] * len(final)
    engine = ocr_engine
    if final:
        log(t("ex_step_ocr", n=len(final)))
        prog = lambda i, n: _progress("OCR", i / max(1, n))  # noqa: E731
        try:
            if ocr_engine == "vlm":
                from . import vlm_ocr
                if not vlm_ocr.installed():
                    log(t("ex_vlm_download"))
                    vlm_ocr.download_all(lambda name, a, b: _progress(name, a / b if b else 0))
                    _progress_end()
                texts = vlm_ocr.read_files([p for _, p in final], progress=prog)
            else:
                texts = st.ocr_files([p for _, p in final], tmp, progress=prog)
        except RuntimeError as e:
            engine = None
            log(t("ex_ocr_failed") + (f" ({t('ocr_no_language')})" if "no-ocr-language" in str(e) else f": {e}"))
        _progress_end()
    items = [{"time": tr.fmt_ts(sec * 1000), "seconds": round(sec, 2),
              "file": "frames/" + os.path.basename(p), "text": txt or ""}
             for (sec, p), txt in zip(final, texts)]
    return items, engine


# ------------------------------------------------------------------ bir video
def export_video(url, out_dir, opts):
    os.makedirs(out_dir, exist_ok=True)
    tmp = os.path.join(out_dir, TMP_NAME)
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    try:
        log(t("ex_step_info"))
        info, info_path = fetch_info(url, opts.cookies, tmp)
        meta = build_meta(info)
        log(f"  {meta['title']}  ·  {meta['channel'] or '?'}  ·  {meta['duration_text'] or '?'}")
        result = dict(meta)
        if not opts.no_transcript:
            segs, src = make_transcript(info, info_path, tmp, opts)
            with open(os.path.join(out_dir, "transcript.txt"), "w", encoding="utf-8") as f:
                f.write(transcript_text(segs))
            result["transcript"] = dict(src, file="transcript.txt", segments=len(segs))
        if not opts.no_frames:
            log(t("ex_step_video"))
            h = int(opts.max_height)
            video = download_media(info_path, f"bv*[height<={h}][vcodec^=avc1]/bv*[height<={h}]/b[height<={h}]/bv*/b",
                                   "video", tmp, opts.cookies, t("ex_dl_video"))
            items, engine = make_frames(video, out_dir, tmp, info.get("duration"), opts.ocr)
            with open(os.path.join(out_dir, "ocr.json"), "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
            result["frames"] = {"dir": "frames", "count": len(items), "ocr": "ocr.json", "ocr_engine": engine}
        if opts.keep_media:
            mdir = os.path.join(out_dir, "media")
            os.makedirs(mdir, exist_ok=True)
            for f in glob.glob(os.path.join(tmp, "video.*")) + glob.glob(os.path.join(tmp, "audio.*")):
                if not f.endswith(".wav"):
                    shutil.move(f, os.path.join(mdir, os.path.basename(f)))
        result["exported_at"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        result["tool"] = f"kamug {__version__}"
        with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------ giriş
def parse_args(argv):
    ap = argparse.ArgumentParser(prog="kamug-export", description=t("ex_desc"))
    ap.add_argument("url", help=t("ex_arg_url"))
    ap.add_argument("--out", "-o", required=True, help=t("ex_arg_out"))
    ap.add_argument("--lang", help=t("ex_arg_lang"))
    ap.add_argument("--whisper", action="store_true", help=t("ex_arg_whisper"))
    ap.add_argument("--no-auto-subs", action="store_true", help=t("ex_arg_no_auto"))
    ap.add_argument("--model", choices=list(tr.MODELS), help=t("ex_arg_model"))
    ap.add_argument("--ocr", choices=["windows", "vlm"], default="windows", help=t("ex_arg_ocr"))
    ap.add_argument("--max-height", type=int, default=1080, help=t("ex_arg_height"))
    pl = ap.add_mutually_exclusive_group()
    pl.add_argument("--playlist", action="store_true", help=t("ex_arg_playlist"))
    pl.add_argument("--no-playlist", action="store_true", help=t("ex_arg_no_playlist"))
    ap.add_argument("--cookies", default="", help=t("ex_arg_cookies"))
    ap.add_argument("--keep-media", action="store_true", help=t("ex_arg_keep"))
    ap.add_argument("--no-transcript", action="store_true", help=t("ex_arg_no_transcript"))
    ap.add_argument("--no-frames", action="store_true", help=t("ex_arg_no_frames"))
    ap.add_argument("--quiet", "-q", action="store_true", help=t("ex_arg_quiet"))
    return ap.parse_args(argv)


def main(argv=None):
    global _quiet
    for s in (sys.stdout, sys.stderr):            # konsol kod sayfası Türkçe başlıkları bozmasın
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    opts = parse_args(sys.argv[1:] if argv is None else argv)
    _quiet = opts.quiet
    url = ytdl.find_url(opts.url)
    if not url:
        log(t("ex_bad_url"))
        return 2
    out = os.path.abspath(opts.out)
    try:
        ensure_ytdlp()
    except Exception as e:
        log(t("yt_install_failed") + f" ({e})")
        return 1
    playlist = opts.playlist or (ytdl.playlist_only(url) and not opts.no_playlist)
    try:
        kind, plinfo, links = probe(url, playlist, opts.cookies)
    except ExportError as e:
        log(t("ex_failed", err=e))
        return 1
    t0 = time.time()
    if kind == "video":
        try:
            export_video(links[0], out, opts)
        except ExportError as e:
            log(t("ex_failed", err=e))
            return 1
        log(t("ex_done", out=out, sec=int(time.time() - t0)))
        print(out)
        return 0
    log(t("ex_playlist", title=plinfo.get("title") or "?", n=len(links)))
    os.makedirs(out, exist_ok=True)
    videos, failed = [], 0
    width = max(3, len(str(len(links))))
    for i, link in enumerate(links, 1):
        log(f"\n[{i}/{len(links)}] {link}")
        vid = re.search(r"[?&]v=([\w-]+)", link)
        sub = f"{i:0{width}d}" + (f"_{vid.group(1)}" if vid else "")
        entry = {"index": i, "url": link, "folder": sub}
        try:
            m = export_video(link, os.path.join(out, sub), opts)
            entry.update(id=m.get("id"), title=m.get("title"), duration=m.get("duration"))
        except ExportError as e:
            failed += 1
            entry["error"] = str(e)
            log(t("ex_failed", err=e))
        videos.append(entry)
        with open(os.path.join(out, "meta.json"), "w", encoding="utf-8") as f:     # her videodan sonra güncel
            json.dump({"playlist": plinfo, "videos": videos, "tool": f"kamug {__version__}"}, f,
                      ensure_ascii=False, indent=2)
    log(t("ex_done_list", out=out, ok=len(links) - failed, n=len(links), sec=int(time.time() - t0)))
    print(out)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
