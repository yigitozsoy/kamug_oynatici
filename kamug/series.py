"""Dizi / film tanıma: dosya adından sezon-bölüm çözümleme, temiz ad önerisi, altyazı eşleme ve intro bilgisi.

Arayüzden bağımsızdır (saf fonksiyonlar + küçük bir JSON deposu); test edilebilir.
"""
import os
import re
from collections import Counter

from .config import DATA_DIR, _JsonStore
from .formats import SUBTITLE_EXT

# ------------------------------------------------------------------ çözümleme
# Adın içindeki gürültü: kalite, kaynak, kodek, ses, grup etiketleri
_NOISE = re.compile(
    r"\b(2160p|1080p|1080i|720p|576p|480p|4k|uhd|hdr10\+?|hdr|dv|dolby ?vision|10 ?bit|8 ?bit|"
    r"web[ .-]?dl|web[ .-]?rip|webrip|web|blu[ .-]?ray|bdrip|brrip|bd|hdtv|hdrip|dvdrip|dvd|remux|"
    r"x264|x265|h[ .]?264|h[ .]?265|hevc|avc|xvid|divx|av1|vp9|aac(2[ .]0)?|ac3|eac3|e-ac-3|ddp?5[ .]1|dd2[ .]0|"
    r"dts(-hd)?|truehd|atmos|flac|opus|mp3|5[ .]1|7[ .]1|2[ .]0|proper|repack|extended|uncut|unrated|"
    r"multi|dual[ .-]?audio|subbed|dubbed|nf|amzn|dsnp|hmax|atvp|hulu|cr)\b", re.I)

_PATTERNS = [
    # S03E13, S3E13, S03.E13, S03 E13, S03E13-E14, S03E13E14
    re.compile(r"(?<![a-z0-9])s(?P<s>\d{1,2})[ ._-]*e(?P<e>\d{1,4})"
               r"(?:(?:-|[ ._])?e(?P<e2>\d{1,4})|-(?P<e3>\d{1,3})(?![0-9p]))?(?![0-9])", re.I),
    # 3x13
    re.compile(r"(?<![a-z0-9])(?P<s>\d{1,2})x(?P<e>\d{2,3})(?![0-9])", re.I),
    # Season 3 Episode 13
    re.compile(r"season[ ._-]*(?P<s>\d{1,2})[ ._-]*(?:episode|ep)[ ._-]*(?P<e>\d{1,4})", re.I),
    # 3. Sezon 13. Bölüm  /  Sezon 3 Bölüm 13
    re.compile(r"(?P<s>\d{1,2})\.?[ ._-]*sezon[ ._-]*(?P<e>\d{1,4})\.?[ ._-]*b[öo]l[üu]m", re.I),
    re.compile(r"sezon[ ._-]*(?P<s>\d{1,2})[ ._-]*b[öo]l[üu]m[ ._-]*(?P<e>\d{1,4})", re.I),
]
# Sezonsuz (çoğunlukla anime): "Title - 13", "Title Episode 13", "Title EP13", "Title 13. Bölüm"
_ABS_PATTERNS = [
    re.compile(r"(?:^|[ ._])(?:episode|ep|e)[ ._-]?(?P<e>\d{1,4})(?:v\d)?(?![0-9])", re.I),
    re.compile(r"(?P<e>\d{1,4})\.?[ ._-]*b[öo]l[üu]m", re.I),
    re.compile(r"\s-\s(?P<e>\d{1,4})(?:v\d)?(?:\s|$|\[|\()", re.I),
]
_YEAR = re.compile(r"(?<![0-9])[\(\[ ._-]?((?:19|20)\d{2})[\)\] ._-]?(?![0-9])")
_SEASON_DIR = re.compile(r"(?:season|sezon|s)[ ._-]*(\d{1,2})\b|(\d{1,2})\.?[ ._-]*sezon", re.I)


