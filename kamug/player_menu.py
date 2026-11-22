"""Oynatıcı dişli menüsünün sayfaları (YouTube'daki gibi iç içe sayfalar)."""
from PyQt6.QtCore import QTimer

from .config import prefs, sync_store
from .i18n import t
from .window import SPEEDS, ASPECTS


def _speed_label(r):
    return t("normal") if abs(r - 1.0) < 1e-3 else f"{r:g}x"


def build_root(w):
    e = w.engine
    is_video = w.current.is_video

    def root(pb):
        if is_video:
            cur = e.get_sub_track()
            names = dict(e.sub_tracks())
            pb.nav("subtitles", t("subtitles"), t("off") if cur == -1 else names.get(cur, t("on")), build_subs(w))
        pb.nav("speed", t("speed"), _speed_label(e.rate()), build_speed(w))
        pb.nav("equalizer", t("audio"), "", build_audio(w))
        if is_video:
            pb.nav("tune", t("video_settings"), "", build_video(w))
        pb.nav("timer", t("sleep_timer"), _sleep_label(w), build_sleep(w))
        if is_video and w._series is not None:
            pb.nav("skip", t("intro_menu"), _intro_label(w), build_intro(w))
        if prefs.get("pip_enabled", True):
            pb.toggle("pip", t("pip_mode"), w._pip, lambda v: QTimer.singleShot(150, w.toggle_pip))
    return root


def _intro_label(w):
    from .library import fmt_time
    r = w._intro
    return t("intro_range", a=fmt_time(r[0]), b=fmt_time(r[1])) if r else t("intro_none")


def build_intro(w):
    """İntro atlama: şimdiki anı başlangıç/bitiş yap, otomatik bul, otomatik atla, sıfırla."""
    from . import series as ser
    from .library import fmt_time

    def page(pb):
        s = w._series
        from PyQt6.QtWidgets import QLabel
        rng = QLabel(_intro_label(w))
        rng.setObjectName("MValue")
        pb.header(t("intro_menu"), rng)
        now = fmt_time(w.engine.get_time()) if w.engine else "0:00"
        pb.action("skip", t("intro_set_start", t=now), lambda: w.set_intro_point("start"))
        pb.action("skip", t("intro_set_end", t=now), lambda: w.set_intro_point("end"))
        pb.action("search", t("intro_detect"), lambda: _detect(w))
        d = ser.store.get(s.key)
        pb.toggle(None, t("intro_auto_skip"), bool(d.get("auto_skip")),
                  lambda v: ser.store.update(s.key, auto_skip=True if v else None))
        pb.toggle(None, t("intro_disable"), bool(d.get("intro_off")), lambda v: _off(w, v))
        pb.action("replay", t("intro_reset"), lambda: _reset(w))
        pb.note(t("intro_manual_desc"))
    return page


def _detect(w):
    from . import series as ser
    s = w._series
    ser.store.update(s.key, intro=None, intro_ref=None, intro_auto=None, intro_off=None)
    w._load_intro(w.current.path, force=True)


def _off(w, v):
    from . import series as ser
    ser.store.update(w._series.key, intro_off=True if v else None)
    w._intro = ser.store.intro_for(w._series, w.current.path)


def _reset(w):
    from . import series as ser
    ser.store.update(w._series.key, intro=None, intro_ref=None, intro_auto=None, intro_off=None, auto_skip=None)
    w._intro = None
    w.overlay.set_skip(False)


def build_subs(w):
    e = w.engine

    def page(pb):
        pb.header(t("subtitles"))
        cur = e.get_sub_track()
        pb.option(t("off"), cur == -1, lambda: (e.set_sub_track(-1), w._update_cc_icon()))
        for tid, name in e.sub_tracks():
            if tid == -1:
                continue
            pb.option(name, tid == cur, lambda tid=tid: (e.set_sub_track(tid), QTimer.singleShot(100, w._update_cc_icon)))
        pb.action("add", t("add_subtitle") + "…", w.add_subtitle_dialog)
        pb.separator()
        pb.stepper(t("sub_delay"), f"{e.get_sub_delay():+d} ms",
                   lambda: w.adjust_sub_delay(-50), lambda: w.adjust_sub_delay(50),
                   lambda: (e.set_sub_delay(0), "+0 ms")[1])
        pb.nav("palette", t("sub_style"), "", build_sub_style(w))
        enc = prefs.get("sub_encoding", "auto")
        pb.nav("language", t("sub_encoding"), _enc_label(enc), build_encoding(w))
        pb.action("save", t("save_sync"), lambda: _save_sync(w), close=False)
    return page


