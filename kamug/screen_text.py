"""Videodaki yazıları okuma (OCR).

1. ffmpeg saniyede bir kareyi küçük gri resim olarak verir; görüntü belirgin değişip sonra durulduğunda (yeni slayt,
   yeni sayfa) o an seçilir. Her kare okunmaz, bu yüzden hızlıdır.
2. Seçilen anların tam kareleri çıkarılır ve Windows'un kendi metin tanımasıyla (Windows.Media.Ocr, ek kurulum yok)
   tek bir PowerShell sürecinde okunur.
3. Aynı yazı tekrar ediyorsa tek kayıt kalır; madde madde açılan slaytta son hali tutulur."""
import difflib
import os
import subprocess

import numpy as np

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SW, SH = 160, 90                # değişim tespiti için küçük kare
MAX_FRAMES = 400

PS_SCRIPT = r"""
param([string]$List)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$t) {
    $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op))
    $task.Wait(-1) | Out-Null
    $task.Result
}
[Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime] | Out-Null
[Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime] | Out-Null
$eng = $null
foreach ($tag in @('tr', 'tr-TR')) {
    if (-not $eng) { try { $eng = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new($tag)) } catch {} }
}
if (-not $eng) { $eng = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
if (-not $eng) { $eng = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new('en-US')) }
if (-not $eng) { [Console]::Error.WriteLine('no-ocr-language'); exit 3 }
$i = 0
foreach ($path in [IO.File]::ReadAllLines($List, [Text.Encoding]::UTF8)) {
    $txt = ''
    try {
        $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
        $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
        $dec = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $bmp = Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $res = Await ($eng.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
        $stream.Dispose()
        $txt = (($res.Lines | ForEach-Object { $_.Text }) -join "`n")
    } catch {}
    [Console]::Out.WriteLine('kamug-ocr ' + $i + "`t" + $txt.Replace('\', '\\').Replace("`n", '\n'))
    [Console]::Out.Flush()
    $i++
}
"""


def _crop_filter(region):
    if not region:
        return ""
    x, y, w, h = region
    return f"crop=iw*{w:.4f}:ih*{h:.4f}:iw*{x:.4f}:ih*{y:.4f},"


def scan_changes(ffmpeg, video, region=None, step=1.0, cancelled=lambda: False, progress=None, duration=None):
    """Görüntünün değişip durulduğu sayfalar: [(başlangıç sn, kare sn)]. progress(oran)."""
    vf = f"fps={1 / step:.4f},{_crop_filter(region)}scale={SW}:{SH},format=gray"
    p = subprocess.Popen([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", video, "-an", "-sn", "-vf", vf,
                          "-f", "rawvideo", "-"], stdout=subprocess.PIPE, creationflags=NO_WINDOW)
    size = SW * SH
    frames = []
    try:
        while True:
            if cancelled():
                p.kill()
                raise InterruptedError
            buf = p.stdout.read(size)
            if len(buf) < size:
                break
            frames.append(np.frombuffer(buf, np.uint8).astype(np.int16))
            if progress and duration:
                progress(min(1.0, len(frames) * step / duration))
    finally:
        p.stdout.close()
        p.wait()
    return group_pages(frames, pick_moments(frames, step), step)


def _changed(a, b, level=24):
    """İki kare arasında belirgin değişen piksellerin oranı (yazı değişimi küçük alan kaplar, ortalama yetmez)."""
    return float((np.abs(a - b) > level).mean())


def pick_moments(frames, step=1.0, change=0.003, settle=0.0015):
    """Kare listesinden (gri, düz dizi) yeni içeriğin göründüğü ve durulduğu anlar."""
    if not frames:
        return []
    out = [0.0]
    last = frames[0]
    pending = None
    for i in range(1, len(frames)):
        f = frames[i]
        if pending is None and _changed(f, last) > change:
            pending = i
        if pending is not None:
            nxt = frames[i + 1] if i + 1 < len(frames) else f
            if _changed(nxt, f) < settle:        # durulmuş: geçiş / animasyon bitti
                out.append(i * step)
                last = f
                pending = None
        if len(out) >= MAX_FRAMES:
            break
    return out


def _ink(f, level=40):
    """Arka plandan (en sık renk ~ ortanca) belirgin ayrılan pikseller: yazı / çizim."""
    return np.abs(f - np.median(f)) > level


def group_pages(frames, moments, step=1.0, keep=0.85):
    """Yazı yazıldıkça (tahta, el yazısı) aynı sayfa defalarca yakalanmasın: önceki anın yazısının çoğu yeni karede
    duruyorsa (yalnızca eklenmiş) aynı sayfadır → kayıt güncellenir, zamanı ilk görünüş kalır. Araya başka bir şey
    girip (ör. tablo gösterilip) aynı sayfaya dönülürse de o sayfanın kaydı güncellenir, yeni kayıt açılmaz.
    Döndürür: [(başlangıç sn, karenin alınacağı sn)] (başlangıca göre sıralı)."""
    pages, inks = [], []

    def same(old, new):
        n = int(old.sum())
        return n == 0 or (int((old & new).sum()) / n >= keep and new.sum() >= n * 0.9)
    for sec in moments:
        i = min(len(frames) - 1, int(round(sec / step)))
        ink = _ink(frames[i])
        for j in range(len(pages) - 1, max(-1, len(pages) - 9), -1):     # son sayfalar (önce en yakını)
            if same(inks[j], ink):
                pages[j] = (pages[j][0], sec)
                inks[j] = ink
                break
        else:
            pages.append((sec, sec))
            inks.append(ink)
    return pages


