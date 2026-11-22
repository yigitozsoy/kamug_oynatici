"""Otomatik intro (opening) bulma: bölümlerin başındaki sesin parmak izini çıkarıp karşılaştırır.

Animelerde ve dizilerde opening her bölümde aynı müziktir ama yeri değişebilir (önce kısa bir sahne, sonra
opening). Her bölümün ilk birkaç dakikasının sesinden 0,1 sn'lik karelerle 16 bitlik bir parmak izi çıkarılır
(Haitsma-Kalker yöntemi: frekans bantlarının enerji farklarının işareti). İki bölümde uzun süre aynı kalan parça
introdur. Bulunan parçanın parmak izi saklanır; sonraki bölümlerde yalnızca o bölümün sesi bununla karşılaştırılır.
"""
import base64
import subprocess

import numpy as np

SR = 8000              # örnekleme hızı
HOP = 800              # 0,1 sn
WIN = 4096           # 0,5 sn pencere: kare sınırına denk gelmeyen kaymalarda da parmak izi tutarlı kalır
SCAN_SEC = 480         # bölümün ilk 8 dakikası taranır
MIN_SEC = 20           # bundan kısa ortak parça intro sayılmaz
MAX_SEC = 180
FPS = SR / HOP         # parmak izi karesi / sn

_POP = np.array([bin(i).count("1") for i in range(1 << 16)], dtype=np.uint8)


def read_audio(path, seconds=SCAN_SEC):
    """Dosyanın başından mono 8 kHz ses (float32)."""
    from .thumbs import FFMPEG
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-t", str(seconds), "-i", path, "-vn", "-sn",
           "-ac", "1", "-ar", str(SR), "-f", "s16le", "pipe:1"]
    r = subprocess.run(cmd, capture_output=True, timeout=120,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def fingerprint(samples):
    """uint16 dizisi: her 0,1 sn için 16 bitlik parmak izi."""
    n = (len(samples) - WIN) // HOP
    if n < 10:
        return np.zeros(0, dtype=np.uint16)
    idx = np.arange(WIN)[None, :] + HOP * np.arange(n)[:, None]
    frames = samples[idx] * np.hanning(WIN)[None, :].astype(np.float32)
    spec = np.abs(np.fft.rfft(frames, axis=1)) ** 2
    freqs = np.fft.rfftfreq(WIN, 1 / SR)
    edges = np.geomspace(300, 3000, 18)
    bands = np.stack([spec[:, (freqs >= edges[i]) & (freqs < edges[i + 1])].sum(axis=1) for i in range(17)], axis=1)
    e = np.log(bands + 1e-9)
    d = e[:, :-1] - e[:, 1:]                       # komşu bant farkı (16)
    bits = (d[1:] - d[:-1]) > 0                    # zamandaki değişim
    weights = (1 << np.arange(16)).astype(np.uint32)
    fp = (bits.astype(np.uint32) * weights).sum(axis=1).astype(np.uint16)
    # Sessiz / çok kısık karelerin parmak izi her dosyada aynı çıkar (siyah ekranlı başlangıçlar birbirine "intro"
    # diye eşleşiyordu): bunlara rastgele değer ver ki hiçbir şeyle eşleşmesinler
    rms = np.sqrt((frames[1:] ** 2).mean(axis=1))
    quiet = rms < 0.004
    if quiet.any():
        fp[quiet] = np.random.default_rng().integers(0, 1 << 16, int(quiet.sum()), dtype=np.uint16)
    return fp


def _longest_run(mask):
    """Boole dizisindeki en uzun True dizisi: (başlangıç, uzunluk)."""
    if not mask.any():
        return 0, 0
    m = np.concatenate(([0], mask.astype(np.int8), [0]))
    dif = np.diff(m)
    starts, ends = np.flatnonzero(dif == 1), np.flatnonzero(dif == -1)
    k = int(np.argmax(ends - starts))
    return int(starts[k]), int(ends[k] - starts[k])


def match(fa, fb, min_sec=MIN_SEC):
    """İki parmak izinde ortak en uzun parça: (a_başlangıç, b_başlangıç, uzunluk) kare cinsinden ya da None."""
    na, nb = len(fa), len(fb)
    min_len = int(min_sec * FPS)
    if na < min_len or nb < min_len:
        return None
    best = None
    kernel = np.ones(15, dtype=np.float32) / 15     # 1,5 sn yumuşatma: tek tük gürültü kareleri parçayı bölmesin
    for d in range(-(nb - min_len), na - min_len + 1):
        a0, b0 = max(0, d), max(0, -d)
        n = min(na - a0, nb - b0)
        if n < min_len:
            continue
        err = _POP[fa[a0:a0 + n] ^ fb[b0:b0 + n]]
        good = err <= 4                              # rastgele seste beklenen 8 bit hata
        if good.sum() < min_len * 0.6:
            continue
        smooth = np.convolve(good.astype(np.float32), kernel, mode="same") > 0.5
        s, ln = _longest_run(smooth)
        if ln >= min_len and (best is None or ln > best[2]):
            best = (a0 + s, b0 + s, ln)
    return best


def to_sec(frames):
    return frames / FPS


def encode_fp(fp):
    return base64.b64encode(np.asarray(fp, dtype="<u2").tobytes()).decode("ascii")


def decode_fp(s):
    return np.frombuffer(base64.b64decode(s), dtype="<u2").astype(np.uint16)


def detect(paths, ref=None, progress=None):
    """Bölüm yolları için intro aralıkları. ref: önceden bulunmuş intro parmak izi (base64) ya da None.
    Döndürür: (ref, {yol: (başlangıç_ms, bitiş_ms) ya da None}). Uzun sürebilir; arka planda çağrılmalı."""
    fps = {}
    for i, p in enumerate(paths):
        try:
            fps[p] = fingerprint(read_audio(p))
        except Exception:
            fps[p] = np.zeros(0, dtype=np.uint16)
        if progress:
            progress(i + 1, len(paths) * 2)
    out = {}
    ref_fp = decode_fp(ref) if ref else None
    if ref_fp is None:
        # Referansı bölüm çiftlerinden bul: en uzun ortak parça
        best = None
        ps = [p for p in paths if len(fps[p])]
        for i in range(len(ps)):
            for j in range(i + 1, min(len(ps), i + 3)):
                m = match(fps[ps[i]], fps[ps[j]])
                if m and m[2] <= MAX_SEC * FPS and (best is None or m[2] > best[1][2]):
                    best = (ps[i], m)
        if best is None:
            return None, {p: None for p in paths}
        src, (a0, _b0, ln) = best
        ref_fp = fps[src][a0:a0 + ln]
        ref = encode_fp(ref_fp)
    for i, p in enumerate(paths):
        m = match(ref_fp, fps[p], min_sec=min(MIN_SEC, to_sec(len(ref_fp)) * 0.6))
        if m:
            _a0, b0, ln = m
            # Kısaltılmış opening de olabilir; yalnızca referansın ≥%60'ı eşleşirse kabul
            out[p] = (int(to_sec(b0) * 1000), int(to_sec(b0 + ln) * 1000)) if ln >= len(ref_fp) * 0.6 else None
        else:
            out[p] = None
        if progress:
            progress(len(paths) + i + 1, len(paths) * 2)
    return ref, out