def _save_sync(w):
    if w.current:
        sync_store.set(w.current.path, w.engine.get_audio_delay(), w.engine.get_sub_delay())
        w.osd(t("sync_saved"))


# (VLC/iconv adı, i18n anahtarı). UTF-8 dışındaki eski Windows/Asya kodlamaları; UTF-8 altyazı her dilde çalışır.
ENCODINGS = [("auto", None), ("UTF-8", None), ("UTF-16", None),
             ("Windows-1254", "turkish"), ("ISO-8859-9", "turkish"),
             ("Windows-1252", "enc_west"), ("Windows-1250", "enc_central"), ("Windows-1251", "enc_cyr"),
             ("Windows-1253", "enc_greek"), ("Windows-1255", "enc_hebrew"), ("Windows-1256", "enc_arabic"),
             ("Shift_JIS", "enc_japanese"), ("EUC-JP", "enc_japanese"), ("GB18030", "enc_chinese_s"),
             ("Big5", "enc_chinese_t"), ("EUC-KR", "enc_korean"), ("Windows-874", "enc_thai")]


def _enc_label(enc):
    if enc == "auto":
        return t("automatic")
    key = dict(ENCODINGS).get(enc)
    return f"{enc} ({t(key)})" if key else enc


def build_encoding(w):
    def page(pb):
        pb.header(t("sub_encoding"))
        cur = prefs.get("sub_encoding", "auto")
        for enc, _ in ENCODINGS:
            pb.option(_enc_label(enc), enc == cur, lambda enc=enc: (prefs.set("sub_encoding", enc), w._schedule_rebuild()))
        pb.note(t("sub_encoding_note"))
    return page


def build_sub_style(w):
    def set_and_rebuild(key, val):
        prefs.set(key, val)
        w._schedule_rebuild()

    def step(key, d, lo, hi, fmt):
        def go():
            v = max(lo, min(hi, int(prefs.get(key)) + d))
            set_and_rebuild(key, v)
            return fmt(v)
        return go

    def page(pb):
        pb.header(t("sub_style"))
        pb.stepper(t("sub_size"), f"{prefs.get('sub_size')}%",
                   step("sub_size", -10, 30, 400, lambda v: f"{v}%"), step("sub_size", 10, 30, 400, lambda v: f"{v}%"),
                   lambda: (set_and_rebuild("sub_size", 100), "100%")[1])
        font = prefs.get("sub_font", "") or ""
        pb.nav("subtitles", t("sub_font"), font or t("default"), build_sub_font(w))
        pb.swatches(t("sub_color"), ["#ffffff", "#ffff00", "#00ff66", "#00e5ff", "#ff66cc", "#ff4040"],
                    prefs.get("sub_color"), lambda c: set_and_rebuild("sub_color", c))
        bg = int(prefs.get("sub_bg", 0))
        pb.nav("filter", t("sub_background"), _bg_label(bg), build_sub_bg(w))
        ol = int(prefs.get("sub_outline", 4))
        pb.nav("brightness", t("sub_outline"), _outline_label(ol), build_sub_outline(w))
        pb.toggle(None, t("sub_bold"), bool(prefs.get("sub_bold")), lambda v: set_and_rebuild("sub_bold", v))
        pb.stepper(t("sub_margin"), f"{prefs.get('sub_margin')} px",
                   step("sub_margin", -10, 0, 400, lambda v: f"{v} px"), step("sub_margin", 10, 0, 400, lambda v: f"{v} px"),
                   lambda: (set_and_rebuild("sub_margin", 24), "24 px")[1])
        pb.note(t("sub_style_note"))
    return page


SUB_FONTS = ["", "Segoe UI", "Segoe UI Semibold", "Arial", "Tahoma", "Verdana", "Calibri", "Trebuchet MS"]


def build_sub_font(w):
    def page(pb):
        pb.header(t("sub_font"))
        cur = prefs.get("sub_font", "") or ""
        for f in SUB_FONTS:
            pb.option(f or t("default"), f == cur, lambda f=f: (prefs.set("sub_font", f), w._schedule_rebuild()))
    return page


def _bg_label(v):
    return t("none") if v == 0 else (t("semi") if v < 200 else t("opaque"))