def extract_frame(ffmpeg, video, sec, dest, region=None, width=1600):
    vf = f"{_crop_filter(region)}scale='min({width},iw)':-2"
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{sec:.2f}", "-i", video,
                    "-frames:v", "1", "-vf", vf, dest], creationflags=NO_WINDOW, timeout=60)
    return os.path.isfile(dest)


def ocr_files(paths, work_dir, cancelled=lambda: False, progress=None):
    """Görselleri tek PowerShell sürecinde okur → [metin]. progress(i, n)."""
    script = os.path.join(work_dir, "ocr.ps1")
    with open(script, "w", encoding="utf-8-sig") as f:
        f.write(PS_SCRIPT)
    lst = os.path.join(work_dir, "list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        f.write("\n".join(os.path.abspath(p) for p in paths))
    p = subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                          script, lst], stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                         creationflags=NO_WINDOW)
    texts = [""] * len(paths)
    got = 0
    try:
        for raw in p.stdout:
            if cancelled():
                p.kill()
                raise InterruptedError
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if not line.startswith("kamug-ocr "):
                continue
            idx, _, txt = line[len("kamug-ocr "):].partition("\t")
            try:
                i = int(idx)
            except ValueError:
                continue
            if 0 <= i < len(texts):
                texts[i] = txt.replace("\\n", "\n").replace("\\\\", "\\").strip()
            got += 1
            if progress:
                progress(got, len(paths))
    finally:
        p.stdout.close()
        err = p.stderr.read().decode("utf-8", "replace")
        p.wait()
    if p.returncode == 3 or "no-ocr-language" in err:
        raise RuntimeError("no-ocr-language")
    return texts


def _norm(t):
    return " ".join(t.lower().split())


def dedupe(items, same=0.88):
    """[(sn, metin, görsel)] → tekrarlar atılmış liste. Önceki metin yenisinin içindeyse (madde madde açılan slayt)
    önceki kayıt yenisiyle güncellenir (zamanı ilk görünüş kalır)."""
    out = []
    for sec, txt, img in items:
        n = _norm(txt)
        if len(n) < 3:
            continue
        if out:
            pn = _norm(out[-1][1])
            if difflib.SequenceMatcher(None, pn, n).ratio() >= same:
                continue
            if pn and pn in n:
                out[-1] = (out[-1][0], txt, img)
                continue
        out.append((sec, txt, img))
    return out


def run(ffmpeg, video, out_dir, region=None, duration=None, cancelled=lambda: False, progress=None, reader=None):
    """Tüm akış → [{"s": ms, "t": metin, "img": dosya adı}]. progress(aşama, oran) aşama: scan | frames | ocr.
    reader(dosyalar, cancelled, progress(i, n)) → [metin]: verilirse Windows OCR yerine o okur (gelişmiş okuma)."""
    os.makedirs(out_dir, exist_ok=True)
    for n in os.listdir(out_dir):
        if n.startswith("f_"):
            try:
                os.remove(os.path.join(out_dir, n))
            except OSError:
                pass
    moments = scan_changes(ffmpeg, video, region, cancelled=cancelled, duration=duration,
                           progress=(lambda r: progress("scan", r)) if progress else None)
    files = []
    for i, (sec, cap) in enumerate(moments):
        if cancelled():
            raise InterruptedError
        dest = os.path.join(out_dir, f"f_{int(sec * 1000):09d}.jpg")
        # yarım saniye sonrası: geçiş karesine (iki slayt üst üste) denk gelmesin
        if extract_frame(ffmpeg, video, cap + 0.5, dest, region):
            files.append((sec, dest))
        if progress:
            progress("frames", (i + 1) / max(1, len(moments)))
    if not files:
        return []
    prog = (lambda i, n: progress("ocr", i / max(1, n))) if progress else None
    if reader:
        texts = reader([f for _, f in files], cancelled, prog)
    else:
        texts = ocr_files([f for _, f in files], out_dir, cancelled, prog)
    kept = dedupe([(sec, txt, f) for (sec, f), txt in zip(files, texts)])
    keep_files = {os.path.basename(f) for _, _, f in kept}
    for _, f in files:                        # okunmayan / tekrar eden karelerin görselleri silinir
        if os.path.basename(f) not in keep_files:
            try:
                os.remove(f)
            except OSError:
                pass
    for n in ("ocr.ps1", "list.txt"):
        try:
            os.remove(os.path.join(out_dir, n))
        except OSError:
            pass
    return [{"s": int(sec * 1000), "t": txt, "img": os.path.basename(f)} for sec, txt, f in kept]