class Parsed:
    """kind: "episode" | "movie". Bölümde season/episode (episode2 = çift bölüm), filmde year."""
    __slots__ = ("kind", "title", "season", "episode", "episode2", "year", "explicit_season")

    def __init__(self, kind, title, season=None, episode=None, episode2=None, year=None, explicit_season=True):
        self.kind = kind
        self.title = title
        self.season = season
        self.episode = episode
        self.episode2 = episode2
        self.year = year
        self.explicit_season = explicit_season

    @property
    def key(self):
        return (self.season or 1, self.episode) if self.kind == "episode" else None

    def __repr__(self):
        if self.kind == "episode":
            return f"<{self.title} S{self.season}E{self.episode}{'-' + str(self.episode2) if self.episode2 else ''}>"
        return f"<{self.title} ({self.year})>"


def _clean_title(raw):
    s = re.sub(r"\[[^\]]*\]|\{[^}]*\}", " ", raw)           # [SubsPlease] gibi grup etiketleri
    s = re.sub(r"\((?!(?:19|20)\d{2}\))[^)]*\)", " ", s)      # (1080p) — ama (2019) kalsın
    s = re.sub(r"(?<=[a-zA-Z0-9ğüşıöçĞÜŞİÖÇ])[._](?=[a-zA-Z0-9ğüşıöçĞÜŞİÖÇ])", " ", s)
    s = s.replace("_", " ")
    s = _NOISE.split(s)[0] if _NOISE.search(s) else s
    s = re.sub(r"\s+", " ", s).strip(" -._–—,")
    if s and (s.islower() or s.isupper()):
        s = " ".join(w if w.isdigit() else w[:1].upper() + w[1:].lower() for w in s.split(" "))
    return s


def parse(filename):
    """Dosya adından dizi bölümü ya da film bilgisi çıkarır; tanınmazsa None."""
    stem = os.path.splitext(os.path.basename(filename))[0]
    for pat in _PATTERNS:
        m = pat.search(stem)
        if m:
            title = _clean_title(stem[:m.start()])
            e2 = m.groupdict().get("e2") or m.groupdict().get("e3")
            e, e2 = int(m.group("e")), (int(e2) if e2 else None)
            if e2 is not None and e2 <= e:
                e2 = None
            return Parsed("episode", title, int(m.group("s")), e, e2)
    # Sezonsuz bölüm (anime); yıl gibi görünen sayılar ve kalite (1080) bölüm sayılmaz
    for pat in _ABS_PATTERNS:
        for m in pat.finditer(stem):
            e = int(m.group("e"))
            if (1900 <= e <= 2099) or e in (480, 576, 720, 1080, 2160) or e == 0:
                continue
            title = _clean_title(stem[:m.start()])
            if title:
                return Parsed("episode", title, 1, e, explicit_season=False)
    # Film: "Inception (2010)", "Inception.2010.1080p.BluRay"
    for m in _YEAR.finditer(stem):
        title = _clean_title(stem[:m.start()])
        if title and len(title) >= 2:
            return Parsed("movie", title, year=int(m.group(1)))
    return None


def season_from_dir(path):
    """Klasör adı "Season 3" / "S03" / "3. Sezon" ise sezon numarası."""
    name = os.path.basename(os.path.dirname(os.path.abspath(path)))
    m = _SEASON_DIR.search(name)
    if m:
        return int(m.group(1) or m.group(2))
    return None


def _norm(title):
    return re.sub(r"[^0-9a-zğüşıöç]+", "", (title or "").lower())


# ------------------------------------------------------------------ klasör analizi
class Series:
    """Bir klasördeki bir dizinin bölümleri."""

    def __init__(self, title, folder):
        self.title = title
        self.folder = folder
        self.episodes = []          # [(path, Parsed)], sezon/bölüme göre sıralı

    @property
    def key(self):
        return os.path.normcase(os.path.abspath(self.folder)) + "|" + _norm(self.title)

    def find(self, path):
        n = os.path.normcase(os.path.abspath(path))
        for p, ep in self.episodes:
            if os.path.normcase(os.path.abspath(p)) == n:
                return ep
        return None

    def seasons(self):
        return sorted({ep.season for _, ep in self.episodes})