def _outline_label(v):
    return {0: t("none"), 2: t("thin"), 4: t("normal"), 6: t("thick")}.get(v, str(v))


def build_sub_bg(w):
    def page(pb):
        pb.header(t("sub_background"))
        cur = int(prefs.get("sub_bg", 0))
        for v in (0, 128, 255):
            pb.option(_bg_label(v), cur == v, lambda v=v: (prefs.set("sub_bg", v), w._schedule_rebuild()))
    return page


def build_sub_outline(w):
    def page(pb):
        pb.header(t("sub_outline"))
        cur = int(prefs.get("sub_outline", 4))
        for v in (0, 2, 4, 6):
            pb.option(_outline_label(v), cur == v, lambda v=v: (prefs.set("sub_outline", v), w._schedule_rebuild()))
    return page


def build_speed(w):
    e = w.engine

    def set_rate(r):
        e.set_rate(r)
        w.osd(t("speed") + ": " + _speed_label(r))

    def page(pb):
        pb.header(t("speed"))
        cur = e.rate()

        def st(d):
            def go():
                r = round(max(0.25, min(4.0, e.rate() + d)), 2)
                set_rate(r)
                return _speed_label(r)
            return go
        pb.stepper(t("custom"), _speed_label(cur), st(-0.05), st(0.05), lambda: (set_rate(1.0), _speed_label(1.0))[1])
        for s in SPEEDS:
            pb.option(_speed_label(s), abs(cur - s) < 1e-3, lambda s=s: set_rate(s))
    return page


def build_audio(w):
    e = w.engine

    def page(pb):
        pb.header(t("audio"))
        tracks = [x for x in e.audio_tracks() if x[0] != -1]
        cur = e.get_audio_track()
        if len(tracks) > 1:
            pb.nav("audio_track", t("audio_track"), dict(tracks).get(cur, ""), build_audio_tracks(w))
        eq = e.equalizer_index()
        presets = dict(e.equalizer_presets())
        pb.nav("equalizer", t("equalizer"), t("off") if eq < 0 else presets.get(eq, ""), build_eq(w))
        pb.nav("volume", t("channels"), _channel_label(e.get_channel()), build_channels(w))
        pb.stepper(t("volume_boost"), f"{e.volume()}%",
                   lambda: (w.set_volume(e.volume() - 10), f"{e.volume()}%")[1],
                   lambda: (w.set_volume(e.volume() + 10), f"{e.volume()}%")[1],
                   lambda: (w.set_volume(100), "100%")[1])
        pb.stepper(t("audio_delay"), f"{e.get_audio_delay():+d} ms",
                   lambda: w.adjust_audio_delay(-50), lambda: w.adjust_audio_delay(50),
                   lambda: (e.set_audio_delay(0), "+0 ms")[1])
    return page


def build_audio_tracks(w):
    e = w.engine

    def page(pb):
        pb.header(t("audio_track"))
        cur = e.get_audio_track()
        for tid, name in e.audio_tracks():
            if tid == -1:
                continue
            pb.option(name, tid == cur, lambda tid=tid: e.set_audio_track(tid))
    return page


def build_eq(w):
    e = w.engine

    def page(pb):
        pb.header(t("equalizer"))
        cur = e.equalizer_index()
        pb.option(t("off"), cur < 0, lambda: e.set_equalizer(-1))
        for i, name in e.equalizer_presets():
            pb.option(name, i == cur, lambda i=i: e.set_equalizer(i))
    return page


CHANNELS = [(1, "stereo"), (2, "reverse_stereo"), (3, "left"), (4, "right"), (5, "dolby")]


def _channel_label(c):
    return dict((k, t("ch_" + v)) for k, v in CHANNELS).get(c, t("ch_stereo"))


def build_channels(w):
    e = w.engine

    def page(pb):
        pb.header(t("channels"))
        cur = e.get_channel()
        for k, v in CHANNELS:
            pb.option(t("ch_" + v), k == cur, lambda k=k: e.set_channel(k))
    return page


def build_video(w):
    def page(pb):
        pb.header(t("video_settings"))
        pb.nav("aspect", t("aspect_ratio"), w._aspect or t("default"), build_aspect(w))
        pb.nav("crop", t("crop"), w._crop or t("none"), build_crop(w))
        pb.nav("rotate_right", t("rotate"), f"{w._rotation}°", build_rotate(w))
        z = w._video_zoom
        pb.nav("zoom_in", t("zoom"), _zoom_label(z), build_zoom(w))
        pb.nav("brightness", t("image_adjust"), "", build_adjust(w))

        def deint(v):
            w._deinterlace = v
            w.engine.set_deinterlace("yadif" if v else None)
        pb.toggle("hd", t("deinterlace"), w._deinterlace, deint)
        pb.action("camera", t("snapshot"), w.take_snapshot)
    return page


