"""Konuşmacı ayırma (hafif, ek indirme yok): transkript satırlarını sese göre gruplar → "Konuşmacı 1 / 2 …".

Her satır ≤2 sn'lik parçalara bölünür; parça başına MFCC (ses rengi) ortalaması + sapması çıkarılır, parçalar küresel
k-ortalama ile kümelenir, satırın konuşmacısı parçalarının çoğunluğudur. Kişi sayısı verilmezse 1–6 arasında
siluet puanına göre seçilir. Sesleri belirgin farklı kişilerde (ör. kadın / erkek, öğretmen / öğrenci) iyi çalışır;
birbirine çok benzeyen seslerde karışabilir."""
import wave

import numpy as np

SR = 16000
WIN, HOP = 400, 160          # 25 ms / 10 ms
N_MEL, N_MFCC = 40, 20
CHUNK_MS = 2000


def read_wav(path):
    with wave.open(path, "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError("16-bit PCM bekleniyor")
        data = np.frombuffer(w.readframes(w.getnframes()), np.int16)
        if w.getnchannels() > 1:
            data = data.reshape(-1, w.getnchannels()).mean(axis=1)
    return data.astype(np.float32) / 32768.0


def _mel_bank():
    def hz2mel(f):
        return 2595 * np.log10(1 + f / 700.0)

    def mel2hz(m):
        return 700 * (10 ** (m / 2595.0) - 1)
    nfft = 512
    pts = mel2hz(np.linspace(hz2mel(60), hz2mel(7600), N_MEL + 2))
    bins = np.floor((nfft + 1) * pts / SR).astype(int)
    fb = np.zeros((N_MEL, nfft // 2 + 1), np.float32)
    for i in range(1, N_MEL + 1):
        a, b, c = bins[i - 1], bins[i], bins[i + 1]
        if b > a:
            fb[i - 1, a:b] = (np.arange(a, b) - a) / (b - a)
        if c > b:
            fb[i - 1, b:c] = (c - np.arange(b, c)) / (c - b)
    return fb


_FB = None
_DCT = None


def mfcc(sig):
    """Sinyal → (kare sayısı, N_MFCC) MFCC (c0 hariç; c0 ses yüksekliğidir, konuşmacıyı ayırt etmez)."""
    global _FB, _DCT
    if _FB is None:
        _FB = _mel_bank()
        n = np.arange(N_MEL)
        _DCT = np.cos(np.pi / N_MEL * (n[None, :] + 0.5) * np.arange(N_MFCC + 1)[:, None]).astype(np.float32)
    if len(sig) < WIN:
        return np.zeros((0, N_MFCC), np.float32)
    sig = np.append(sig[0], sig[1:] - 0.97 * sig[:-1])
    n = 1 + (len(sig) - WIN) // HOP
    idx = np.arange(WIN)[None, :] + HOP * np.arange(n)[:, None]
    frames = sig[idx] * np.hamming(WIN).astype(np.float32)
    spec = np.abs(np.fft.rfft(frames, 512)) ** 2
    energy = spec.sum(axis=1)
    keep = energy > max(1e-8, np.percentile(energy, 30) * 0.5)      # sessiz kareler atılır
    mel = np.log(spec[keep] @ _FB.T + 1e-10)
    return (mel @ _DCT.T)[:, 1:]


def _units(sig, segs):
    """Satırları ≤2 sn'lik parçalara böler → (özellik matrisi, parça → satır indisi)."""
    feats, owner, frames_all = [], [], []
    for si, s in enumerate(segs):
        a, b = max(0, int(s["s"])), int(s["e"])
        if b - a < 400:
            continue
        n = max(1, round((b - a) / CHUNK_MS))
        step = (b - a) / n
        for k in range(n):
            x0, x1 = int((a + k * step) * SR / 1000), int((a + (k + 1) * step) * SR / 1000)
            m = mfcc(sig[x0:x1])
            if len(m) < 30:
                continue
            frames_all.append(m)
            owner.append(si)
    if not frames_all:
        return np.zeros((0, 2 * N_MFCC)), []
    allf = np.concatenate(frames_all)
    mu, sd = allf.mean(axis=0), allf.std(axis=0) + 1e-6
    for m in frames_all:
        z = (m - mu) / sd
        feats.append(np.concatenate([z.mean(axis=0), z.std(axis=0)]))
    x = np.array(feats, np.float32)
    x -= x.mean(axis=0)
    x /= np.linalg.norm(x, axis=1, keepdims=True) + 1e-9
    return x, owner


def _kmeans(x, k, seed=0, iters=40):
    rng = np.random.default_rng(seed)
    c = [x[rng.integers(len(x))]]
    for _ in range(1, k):                        # k-means++ başlangıcı
        d = 1 - np.max(x @ np.array(c).T, axis=1)
        d = np.maximum(d, 0) ** 2
        c.append(x[rng.choice(len(x), p=d / d.sum())] if d.sum() > 0 else x[rng.integers(len(x))])
    c = np.array(c)
    lab = np.zeros(len(x), int)
    for _ in range(iters):
        new = np.argmax(x @ c.T, axis=1)
        if _ and np.array_equal(new, lab):
            break
        lab = new
        for j in range(k):
            m = x[lab == j]
            if len(m):
                v = m.mean(axis=0)
                c[j] = v / (np.linalg.norm(v) + 1e-9)
    score = float(np.sum(np.max(x @ c.T, axis=1)))
    return lab, score


def _best_kmeans(x, k):
    return max((_kmeans(x, k, seed) for seed in range(6)), key=lambda r: r[1])[0]


def _silhouette(x, lab, sample=1500):
    if len(set(lab)) < 2:
        return -1.0
    idx = np.arange(len(x))
    if len(x) > sample:
        idx = np.random.default_rng(1).choice(len(x), sample, replace=False)
    xs, ls = x[idx], lab[idx]
    d = 1 - xs @ xs.T
    out = []
    for i in range(len(xs)):
        same = ls == ls[i]
        same[i] = False
        if not same.any():
            continue
        a = d[i, same].mean()
        b = min(d[i, ls == j].mean() for j in set(ls.tolist()) if j != ls[i])
        out.append((b - a) / max(a, b, 1e-9))
    return float(np.mean(out)) if out else -1.0


def diarize(wav_path, segs, n_speakers=None, min_silhouette=0.4):
    """segs'e (yerinde) "spk": 1.. ekler. Döndürür: bulunan kişi sayısı.
    min_silhouette: tek kişiyi yanlışlıkla ikiye bölmemek için (denemede tek ses 0,27–0,36, iki ses 0,69 çıktı);
    otomatik yanılırsa kullanıcı kişi sayısını kendisi seçer."""
    sig = read_wav(wav_path)
    x, owner = _units(sig, segs)
    if len(x) < 4:
        for s in segs:
            s["spk"] = 1
        return 1
    if n_speakers:
        k = max(1, min(int(n_speakers), len(x) // 2))
        lab = _best_kmeans(x, k) if k > 1 else np.zeros(len(x), int)
    else:
        best = (min_silhouette, 1, np.zeros(len(x), int))
        for k in range(2, min(6, len(x) // 3) + 1):
            lb = _best_kmeans(x, k)
            sc = _silhouette(x, lb)
            if sc > best[0] + 0.01 * (k - 2):          # gereksiz yere çok kişi seçilmesin
                best = (sc, k, lb)
        k, lab = best[1], best[2]
    votes = {}
    for u, si in enumerate(owner):
        votes.setdefault(si, []).append(int(lab[u]))
    # Konuşmacı numaraları ilk konuşma sırasına göre (ilk konuşan = 1)
    order = {}
    for si in sorted(votes):
        top = max(set(votes[si]), key=votes[si].count)
        order.setdefault(top, len(order) + 1)
    last = 1
    for si, s in enumerate(segs):
        if si in votes:
            top = max(set(votes[si]), key=votes[si].count)
            last = order[top]
        s["spk"] = last                                  # çok kısa satır: bir öncekinin konuşmacısı
    return len(order)