def analyze(paths):
    """Video yolları -> {norm başlık: Series}. Aynı başlığın bölümleri bir dizi sayılır.
    Sezonsuz numaralı bölümlerde sezon klasör adından alınır ("Season 3")."""
    groups = {}
    for p in paths:
        ep = parse(p)
        if ep is None or ep.kind != "episode":
            continue
        if not ep.explicit_season:
            s = season_from_dir(p)
            if s:
                ep.season = s
        k = _norm(ep.title)
        if not k:
            continue
        groups.setdefault(k, []).append((p, ep))
    out = {}
    for k, eps in groups.items():
        # Başlığın en sık yazılışı (bazı dosyalarda "Attack on Titan", bazılarında "attack.on.titan")
        title = Counter(ep.title for _, ep in eps).most_common(1)[0][0]
        s = Series(title, os.path.dirname(os.path.abspath(eps[0][0])))
        s.episodes = sorted(eps, key=lambda x: (x[1].season, x[1].episode))
        out[k] = s
    return out


def series_for(path, folder_paths):
    """Açık dosyanın dizisi (klasördeki diğer videolarla birlikte) ya da None."""
    ep = parse(path)
    if ep is None or ep.kind != "episode":
        return None
    return analyze(folder_paths).get(_norm(ep.title))


# ------------------------------------------------------------------ ad önerisi
NAME_FORMATS = {
    "dash": "{title} - S{s:02d}E{e:02d}",          # Attack on Titan - S03E13
    "dot": "{title}.S{s:02d}E{e:02d}",              # Attack on Titan.S03E13
    "plain": "{title} S{s:02d}E{e:02d}",            # Attack on Titan S03E13
    "x": "{title} - {s}x{e:02d}",                   # Attack on Titan - 3x13
}

_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def episode_name(title, ep, fmt="dash", width=2):
    f = NAME_FORMATS.get(fmt, NAME_FORMATS["dash"])
    if width != 2:
        f = f.replace("E{e:02d}", "E{e:0%dd}" % width)
    name = f.format(title=title.strip(), s=ep.season or 1, e=ep.episode)
    if ep.episode2:
        name += ("-E{:0%dd}" % width).format(ep.episode2)
    return _BAD.sub("", name).strip(" .")


def movie_name(p):
    return _BAD.sub("", f"{p.title} ({p.year})" if p.year else p.title).strip(" .")


def rename_plan(series, title=None, fmt="dash"):
    """[(eski yol, yeni yol)] — değişmeyenler dahil değil."""
    title = (title or series.title).strip()
    width = 3 if any(ep.episode >= 100 for _, ep in series.episodes) else 2
    plan = []
    for p, ep in series.episodes:
        ext = os.path.splitext(p)[1]
        new = os.path.join(os.path.dirname(p), episode_name(title, ep, fmt, width) + ext)
        if os.path.normcase(new) != os.path.normcase(p):
            plan.append((p, new))
    return plan


def needs_cleanup(series, fmt="dash"):
    """Adlar önerilenden farklı mı (dağınık mı)?"""
    return bool(rename_plan(series, fmt=fmt))


# ------------------------------------------------------------------ altyazılar
_LANGS = {
    "tr": ("tr", "tur", "turkish", "türkçe", "turkce"), "en": ("en", "eng", "english", "ingilizce"),
    "de": ("de", "ger", "deu", "german"), "fr": ("fr", "fre", "fra", "french"), "es": ("es", "spa", "spanish"),
    "ja": ("ja", "jpn", "japanese"), "ar": ("ar", "ara", "arabic"), "ru": ("ru", "rus", "russian"),
    "it": ("it", "ita", "italian"), "pt": ("pt", "por", "portuguese"), "ko": ("ko", "kor", "korean"),
    "zh": ("zh", "chi", "zho", "chinese"),
}
ISO639_2 = {"tr": "tur", "en": "eng", "de": "ger", "fr": "fre", "es": "spa", "ja": "jpn", "ar": "ara", "ru": "rus",
            "it": "ita", "pt": "por", "ko": "kor", "zh": "chi"}


def sub_language(path):
    """Altyazı adındaki dil etiketi (".tr.srt", "Turkish") -> "tr" gibi kod ya da None."""
    stem = os.path.splitext(os.path.basename(path))[0].lower()
    toks = re.split(r"[ ._\-\[\]()]+", stem)
    for code, names in _LANGS.items():
        if any(tk in names for tk in toks[-3:]) or any(n in toks for n in names[2:]):
            return code
    return None