def _zoom_label(z):
    if z == "fit":
        return t("zoom_fit")
    if z == "fill":
        return t("zoom_fill")
    if z == "orig":
        return t("zoom_orig")
    return f"{int(float(z) * 100)}%"


def build_aspect(w):
    def page(pb):
        pb.header(t("aspect_ratio"))
        for a in ASPECTS:
            def go(a=a):
                w._aspect = a
                w.engine.set_aspect(a)
                w.osd(t("aspect_ratio") + ": " + (a or t("default")))
            pb.option(a or t("default"), w._aspect == a, go)
    return page


def build_crop(w):
    def page(pb):
        pb.header(t("crop"))
        for a in ASPECTS:
            def go(a=a):
                w._crop = a
                w.engine.set_crop(a)
                w.osd(t("crop") + ": " + (a or t("none")))
            pb.option(a or t("none"), w._crop == a, go)
    return page


def build_rotate(w):
    def page(pb):
        pb.header(t("rotate"))
        for deg in (0, 90, 180, 270):
            pb.option(f"{deg}°", w._rotation == deg, lambda deg=deg: w.set_rotation(deg))
    return page


def build_zoom(w):
    def page(pb):
        pb.header(t("zoom"))
        for z in ("fit", "fill", "orig", 1.5, 2.0, 3.0):
            def go(z=z):
                w._video_zoom = z
                w._apply_video_zoom()
                w.osd(t("zoom") + ": " + _zoom_label(z))
            pb.option(_zoom_label(z), w._video_zoom == z, go)
        pb.note(t("zoom_note"))
    return page


def build_adjust(w):
    a = w._adjust

    def setv(key, v):
        a[key] = v
        w.engine.set_adjust(**a)

    def page(pb):
        pb.header(t("image_adjust"))
        pb.slider(t("brightness"), 0, 200, int(a["brightness"] * 100), lambda v: setv("brightness", v / 100),
                  lambda v: f"{v}%")
        pb.slider(t("contrast"), 0, 200, int(a["contrast"] * 100), lambda v: setv("contrast", v / 100),
                  lambda v: f"{v}%")
        pb.slider(t("saturation"), 0, 300, int(a["saturation"] * 100), lambda v: setv("saturation", v / 100),
                  lambda v: f"{v}%")
        pb.slider(t("hue"), -180, 180, int(a["hue"]), lambda v: setv("hue", float(v)), lambda v: f"{v}°")
        pb.slider(t("gamma"), 10, 300, int(a["gamma"] * 100), lambda v: setv("gamma", v / 100),
                  lambda v: f"{v / 100:.2f}")

        def reset():
            a.update(brightness=1.0, contrast=1.0, saturation=1.0, hue=0.0, gamma=1.0)
            w.engine.set_adjust(**a)
        pb.action("undo", t("reset"), lambda: (reset(), pb.menu.refresh()), close=False)
    return page


def _sleep_label(w):
    if w._sleep_end_of_media:
        return t("end_of_media")
    if w.sleep_timer.isActive():
        return t("n_minutes", n=max(1, w.sleep_timer.remainingTime() // 60000))
    return t("off")


def build_sleep(w):
    def set_sleep(minutes):
        w._sleep_end_of_media = False
        w.sleep_timer.stop()
        if minutes == -1:
            w._sleep_end_of_media = True
            w.osd(t("sleep_timer") + ": " + t("end_of_media"))
        elif minutes > 0:
            w.sleep_timer.start(minutes * 60000)
            w.osd(t("sleep_timer") + ": " + t("n_minutes", n=minutes))
        else:
            w.osd(t("sleep_timer") + ": " + t("off"))

    def page(pb):
        pb.header(t("sleep_timer"))
        active = w.sleep_timer.isActive()
        pb.option(t("off"), not active and not w._sleep_end_of_media, lambda: set_sleep(0))
        for m in (10, 15, 30, 45, 60, 90):
            pb.option(t("n_minutes", n=m), False, lambda m=m: set_sleep(m))
        pb.option(t("end_of_media"), w._sleep_end_of_media, lambda: set_sleep(-1))
    return page
