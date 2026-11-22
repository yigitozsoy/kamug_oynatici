"""Transkripti ve ekrandaki yazıları yazıt notu (.yazit) olarak kaydeder; yazıt kuruluysa onda açar.

yazıt, tamga ailesinin not / ekran kaydı / çizim uygulaması.
.yazit = JSON {"format": "delta-note", "version": 2, "id", "meta", "items"} (iç biçim adı, uyumluluk için değişmez).
Yazı kutusu {"t": "text", "txt", "s", "c", "pos", "z"} (yazıt yazıyı kendisi kaydırmaz: satırlar burada bölünür),
görsel {"t": "image", "png" (base64), "sc", "pos", "z"}. Paragrafların "ln" alanı {"kamug": video yolu, "t": saniye}:
yazıt'ta tıklanınca kamug videoyu o saniyede açar."""
import base64
import json
import os
import textwrap
import time
import uuid

from .i18n import t
from .transcript import fmt_ts, frames_dir, paragraphs

BODY_PX = 18
LINE_H = 27                 # BODY_PX yazı için satır yüksekliği (yazıt'ın yazı kutusu satır aralığı ile uyumlu)
WRAP = 78                   # satır başına karakter
COL_W = 920                 # konuşma sütunu genişliği; ekrandaki yazılar sağ sütunda
IMG_W = 520
NOTE_EXT = ".yazit"


def yazit_data_dir():
    base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    new, old = os.path.join(base, "yazit"), os.path.join(base, "delta")   # yazıt'ın eski veri klasörü (ilk açılışta taşınır)
    return new if os.path.isdir(new) or not os.path.isdir(old) else old


def notes_root():
    """yazıt'ın not klasörü (yazıt tercihlerindeki notes_dir, yoksa Resimler\\yazit)."""
    try:
        with open(os.path.join(yazit_data_dir(), "preferences.json"), encoding="utf-8") as f:
            d = json.load(f).get("notes_dir") or ""
        if d and os.path.isdir(d):
            return d
    except (OSError, ValueError, AttributeError):
        pass
    try:
        from PyQt6.QtCore import QStandardPaths
        pics = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
    except Exception:
        pics = ""
    pics = pics or os.path.join(os.path.expanduser("~"), "Pictures")
    old = os.path.join(pics, "delta")      # yazıt taşıyamadıysa (ör. iki klasör de doluysa) eskisini kullanmaya devam eder
    return old if os.path.isdir(old) else os.path.join(pics, "yazit")


def find_yazit():
    """Kurulu yazit.exe yolu (yoksa yazıt'ın eski sürümü) ya da None."""
    progs = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")
    cands = [os.path.join(progs, "yazit", "yazit.exe")]
    old = [os.path.join(progs, "delta", "delta.exe")]
    try:
        import winreg
        base = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as k:
            for i in range(winreg.QueryInfoKey(k)[0]):
                try:
                    with winreg.OpenKey(k, winreg.EnumKey(k, i)) as sk:
                        name = str(winreg.QueryValueEx(sk, "DisplayName")[0])
                        low = name.lower()
                        loc = str(winreg.QueryValueEx(sk, "InstallLocation")[0])
                        if low.startswith(("yazıt", "yazit")):
                            cands.append(os.path.join(loc, "yazit.exe"))
                        elif low.startswith("delta"):
                            old.append(os.path.join(loc, "delta.exe"))
                except OSError:
                    continue
    except OSError:
        pass
    return next((c for c in cands + old if c and os.path.isfile(c)), None)


def _safe(name):
    s = name.replace(":", ".")
    s = "".join("_" if c in '<>"/\\|?*' or ord(c) < 32 else c for c in s)
    return " ".join(s.split()).strip().rstrip(".")[:120] or "kamug"


def _wrap(text, width=WRAP):
    return "\n".join(textwrap.wrap(text, width, break_long_words=False, break_on_hyphens=False)) or text


def _png_bytes(path, width=IMG_W):
    """Kare görselini yazıt için küçültülmüş PNG'ye çevirir (QImage iş parçacığında da güvenli)."""
    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, Qt
    from PyQt6.QtGui import QImage
    img = QImage(path)
    if img.isNull():
        return None, 0, 0
    if img.width() > width:
        img = img.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba), img.width(), img.height()