def list_subtitles(folder):
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    out = [os.path.join(folder, n) for n in names if os.path.splitext(n)[1].lower() in SUBTITLE_EXT
           and os.path.splitext(n)[1].lower() != ".txt"]
    # "Subs" / "Altyazı" alt klasörleri de
    for n in names:
        if n.lower() in ("subs", "subtitles", "sub", "altyazı", "altyazi", "altyazılar"):
            d = os.path.join(folder, n)
            if os.path.isdir(d):
                for root, _, files in os.walk(d):
                    out += [os.path.join(root, f) for f in files if os.path.splitext(f)[1].lower() in SUBTITLE_EXT]
    return out


def _similar(a, b):
    a, b = _norm(a), _norm(b)
    return bool(a) and bool(b) and (a in b or b in a)


def _initials(title):
    return "".join(w[0] for w in re.findall(r"[0-9a-zğüşıöç]+", (title or "").lower()))


def _other_titles(series):
    """Aynı klasördeki başka dizilerin başlıkları (altyazıyı yanlış diziye bağlamamak için)."""
    out = set()
    try:
        names = os.listdir(series.folder)
    except OSError:
        return out
    from .formats import kind_of
    for n in names:
        if kind_of(n) != "video":
            continue
        p = parse(n)
        if p is not None and p.kind == "episode" and p.title and not _similar(p.title, series.title):
            out.add(p.title)
    return out


def _title_fits(sub_title, series, others):
    """Altyazının başlığı bu diziye uyuyor mu? Başlık yoksa, benziyorsa, kısaltmasıysa ("aot") ya da klasörde
    ona benzeyen başka bir dizi yoksa evet."""
    n = _norm(sub_title)
    if not n or _similar(sub_title, series.title):
        return True
    if len(n) >= 2 and n == _initials(series.title):
        return True
    return not any(_similar(sub_title, o) or n == _initials(o) for o in others)


def match_subtitles(series, sub_paths, prefer_lang="tr"):
    """{video yolu: altyazı yolu}. Eşleşme sezon+bölüm numarasıyla; aynı bölüme birden çok altyazı varsa
    tercih edilen dil, sonra adı videoya en çok benzeyen seçilir."""
    by_key = {}
    single_season = len(series.seasons()) == 1
    others = _other_titles(series)
    for sp in sub_paths:
        p = parse(sp)
        if p is None or p.kind != "episode":
            continue
        if not _title_fits(p.title, series, others):
            continue
        s = p.season if p.explicit_season else (season_from_dir(sp) or (series.episodes[0][1].season
                                                                         if single_season else 1))
        by_key.setdefault((s, p.episode), []).append(sp)
    out = {}
    for vp, ep in series.episodes:
        cands = by_key.get((ep.season, ep.episode))
        if not cands:
            continue
        vstem = os.path.splitext(os.path.basename(vp))[0].lower()

        def score(sp):
            lang = sub_language(sp)
            same_name = os.path.basename(sp).lower().startswith(vstem)
            return (lang == prefer_lang, same_name, lang is None, -len(os.path.basename(sp)))
        out[vp] = max(cands, key=score)
    return out


def vlc_autoloads(video, sub):
    """VLC bu altyazıyı kendisi yükler mi (aynı klasörde ve adı video adıyla başlıyor)?"""
    if os.path.normcase(os.path.dirname(os.path.abspath(video))) != os.path.normcase(os.path.dirname(os.path.abspath(sub))):
        return False
    vstem = os.path.splitext(os.path.basename(video))[0].lower()
    return os.path.basename(sub).lower().startswith(vstem)


def sub_rename_target(new_video, sub):
    """Video yeniden adlandırılınca altyazının yeni adı: "<video adı>[.dil].<uzantı>" (VLC kendisi bulsun)."""
    lang = sub_language(sub)
    ext = os.path.splitext(sub)[1].lower()
    base = os.path.splitext(new_video)[0]
    return base + (f".{lang}" if lang else "") + ext


def subtitle_charenc(path):
    """UTF-8 olmayan altyazı dosyası için ffmpeg'e kodlama adı (yoksa ffmpeg UTF-8 sanıp harfleri bozar).
    Oynatıcıda seçili kodlama; o da otomatikse Türkçe arayüzde CP1254, değilse Windows'un ANSI kod sayfası."""
    from .config import prefs
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return None
    if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        return None                      # BOM'lu UTF-8/16: ffmpeg kendisi tanır
    try:
        raw.decode("utf-8")
        return None
    except UnicodeDecodeError:
        pass
    enc = prefs.get("sub_encoding", "auto")
    if enc and enc not in ("auto", "UTF-8", "UTF-16"):
        return enc
    if prefs.get("language", "tr") == "tr":
        return "CP1254"                   # Windows İngilizce olsa da Türkçe altyazılar çoğunlukla 1254
    import locale
    return locale.getencoding().upper()


def embed_command(ffmpeg, video, sub, out, lang=None):
    """Altyazıyı videoya ayrı iz olarak ekleyen (yeniden kodlamasız) ffmpeg komutu. Çıktı .mkv.
    Yeni altyazı ilk altyazı izi olur ve varsayılan seçilir; videodaki diğer altyazılar korunur."""
    src_mkv = os.path.splitext(video)[1].lower() in (".mkv", ".mka", ".webm")
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", video]
    enc = subtitle_charenc(sub)
    if enc:
        cmd += ["-sub_charenc", enc]
    cmd += ["-i", sub, "-map", "0:v?", "-map", "0:a?", "-map", "1:0", "-map", "0:s?"]
    if src_mkv:
        cmd += ["-map", "0:t?"]           # mkv'deki gömülü yazı tipleri (ASS altyazılar için)
    cmd += ["-c", "copy"]
    if not src_mkv:
        cmd += ["-c:s", "srt"]            # mp4'teki mov_text altyazılar mkv'ye srt olarak geçer
    sext = os.path.splitext(sub)[1].lower()
    cmd += ["-c:s:0", "copy" if sext in (".srt", ".ass", ".ssa", ".vtt") else "srt"]
    lang = lang or sub_language(sub)
    if lang:
        cmd += ["-metadata:s:s:0", f"language={ISO639_2.get(lang, lang)}"]
    cmd += ["-disposition:s:0", "default", out]
    return cmd


# ------------------------------------------------------------------ dizi ayarları (intro)
class SeriesStore(_JsonStore):
    """Diziye özel ayarlar: elle intro aralığı, otomatik bulunan aralıklar, intro parmak izi."""

    def __init__(self):
        super().__init__(os.path.join(DATA_DIR, "series.json"))

    def get(self, key):
        return self.data.get(key, {})

    def update(self, key, **kw):
        d = dict(self.data.get(key, {}))
        for k, v in kw.items():
            if v is None:
                d.pop(k, None)
            else:
                d[k] = v
        if d:
            self.data[key] = d
        else:
            self.data.pop(key, None)
        self.save()

    def intro_for(self, series, path):
        """Bu bölümün intro aralığı (ms, ms) ya da None. Elle ayar her bölüme uygulanır, öncelikli."""
        d = self.get(series.key)
        if d.get("intro_off"):
            return None
        man = d.get("intro")
        if man and man[1] > man[0]:
            return tuple(man)
        ep = series.find(path)
        if ep is None:
            return None
        r = d.get("intro_auto", {}).get(f"{ep.season}x{ep.episode}")
        return tuple(r) if r else None

    def set_auto(self, series, path, rng):
        ep = series.find(path)
        if ep is None:
            return
        d = self.get(series.key)
        auto = dict(d.get("intro_auto", {}))
        auto[f"{ep.season}x{ep.episode}"] = list(rng) if rng else []
        self.update(series.key, intro_auto=auto)

    def auto_known(self, series, path):
        """Bu bölüm için otomatik arama yapıldı mı (bulunamadıysa da [] kaydedilir)?"""
        ep = series.find(path)
        return ep is not None and f"{ep.season}x{ep.episode}" in self.get(series.key).get("intro_auto", {})


store = SeriesStore()