def build_note(video, data, key, title=None):
    """Transkript verisinden yazıt notu (dict)."""
    title = title or os.path.splitext(os.path.basename(video))[0]
    items, z = [], 0

    def text(txt, x, y, size=BODY_PX, bold=False, color="auto", link=None):
        nonlocal z
        z += 1
        d = {"t": "text", "c": color, "s": size, "txt": txt, "pos": [x, y], "z": z}
        if bold:
            d["b"] = 1
        if link is not None:
            d["ln"] = {"kamug": video, "t": round(link / 1000.0, 2)}
        items.append(d)
        return d

    text(title, 0, 0, 34, bold=True)
    sp = data.get("speech") or {}
    info = [os.path.basename(video)]
    if data.get("duration"):
        info.append(fmt_ts(data["duration"]))
    text("  ·  ".join(info), 0, 54, 15, color="#9e9e9e")

    y = 110
    segs = sp.get("segments") or []
    if segs:
        text(t("tr_speech"), 0, y, 24, bold=True)
        y += 46
        for start, para in paragraphs(segs):
            body = f"▶ {fmt_ts(start)}   " + para
            wrapped = _wrap(body)
            text(wrapped, 0, y, link=start)
            y += LINE_H * (wrapped.count("\n") + 1) + 16

    col = 1 if segs else 0
    en = (data.get("speech_en") or {}).get("segments") or []
    if en:                                       # İngilizce çeviri: yan sütun
        x0, ey = col * (COL_W + 80), 110
        text(t("tr_english"), x0, ey, 24, bold=True)
        ey += 46
        for start, para in paragraphs(en):
            wrapped = _wrap(f"▶ {fmt_ts(start)}   " + para)
            text(wrapped, x0, ey, link=start)
            ey += LINE_H * (wrapped.count("\n") + 1) + 16
        col += 1

    frames = (data.get("ocr") or {}).get("frames") or []
    if frames:
        x0 = col * (COL_W + 80)
        fy = 110
        text(t("tr_screen"), x0, fy, 24, bold=True)
        fy += 46
        fdir = frames_dir(key)
        for fr in frames:
            png, w, h = _png_bytes(os.path.join(fdir, fr.get("img", ""))) if fr.get("img") else (None, 0, 0)
            text(f"▶ {fmt_ts(fr['s'])}", x0, fy, 15, color="#9e9e9e", link=fr["s"])
            fy += 28
            if png:
                z += 1
                items.append({"t": "image", "sc": 1.0, "pos": [x0, fy], "z": z - 3_000_000,   # yazıt: görseller yazıların altında (Z_BASE)
                              "png": base64.b64encode(png).decode("ascii")})
                fy += h + 10
            if fr.get("t"):
                wrapped = "\n".join(_wrap(ln, 58) for ln in fr["t"].splitlines() if ln.strip())
                text(wrapped, x0, fy, 16, link=fr["s"])
                fy += 24 * (wrapped.count("\n") + 1) + 30
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    return {"format": "delta-note", "version": 2, "id": uuid.uuid4().hex[:12],
            "meta": {"title": title, "auto": "", "created": now, "modified": now, "view": {}},
            "items": items}


def save_note(video, data, key, path=None, title=None):
    """Notu kaydeder; path verilmezse yazıt'ın not klasöründeki "kamug" alt klasörüne. Döndürür: yol."""
    note = build_note(video, data, key, title)
    if path is None:
        folder = os.path.join(notes_root(), "kamug")
        os.makedirs(folder, exist_ok=True)
        base = _safe(note["meta"]["title"])
        path = os.path.join(folder, base + NOTE_EXT)
        n = 2
        while os.path.exists(path):
            path = os.path.join(folder, f"{base} ({n}){NOTE_EXT}")
            n += 1
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(note, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)
    return path


def open_in_yazit(path):
    """yazıt kuruluysa notu onda açar. Döndürür: açıldı mı."""
    exe = find_yazit()
    if not exe:
        return False
    from PyQt6.QtCore import QProcess
    return bool(QProcess.startDetached(exe, [path])[0])
